import os
import re
from datetime import datetime
from typing import Optional

import secrets
import csv
import io

from fastapi import FastAPI, Depends, Request, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database import get_db, init_db, NewsArticle, Subscriber

def tpl_globals():
    return {"now": datetime.utcnow()}

load_dotenv()

API_KEY = os.getenv("WEBSITE_API_KEY", "changeme")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

security = HTTPBasic()


def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    is_correct_user = secrets.compare_digest(
        credentials.username.encode("utf8"), b"admin"
    )
    is_correct_pass = secrets.compare_digest(
        credentials.password.encode("utf8"), ADMIN_PASSWORD.encode("utf8")
    )
    if not (is_correct_user and is_correct_pass):
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

VALID_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

app = FastAPI(title="AI & Tech Daily")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def on_startup():
    init_db()


# ---------- helpers ----------

def group_articles_by_date(articles):
    grouped = {}
    for article in articles:
        date_key = article.published_date.strftime("%B %d, %Y")
        grouped.setdefault(date_key, []).append(article)
    return grouped


# ---------- routes ----------

@app.get("/", response_class=HTMLResponse)
def homepage(request: Request, db: Session = Depends(get_db)):
    articles = (
        db.query(NewsArticle)
        .filter(NewsArticle.is_published == True)
        .order_by(NewsArticle.published_date.desc())
        .limit(20)
        .all()
    )
    grouped = group_articles_by_date(articles)
    subscriber_count = db.query(Subscriber).filter(Subscriber.is_active == True).count()
    return templates.TemplateResponse(
        "index.html", {
            "request": request,
            "grouped_articles": grouped,
            "subscriber_count": subscriber_count,
            **tpl_globals(),
        }
    )


@app.get("/article/{article_id}", response_class=HTMLResponse)
def article_detail(article_id: int, request: Request, db: Session = Depends(get_db)):
    article = db.query(NewsArticle).filter(
        NewsArticle.id == article_id,
        NewsArticle.is_published == True
    ).first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    related_articles = (
        db.query(NewsArticle)
        .filter(NewsArticle.is_published == True, NewsArticle.id != article_id)
        .order_by(NewsArticle.published_date.desc())
        .limit(3)
        .all()
    )
    return templates.TemplateResponse(
        "article.html", {
            "request": request,
            "article": article,
            "related_articles": related_articles,
            **tpl_globals(),
        }
    )


class SubscribeRequest(BaseModel):
    email: str


@app.post("/subscribe")
def subscribe(payload: SubscribeRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()

    if not VALID_EMAIL_RE.match(email):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": "Please enter a valid email address."},
        )

    existing = db.query(Subscriber).filter(Subscriber.email == email).first()
    if existing:
        if existing.is_active:
            return JSONResponse(content={"status": "already_subscribed", "message": "You are already subscribed!"})
        # Reactivate lapsed subscriber
        existing.is_active = True
        existing.subscribed_at = datetime.utcnow()
        db.commit()
        try:
            from newsletter import send_welcome_email
            send_welcome_email(email)
        except Exception as e:
            print(f"Welcome email failed: {e}")
        return JSONResponse(content={"status": "success", "message": "Welcome back! You are resubscribed."})

    subscriber = Subscriber(email=email, subscribed_at=datetime.utcnow())
    db.add(subscriber)
    db.commit()
    try:
        from newsletter import send_welcome_email
        send_welcome_email(email)
    except Exception as e:
        print(f"Welcome email failed: {e}")
    return JSONResponse(content={"status": "success", "message": "You are subscribed! Check your inbox."})


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(email: str, request: Request, db: Session = Depends(get_db)):
    subscriber = db.query(Subscriber).filter(Subscriber.email == email).first()
    if subscriber:
        subscriber.is_active = False
        db.commit()
    return templates.TemplateResponse(
        "unsubscribe.html",
        {"request": request, "email": email}
    )


class ArticlePayload(BaseModel):
    title: str
    summary: str
    category: Optional[str] = "AI & Tech"
    source_url: Optional[str] = None


class PublishRequest(BaseModel):
    articles: list[ArticlePayload]


def _get_api_key(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
) -> str:
    if x_api_key:
        return x_api_key
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:]
    return ""


@app.post("/api/publish")
def publish_articles(
    payload: PublishRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    api_key = _get_api_key(
        x_api_key=request.headers.get("x-api-key"),
        authorization=request.headers.get("authorization"),
    )
    if api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

    saved = []
    skipped = []
    for item in payload.articles:
        existing = db.query(NewsArticle).filter(NewsArticle.title == item.title).first()
        if existing:
            skipped.append(existing.id)
            continue
        article = NewsArticle(
            title=item.title,
            summary=item.summary if item.summary and len(item.summary) >= 20 else item.title,
            category=item.category or "AI & Tech",
            source_url=item.source_url,
            published_date=datetime.utcnow(),
            is_published=True,
        )
        db.add(article)
        db.flush()
        saved.append(article.id)

    db.commit()
    return {"status": "ok", "saved": len(saved), "ids": saved, "skipped": skipped}


@app.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin),
):
    subscribers = db.query(Subscriber).order_by(Subscriber.subscribed_at.desc()).all()
    total_articles = db.query(NewsArticle).count()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_articles = db.query(NewsArticle).filter(
        NewsArticle.published_date >= today_start
    ).count()
    active_subs = sum(1 for s in subscribers if s.is_active)
    inactive_subs = len(subscribers) - active_subs

    articles = db.query(NewsArticle).order_by(
        NewsArticle.published_date.desc()
    ).limit(50).all()

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "subscribers": subscribers,
            "total_articles": total_articles,
            "today_articles": today_articles,
            "active_subs": active_subs,
            "inactive_subs": inactive_subs,
            "total_subs": len(subscribers),
            "articles": articles,
        },
    )


@app.post("/admin/subscriber/{subscriber_id}/suspend")
async def suspend_subscriber(
        subscriber_id: int,
        db: Session = Depends(get_db),
        username: str = Depends(verify_admin)):
    subscriber = db.query(Subscriber).filter(
        Subscriber.id == subscriber_id
    ).first()
    if not subscriber:
        return JSONResponse({"status": "error", "message": "Not found"})
    subscriber.is_active = not subscriber.is_active
    db.commit()
    status = "active" if subscriber.is_active else "suspended"
    return JSONResponse({
        "status": "success",
        "message": f"Subscriber {status}",
        "is_active": subscriber.is_active
    })


@app.delete("/admin/subscriber/{subscriber_id}")
async def delete_subscriber(
        subscriber_id: int,
        db: Session = Depends(get_db),
        username: str = Depends(verify_admin)):
    subscriber = db.query(Subscriber).filter(
        Subscriber.id == subscriber_id
    ).first()
    if not subscriber:
        return JSONResponse({"status": "error", "message": "Not found"})
    db.delete(subscriber)
    db.commit()
    return JSONResponse({"status": "success", "message": "Subscriber deleted"})


@app.post("/admin/article/{article_id}/toggle")
async def toggle_article(
        article_id: int,
        db: Session = Depends(get_db),
        username: str = Depends(verify_admin)):
    article = db.query(NewsArticle).filter(
        NewsArticle.id == article_id
    ).first()
    if not article:
        return JSONResponse({"status": "error", "message": "Not found"})
    article.is_published = not article.is_published
    db.commit()
    return JSONResponse({
        "status": "success",
        "is_published": article.is_published
    })


@app.delete("/admin/article/{article_id}")
async def delete_article(
        article_id: int,
        db: Session = Depends(get_db),
        username: str = Depends(verify_admin)):
    article = db.query(NewsArticle).filter(
        NewsArticle.id == article_id
    ).first()
    if not article:
        return JSONResponse({"status": "error", "message": "Not found"})
    db.delete(article)
    db.commit()
    return JSONResponse({"status": "success"})


@app.get("/admin/test-email")
async def test_email(
        email: str,
        username: str = Depends(verify_admin)):
    from newsletter import send_test_email
    result = send_test_email(email)
    return JSONResponse(result)


@app.get("/admin/export")
def export_subscribers(
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin),
):
    subscribers = db.query(Subscriber).order_by(Subscriber.subscribed_at.desc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Email", "Subscribed Date", "Status"])
    for s in subscribers:
        writer.writerow([
            s.email,
            s.subscribed_at.strftime("%Y-%m-%d %H:%M") if s.subscribed_at else "",
            "Active" if s.is_active else "Inactive",
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=subscribers.csv"},
    )


@app.get("/api/articles")
def api_articles(db: Session = Depends(get_db)):
    articles = (
        db.query(NewsArticle)
        .filter(NewsArticle.is_published == True)
        .order_by(NewsArticle.published_date.desc())
        .limit(20)
        .all()
    )
    return [
        {
            "id": a.id,
            "title": a.title,
            "summary": a.summary,
            "category": a.category,
            "source_url": a.source_url,
            "published_date": a.published_date.isoformat(),
        }
        for a in articles
    ]

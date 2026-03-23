import os
import re
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Depends, Request, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
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
    article = db.query(NewsArticle).filter(NewsArticle.id == article_id).first()
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
            content={"status": "invalid_email", "message": "Please enter a valid email."},
        )

    existing = db.query(Subscriber).filter(Subscriber.email == email).first()
    if existing:
        if existing.is_active:
            return {"status": "already_subscribed", "message": "You're already subscribed!"}
        # Reactivate lapsed subscriber
        existing.is_active = True
        existing.subscribed_at = datetime.utcnow()
        db.commit()
        from newsletter import send_welcome_email
        send_welcome_email(email)
        return {"status": "success", "message": "Check your inbox!"}

    subscriber = Subscriber(email=email, subscribed_at=datetime.utcnow())
    db.add(subscriber)
    db.commit()
    from newsletter import send_welcome_email
    send_welcome_email(email)
    return {"status": "success", "message": "Check your inbox!"}


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(email: str, token: str, db: Session = Depends(get_db)):
    from newsletter import _unsubscribe_token
    if token != _unsubscribe_token(email):
        raise HTTPException(status_code=400, detail="Invalid unsubscribe link.")
    subscriber = db.query(Subscriber).filter(Subscriber.email == email).first()
    if subscriber:
        subscriber.is_active = False
        db.commit()
    html = """<!DOCTYPE html>
<html>
<head><title>Unsubscribed</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gray-50 min-h-screen flex items-center justify-center">
  <div class="text-center p-8">
    <p class="text-5xl mb-4">👋</p>
    <h1 class="text-2xl font-bold text-gray-800 mb-2">You have been unsubscribed.</h1>
    <p class="text-gray-500 mb-6">You won't receive any more emails from us.</p>
    <a href="/" class="text-indigo-600 hover:text-indigo-800 font-medium">← Back to home</a>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


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
def admin_page(request: Request, db: Session = Depends(get_db)):
    total_articles = db.query(NewsArticle).count()
    latest_articles = (
        db.query(NewsArticle)
        .order_by(NewsArticle.published_date.desc())
        .limit(10)
        .all()
    )
    total_subscribers = db.query(Subscriber).count()
    rows = "".join(
        f"<tr><td>{a.id}</td><td>{a.title}</td><td>{a.published_date.strftime('%Y-%m-%d %H:%M')}</td><td>{'Yes' if a.is_published else 'No'}</td></tr>"
        for a in latest_articles
    )
    html = f"""<!DOCTYPE html><html><head><title>Admin</title>
    <style>body{{font-family:sans-serif;padding:2rem}}table{{border-collapse:collapse;width:100%}}
    th,td{{border:1px solid #ccc;padding:.5rem;text-align:left}}th{{background:#f0f0f0}}</style>
    </head><body>
    <h1>Admin Dashboard</h1>
    <p><strong>Total articles:</strong> {total_articles}</p>
    <p><strong>Total subscribers:</strong> {total_subscribers}</p>
    <h2>Latest 10 Articles</h2>
    <table><thead><tr><th>ID</th><th>Title</th><th>Published</th><th>Published?</th></tr></thead>
    <tbody>{rows}</tbody></table>
    </body></html>"""
    return HTMLResponse(content=html)


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

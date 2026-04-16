import os
import re
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlparse

import secrets
import csv
import io

import httpx
from apscheduler.schedulers.background import BackgroundScheduler

from fastapi import FastAPI, Depends, Request, Header, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from database import get_db, init_db, SessionLocal, NewsArticle, Subscriber

logger = logging.getLogger(__name__)

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


def clear_old_articles(days: int = 14):
    """Delete NewsArticle records older than `days` days."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = db.query(NewsArticle).filter(NewsArticle.published_date < cutoff).delete()
        db.commit()
        logger.info(f"DB cleanup: deleted {deleted} articles older than {days} days")
    except Exception as e:
        db.rollback()
        logger.error(f"DB cleanup error: {e}")
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    init_db()
    clear_old_articles()  # immediate one-time cleanup on startup
    scheduler = BackgroundScheduler()
    scheduler.add_job(clear_old_articles, "cron", hour=3, minute=30, id="daily_db_cleanup")
    scheduler.start()
    logger.info("DB cleanup scheduled daily at 03:30")


# ---------- helpers ----------

def proxy_image_url(url: Optional[str]) -> Optional[str]:
    """Wrap an image URL through images.weserv.nl to bypass hotlink protection."""
    if not url:
        return None
    if "weserv.nl" in url:
        return url
    from urllib.parse import quote
    return f"https://images.weserv.nl/?url={quote(url, safe='')}&w=800&q=85"


def extract_og_image(url: str) -> Optional[str]:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ABbot/1.0; +https://abai.cloud)"}
        r = httpx.get(url, timeout=4, follow_redirects=True, headers=headers)
        if r.status_code != 200:
            return None
        html = r.text
        if 'og:image' not in html:
            return None
        start = html.find('property="og:image"')
        if start == -1:
            start = html.find("property='og:image'")
        if start == -1:
            return None
        content_start = html.find('content="', start)
        if content_start == -1:
            content_start = html.find("content='", start)
            if content_start == -1:
                return None
            quote_char = "'"
        else:
            quote_char = '"'
        content_start += len('content=') + 1
        content_end = html.find(quote_char, content_start)
        if content_end == -1:
            return None
        image_url = html[content_start:content_end].strip()
        if not image_url.startswith("http") or len(image_url) > 500:
            return None
        return image_url
    except Exception:
        return None


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
        .order_by(NewsArticle.published_date.desc(), NewsArticle.id.desc())
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
        .order_by(NewsArticle.published_date.desc(), NewsArticle.id.desc())
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
    image_url: Optional[str] = None
    source_domain: Optional[str] = None
    published: Optional[str] = None


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
    saved_dicts = []
    skipped = []
    for item in payload.articles:
        existing = db.query(NewsArticle).filter(NewsArticle.title == item.title).first()
        if existing:
            skipped.append(existing.id)
            continue
        raw_date = item.published
        if raw_date:
            if isinstance(raw_date, str):
                try:
                    pub_date = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                    # Strip timezone info for SQLite compatibility
                    pub_date = pub_date.replace(tzinfo=None)
                except Exception:
                    pub_date = datetime.utcnow()
            elif isinstance(raw_date, datetime):
                pub_date = raw_date.replace(tzinfo=None)
            else:
                pub_date = datetime.utcnow()
        else:
            pub_date = datetime.utcnow()

        article = NewsArticle(
            title=item.title,
            summary=item.summary if item.summary and len(item.summary) >= 20 else item.title,
            category=item.category or "AI & Tech",
            source_url=item.source_url,
            image_url=proxy_image_url(item.image_url),
            source_domain=item.source_domain,
            published_date=pub_date,
            is_published=True,
        )
        db.add(article)
        db.flush()
        saved.append(article.id)
        saved_dicts.append({
            "title": item.title,
            "summary": item.summary or "",
            "category": item.category or "AI & Tech",
            "source_url": item.source_url or "",
        })

    db.commit()

    if saved_dicts:
        try:
            from newsletter import send_daily_digest
            sent = send_daily_digest(saved_dicts)
            logger.info(f"Auto digest after publish: {sent} emails sent")
        except Exception as e:
            logger.error(f"Auto digest error: {e}")

    return {"status": "ok", "saved": len(saved), "ids": saved, "skipped": skipped}


@app.get("/past-coverage", response_class=HTMLResponse)
def past_coverage(request: Request, db: Session = Depends(get_db)):
    latest_ids = [
        row.id for row in (
            db.query(NewsArticle.id)
            .filter(NewsArticle.is_published == True)
            .order_by(NewsArticle.published_date.desc(), NewsArticle.id.desc())
            .limit(20)
            .all()
        )
    ]
    cutoff = datetime.utcnow() - timedelta(days=14)
    articles = (
        db.query(NewsArticle)
        .filter(
            NewsArticle.is_published == True,
            NewsArticle.published_date >= cutoff,
            ~NewsArticle.id.in_(latest_ids) if latest_ids else True,
        )
        .order_by(NewsArticle.published_date.desc(), NewsArticle.id.desc())
        .all()
    )
    grouped = group_articles_by_date(articles)
    return templates.TemplateResponse(
        "past_coverage.html", {
            "request": request,
            "grouped_articles": grouped,
            **tpl_globals(),
        }
    )


def _read_agentbot_stats():
    """Read cumulative stats from agentbot's data files on the same VPS."""
    import json
    from pathlib import Path
    base = Path("/home/claudeProj/agentbot/data")

    total_ever = None
    try:
        stats = json.loads((base / "article_stats.json").read_text())
        total_ever = stats.get("total_ever")
    except Exception:
        pass

    dedup_count = None
    try:
        dedup = json.loads((base / "published_articles.json").read_text())
        dedup_count = len(dedup)
    except Exception:
        pass

    return total_ever, dedup_count


@app.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin),
    msg: Optional[str] = None,
    sub_page: int = 1,
):
    import math
    total_subs = db.query(Subscriber).count()
    sub_total_pages = max(1, math.ceil(total_subs / 10))
    sub_page = max(1, min(sub_page, sub_total_pages))

    subscribers = (
        db.query(Subscriber)
        .order_by(Subscriber.subscribed_at.desc())
        .limit(10)
        .offset((sub_page - 1) * 10)
        .all()
    )

    active_subs = db.query(Subscriber).filter(Subscriber.is_active == True).count()
    inactive_subs = total_subs - active_subs

    total_articles = db.query(NewsArticle).count()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_articles = db.query(NewsArticle).filter(
        NewsArticle.published_date >= today_start
    ).count()

    articles = db.query(NewsArticle).order_by(
        NewsArticle.published_date.desc()
    ).limit(50).all()

    abbot_total_ever, dedup_count = _read_agentbot_stats()

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "subscribers": subscribers,
            "sub_page": sub_page,
            "sub_total": total_subs,
            "sub_total_pages": sub_total_pages,
            "total_articles": total_articles,
            "today_articles": today_articles,
            "active_subs": active_subs,
            "inactive_subs": inactive_subs,
            "total_subs": total_subs,
            "articles": articles,
            "msg": msg,
            "abbot_total_ever": abbot_total_ever,
            "dedup_count": dedup_count,
        },
    )


@app.post("/admin/add-article")
async def add_article_manual(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Depends(verify_admin),
    title: str = Form(...),
    summary: str = Form(...),
    category: str = Form("General"),
    source_url: str = Form(...),
):
    published_date = datetime.utcnow()

    image_url = proxy_image_url(extract_og_image(source_url))
    source_domain = urlparse(source_url).netloc or None

    article = NewsArticle(
        title=title,
        summary=summary,
        category=category,
        source_url=source_url,
        image_url=image_url,
        source_domain=source_domain,
        published_date=published_date,
        is_published=True,
    )
    db.add(article)
    db.commit()

    return RedirectResponse(
        url=f"/admin?msg=Article+added%3A+{title[:60].replace(' ', '+')}",
        status_code=303,
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


class BroadcastRequest(BaseModel):
    subject: str
    body: str


@app.post("/admin/broadcast")
async def broadcast_email(
        payload: BroadcastRequest,
        db: Session = Depends(get_db),
        username: str = Depends(verify_admin)):
    import resend
    from newsletter import get_from_email, SITE_NAME, _footer_html

    subject = payload.subject.strip()
    body = payload.body.strip()
    if not subject or not body:
        return JSONResponse({"status": "error", "message": "Subject and body are required"})

    subscribers = db.query(Subscriber).filter(Subscriber.is_active == True).all()
    if not subscribers:
        return JSONResponse({"status": "success", "sent": 0, "message": "No active subscribers"})

    from_addr = f"{SITE_NAME} <{get_from_email()}>"
    sent = 0
    errors = []
    for s in subscribers:
        html = f"""<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#333;">
  <p style="font-size:15px;line-height:1.7;white-space:pre-wrap;">{body}</p>
  {_footer_html(s.email)}
</body>
</html>"""
        try:
            resend.Emails.send({
                "from": from_addr,
                "to": s.email,
                "subject": subject,
                "html": html,
            })
            sent += 1
        except Exception as exc:
            logger.error("Broadcast failed for %s: %s", s.email, exc)
            errors.append(str(exc))

    return JSONResponse({
        "status": "success",
        "sent": sent,
        "errors": len(errors),
        "message": f"Sent {sent}/{len(subscribers)} emails",
    })


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


@app.get("/api/trigger-digest")
async def trigger_digest_endpoint(
        request: Request,
        db: Session = Depends(get_db)):
    # Verify API key
    api_key = request.headers.get("X-API-Key", "")
    expected = os.environ.get("WEBSITE_API_KEY", "")
    if not api_key or api_key != expected:
        return JSONResponse(
            {"status": "error", "message": "Unauthorized"},
            status_code=401
        )

    try:
        from newsletter import send_daily_digest

        # Get latest 5 published articles
        articles = db.query(NewsArticle).filter(
            NewsArticle.is_published == True
        ).order_by(
            NewsArticle.published_date.desc(), NewsArticle.id.desc()
        ).limit(5).all()

        article_dicts = [{
            "title": a.title,
            "summary": a.summary,
            "category": a.category,
            "source_url": a.source_url or "",
        } for a in articles]

        sent = send_daily_digest(article_dicts)

        return JSONResponse({
            "status": "success",
            "emails_sent": sent,
            "articles_used": len(article_dicts),
        })

    except Exception as e:
        logger.error(f"Trigger digest error: {e}")
        return JSONResponse(
            {"status": "error", "message": str(e)},
            status_code=500
        )


@app.get("/api/articles")
def api_articles(db: Session = Depends(get_db)):
    articles = (
        db.query(NewsArticle)
        .filter(NewsArticle.is_published == True)
        .order_by(NewsArticle.published_date.desc(), NewsArticle.id.desc())
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

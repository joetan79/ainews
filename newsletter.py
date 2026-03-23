"""
newsletter.py — Email sending via Resend API.

Functions:
    send_welcome_email(email)      — welcome email for new subscribers
    send_daily_digest(articles)    — daily digest to all active subscribers
"""

import os
import hmac
import hashlib
import logging
from dotenv import load_dotenv

load_dotenv()

import resend

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
FROM_EMAIL = os.getenv("FROM_EMAIL", "noreply@example.com")
SITE_NAME = os.getenv("SITE_NAME", "AI & Tech Daily")
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")
SECRET_KEY = os.getenv("WEBSITE_API_KEY", "changeme")

resend.api_key = RESEND_API_KEY

logger = logging.getLogger(__name__)


# ---------- helpers ----------

def _unsubscribe_token(email: str) -> str:
    """Generate a deterministic HMAC token for unsubscribe links."""
    return hmac.new(SECRET_KEY.encode(), email.encode(), hashlib.sha256).hexdigest()[:32]


def _unsubscribe_link(email: str) -> str:
    token = _unsubscribe_token(email)
    return f"{SITE_URL}/unsubscribe?email={email}&token={token}"


def _footer_html(email: str) -> str:
    return f"""
    <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;"/>
    <p style="font-size:12px;color:#9ca3af;text-align:center;">
      You received this because you subscribed to {SITE_NAME}.<br/>
      <a href="{_unsubscribe_link(email)}" style="color:#9ca3af;">Unsubscribe</a>
    </p>
    """


def _header_html() -> str:
    return f"""
    <div style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:28px 32px;border-radius:12px;margin-bottom:24px;">
      <h1 style="color:white;margin:0;font-size:24px;">{SITE_NAME}</h1>
      <p style="color:#c7d2fe;margin:4px 0 0;font-size:13px;">Your Daily AI & Tech Intelligence</p>
    </div>
    """


# ---------- public API ----------

def send_welcome_email(email: str) -> bool:
    """Send a welcome email to a new subscriber. Returns True on success."""
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#333;">
  {_header_html()}
  <h2 style="color:#1f2937;">Welcome aboard!</h2>
  <p>Thanks for subscribing to <strong>{SITE_NAME}</strong>.<br/>
  You'll receive the daily AI &amp; tech digest straight to your inbox — no spam, ever.</p>
  <p>Stay curious,<br/><strong>The {SITE_NAME} Team</strong></p>
  {_footer_html(email)}
</body>
</html>"""

    try:
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": email,
            "subject": f"Welcome to {SITE_NAME}!",
            "html": html,
        })
        logger.info("Welcome email sent to %s", email)
        return True
    except Exception as exc:
        logger.error("Failed to send welcome email to %s: %s", email, exc)
        return False


def send_daily_digest(articles: list) -> int:
    """
    Send the daily digest to all active subscribers.

    Each item in `articles` should be a dict with keys:
        id, title, summary, category

    Returns the number of emails successfully sent.
    """
    if not articles:
        logger.info("No articles — skipping digest.")
        return 0

    # Build article cards HTML once (shared across all emails)
    cards_html = ""
    for a in articles:
        article_id = a.get("id", "")
        article_url = f"{SITE_URL}/article/{article_id}" if article_id else SITE_URL
        summary = a.get("summary", "")
        preview = summary[:220] + ("..." if len(summary) > 220 else "")
        cards_html += f"""
        <div style="border:1px solid #e5e7eb;border-radius:10px;padding:20px;margin-bottom:16px;">
          <span style="background:#eef2ff;color:#4f46e5;font-size:11px;font-weight:600;
                       padding:2px 10px;border-radius:100px;">
            {a.get("category", "AI & Tech")}
          </span>
          <h3 style="margin:10px 0 6px;color:#111827;font-size:16px;">{a.get("title", "")}</h3>
          <p style="color:#6b7280;font-size:14px;margin:0 0 12px;line-height:1.6;">{preview}</p>
          <a href="{article_url}"
             style="color:#4f46e5;font-size:13px;font-weight:600;text-decoration:none;">
            Read more →
          </a>
        </div>"""

    # Fetch active subscribers
    from database import SessionLocal, Subscriber
    db = SessionLocal()
    try:
        subscribers = db.query(Subscriber).filter(Subscriber.is_active == True).all()
        subscriber_emails = [s.email for s in subscribers]
    finally:
        db.close()

    if not subscriber_emails:
        logger.info("No active subscribers — skipping digest.")
        return 0

    sent_count = 0
    for email in subscriber_emails:
        html = f"""<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#333;">
  {_header_html()}
  <h2 style="color:#1f2937;font-size:18px;margin-bottom:16px;">Today's top stories</h2>
  {cards_html}
  <div style="text-align:center;margin-top:24px;">
    <a href="{SITE_URL}"
       style="background:#4f46e5;color:white;padding:12px 28px;border-radius:8px;
              text-decoration:none;font-weight:600;font-size:14px;">
      Read all articles →
    </a>
  </div>
  {_footer_html(email)}
</body>
</html>"""

        try:
            resend.Emails.send({
                "from": FROM_EMAIL,
                "to": email,
                "subject": f"{SITE_NAME} — Daily Digest",
                "html": html,
            })
            sent_count += 1
            logger.info("Digest sent to %s", email)
        except Exception as exc:
            logger.error("Failed to send digest to %s: %s", email, exc)

    logger.info("Daily digest: %d/%d emails sent.", sent_count, len(subscriber_emails))
    return sent_count

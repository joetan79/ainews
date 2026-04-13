# ainews Master Documentation
**Version:** April 2026  
**URL:** https://abai.cloud  
**Purpose:** Brief a new AI conversation about the ainews project so development can continue.

---

## TABLE OF CONTENTS

1. [Project Overview](#1-project-overview)
2. [File Structure](#2-file-structure)
3. [Routes and Endpoints](#3-routes-and-endpoints)
4. [Database Models](#4-database-models)
5. [Email System](#5-email-system)
6. [Admin Interface](#6-admin-interface)
7. [Environment Variables](#7-environment-variables)
8. [Integration with ABbot](#8-integration-with-abbot)
9. [Frontend Features](#9-frontend-features)
10. [Development Commands](#10-development-commands)
11. [Pending Improvements](#11-pending-improvements)

---

## 1. PROJECT OVERVIEW

ainews is a FastAPI web application that:
- Receives AI & tech news articles published by ABbot (Telegram bot)
- Displays them on a clean dark/light mode website with Google Translate
- Sends email digests to subscribers via Resend API
- Provides an admin dashboard for managing articles and subscribers

| Item | Value |
|------|-------|
| Location | `/home/claudeProj/ainews/` |
| URL | https://abai.cloud |
| Running | screen session `ainews` |
| Start command | `uvicorn main:app --host 127.0.0.1 --port 8000` |
| Proxy | Nginx reverse proxy with SSL |
| Framework | FastAPI + Jinja2 + SQLite (SQLAlchemy) |
| GitHub | joetan79/ainews (private) |

---

## 2. FILE STRUCTURE

```
/home/claudeProj/ainews/
├── main.py                 # FastAPI backend, all routes and API logic
├── database.py             # SQLAlchemy models: NewsArticle, Subscriber
├── newsletter.py           # Resend email: welcome email, digest email
├── abbot_publisher.py      # Helper used by ABbot to publish articles (not served)
├── sample_data.py          # Dev/test seed data script
├── nginx.conf              # Nginx reverse proxy configuration
├── setup_https.sh          # Script to set up SSL/HTTPS with Certbot
├── setup_no_domain.sh      # Setup script without custom domain
├── start.sh                # uvicorn startup script
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (NOT in git)
├── .env.example            # Template for .env
├── ainews.db               # SQLite database file
│
├── templates/
│   ├── base.html           # Base layout (dark/light toggle, Google Translate, nav)
│   ├── index.html          # Homepage: articles grouped by date, subscriber count
│   ├── article.html        # Single article detail + 3 related articles
│   ├── admin.html          # Admin dashboard (articles + subscribers management)
│   └── unsubscribe.html    # Email unsubscribe confirmation page
│
└── static/
    ├── style.css           # All site styles (dark/light mode, responsive)
    ├── favicon.ico
    ├── favicon.svg
    └── apple-touch-icon.png
```

---

## 3. ROUTES AND ENDPOINTS

### Public Routes
| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/` | Homepage — latest 20 published articles grouped by date |
| GET | `/article/{id}` | Single article with title, summary, source link, 3 related |
| POST | `/subscribe` | Email subscription — validates email, sends welcome email |
| GET | `/unsubscribe?email=...` | Unsubscribe page — deactivates subscriber |

### API Routes
| Method | Route | Auth | Purpose |
|--------|-------|------|---------|
| POST | `/api/publish` | X-API-Key or Bearer token | ABbot publishes articles here |

**Publish endpoint details:**
- Accepts `{"articles": [{"title", "summary", "category", "source_url"}, ...]}`
- Deduplicates by title to prevent double-posting
- Sets `published_date` to current UTC time
- After saving, triggers `send_digest_email()` to all active subscribers
- Returns `{"status": "ok", "published": N, "skipped": N}`

### Admin Routes (HTTP Basic Auth: `admin` / `ADMIN_PASSWORD`)
| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/admin` | Dashboard with article list and subscriber list |
| POST | `/admin/article/{id}/toggle` | Toggle article published/unpublished |
| POST | `/admin/article/{id}/delete` | Delete article permanently |
| GET | `/admin/export` | Export subscriber emails as CSV |

---

## 4. DATABASE MODELS

**File:** `database.py` — SQLAlchemy with SQLite

### `NewsArticle`
```python
id            Integer  PK
title         String(500)
summary       Text
category      String(100)  default="AI & Tech"
source_url    String(1000) nullable
published_date DateTime    default=datetime.utcnow
is_published  Boolean      default=True
```

### `Subscriber`
```python
id            Integer  PK
email         String(255) unique
subscribed_at DateTime
is_active     Boolean  default=True
```

---

## 5. EMAIL SYSTEM

**File:** `newsletter.py`  
**Service:** Resend API  
**From:** `noreply@abai.cloud` (FROM_EMAIL env var)

### `send_welcome_email(email)`
Sent when new subscriber signs up or reactivates. Confirms subscription with unsubscribe link.

### `send_digest_email(articles, subscribers)`
Sent when ABbot publishes new articles. Lists article titles and summaries with source links. Includes unsubscribe link per subscriber.

### Email trigger flow
1. ABbot calls `POST /api/publish` with new articles
2. `main.py` saves articles to DB
3. `send_digest_email()` called with newly saved articles + all active subscribers
4. Each subscriber receives the digest

---

## 6. ADMIN INTERFACE

**URL:** `/admin`  
**Auth:** HTTP Basic — username: `admin`, password: `ADMIN_PASSWORD` env var  

**Features:**
- View all articles with published status toggle
- Delete articles
- View all subscribers with active/inactive status
- Export subscriber list as CSV download

---

## 7. ENVIRONMENT VARIABLES

```bash
# ainews/.env
WEBSITE_API_KEY=your_secret_api_key     # Shared with ABbot for /api/publish auth
SITE_URL=https://abai.cloud             # Used in email links
SITE_NAME=AI & Tech Daily               # Used in email templates
RESEND_API_KEY=your_resend_key          # Resend email service API key
FROM_EMAIL=noreply@abai.cloud           # Email sender address
DATABASE_URL=sqlite:///./ainews.db      # SQLite database path
ADMIN_PASSWORD=your_admin_password      # HTTP Basic auth for /admin
```

---

## 8. INTEGRATION WITH ABBOT

ABbot (`/home/claudeProj/agentbot/`) publishes articles to ainews via HTTP POST.

### Publish call in `modules/agent.py`:
```python
import httpx, os
response = httpx.post(
    f"{os.environ['WEBSITE_URL']}/api/publish",
    json={"articles": [
        {
            "title": "Article Title",
            "summary": "2-3 sentence summary",
            "category": "AI & Tech",
            "source_url": "https://source.com/article"
        }
    ]},
    headers={
        "X-API-Key": os.environ["WEBSITE_API_KEY"],
        "Authorization": f"Bearer {os.environ['WEBSITE_API_KEY']}"
    },
    timeout=30,
)
```

### Triggered by:
- Scheduled news jobs (02:00, 10:00, 18:00 daily) automatically publish to website
- `/news` command from owner also publishes
- ABbot deduplicates articles using `published_articles.json` before sending

### Shared secret:
`WEBSITE_API_KEY` is in both `.env` files. Must match for auth to work.

---

## 9. FRONTEND FEATURES

### Dark/Light Mode
- CSS custom properties for color themes
- Toggle button in nav bar
- Preference saved in `localStorage`

### Google Translate
- Google Translate widget embedded in `base.html`
- Supports English ↔ Chinese and other languages
- Auto-detects page language

### Article Display
- Grouped by date on homepage
- Category badges (AI & Tech, AI Models, AI Business, AI Research, etc.)
- Source link on each article
- Responsive layout for mobile

### Email Subscription
- Form on homepage
- AJAX submission, shows success/error inline
- Double-submit prevention
- Valid email regex validation (server-side)

---

## 10. DEVELOPMENT COMMANDS

```bash
# Change to ainews directory
cd /home/claudeProj/ainews

# Activate venv
source venv/bin/activate

# Start development server
uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Run in screen (production)
screen -r ainews
# Ctrl+C to stop
uvicorn main:app --host 127.0.0.1 --port 8000
# Ctrl+A then D to detach

# Check port
lsof -i :8000

# Kill port 8000
kill -9 $(lsof -t -i:8000)

# View database
sqlite3 ainews.db ".tables"
sqlite3 ainews.db "SELECT COUNT(*) FROM newsarticle;"
sqlite3 ainews.db "SELECT COUNT(*) FROM subscriber WHERE is_active=1;"

# Sync to GitHub
cd /home/claudeProj/ainews && gsync

# Claude Code for ainews
cd /home/claudeProj/ainews && claude
```

---

## 11. PENDING IMPROVEMENTS

- Article full-text fetching (currently shows RSS summary only)
- Pagination on homepage (currently shows last 20)
- Category filtering on homepage
- Search functionality
- RSS feed for ainews itself
- Article view count tracking
- Social sharing buttons
- Mobile app
- Comment system
- Multiple newsletter digest frequencies (daily vs. immediate)

---

*Generated from project files — April 13, 2026*  
*Location: `/home/claudeProj/ainews/AINEWS_MASTER.md`*  
*See also: `/home/claudeProj/agentbot/ABBOT_MASTER.md` for the full ABbot system documentation.*

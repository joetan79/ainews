# AI & Tech Daily

Automated AI news website powered by ABbot.

## Features
- Daily AI & tech news auto-published
- Email newsletter subscription
- Responsive design
- Nginx + SSL

## Setup
1. Clone repo
2. python3 -m venv venv
3. source venv/bin/activate
4. pip install -r requirements.txt
5. cp .env.example .env
6. Fill in your configuration values
7. uvicorn main:app --host 127.0.0.1 --port 8000

## Tech Stack
- Python FastAPI
- SQLAlchemy + SQLite
- Jinja2 Templates
- Tailwind CSS
- Nginx + SSL

# AI & Tech Daily

Automated AI news website powered by ABbot.

## Features
- Daily AI & tech news auto-published
- Email newsletter subscription
- Responsive design
- Nginx + SSL on abai.cloud

## Setup
1. Clone repo
2. python3 -m venv venv
3. source venv/bin/activate
4. pip install -r requirements.txt
5. cp .env.example .env && nano .env
6. uvicorn main:app --host 127.0.0.1 --port 8000

## Tech Stack
- FastAPI + SQLAlchemy
- Jinja2 + Tailwind CSS
- Nginx + SSL (Let's Encrypt)

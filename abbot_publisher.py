"""
ABbot Publisher — posts collected news articles to the ABbot Daily website.

Usage:
    from abbot_publisher import publish_to_website

    articles = [
        {
            "title": "GPT-5 Released",
            "summary": "OpenAI released GPT-5 today...",
            "category": "AI Models",
            "source_url": "https://example.com/gpt5",
        }
    ]
    result = publish_to_website(articles)
"""

import logging
import os

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def trigger_digest() -> None:
    """
    Call GET /api/trigger-digest on the website to send the newsletter
    to all subscribers.
    """
    load_dotenv(dotenv_path="/home/claudeProj/agentbot/.env")
    api_key = os.getenv("WEBSITE_API_KEY", "changeme")
    base_url = os.getenv("WEBSITE_URL", "http://localhost:8000")

    endpoint = f"{base_url.rstrip('/')}/api/trigger-digest"
    headers = {"X-API-Key": api_key}

    with httpx.Client(timeout=30) as client:
        response = client.get(endpoint, headers=headers)
        response.raise_for_status()
        result = response.json()

    sent = result.get("emails_sent", result.get("sent", 0))
    logger.info(f"[publisher] Digest triggered — {sent} email(s) sent to subscribers.")


def publish_to_website(articles: list) -> bool:
    """
    Publish a list of article dicts to the AI & Tech Daily website.

    Each dict should contain:
        - title      (str, required)
        - summary    (str, required)
        - category   (str, optional, default "AI & Tech")
        - source_url (str, optional)

    Returns True on success, False on failure.
    """
    try:
        load_dotenv(dotenv_path="/home/claudeProj/agentbot/.env")
        api_key = os.getenv("WEBSITE_API_KEY", "changeme")
        base_url = os.getenv("WEBSITE_URL", "http://localhost:8000")

        if not articles:
            logger.error("[publisher] No articles provided — aborting publish.")
            return False

        endpoint = f"{base_url.rstrip('/')}/api/publish"
        payload = {"articles": articles}
        headers = {
            "X-API-Key": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=30) as client:
            response = client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()

        logger.info(f"[publisher] Published {len(articles)} articles to website.")
        trigger_digest()
        return True

    except Exception as e:
        logger.error(f"[publisher] Failed to publish articles: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_articles = [
        {
            "title": "Test Article",
            "summary": "This is a test summary.",
            "category": "AI & Tech",
            "source_url": "https://example.com",
        }
    ]
    result = publish_to_website(test_articles)
    print(f"Test result: {result}")

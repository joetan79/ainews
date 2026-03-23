"""Insert 3 sample AI news articles for testing."""
from datetime import datetime, timedelta
from database import init_db, SessionLocal, NewsArticle

init_db()

db = SessionLocal()

articles = [
    NewsArticle(
        title="Google DeepMind Unveils Gemini Ultra 2.0 with Multimodal Reasoning",
        summary=(
            "Google DeepMind has released Gemini Ultra 2.0, its most capable AI model to date, "
            "featuring advanced multimodal reasoning across text, images, audio, and video. "
            "The model achieves state-of-the-art performance on 30 out of 32 academic benchmarks "
            "and introduces a novel 'chain-of-thought vision' technique that allows the model to "
            "reason step-by-step about complex visual scenes. Early testers report dramatic "
            "improvements in coding assistance, scientific analysis, and creative tasks compared "
            "to the previous generation. Gemini Ultra 2.0 will be available to Gemini Advanced "
            "subscribers starting next week."
        ),
        category="AI Models",
        source_url="https://deepmind.google/gemini-ultra-2",
        published_date=datetime.utcnow() - timedelta(hours=2),
    ),
    NewsArticle(
        title="OpenAI Launches o3 API with 10x Cost Reduction for Enterprise",
        summary=(
            "OpenAI announced general availability of its o3 reasoning model through the API, "
            "targeting enterprise customers with a 10x price reduction over the o1 series. "
            "The company says o3 excels at complex multi-step tasks including legal document review, "
            "financial modeling, and software architecture design. A new 'Structured Thinking' feature "
            "lets developers inspect the model's internal reasoning traces, giving teams greater "
            "insight into how conclusions are reached. Microsoft Azure customers will get priority "
            "access as part of the existing partnership."
        ),
        category="AI Business",
        source_url="https://openai.com/api/o3",
        published_date=datetime.utcnow() - timedelta(hours=5),
    ),
    NewsArticle(
        title="EU AI Act Enforcement Begins: What Tech Companies Need to Know",
        summary=(
            "The European Union's AI Act has entered its enforcement phase, with companies now "
            "required to comply with risk-based regulations governing the development and deployment "
            "of artificial intelligence systems. High-risk applications — including AI used in hiring, "
            "credit scoring, and critical infrastructure — must pass conformity assessments and "
            "maintain detailed technical documentation. The EU AI Office has published a compliance "
            "toolkit to help small and medium enterprises navigate the new rules. Non-compliance "
            "can result in fines of up to €35 million or 7% of global annual turnover, whichever "
            "is higher. Industry groups have called for clearer guidance on open-source model obligations."
        ),
        category="AI Policy",
        source_url="https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai",
        published_date=datetime.utcnow() - timedelta(hours=8),
    ),
]

db.add_all(articles)
db.commit()
print(f"Inserted {len(articles)} sample articles successfully.")
db.close()

import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, func, text, inspect as sa_inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ainews.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class NewsArticle(Base):
    __tablename__ = "news_articles"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=False)
    category = Column(String, default="AI & Tech")
    source_url = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    source_domain = Column(String, nullable=True)
    published_date = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_published = Column(Boolean, default=True)


class XPost(Base):
    __tablename__ = "x_posts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    summary = Column(Text, nullable=True)
    source_url = Column(String, unique=True, nullable=False)
    source_name = Column(String, nullable=True)
    published_date = Column(String, nullable=True)
    created_at = Column(DateTime, default=func.now())
    is_published = Column(Boolean, default=True)


class Subscriber(Base):
    __tablename__ = "subscribers"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    subscribed_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)


class WhiteboardContent(Base):
    __tablename__ = "whiteboard_content"

    id = Column(Integer, primary_key=True)
    content = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow)


class WhiteboardNote(Base):
    __tablename__ = "whiteboard_notes"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False, default="Untitled")
    content = Column(Text, nullable=False, default="")
    image_data = Column(Text, nullable=True)
    has_image = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_db():
    """Add columns that were added after initial table creation."""
    inspector = sa_inspect(engine)
    if "whiteboard_notes" in inspector.get_table_names():
        existing = {c["name"] for c in inspector.get_columns("whiteboard_notes")}
        with engine.connect() as conn:
            if "title" not in existing:
                conn.execute(text(
                    "ALTER TABLE whiteboard_notes ADD COLUMN title VARCHAR(200) NOT NULL DEFAULT 'Untitled'"
                ))
            if "updated_at" not in existing:
                conn.execute(text(
                    "ALTER TABLE whiteboard_notes ADD COLUMN updated_at DATETIME"
                ))
            conn.commit()


def init_db():
    Base.metadata.create_all(bind=engine)
    _migrate_db()

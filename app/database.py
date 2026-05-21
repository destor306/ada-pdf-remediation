"""
SQLite database setup via SQLAlchemy.
Uses DATABASE_URL env var when set (e.g. Supabase PostgreSQL), falls back to SQLite for local dev.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "ada.db"
_raw_url = os.environ.get("DATABASE_URL", "").strip()

# Fall back to SQLite if DATABASE_URL is not set or empty
if not _raw_url:
    DATABASE_URL = f"sqlite:///{DB_PATH}"
elif _raw_url.startswith("postgres://"):
    # Supabase uses postgres:// but SQLAlchemy needs postgresql://
    DATABASE_URL = _raw_url.replace("postgres://", "postgresql://", 1)
else:
    DATABASE_URL = _raw_url

connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401 — registers models
    Base.metadata.create_all(bind=engine)

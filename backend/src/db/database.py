"""Database connection and session management."""

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from src.core.config import settings
from src.db.models import Base

logger = logging.getLogger(__name__)

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=not _is_sqlite,
    **({} if _is_sqlite else {"pool_size": 5, "max_overflow": 10}),
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables and apply additive schema upgrades."""
    Base.metadata.create_all(bind=engine)
    _apply_schema_upgrades()
    logger.info("Database tables initialized")


def _apply_schema_upgrades() -> None:
    """
    Idempotent ALTER TABLE migrations for existing deployments.
    Uses PostgreSQL IF NOT EXISTS — safe to run on every startup.
    """
    migrations = [
        # v2: DL embedding FAISS row ID
        "ALTER TABLE assets ADD COLUMN IF NOT EXISTS dl_faiss_row_id INTEGER;",
    ]
    try:
        with engine.connect() as conn:
            for sql in migrations:
                conn.execute(text(sql))
            conn.commit()
        logger.debug("Schema upgrades applied")
    except Exception as e:
        logger.warning(f"Schema upgrade warning (non-fatal): {e}")


def check_db() -> bool:
    """Return True if database is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error(f"Database check failed: {e}")
        return False


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for database sessions with automatic cleanup."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency for database sessions."""
    with get_db_session() as session:
        yield session

"""
SQLAlchemy engine, session factory, and base declarative class.

Design decision: we use ``sessionmaker`` with ``expire_on_commit=False`` so that
objects remain accessible after a commit without triggering lazy-load queries
against a potentially closed session. This is important for the scoring path
where we create an Assessment, commit it, and then immediately serialise it.

The engine is created lazily via ``get_engine()`` so that importing this module
for tests (which don't need a database) does not require a database driver.

Neon serverless Postgres closes idle connections after ~5 minutes, so we:
  - Enable ``pool_pre_ping`` to detect stale connections before use.
  - Set ``pool_recycle=300`` to proactively recycle connections every 5 min.
  - Keep the pool small (5+10 overflow) since serverless scales on demand.
  - Add a ``connect_timeout`` so cold-start connections don't hang indefinitely.
"""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model."""


@lru_cache
def get_engine():
    """Lazy engine creation — only connects when actually needed."""
    _settings = get_settings()
    return create_engine(
        _settings.database_url,
        echo=_settings.sql_echo,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=3,
        max_overflow=5,
        pool_timeout=10,
        connect_args={"connect_timeout": 10},
    )


def _get_session_factory():
    """Build a sessionmaker bound to the lazy engine."""
    return sessionmaker(
        bind=get_engine(),
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


def get_db():
    """FastAPI dependency that yields a scoped session and guarantees cleanup."""
    SessionLocal = _get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

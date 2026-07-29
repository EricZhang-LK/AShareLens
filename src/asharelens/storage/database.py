"""Database engine and session construction."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative root imported by Alembic and repositories."""


def create_database_engine(
    url: str,
    *,
    echo: bool = False,
) -> Engine:
    """Create an engine with production-safe liveness defaults."""

    parsed = make_url(url)
    options: dict[str, object] = {
        "echo": echo,
        "pool_pre_ping": True,
    }
    if parsed.get_backend_name() == "mysql":
        options["pool_recycle"] = 3600
        options["connect_args"] = {"charset": "utf8mb4"}
    return create_engine(url, **options)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create explicit-transaction sessions with no post-commit expiry."""

    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


"""SQLAlchemy engine/session setup for the persistent project and job store."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    _settings.resolved_database_url,
    connect_args={"check_same_thread": False}
    if _settings.resolved_database_url.startswith("sqlite")
    else {},
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
    if _settings.resolved_database_url.startswith("sqlite"):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    from . import models  # noqa: F401  (register tables)

    Base.metadata.create_all(engine)
    _migrate()


def _migrate() -> None:
    """Add columns introduced after a table was first created (SQLite has no ALTER ... IF NOT EXISTS)."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    wanted = {
        "projects": {"plan": "JSON"},
    }
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if table not in insp.get_table_names():
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for col, ddl in cols.items():
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session

from __future__ import annotations

from pathlib import Path
import os

from sqlalchemy import Engine, create_engine

from backend.app.database.models import Base


DEFAULT_DB = Path(__file__).resolve().parents[3] / "data" / "dermaguard.db"


def init_database(database_url: str | None = None) -> Engine:
    if database_url is None:
        database_url = os.getenv("DERMAGUARD_DATABASE_URL")
    if database_url is None:
        DEFAULT_DB.parent.mkdir(parents=True, exist_ok=True)
        database_url = f"sqlite:///{DEFAULT_DB}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    return engine

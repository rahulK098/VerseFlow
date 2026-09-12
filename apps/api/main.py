from contextlib import asynccontextmanager
from os import getenv
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect as sa_inspect, text

from database import Base, engine
from routers import exports, jobs, uploads


# Columns added after the initial schema, per table (dev-only, idempotent)
_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "renders": [
        ("label",      "ALTER TABLE renders ADD COLUMN label VARCHAR(256)"),
        ("start_sec",  "ALTER TABLE renders ADD COLUMN start_sec FLOAT"),
        ("end_sec",    "ALTER TABLE renders ADD COLUMN end_sec FLOAT"),
        ("template",   "ALTER TABLE renders ADD COLUMN template VARCHAR(64)"),
        ("background", "ALTER TABLE renders ADD COLUMN background VARCHAR(32)"),
        ("aspect",     "ALTER TABLE renders ADD COLUMN aspect VARCHAR(16)"),
    ],
    "jobs": [
        ("source_type", "ALTER TABLE jobs ADD COLUMN source_type VARCHAR(16) DEFAULT 'audio'"),
    ],
}


def _migrate_db() -> None:
    inspector = sa_inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.connect() as conn:
        for table, cols in _MIGRATIONS.items():
            if table not in tables:
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for col, ddl in cols:
                if col not in existing:
                    conn.execute(text(ddl))
        conn.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    for env_key in ("UPLOAD_DIR", "EXPORT_DIR"):
        d = getenv(env_key)
        if d:
            Path(d).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate_db()
    yield


app = FastAPI(
    title="VerseFlow API",
    description="Upload a song → generate Shorts and lyric videos using open-source AI",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(uploads.router, prefix="/api", tags=["uploads"])
app.include_router(jobs.router, prefix="/api", tags=["jobs"])
app.include_router(exports.router, prefix="/api", tags=["exports"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "verseflow-api", "version": "0.3.0"}

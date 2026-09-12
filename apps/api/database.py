import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///C:/openSource/VerseFlow/verseflow.db")

# Normalize asyncpg URLs to sync psycopg2 driver
if "+asyncpg" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("+asyncpg", "")

# On first Docker start the data volume is empty — create the SQLite parent dir now
# so SQLAlchemy doesn't fail when it tries to open the file.
if DATABASE_URL.startswith("sqlite"):
    _db_file = DATABASE_URL.split("///", 1)[-1]
    if _db_file:
        Path(_db_file).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass

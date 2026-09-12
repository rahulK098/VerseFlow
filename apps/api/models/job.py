import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # pending → analyzing → ready (transcription done, waiting for user to generate clips)
    # failed if anything goes wrong
    status: Mapped[str] = mapped_column(String(32), default="pending")
    title: Mapped[str] = mapped_column(String(512), default="")
    input_file: Mapped[str] = mapped_column(String(1024), default="")
    source_type: Mapped[str] = mapped_column(String(16), default="audio")  # audio | video
    analysis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    renders: Mapped[list["Render"]] = relationship("Render", back_populates="job", cascade="all, delete-orphan")
    assets: Mapped[list["Asset"]] = relationship("Asset", back_populates="job", cascade="all, delete-orphan")


class Render(Base):
    __tablename__ = "renders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(64), default="clip")
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    start_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    template: Mapped[str | None] = mapped_column(String(64), nullable=True)
    background: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aspect: Mapped[str | None] = mapped_column(String(16), nullable=True)  # 9:16 | 16:9 | 1:1
    status: Mapped[str] = mapped_column(String(32), default="queued")
    output_file: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job: Mapped["Job"] = relationship("Job", back_populates="renders")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("jobs.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(256))
    local_path: Mapped[str] = mapped_column(String(1024))
    query: Mapped[str] = mapped_column(String(512))

    job: Mapped["Job"] = relationship("Job", back_populates="assets")

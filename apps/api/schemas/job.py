from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class RenderOut(BaseModel):
    id: str
    type: str
    label: str | None = None
    template: str | None = None
    background: str | None = None
    aspect: str | None = None
    status: str
    start_sec: float | None = None
    end_sec: float | None = None
    output_file: str | None = None
    duration_sec: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: str
    status: str
    title: str
    input_file: str
    source_type: str = "audio"
    error: str | None = None
    created_at: datetime
    updated_at: datetime
    renders: list[RenderOut] = []
    # Populated by the router after parsing analysis_json
    duration_sec: float | None = None
    transcript: str | None = None
    segments: list[dict] = []
    highlights: list[dict] = []

    model_config = {"from_attributes": True}


class JobList(BaseModel):
    id: str
    status: str
    title: str
    source_type: str = "audio"
    created_at: datetime
    render_count: int = 0

    model_config = {"from_attributes": True}


class ProgressOut(BaseModel):
    percent: int
    stage: str
    message: str
    updated_at: str | None = None


class ClipRequest(BaseModel):
    start_sec: float = 0.0
    end_sec: float
    label: str | None = None
    template: Literal["minimal", "bold", "karaoke", "neon", "pop", "slide"] = "minimal"
    background: Literal["stock", "blank", "visualizer", "waves", "scope", "source"] = "stock"
    aspect: Literal["9:16", "16:9", "1:1"] = "9:16"
    title_card: bool = False  # burn the label as a top title for the first 3 s

    @field_validator("label")
    @classmethod
    def _clean_label(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return v.strip()[:200] or None

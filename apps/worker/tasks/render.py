import json
import os
import sys
from pathlib import Path

_API_PATH = Path(__file__).resolve().parent.parent.parent / "api"
if str(_API_PATH) not in sys.path:
    sys.path.insert(0, str(_API_PATH))

import redis as redis_lib

from celery_app import app
from pipeline.captions import build_ass_captions
from pipeline.ffmpeg_runner import render_video

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
EXPORT_DIR = Path(os.getenv("EXPORT_DIR", "C:/openSource/VerseFlow/exports"))


def _redis():
    try:
        r = redis_lib.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def _db():
    from database import SessionLocal
    return SessionLocal()


@app.task(name="tasks.render.render_job", bind=True, max_retries=1)
def render_job(
    self,
    job_id: str,
    render_id: str,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    template: str = "minimal",
    background: str = "stock",
    aspect: str = "9:16",
    title: str | None = None,
):
    """Render a single user-defined clip and update its Render record."""
    r = _redis()
    try:
        from models.job import Asset, Job, Render

        db = _db()
        job = db.query(Job).filter(Job.id == job_id).first()
        render = db.query(Render).filter(Render.id == render_id).first()
        if not job or not render:
            db.close()
            return {"error": "job or render not found"}

        analysis = json.loads(job.analysis_json) if job.analysis_json else {}
        input_file = job.input_file
        total_duration = analysis.get("duration_sec", 30.0)
        if end_sec is None:
            end_sec = total_duration

        # Load cached stock clips only when they'll be used as the background.
        stock_clips: list[str] = []
        if background == "stock":
            assets = db.query(Asset).filter(Asset.job_id == job_id).all()
            stock_clips = [a.local_path for a in assets if Path(a.local_path).exists()]

        # "source" background cuts the clip from the uploaded video itself
        source_video = input_file if background == "source" else None

        render.status = "rendering"
        db.commit()
        db.close()

        segment_duration = round(end_sec - start_sec, 3)

        all_words = analysis.get("words", [])
        segment_words = [
            {
                **w,
                "start": round(w["start"] - start_sec, 3),
                "end":   round(w["end"]   - start_sec, 3),
            }
            for w in all_words
            if start_sec <= w.get("start", 0.0) < end_sec
        ]

        export_dir = EXPORT_DIR / job_id
        export_dir.mkdir(parents=True, exist_ok=True)

        output_path = str(export_dir / f"{render_id}.mp4")
        ass_path    = str(export_dir / f"{render_id}.ass")

        # Beats inside this segment, shifted 0-relative — drives beat-synced cuts
        segment_beats = [
            round(b - start_sec, 3)
            for b in analysis.get("beats", [])
            if start_sec < b < end_sec
        ]

        timeline = {
            "type":            "clip",
            "audio_file":      input_file,
            "audio_start_sec": start_sec,
            "total_duration":  segment_duration,
            "beat_times":      segment_beats,
        }

        build_ass_captions(segment_words, ass_path, template=template, aspect=aspect, title=title)
        render_video(
            timeline,
            ass_path,
            output_path,
            stock_clips=stock_clips or None,
            background=background,
            aspect=aspect,
            source_video=source_video,
        )

        db = _db()
        render = db.query(Render).filter(Render.id == render_id).first()
        if render:
            render.status = "done"
            render.output_file = output_path
            render.duration_sec = segment_duration
        db.commit()
        db.close()

        if r:
            r.setex(
                f"render:{render_id}:done", 60,
                json.dumps({"render_id": render_id, "status": "done"}),
            )

        return {"render_id": render_id, "status": "done"}

    except Exception as exc:
        db = _db()
        render = db.query(Render).filter(Render.id == render_id).first()  # type: ignore[assignment]
        if render:
            render.status = "failed"
            db.commit()
        db.close()
        raise self.retry(exc=exc, countdown=30)

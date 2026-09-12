import asyncio
import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from database import SessionLocal
from deps import get_db
from models.job import Job, Render
from schemas.job import ClipRequest, JobList, JobOut, ProgressOut, RenderOut

router = APIRouter()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_STATUS_MAP: dict[str, tuple[int, str, str]] = {
    "pending":     (0,   "pending",     "Waiting to start — is the worker running?"),
    "downloading": (10,  "downloading", "Downloading media from URL"),
    "analyzing":   (50,  "analyzing",   "Transcribing audio with Whisper"),
    "ready":       (100, "ready",       "Transcription complete — choose a section below"),
    "failed":      (0,   "failed",      "Processing failed"),
}


def _redis():
    try:
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def _parse_analysis(job: Job) -> dict:
    if job.analysis_json:
        try:
            return json.loads(job.analysis_json)
        except Exception:
            pass
    return {}


def _job_out(job: Job) -> dict:
    """Build a JobOut-compatible dict with parsed analysis fields."""
    analysis = _parse_analysis(job)
    return {
        "id": job.id,
        "status": job.status,
        "title": job.title,
        "input_file": job.input_file,
        "source_type": job.source_type or "audio",
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "renders": job.renders,
        "duration_sec": analysis.get("duration_sec"),
        "transcript": analysis.get("transcript"),
        "segments": analysis.get("segments", []),
        "highlights": analysis.get("highlights", []),
    }


# ── Project list / detail ──────────────────────────────────────────────────

@router.get("/jobs", response_model=list[JobList])
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).all()
    return [
        JobList(
            id=j.id, status=j.status, title=j.title,
            source_type=j.source_type or "audio",
            created_at=j.created_at, render_count=len(j.renders),
        )
        for j in jobs
    ]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return _job_out(job)


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    db.delete(job)
    db.commit()


# ── Audio streaming ───────────────────────────────────────────────────────

@router.get("/jobs/{job_id}/audio")
def stream_audio(job_id: str, db: Session = Depends(get_db)):
    """Stream the original uploaded audio file so the browser can play it."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    path = Path(job.input_file)
    if not path.exists():
        raise HTTPException(404, "Audio file missing on disk")
    mime, _ = mimetypes.guess_type(str(path))
    return FileResponse(str(path), media_type=mime or "audio/mpeg")


# ── Clip generation ───────────────────────────────────────────────────────

@router.post("/jobs/{job_id}/clips", response_model=RenderOut, status_code=201)
def generate_clip(job_id: str, req: ClipRequest, db: Session = Depends(get_db)):
    """Create a render for a user-defined time range and queue it."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if not job.analysis_json:
        raise HTTPException(400, "Transcription not ready yet")

    analysis = _parse_analysis(job)
    total = analysis.get("duration_sec", 0.0)
    end_sec = min(req.end_sec, total)

    if req.start_sec < 0 or req.start_sec >= end_sec:
        raise HTTPException(400, f"Invalid range {req.start_sec:.1f}–{end_sec:.1f}s (song is {total:.1f}s)")

    label = req.label or f"{req.start_sec:.0f}s – {end_sec:.0f}s"

    # Video projects default to their own footage unless the user chose otherwise
    background = req.background
    if background == "stock" and (job.source_type or "audio") == "video":
        background = "source"

    render = Render(
        job_id=job_id,
        type="clip",
        label=label,
        template=req.template,
        background=background,
        aspect=req.aspect,
        start_sec=req.start_sec,
        end_sec=end_sec,
        status="queued",
    )
    db.add(render)
    db.commit()
    db.refresh(render)

    try:
        worker_path = Path(__file__).resolve().parent.parent.parent / "worker"
        if str(worker_path) not in sys.path:
            sys.path.insert(0, str(worker_path))
        from tasks.render import render_job  # noqa: PLC0415
        render_job.apply_async(
            args=[job_id, render.id, req.start_sec, end_sec],
            kwargs={
                "template": req.template,
                "background": background,
                "aspect": req.aspect,
                "title": label if req.title_card else None,
            },
            queue="render_queue",
        )
    except Exception as exc:
        print(f"[generate_clip] Could not queue task: {exc}")

    return render


# ── Render management ──────────────────────────────────────────────────────

@router.delete("/renders/{render_id}", status_code=204)
def delete_render(render_id: str, db: Session = Depends(get_db)):
    render = db.query(Render).filter(Render.id == render_id).first()
    if not render:
        raise HTTPException(404, "Render not found")
    if render.output_file:
        try:
            Path(render.output_file).unlink(missing_ok=True)
            Path(render.output_file).with_suffix(".ass").unlink(missing_ok=True)
        except Exception:
            pass
    db.delete(render)
    db.commit()


# ── SSE progress stream ───────────────────────────────────────────────────

@router.get("/jobs/{job_id}/progress", response_model=ProgressOut)
def get_progress(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    r = _redis()
    if r:
        raw = r.get(f"job:{job_id}:progress")
        if raw:
            return ProgressOut(**json.loads(raw))
    pct, stage, msg = _STATUS_MAP.get(job.status, (0, "unknown", "Unknown status"))
    if job.status == "failed" and job.error:
        msg = job.error[:200]
    return ProgressOut(percent=pct, stage=stage, message=msg)


@router.get("/jobs/{job_id}/stream")
async def stream_progress(job_id: str):
    with SessionLocal() as _check:
        if not _check.query(Job).filter(Job.id == job_id).first():
            raise HTTPException(404, "Job not found")

    async def _gen() -> AsyncIterator[str]:
        try:
            r = _redis()
            while True:
                with SessionLocal() as db:
                    job = db.query(Job).filter(Job.id == job_id).first()
                    if not job:
                        break

                    payload: str | None = None
                    if r:
                        raw = r.get(f"job:{job_id}:progress")
                        if raw:
                            payload = raw
                    if payload is None:
                        pct, stage, msg = _STATUS_MAP.get(job.status, (0, "unknown", "Unknown"))
                        if job.status == "failed" and job.error:
                            msg = job.error[:200]
                        payload = json.dumps({"percent": pct, "stage": stage, "message": msg})

                    yield f"data: {payload}\n\n"

                    # Exit once analysis is done or failed — rendering is tracked per-clip
                    if job.status in ("ready", "failed"):
                        break

                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(_gen(), media_type="text/event-stream", headers=headers)

import json
import os
import sys
from pathlib import Path

_API_PATH = Path(__file__).resolve().parent.parent.parent / "api"
if str(_API_PATH) not in sys.path:
    sys.path.insert(0, str(_API_PATH))

import redis as redis_lib

from celery_app import app
from pipeline.align import align
from pipeline.beats import detect_beats
from pipeline.highlights import detect_highlights
from pipeline.mood import detect_mood
from pipeline.stems import isolate_vocals, isolation_enabled
from pipeline.transcribe import transcribe

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


def _redis():
    try:
        r = redis_lib.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def _progress(r, job_id: str, pct: int, stage: str, msg: str):
    if r:
        r.setex(f"job:{job_id}:progress", 300, json.dumps({"percent": pct, "stage": stage, "message": msg}))


def _db():
    from database import SessionLocal
    return SessionLocal()


def _set_status(job_id: str, status: str, analysis_json: str | None = None, error: str | None = None):
    from models.job import Job
    db = _db()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = status
            if analysis_json is not None:
                job.analysis_json = analysis_json
            if error is not None:
                job.error = error
            db.commit()
    finally:
        db.close()


@app.task(name="tasks.analyze.analyze_job", bind=True, max_retries=2)
def analyze_job(self, job_id: str):
    r = _redis()
    try:
        _progress(r, job_id, 5, "analyzing", "Starting transcription")
        _set_status(job_id, "analyzing")

        from models.job import Job
        db = _db()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            return {"error": "job not found"}
        input_file, title = job.input_file, job.title
        source_type = job.source_type or "audio"
        db.close()

        # Songs: separate the vocal stem first — Whisper on a mixed track misses
        # lyrics that instruments mask. Timing is preserved, so timestamps still
        # match the original audio at render time.
        transcribe_input = input_file
        if isolation_enabled(source_type):
            _progress(r, job_id, 12, "analyzing", "Isolating vocals (demucs)")
            vocals = isolate_vocals(input_file)
            if vocals:
                transcribe_input = vocals

        _progress(r, job_id, 25, "analyzing", "Transcribing audio with Whisper")
        transcript = transcribe(transcribe_input)

        _progress(r, job_id, 55, "analyzing", "Aligning word timestamps")
        words = align(transcribe_input, transcript)

        _progress(r, job_id, 65, "analyzing", "Tracking beats")
        beat_info = detect_beats(input_file)

        _progress(r, job_id, 75, "analyzing", "Detecting mood with Ollama")
        mood = detect_mood(transcript.get("text", ""))

        _progress(r, job_id, 85, "analyzing", "Finding highlight moments")
        highlights = detect_highlights(
            transcript.get("segments", []),
            transcript.get("duration_sec", 0.0),
        )

        _progress(r, job_id, 95, "analyzing", "Saving transcript")
        analysis = {
            "job_id": job_id,
            "title": title,
            "duration_sec": transcript.get("duration_sec", 0.0),
            "transcript": transcript.get("text", ""),
            "words": words,
            "segments": transcript.get("segments", []),
            "mood": mood,
            "highlights": highlights,
            "tempo": beat_info.get("tempo", 0.0),
            "beats": beat_info.get("beats", []),
        }

        # Stop here — status "ready" means the project is ready for the user
        # to choose a time range and generate clips manually.
        _set_status(job_id, "ready", analysis_json=json.dumps(analysis))
        _progress(r, job_id, 100, "ready", "Transcription complete — choose a section to generate")

        # Kick off stock footage fetch in the background (doesn't block "ready" state)
        from tasks.assets import fetch_assets
        fetch_assets.apply_async(args=[job_id], queue="asset_queue")

        return {"job_id": job_id, "status": "ready"}

    except Exception as exc:
        _progress(r, job_id, 0, "failed", str(exc)[:200])
        _set_status(job_id, "failed", error=str(exc)[:500])
        raise self.retry(exc=exc, countdown=10)

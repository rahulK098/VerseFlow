import json
import os
import sys
from pathlib import Path

_API_PATH = Path(__file__).resolve().parent.parent.parent / "api"
if str(_API_PATH) not in sys.path:
    sys.path.insert(0, str(_API_PATH))

import redis as redis_lib

from celery_app import app

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "C:/openSource/VerseFlow/uploads"))
MAX_DOWNLOAD_MB = int(os.getenv("MAX_DOWNLOAD_MB", "2048"))

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}


def _redis():
    try:
        r = redis_lib.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def _progress(r, job_id, pct, stage, msg):
    if r:
        r.setex(f"job:{job_id}:progress", 300, json.dumps({"percent": pct, "stage": stage, "message": msg}))


def _db():
    from database import SessionLocal
    return SessionLocal()


@app.task(name="tasks.ingest.ingest_url", bind=True, max_retries=1)
def ingest_url(self, job_id: str, url: str):
    """Download a video/audio from a URL with yt-dlp, then chain into analysis."""
    r = _redis()
    from models.job import Job

    try:
        _progress(r, job_id, 3, "downloading", "Starting download")
        db = _db()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            db.close()
            return {"error": "job not found"}
        job.status = "downloading"
        db.commit()
        db.close()

        import yt_dlp

        out_dir = UPLOAD_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)

        def _hook(d):
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes", 0)
                if total:
                    # Map download progress onto 5–40 % of the job bar
                    pct = 5 + int(35 * done / total)
                    _progress(r, job_id, pct, "downloading", "Downloading media")

        ydl_opts = {
            "format": "bv*[height<=1080]+ba/b",
            "outtmpl": str(out_dir / "input.%(ext)s"),
            "merge_output_format": "mp4",
            "max_filesize": MAX_DOWNLOAD_MB * 1024 * 1024,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [_hook],
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        files = sorted(out_dir.glob("input.*"))
        if not files:
            raise RuntimeError("yt-dlp produced no output file (filesize limit or unsupported URL?)")
        input_file = files[0]
        source_type = "video" if input_file.suffix.lower() in VIDEO_EXTENSIONS else "audio"
        title = (info.get("title") or url)[:200]

        db = _db()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.input_file = str(input_file)
            job.title = title
            job.source_type = source_type
            job.status = "pending"
            db.commit()
        db.close()

        _progress(r, job_id, 45, "downloading", "Download complete — starting analysis")

        from tasks.analyze import analyze_job
        analyze_job.apply_async(args=[job_id], queue="analysis_queue")
        return {"job_id": job_id, "title": title, "source_type": source_type}

    except Exception as exc:
        _progress(r, job_id, 0, "failed", str(exc)[:200])
        db = _db()
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = "failed"
            job.error = f"Download failed: {exc}"[:500]
            db.commit()
        db.close()
        raise self.retry(exc=exc, countdown=20)

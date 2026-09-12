import hashlib
import json
import os
import sys
from pathlib import Path

_API_PATH = Path(__file__).resolve().parent.parent.parent / "api"
if str(_API_PATH) not in sys.path:
    sys.path.insert(0, str(_API_PATH))

import redis as redis_lib

from celery_app import app
from pipeline.mood import keywords_to_queries
from pipeline.providers import search_all

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


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


@app.task(name="tasks.assets.fetch_assets", bind=True, max_retries=2)
def fetch_assets(self, job_id: str):
    """Download stock footage clips for a job in the background. Job stays 'ready'."""
    r = _redis()
    try:
        from models.job import Asset, Job

        db = _db()
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job or not job.analysis_json:
            db.close()
            return
        analysis = json.loads(job.analysis_json)
        mood = analysis.get("mood", {})
        db.close()

        queries = keywords_to_queries(mood)
        total_clips = 0

        for i, query in enumerate(queries[:3]):
            _progress(r, job_id, 50 + i * 15, "assets", f"Fetching stock clips for '{query}'")
            clips = search_all(query, count=6)
            print(f"[assets] {len(clips)} clips for query '{query}'")

            if clips:
                db = _db()
                for clip in clips:
                    external_id = hashlib.md5(clip.source_url.encode()).hexdigest()
                    # Skip if already stored (re-run safety)
                    exists = db.query(Asset).filter(
                        Asset.job_id == job_id,
                        Asset.external_id == external_id,
                    ).first()
                    if not exists:
                        db.add(Asset(
                            job_id=job_id,
                            provider=clip.provider,
                            external_id=external_id,
                            local_path=clip.path,
                            query=query,
                        ))
                db.commit()
                db.close()
                total_clips += len(clips)

        print(f"[assets] job {job_id}: {total_clips} total clips cached")

    except Exception as exc:
        print(f"[assets] fetch_assets error for job {job_id}: {exc}")
        raise self.retry(exc=exc, countdown=30)

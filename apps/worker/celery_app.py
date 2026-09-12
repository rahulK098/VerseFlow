import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "verseflow",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["tasks.ingest", "tasks.analyze", "tasks.assets", "tasks.render", "tasks.export"],
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "tasks.ingest.*":  {"queue": "analysis_queue"},
        "tasks.analyze.*": {"queue": "analysis_queue"},
        "tasks.assets.*":  {"queue": "asset_queue"},
        "tasks.render.*":  {"queue": "render_queue"},
        "tasks.export.*":  {"queue": "export_queue"},
    },
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

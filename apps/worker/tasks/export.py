"""Export task — future: upload renders to MinIO/Cloudflare R2."""
from celery_app import app


@app.task(name="tasks.export.export_job")
def export_job(job_id: str):
    # TODO: upload exports dir to MinIO bucket
    return {"job_id": job_id, "status": "exported"}

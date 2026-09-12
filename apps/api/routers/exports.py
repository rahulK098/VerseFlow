from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from deps import get_db
from models.job import Job, Render
from schemas.job import RenderOut

router = APIRouter()


@router.get("/jobs/{job_id}/exports", response_model=list[RenderOut])
def list_exports(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return job.renders


@router.get("/exports/{render_id}/download")
def download_render(render_id: str, db: Session = Depends(get_db)):
    render = db.query(Render).filter(Render.id == render_id).first()
    if not render:
        raise HTTPException(404, "Render not found")
    if render.status != "done":
        raise HTTPException(400, f"Render not ready (status={render.status})")
    path = Path(render.output_file)
    if not path.exists():
        raise HTTPException(404, "Output file missing on disk")
    return FileResponse(str(path), media_type="video/mp4", filename=f"{render.type}.mp4")

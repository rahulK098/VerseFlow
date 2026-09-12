import ipaddress
import os
import re
import shutil
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from deps import get_db
from models.job import Job
from schemas.job import JobOut

router = APIRouter()

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "C:/openSource/VerseFlow/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}
ALLOWED_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024

# Magic-byte signatures per container. MP4/MOV/M4A put "ftyp" at offset 4;
# WebM/MKV share the EBML header; MP3 is an ID3 tag or raw MPEG frame-sync.
_MAGIC = {
    ".mp3":  [(0, b"ID3"), (0, b"\xff\xfb"), (0, b"\xff\xf3"), (0, b"\xff\xf2"), (0, b"\xff\xe3")],
    ".wav":  [(0, b"RIFF")],
    ".flac": [(0, b"fLaC")],
    ".ogg":  [(0, b"OggS")],
    ".m4a":  [(4, b"ftyp")],
    ".mp4":  [(4, b"ftyp")],
    ".mov":  [(4, b"ftyp")],
    ".webm": [(0, b"\x1a\x45\xdf\xa3")],
    ".mkv":  [(0, b"\x1a\x45\xdf\xa3")],
}


def _looks_like_audio(header: bytes, ext: str) -> bool:
    return any(header[off:off + len(sig)] == sig for off, sig in _MAGIC.get(ext, []))


def _clean_title(raw: str) -> str:
    # Strip control chars and cap length; title is display-only
    title = re.sub(r"[\x00-\x1f\x7f]", "", raw).strip()
    return title[:200] or "Untitled"


@router.post("/upload", response_model=JobOut, status_code=201)
def upload_audio(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported format '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}")

    header = file.file.read(12)
    file.file.seek(0)
    if not _looks_like_audio(header, ext):
        raise HTTPException(400, f"File content does not match a valid {ext} audio file")

    job_id = str(uuid.uuid4())
    title = _clean_title(Path(file.filename).stem)
    source_type = "video" if ext in VIDEO_EXTENSIONS else "audio"

    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True)
    dest = job_dir / f"input{ext}"

    # Stream to disk with a hard size cap
    written = 0
    with dest.open("wb") as f:
        while chunk := file.file.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                f.close()
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(413, f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
            f.write(chunk)

    job = Job(id=job_id, status="pending", title=title, input_file=str(dest), source_type=source_type)
    db.add(job)
    db.commit()
    db.refresh(job)

    # Queue the analysis task — best-effort; Celery may not be running
    try:
        import sys
        worker_path = Path(__file__).resolve().parent.parent.parent / "worker"
        if str(worker_path) not in sys.path:
            sys.path.insert(0, str(worker_path))
        from tasks.analyze import analyze_job
        analyze_job.apply_async(args=[job_id], queue="analysis_queue")
    except Exception as exc:
        print(f"[upload] Could not queue task (worker not running?): {exc}")

    return job


# ── URL import (yt-dlp) ────────────────────────────────────────────────────

class ImportRequest(BaseModel):
    url: str


def _validate_import_url(raw: str) -> str:
    """SSRF guard: public http(s) hosts only — no private/loopback/metadata IPs."""
    try:
        parsed = urlparse(raw.strip())
    except ValueError:
        raise HTTPException(400, "Invalid URL")
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "URL must start with http:// or https://")
    host = parsed.hostname
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise HTTPException(400, f"Cannot resolve host '{host}'")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(400, "URL resolves to a private address")
    return parsed.geturl()


@router.post("/import", response_model=JobOut, status_code=201)
def import_url(req: ImportRequest, db: Session = Depends(get_db)):
    """Create a project from a YouTube/Twitch/podcast/etc. URL via yt-dlp."""
    url = _validate_import_url(req.url)

    job = Job(status="downloading", title=url[:200], input_file="", source_type="video")
    db.add(job)
    db.commit()
    db.refresh(job)

    try:
        import sys
        worker_path = Path(__file__).resolve().parent.parent.parent / "worker"
        if str(worker_path) not in sys.path:
            sys.path.insert(0, str(worker_path))
        from tasks.ingest import ingest_url
        ingest_url.apply_async(args=[job.id, url], queue="analysis_queue")
    except Exception as exc:
        print(f"[import] Could not queue task (worker not running?): {exc}")

    return job

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

STEMS_CACHE_DIR = Path(os.getenv("STEMS_CACHE_DIR", "/data/stems"))
# auto = isolate vocals for audio uploads (songs) only; video uploads are usually speech
VOCAL_ISOLATION = os.getenv("VOCAL_ISOLATION", "auto").lower()  # auto | 1 | 0
DEMUCS_MODEL = os.getenv("DEMUCS_MODEL", "htdemucs")


def isolation_enabled(source_type: str) -> bool:
    if VOCAL_ISOLATION in ("1", "true", "yes"):
        return True
    if VOCAL_ISOLATION in ("0", "false", "no"):
        return False
    return source_type == "audio"


def _cache_key(audio_path: str) -> str:
    st = Path(audio_path).stat()
    return hashlib.md5(f"{audio_path}:{st.st_size}:{st.st_mtime_ns}".encode()).hexdigest()


def isolate_vocals(audio_path: str) -> str | None:
    """Separate the vocal stem with demucs so Whisper hears clean vocals.

    Whisper accuracy on mixed music is poor — instruments mask the voice.
    Separation preserves timing, so word timestamps still align with the
    original audio at render time. Returns the vocals wav, or None when
    demucs is unavailable or fails (caller transcribes the original).
    """
    try:
        import demucs  # noqa: F401
    except ImportError:
        print("[stems] demucs not installed — transcribing original mix")
        return None

    cached = STEMS_CACHE_DIR / f"{_cache_key(audio_path)}_vocals.wav"
    if cached.exists() and cached.stat().st_size > 0:
        return str(cached)

    STEMS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_out = STEMS_CACHE_DIR / f"tmp_{_cache_key(audio_path)}"
    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-n", DEMUCS_MODEL,
        "-d", "cpu",
        "-o", str(tmp_out),
        audio_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0:
            print(f"[stems] demucs failed: {result.stderr[-300:]}")
            return None
        vocals = next(tmp_out.glob(f"{DEMUCS_MODEL}/*/vocals.wav"), None)
        if not vocals:
            print("[stems] demucs produced no vocals.wav")
            return None
        shutil.move(str(vocals), str(cached))
        return str(cached)
    except Exception as exc:
        print(f"[stems] vocal isolation error: {exc}")
        return None
    finally:
        shutil.rmtree(tmp_out, ignore_errors=True)

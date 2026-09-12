import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

CACHE_DIR = Path(os.getenv("CACHE_DIR", "/data/cache_videos"))
LOCAL_CLIPS_DIR = Path(os.getenv("LOCAL_CLIPS_DIR", "/data/local_clips"))
PEXELS_KEY = os.getenv("PEXELS_API_KEY", "")
PIXABAY_KEY = os.getenv("PIXABAY_API_KEY", "")
COVERR_KEY = os.getenv("COVERR_API_KEY", "")

MIN_DUR = 4.0
MAX_DUR = 8.0


@dataclass
class StockClip:
    path: str
    duration: float
    source_url: str
    provider: str


def _cache_path(url: str) -> Path:
    return CACHE_DIR / (hashlib.md5(url.encode()).hexdigest() + ".mp4")


def _is_safe_url(url: str, allowed_host_suffixes: tuple[str, ...]) -> bool:
    """SSRF guard: only https URLs on the provider's own hosts are fetched."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == s or host.endswith("." + s) for s in allowed_host_suffixes)


def _download(url: str, allowed_host_suffixes: tuple[str, ...]) -> Path | None:
    if not _is_safe_url(url, allowed_host_suffixes):
        print(f"[providers] blocked non-allowlisted URL: {url[:80]}")
        return None
    dest = _cache_path(url)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    max_bytes = 200 * 1024 * 1024
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; VerseFlow/1.0)"}
        r = requests.get(url, headers=headers, timeout=60, stream=True, allow_redirects=False)
        r.raise_for_status()
        tmp = dest.with_suffix(".tmp")
        written = 0
        with tmp.open("wb") as f:
            for chunk in r.iter_content(8192):
                written += len(chunk)
                if written > max_bytes:
                    raise ValueError(f"download exceeds {max_bytes // (1024*1024)} MB cap")
                f.write(chunk)
        tmp.rename(dest)
        return dest
    except Exception as exc:
        print(f"[providers] download failed {url[:80]}: {exc}")
        dest.with_suffix(".tmp").unlink(missing_ok=True)
        return None


def search_pexels(query: str, count: int = 8) -> list[StockClip]:
    if not PEXELS_KEY:
        return []
    try:
        r = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": query, "orientation": "portrait", "per_page": min(count * 2, 20), "size": "medium"},
            timeout=10,
        )
        r.raise_for_status()
        videos = r.json().get("videos", [])
    except Exception as exc:
        print(f"[providers] Pexels error: {exc}")
        return []

    clips: list[StockClip] = []
    seen: set[str] = set()
    for v in videos:
        dur = v.get("duration", 0)
        if dur < MIN_DUR:
            continue
        files = sorted(
            [f for f in v.get("video_files", []) if f.get("width", 0) >= 720],
            key=lambda f: abs(f.get("width", 0) - 1080),
        )
        if not files:
            continue
        link = files[0]["link"]
        if link in seen:
            continue
        seen.add(link)
        path = _download(link, ("pexels.com",))
        if path:
            clips.append(StockClip(str(path), min(dur, MAX_DUR), link, "pexels"))
        if len(clips) >= count:
            break
    return clips


def search_pixabay(query: str, count: int = 8) -> list[StockClip]:
    if not PIXABAY_KEY:
        return []
    try:
        r = requests.get(
            "https://pixabay.com/api/videos/",
            params={
                "key": PIXABAY_KEY,
                "q": query,
                "video_type": "film",
                "per_page": min(count * 2, 20),
                "min_duration": int(MIN_DUR),
            },
            timeout=10,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])
    except Exception as exc:
        print(f"[providers] Pixabay error: {exc}")
        return []

    clips: list[StockClip] = []
    seen: set[str] = set()
    for hit in hits:
        videos = hit.get("videos", {})
        chosen: dict = {}
        for size in ("medium", "large", "small"):
            v = videos.get(size, {})
            if v.get("width", 0) >= 640:
                chosen = v
                break
        link = chosen.get("url", "")
        if not link or link in seen:
            continue
        seen.add(link)
        dur = hit.get("duration", 0)
        if dur < MIN_DUR:
            continue
        path = _download(link, ("pixabay.com",))
        if path:
            clips.append(StockClip(str(path), min(dur, MAX_DUR), link, "pixabay"))
        if len(clips) >= count:
            break
    return clips


def search_coverr(query: str, count: int = 8) -> list[StockClip]:
    if not COVERR_KEY:
        return []
    try:
        r = requests.get(
            "https://api.coverr.co/videos",
            headers={"Authorization": f"Bearer {COVERR_KEY}"},
            params={"query": query, "page_size": min(count * 2, 20), "urls": "true"},
            timeout=10,
        )
        r.raise_for_status()
        hits = r.json().get("hits", [])
    except Exception as exc:
        print(f"[providers] Coverr error: {exc}")
        return []

    clips: list[StockClip] = []
    seen: set[str] = set()
    for hit in hits:
        link = hit.get("urls", {}).get("mp4", "")
        dur = hit.get("duration", 0) or MAX_DUR
        if not link or link in seen or dur < MIN_DUR:
            continue
        seen.add(link)
        path = _download(link, ("coverr.co",))
        if path:
            clips.append(StockClip(str(path), min(dur, MAX_DUR), link, "coverr"))
        if len(clips) >= count:
            break
    return clips


def search_nasa(query: str, count: int = 4) -> list[StockClip]:
    """NASA Image and Video Library — free, no API key required.

    Opt-in via NASA_PROVIDER=1: NASA footage often has mission titles/captions
    burned into the frames, which clashes with our own captions.
    """
    if os.getenv("NASA_PROVIDER", "0").lower() not in ("1", "true", "yes"):
        return []
    try:
        r = requests.get(
            "https://images-api.nasa.gov/search",
            params={"q": query, "media_type": "video", "page_size": min(count * 2, 20)},
            timeout=10,
        )
        r.raise_for_status()
        items = r.json().get("collection", {}).get("items", [])
    except Exception as exc:
        print(f"[providers] NASA error: {exc}")
        return []

    clips: list[StockClip] = []
    for item in items:
        collection_href = item.get("href", "")
        if not _is_safe_url(collection_href, ("nasa.gov",)):
            continue
        try:
            assets = requests.get(collection_href, timeout=10).json()
        except Exception:
            continue
        # Prefer the smaller mobile encode over the original
        link = next((u for u in assets if u.endswith("~mobile.mp4")), None) or \
               next((u for u in assets if u.endswith(".mp4")), None)
        if not link:
            continue
        link = link.replace("http://", "https://")
        path = _download(link, ("nasa.gov",))
        if path:
            clips.append(StockClip(str(path), MAX_DUR, link, "nasa"))
        if len(clips) >= count:
            break
    return clips


def search_local(query: str, count: int = 8) -> list[StockClip]:
    """User-supplied clips dropped into LOCAL_CLIPS_DIR — zero config, no API key.

    Files whose name contains a query word are preferred; otherwise any clip is used.
    """
    if not LOCAL_CLIPS_DIR.is_dir():
        return []
    all_files = sorted(LOCAL_CLIPS_DIR.glob("*.mp4")) + sorted(LOCAL_CLIPS_DIR.glob("*.mov"))
    if not all_files:
        return []
    words = [w.lower() for w in query.split() if len(w) > 2]
    matched = [f for f in all_files if any(w in f.stem.lower() for w in words)]
    chosen = (matched or all_files)[:count]
    return [StockClip(str(f), MAX_DUR, f.name, "local") for f in chosen]


def search_all(query: str, count: int = 8) -> list[StockClip]:
    """Combine providers until count clips are collected.

    Order: local folder (user intent) → Pexels → Pixabay → Coverr → NASA (keyless fallback).
    """
    clips: list[StockClip] = []
    for provider in (search_local, search_pexels, search_pixabay, search_coverr, search_nasa):
        if len(clips) >= count:
            break
        try:
            clips += provider(query, count - len(clips))
        except Exception as exc:
            print(f"[providers] {provider.__name__} failed: {exc}")
    return clips[:count]

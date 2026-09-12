# VerseFlow — Personal Build Plan

> Upload a song → generate multiple ready-to-post Shorts and lyric videos in parallel using open-source AI and FFmpeg-based rendering.

## Goal

Build this as a **solo personal project** with:
- Near-zero monthly cost ($0 locally)
- Fully open-source stack
- No paid AI APIs

---

## Documents

Internal planning notes (architecture, stack decisions, phases, todo, decisions log, pipeline detail) live in a local `docs/` folder that is gitignored and not distributed with the repo.

| File | Contents |
|---|---|
| [`docker-compose.yml`](docker-compose.yml) | Full local dev environment (Postgres, Redis, MinIO, API, worker, frontend) |
| [`docker/README.md`](docker/README.md) | Background on the Docker services |

---

## Quick Start (local dev)

```bash
# 1. Clone the repo
git clone <repo-url> verseflow && cd verseflow

# 2. Create a .env file with your API keys / config
#    (see docker-compose.yml for the full list of variables)

# 3. Build and start everything — Postgres, Redis, MinIO, API, worker, frontend
docker compose up --build

# Frontend:  http://localhost:3000
# API docs:  http://localhost:8000/docs
# MinIO UI:  http://localhost:9001
```

The worker runs the processing pipeline as Celery tasks (`apps/worker/tasks/`), not standalone scripts — jobs are queued through the API, not run via CLI.

---

## V1 Deliverables

- [ ] Upload MP3 / WAV via browser
- [ ] AI transcription + word-level timestamps
- [ ] Mood + genre + energy detection
- [ ] Generate 3 Shorts (1080×1920 MP4)
- [ ] Generate lyric video
- [ ] Generate visualizer video
- [ ] Real-time progress via SSE
- [ ] Download exports from dashboard

## Monthly Cost Target

| Environment | Cost |
|---|---|
| Local development | **$0** |
| Hetzner CX22 VPS | **~€4/mo** |
| Cloudflare R2 (10GB storage) | **$0** |
| All AI / ML tools | **$0** |
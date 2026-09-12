# Docker Setup

## What's in the stack

| Service | Port | Purpose |
|---|---|---|
| Redis | 6379 | Job queue + progress cache |
| MinIO (API) | 9000 | S3-compatible object storage |
| MinIO (Console) | 9001 | MinIO web UI |
| FastAPI | 8000 | REST API + SSE |
| Celery Worker | — | Background task processor |
| Next.js Frontend | 3000 | Web UI |
| Flower | 5555 | Worker monitoring *(profile: monitoring)* |
| Redis Commander | 8081 | Redis UI *(profile: monitoring)* |

The database is SQLite by default (a file inside the shared `verseflow_data` volume), not a separate Postgres container — see [Switching to PostgreSQL from SQLite](#switching-to-postgresql-from-sqlite) below.

---

## Quickstart

The compose file lives at the repo root, not in this folder. From the repo root:

```bash
# Create a .env file with your API keys / config
#    (see docker-compose.yml for the full list of variables)

# Build and start everything: redis, minio, api, worker, frontend
docker compose up --build

# Verify everything is healthy
docker compose ps
```

---

## With monitoring tools

```bash
docker compose --profile monitoring up -d
```

Adds Celery Flower (worker monitor) and Redis Commander on top of the running stack.

---

## Environment variables

Create `.env` at the repo root:

```env
# MinIO (local dev — leave as-is)
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin

# Ollama (running on host machine, not in Docker)
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5:3b

# Whisper
WHISPER_MODEL=medium
WHISPER_DEVICE=cpu

# Stock content APIs (get free keys)
PEXELS_API_KEY=your_pexels_key_here
PIXABAY_API_KEY=your_pixabay_key_here
```

**Note:** `host.docker.internal` resolves to your host machine's IP from inside Docker. Ollama runs on your machine (not in Docker) so the worker container can reach it via this hostname on Linux/Mac. On Linux, if `host.docker.internal` doesn't resolve, use your host's actual local IP (e.g. `http://192.168.1.x:11434`).

---

## Useful commands

```bash
# View logs for a specific service
docker compose logs -f redis
docker compose logs -f api

# Restart a service
docker compose restart worker

# Open a shell in a container
docker compose exec redis redis-cli

# Stop everything (keep volumes)
docker compose down

# Stop and delete all data (fresh start)
docker compose down -v

# Check MinIO via mc CLI
docker run --rm -it --network verseflow_network minio/mc:latest \
  alias set local http://minio:9000 minioadmin minioadmin && \
  mc ls local/verseflow
```

---

## MinIO Console

Open http://localhost:9001 in your browser.
- Username: `minioadmin`
- Password: `minioadmin`

The `verseflow` bucket is created automatically on first start by the `minio_init` service.

Folder structure inside the bucket:
```
verseflow/
├── uploads/    ← uploaded MP3 files
├── assets/     ← downloaded stock clips
└── exports/    ← rendered MP4 outputs
```

---

## Switching to Cloudflare R2 (production)

Change these env vars — no code changes needed:

```env
STORAGE_ENDPOINT=https://<account_id>.r2.cloudflarestorage.com
STORAGE_ACCESS_KEY=<r2_access_key_id>
STORAGE_SECRET_KEY=<r2_secret_access_key>
STORAGE_BUCKET=verseflow
```

Get your R2 credentials from: Cloudflare Dashboard → R2 → Manage API Tokens.

---

## Switching to PostgreSQL from SQLite

The current `docker-compose.yml` doesn't include a Postgres service — the api/worker containers use SQLite by default (`DATABASE_URL=sqlite:////data/db/verseflow.db`). To move to Postgres you'd need to add a `postgres` service to `docker-compose.yml`, then point `DATABASE_URL` at it, e.g.:

```env
DATABASE_URL=postgresql+asyncpg://verseflow:verseflow@postgres:5432/verseflow
```

---

## Dockerfile references

- `docker/Dockerfile.api` — FastAPI container
- `docker/Dockerfile.worker` — Celery worker container (includes FFmpeg + Python ML deps)
- `docker/Dockerfile.frontend` — Next.js container
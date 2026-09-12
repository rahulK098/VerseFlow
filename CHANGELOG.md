# Changelog

All notable changes to VerseFlow are recorded here.
Format: `## [version] YYYY-MM-DD` → grouped by Added / Changed / Fixed / Removed.

---

## [0.7.3] 2026-09-12 — Repo hygiene + README/docs correctness pass

### Changed
- `.gitignore` — added `.claude/`, `.skills/`, `docs/` (none were tracked yet; kept local-only going forward). `docs/` is now excluded from the repo, so README no longer links to it.
- `README.md` — Quick Start rewritten: dropped the `apps/worker/analyze.py` / `render.py` CLI invocation (these scripts don't exist — the worker runs the pipeline as Celery tasks under `apps/worker/tasks/`, queued through the API); now points at `docker compose up --build` from the repo root. Documents table trimmed since `docs/` is gitignored; now points at the root `docker-compose.yml` (the real/current compose file) instead of the stale `docker/docker-compose.yml`.
- `docker/README.md` — rewritten to match the current root `docker-compose.yml`: removed the nonexistent PostgreSQL service/env vars and `--profile full` (api/worker/frontend aren't profile-gated), corrected the quickstart to run from the repo root, fixed `Dockerfile.*` descriptions (they already exist and are in active use, not a future-phase placeholder).

### Removed
- `docker/docker-compose.yml` — stale, never-tracked duplicate of the root compose file (backing-services-only, pre-Celery-migration shape). Root `docker-compose.yml` is the one actually in use.

---

## [0.7.2] 2026-07-05 — Azure OpenAI provider

### Added
- **Azure OpenAI** as an LLM provider (`pipeline/highlights.py`): `AZURE_OPENAI_KEY` / `AZURE_OPENAI_KEY2` (automatic failover to the secondary key on any error), `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION`. Enrolled at the top of the fallback chain; set as primary via `LLM_PROVIDER=azure`.
- Queried the resource's deployments and selected `chat` (**gpt-4.1-mini**) as default — the cheapest chat-capable deployment available (vs `gpt-4.1` at ~5× the price; the third deployment is embeddings-only).
- Verified live from inside the worker: Azure answers as primary.

---

## [0.7.1] 2026-07-05 — Fix frozen frames / missing captions in stock renders

### Fixed
- **Video froze with no captions while audio kept playing** — two root causes in the stock-footage path (`pipeline/ffmpeg_runner.py`):
  1. Stock clips **shorter than their slot** left the concat video track shorter than the render — video (and burned captions, which live on video frames) ended early while the song continued. `_prepare_clip` now uses `-stream_loop -1` so short sources repeat until their slot is filled exactly.
  2. **Mixed frame rates across providers** broke concat-demuxer timestamps at clip boundaries (frozen/glitchy frames). Prepared clips are now normalized to `fps=30,setsar=1`.
  - Safety net: final encodes (stock + source paths) add `tpad=stop_mode=clone` **before** the `ass` filter, so even a fractional video shortfall clone-holds the last frame *with captions still rendering* instead of dropping them; `-shortest` replaced by an exact `-t` cap.
- Verified end-to-end: 30 s stock render → ffprobe shows video 30.000 s @ 30 fps and audio 30.000 s, exact match.

---

## [0.7.0] 2026-07-05 — Music intelligence: vocal isolation + beat-synced cuts

### Added
- **Vocal isolation before transcription** (`pipeline/stems.py`) — demucs (`htdemucs`, two-stems mode) separates the vocal track so Whisper hears clean vocals instead of a full mix; big lyric-accuracy win on songs. Timing is preserved, so word timestamps still align with the original audio at render time.
  - `VOCAL_ISOLATION` env: `auto` (default — songs/audio uploads only, video skipped) | `1` | `0`; `DEMUCS_MODEL` selectable
  - Stems cached in `/data/stems` keyed by file identity — re-analysis is free
  - Graceful: demucs missing or failing → transcribe the original mix as before
- **Beat detection** (`pipeline/beats.py`) — librosa `beat_track`; tempo + beat times stored in `analysis_json`.
- **Beat-synced background cuts** — stock-footage renders now cut clips **on the beat**: `_beat_cut_durations()` aims for ~6 s slots but snaps every boundary to the nearest beat (min 2.5 s per slot). No beats → previous fixed-slot behaviour. Verified: all cut boundaries land on beats, durations sum exactly to the render length.
- Worker deps: `torch`/`torchaudio` (CPU wheels via pytorch extra index — no CUDA bloat), `demucs`, `librosa`.

### Changed
- `tasks/analyze.py` — progress stages: 12 % vocal isolation → 25 % transcription → 55 % alignment → 65 % beat tracking → 75 % mood → 85 % highlights.

---

## [0.6.0] 2026-07-04 — URL import, hook title cards, more visualizers, batch generate

### Added
- **URL import (yt-dlp)** — paste a YouTube/Twitch/podcast link on the upload page:
  - `POST /api/import` with SSRF validation (http/https only, all resolved IPs must be public — blocks private/loopback/link-local/metadata addresses)
  - New worker task `tasks/ingest.py`: downloads best ≤1080p as mp4 (2 GB cap via `MAX_DOWNLOAD_MB`), maps download progress onto 5–40 % of the job bar, sets title/source_type from metadata, then chains into `analyze_job`
  - New `downloading` job status wired through `_STATUS_MAP`, SSE, and both frontend pages
  - `yt-dlp` added to worker requirements (image rebuilt); `tasks.ingest` registered in `celery_app.py` include + routes
- **Hook title cards** — `build_ass_captions(title=…)` burns a top-center animated title (pop-in + fade, layer 1, first 3 s). `ClipRequest.title_card: bool`; suggested-clip Generate always burns its hook; manual clips have a checkbox. ASS-escaped to strip override braces.
- **Two new visualizer backgrounds**: `waves` (purple/pink `showwaves` cline) and `scope` (`avectorscope` lissajous) alongside the existing spectrum; all pure FFmpeg.
- **"Generate all"** button renders every suggested clip in one click (hooks burned as title cards).

### Fixed
- `celery_app.py` was missing the new task module from `include` — `tasks.ingest.ingest_url` never registered until added.

---

## [0.5.4] 2026-07-04 — Groq + Gemini providers, multi-cloud fallback chain

### Added
- **Groq** (`GROQ_API_KEY`, default `llama-3.3-70b-versatile`) and **Google Gemini** (`GEMINI_API_KEY`, default `gemini-2.5-flash`) as LLM providers — both have generous free tiers and are much faster than CPU Ollama.
- `_ask_llm` now walks a **chain**: primary (`LLM_PROVIDER`) → every other cloud provider with a key configured → local Ollama → heuristic. Adding any key automatically enrolls that provider as a fallback; no other config needed.
- `.env` placeholders + compose env for `GROQ_*` / `GEMINI_*` with sign-up links.

---

## [0.5.3] 2026-07-04 — LLM fallback chain + fix "stuck at 80%"

### Fixed
- **Analysis hung at ~80%** — two causes: (1) OpenRouter returned `402 Payment Required` (paid model on a $0-credit account), (2) the Ollama fallback (`qwen3:8b`, a thinking model) exceeded the 60 s timeout on CPU. Analysis still completed but hung for minutes at the mood/highlights stages.
- `_ask_llm` now falls back **cloud → local Ollama → heuristic** instead of jumping straight to the heuristic when a cloud provider errors (quota, network, invalid model).
- Default `OPENROUTER_MODEL` → `meta-llama/llama-3.3-70b-instruct:free` (previous default slug 404'd; verified against the live OpenRouter model list). Free variants work on $0 balance but are rate-limited (~50 req/day; a one-time $10 top-up raises this to 1000/day).
- `OLLAMA_MODEL` → `llama3.1` in `.env` (fast instruct model; `qwen3:8b` burns minutes thinking on CPU); Ollama timeout 60→120 s.
- Verified from inside the worker: OpenRouter 429 (rate limit) → clean fallback → Ollama replies in seconds.

---

## [0.5.2] 2026-07-04 — OpenRouter LLM provider

### Added
- **OpenRouter** as an LLM provider (`pipeline/highlights.py`): set `LLM_PROVIDER=openrouter` + `OPENROUTER_API_KEY` in `.env`; model via `OPENROUTER_MODEL` (default `deepseek/deepseek-chat-v3-0324`). One key gives access to hundreds of models via the OpenAI-compatible endpoint.
- `pipeline/mood.py` now uses the shared `_ask_llm` provider chain instead of its own hardcoded Ollama call — mood/genre/keyword detection (drives stock footage queries) benefits from the same provider selection.
- `.env` pre-seeded with `LLM_PROVIDER=openrouter` block (key left blank for the user to fill); compose passes `OPENROUTER_*` to the worker.

---

## [0.5.1] 2026-07-04 — Hotfixes: frontend 404s, VAD stripping songs, Ollama connectivity

### Fixed
- **All `/jobs*` routes returned 404** while `/` worked — stale/corrupted Turbopack cache in the `frontend_next_cache` named volume (source files were present in the container; the route manifest wasn't seeing them). Fixed by removing the volume and recreating the frontend container. If it recurs: `docker compose stop frontend && docker compose rm -f frontend && docker volume rm verseflow_frontend_next_cache && docker compose up -d frontend`.
- **VAD stripped 1:51 from a 2:45 song** — Silero VAD classifies singing as non-speech. `vad_filter` is now **off by default** and controlled by `WHISPER_VAD` env (set `1` for podcasts/interviews where silence-skipping helps). `pipeline/transcribe.py` + compose env.
- **Worker couldn't reach Ollama** — `.env` had `OLLAMA_BASE_URL=http://localhost:11434`, which resolves to the *container itself* inside Docker. Changed to `http://host.docker.internal:11434`. Also switched `OLLAMA_MODEL` to `qwen3:8b` (the model actually installed; `qwen2.5:3b` wasn't pulled). Verified worker → Ollama connectivity.
- Note: projects analyzed before these fixes have truncated transcripts (VAD) and generic heuristic hooks (no LLM) stored in `analysis_json` — **re-upload** to re-analyze with the fixes.

---

## [0.5.0] 2026-07-04 — Video projects, AI highlights, multi-aspect, visualizer (autoshorts-inspired)

Inspired by [JayWebtech/autoshorts](https://github.com/JayWebtech/autoshorts); roadmap to beat opus.pro now lives at `docs/09-roadmap.md`.

### Added
- **Video upload** (`.mp4 .mov .webm .mkv`): magic-byte validated (ftyp/EBML), `Job.source_type` column (migrated), 500 MB default limit. faster-whisper transcribes video directly via PyAV — no separate audio-extraction step needed.
- **AI highlight detection** — new `pipeline/highlights.py`: LLM picks 3–6 viral moments (15–60 s) with score 0–100, punchy hook, and reason. Provider chain via `LLM_PROVIDER`: `ollama` (default, local/free) | `deepseek` | `anthropic` — all plain `requests`. **Word-density heuristic fallback** when no LLM is reachable. Results snapped to segment boundaries, overlaps dropped, stored in `analysis_json["highlights"]`.
- **✨ Suggested clips UI** — score badge (color-tiered), hook, time range, play-from-here, one-click Generate per highlight.
- **Multi-aspect output** — `aspect: "9:16" | "16:9" | "1:1"` end-to-end (schema → `Render.aspect` column → FFmpeg dimensions → ASS PlayRes/margins/`\move` coords). 16:9 enables YouTube lyric videos as requested. Frontend Format dropdown + aspect-aware clip cards.
- **`source` background** — video projects cut clips straight from the uploaded footage: coarse `-ss` fast seek + frame-accurate decode-side `trim`, center-crop to target aspect, captions burned. Video projects default to it automatically.
- **`visualizer` background** — audio-reactive spectrum (`showspectrum` FFmpeg filter, zero dependencies) behind captions; falls back to black on failure.
- **`docs/09-roadmap.md`** — living market roadmap: shipped-vs-opus.pro table, near/mid/long-term features (vocal isolation via demucs, librosa beat-sync, mediapipe reframing, yt-dlp import, scene-matched B-roll…), competitive tracker, build principles.

### Changed
- `main.py` — `_migrate_db()` generalized to a per-table migration map (jobs + renders).
- `routers/jobs.py` — exposes `source_type` + `highlights`; stores `aspect`; coerces `stock`→`source` background for video jobs.
- Upload page — accepts video, updated copy; projects list shows 🎬/🎵 source badge.
- `docker-compose.yml` — `LLM_PROVIDER`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY` env vars; `MAX_UPLOAD_MB` default 500.
- `test_captions_smoke.py` — now covers all 6 templates × 3 aspects (checks PlayRes and coordinate-token resolution).

---

## [0.4.2] 2026-07-04 — Caption sync fixes, blank background, animated captions

### Fixed
- **Caption/audio desync** (two root causes):
  1. `pipeline/transcribe.py` — faster-whisper now runs with `word_timestamps=True`, producing real per-word timestamps via its cross-attention alignment. Previously `pipeline/align.py` always fell into its no-WhisperX fallback, which spread words **evenly** across each segment — seconds of drift on long segments. `align.py` priority is now: WhisperX (if installed) → faster-whisper word timestamps → even distribution (stub only).
  2. `pipeline/ffmpeg_runner.py` — audio segment extraction moved from input-side `-ss` (byte-estimated on VBR MP3s, up to ~1 s off) to a decode-side `atrim=start:duration,asetpts=PTS-STARTPTS` filter — sample-accurate in both render paths.
  - Also enabled `vad_filter=True` so Whisper skips instrumental sections instead of hallucinating lyrics during intros/breaks.
  - **Note:** timestamps live in `analysis_json` at upload time, so previously-uploaded projects keep their old drifted timings — re-upload the song to benefit.
- **Text-covered background footage** — NASA provider is now **opt-in** (`NASA_PROVIDER=1`); NASA clips frequently have mission titles/captions burned in, which clashed with our captions.

### Added
- **Background picker** per clip: `background: "stock" | "blank"` through the whole stack (`ClipRequest`/`RenderOut` schemas, `Render.background` column + migration, router kwarg, `render_job` kwarg). `"blank"` skips stock clips entirely — clean black canvas with captions only.
- **Animated captions** — every template now carries an ASS override `effect` applied per word line:
  - `minimal` — soft fade in/out (`\fad`)
  - `bold` — fade + pop-in to 112 %
  - `neon` — slow fade + gentle zoom
  - **`pop` (new)** — bounce-in: overshoot to 130 %, settle at 100 %, deep-blue outline, 84 pt
  - **`slide` (new)** — words slide up 60 px while fading in
  - `karaoke` — unchanged (`\k` sweep is the animation)
- Frontend: "Background" dropdown (Stock footage / Blank) next to the caption-style picker; template descriptions updated; two new template options.
- `apps/worker/test_captions_smoke.py` — generates an ASS file for all 6 templates and asserts dialogue lines exist.

---

## [0.4.1] 2026-07-03 — More stock providers + security hardening (VibeSec pass)

### Added
- **3 new stock footage providers** in `pipeline/providers.py` (total is now 5):
  - `search_local()` — drop your own `.mp4`/`.mov` clips into `./local_clips/` (bind-mounted to `/data/local_clips`); filenames matching a mood keyword are preferred; highest priority, zero config.
  - `search_coverr()` — Coverr API via `COVERR_API_KEY` (Bearer auth).
  - `search_nasa()` — NASA Image & Video Library, **no API key needed**; enabled by default, disable with `NASA_PROVIDER=0`. Makes stock footage work out of the box.
  - `search_all()` now walks local → Pexels → Pixabay → Coverr → NASA until the requested count is filled; each provider failure is isolated.
- Project skills installed to `.claude/skills/`: `vibesec` (secure-coding guide) and `find-skills` (skills-ecosystem discovery), sourced from the user-provided `.skills/` directory.
- `claude-mem@thedotmack` v13.9.3 plugin installed at user scope (persistent memory across Claude Code sessions; activates on next session).
- `docs/07-stock-providers.md` — provider table, setup, caching/fetch flow, how to add a provider.
- `docs/08-security.md` — implemented controls + known gaps before public deployment.
- `local_clips/` directory (git-kept, contents ignored).

### Security (VibeSec skill applied)
- `routers/uploads.py` — magic-byte validation per audio container (ID3/MPEG-sync, RIFF, fLaC, OggS, ftyp) so renamed executables are rejected; streamed size cap via `MAX_UPLOAD_MB` (default 100 MB, returns 413 and cleans up partial files); title sanitization (control chars stripped, 200-char cap).
- `schemas/job.py` — `ClipRequest.template` is now `Literal["minimal","bold","karaoke","neon"]` (422 on anything else); `label` trimmed + capped at 200 chars.
- `pipeline/providers.py` — SSRF guard: downloads only over HTTPS from each provider's own domain (`_is_safe_url` host allowlist); redirects disabled; 200 MB per-file cap; partial `.tmp` files cleaned up on failure.

### Changed
- `docker-compose.yml` — worker gains `COVERR_API_KEY`, `NASA_PROVIDER`, `CACHE_DIR`, `LOCAL_CLIPS_DIR`, `MAX_UPLOAD_MB` env vars and a `./local_clips:/data/local_clips` bind mount; api gains `COVERR_API_KEY`, `MAX_UPLOAD_MB`.

---

## [0.4.0] 2026-06-21 — Stock footage + caption templates (MoneyPrinterTurbo inspiration)

### Added
- `apps/worker/pipeline/providers.py` — `StockClip` dataclass + `search_pexels()` / `search_pixabay()` / `search_all()` functions. Reads `PEXELS_API_KEY` / `PIXABAY_API_KEY` env vars; MD5-URL-based caching to `/data/cache_videos/`; duration filter (4 s–8 s); portrait orientation filter; gracefully returns `[]` when keys are absent (falls back to black background).
- `apps/worker/tasks/assets.py` — full implementation replacing the TODO stub: loads mood keywords from `analysis_json`, calls `keywords_to_queries()`, searches Pexels then Pixabay for up to 6 clips per query (3 queries max), downloads to cache, writes `Asset` DB records. Duplicate-safe (skips already-stored `external_id`). Job status remains `"ready"` throughout.
- `apps/worker/pipeline/ffmpeg_runner.py` — **Path B** (stock clips): pre-processes each clip to 1080×1920 portrait via `scale=…:force_original_aspect_ratio=increase,crop=1080:1920`, loops clips to cover render duration, writes FFmpeg concat demuxer list, single-pass encode with caption overlay and audio mux. Falls back to Path A (black background) if all clip preps fail.
- Caption templates — 4 presets in `pipeline/captions.py` (full V4+ ASS style format with `SecondaryColour` for karaoke):
  - `minimal` — white text, Arial 72, black outline 3pt, bottom-center (unchanged default)
  - `bold` — yellow text (#FFFF00), Arial 90, black outline 5pt, bottom-center
  - `karaoke` — ASS `\k{N}` timing tags per word; secondary colour yellow sweeps left-to-right through each word as it's sung; words grouped into phrases (≤5 words or >0.4 s gap)
  - `neon` — cyan text (#00FFFF), Arial 78, purple outline 4pt, center-center alignment
- Template picker `<select>` dropdown on the Generate Clip UI in the frontend; selected template shown as metadata on each `ClipCard`.

### Changed
- `tasks/analyze.py` — after setting `status="ready"`, queues `fetch_assets` on `asset_queue` in the background. Job is immediately usable while stock clips download asynchronously.
- `tasks/render.py` — accepts new `template` kwarg; queries `Asset` records for the job and passes valid cached clip paths to `render_video()` (Path B). Falls back to black background when no assets are found.
- `models/job.py` — added `template: Mapped[str | None]` column to `Render`.
- `schemas/job.py` — added `template: str = "minimal"` to `ClipRequest`; added `template: str | None` to `RenderOut`.
- `main.py` — `_migrate_db()` now also adds `template VARCHAR(64)` to existing `renders` tables.
- `routers/jobs.py` — stores `req.template` on the `Render` record and passes it as a kwarg to `render_job.apply_async`.
- `apps/frontend/app/jobs/[id]/page.tsx` — `Render` type gains `template` field; caption style dropdown; `ClipCard` shows `duration · template` metadata line.

---

All notable changes to VerseFlow are recorded here.
Format: `## [version] YYYY-MM-DD` → grouped by Added / Changed / Fixed / Removed.

---

## [0.3.0] 2026-06-14 — Project-based UX + manual clip generation

### Added
- `GET /api/jobs/{id}/audio` — streams the original uploaded audio so the browser can play it inline.
- `POST /api/jobs/{id}/clips` — generates a single clip for a user-defined `start_sec`/`end_sec` range; creates a `Render` record with `status="queued"` and queues `render_job`.
- `DELETE /api/renders/{id}` — deletes a render record and its output file from disk.
- `pyproject.toml` (repo root) — ruff isort config declaring local modules as first-party, eliminating false I001 import-sort warnings across all Python files.

### Changed
- **Upload flow**: each upload is now a persistent *project*. Transcription runs automatically; the user then chooses which portion to render.
- `tasks/analyze.py` — sets `status="ready"` after transcription instead of auto-queuing renders. SSE stream ends at `ready`.
- `tasks/render.py` — rewrote to render a single clip: takes `(job_id, render_id, start_sec, end_sec)`, updates `Render.status` directly (`queued → rendering → done/failed`). Job status stays `ready` throughout.
- `models/job.py` — added `label`, `start_sec`, `end_sec` columns to `Render`.
- `schemas/job.py` — simplified (removed complex validator); added `ClipRequest`; `JobOut` now includes `duration_sec`, `transcript`, `segments` (populated by the router after parsing `analysis_json`).
- `main.py` — `_migrate_db()` auto-adds the new `renders` columns for existing databases.
- `routers/jobs.py` — added clip/audio/render-delete endpoints; SSE exits at `ready`; `get_job` parses analysis_json and returns transcript data.
- **Frontend `app/jobs/[id]/page.tsx`** — full redesign: audio player (`<audio>` with range-request streaming), dual range sliders (start/end in seconds), optional clip name input, "Generate clip" + "Full audio" buttons, per-clip polling, clips grid with inline video player + delete button.
- **Frontend `app/jobs/page.tsx`** — renamed to "Projects", updated status badges.

---

## [0.2.5] 2026-06-14

### Fixed
- `pipeline/timeline.py` — rewrote segment slicing: `short_1`=0–60 s, `short_2`=60–120 s, `short_3`=120–180 s, `lyric_video`=full song. Words are now filtered to the segment window and their timestamps are shifted to 0-relative so ASS captions align with the trimmed audio. Segments that fall outside the song duration return `total_duration=0` and are skipped.
- `pipeline/ffmpeg_runner.py` — added `-ss {audio_start_sec} -t {duration}` before the audio `-i` so FFmpeg performs a fast input seek to the correct position and outputs only the segment length. Previously the full audio was always used.
- `tasks/render.py` — now passes `timeline["captions"]` (pre-filtered, 0-relative) to `build_ass_captions` instead of the raw `analysis["words"]` list; stores `timeline["total_duration"]` (segment length) as `Render.duration_sec` instead of the full song length; skips render types whose `total_duration < 1.0 s`.

---

## [0.2.4] 2026-06-14

### Changed
- `apps/frontend/app/jobs/[id]/page.tsx` — replaced flat download-link list with a 2-column portrait video grid. Each render card shows a `<video>` player (9:16 aspect ratio, `preload="metadata"`, full seek support) above a Download MP4 button. The download URL doubles as the video `src` since `FileResponse` supports HTTP range requests. Cards show a placeholder state for in-progress or failed renders.

---

## [0.2.3] 2026-06-14

### Fixed
- `routers/jobs.py` — `GET /api/jobs/{id}/stream` (SSE): three bugs fixed:
  1. **Session-after-close**: removed `Depends(get_db)` from the SSE endpoint — FastAPI was calling the dependency's `finally` block (closing the session) as soon as the function returned the `StreamingResponse`, before the generator ran a single iteration. Every `db.refresh()` inside the generator was hitting a closed session and raising, which terminated the chunked transfer mid-stream causing `ERR_INCOMPLETE_CHUNKED_ENCODING`. Fixed by opening a fresh `SessionLocal()` context per tick inside the generator.
  2. **Missing SSE headers**: added `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive` to prevent buffering by proxies and browsers.
  3. **Unhandled client disconnect**: added `except asyncio.CancelledError: pass` so closing the browser tab exits the generator cleanly instead of propagating an unhandled exception.

---

## [0.2.2] 2026-06-14

### Fixed
- `next.config.ts`: removed `webpack()` watchOptions block (Turbopack is the default in Next.js 16 and ignores webpack config, causing a startup error). Replaced with `turbopack: {}` empty config to silence the "no turbopack config" warning.
- `docker-compose.yml`: removed `WATCHPACK_POLLING` and `CHOKIDAR_USEPOLLING` env vars from the frontend service — these are webpack/chokidar knobs that Turbopack does not use.

---

## [0.2.1] 2026-06-14

### Fixed
- Frontend hot-reload loop: `.next/` build cache was inside the Windows bind-mount, so every Next.js compile write triggered WATCHPACK polling → another rebuild. Fixed by adding `frontend_next_cache` named volume at `/workspace/apps/frontend/.next`, keeping compiler output isolated from the source watcher.
- Raised webpack `watchOptions.poll` to 2000 ms (from Next.js default ~300 ms) in `next.config.ts` — less filesystem churn while still fast enough for dev feedback.

---

## [0.2.0] 2026-06-14

### Added
- `docker-compose.yml` (repo root) — full dev stack, single `docker compose up --build` starts everything: Redis, MinIO, API, Worker, Frontend. No profiles required for core services; optional monitoring profile for Flower + Redis Commander.
- `docker/Dockerfile.frontend` — Node 20 Alpine image; installs `node_modules` into the image layer so they survive the Windows bind mount; CMD runs `next dev --hostname 0.0.0.0` for Docker networking.
- Named Docker volumes: `verseflow_data` (SQLite DB + uploads + exports, shared between api and worker), `frontend_node_modules` (isolates Linux binaries from Windows source mount).

### Changed
- `docker/Dockerfile.api` — build context is now repo root; deps installed from `/tmp/requirements.txt`; source code is bind-mounted at `/workspace` at runtime (not copied), so `uvicorn --reload` picks up every save.
- `docker/Dockerfile.worker` — same root-context pattern; adds `watchdog[watchmedo]`; CMD uses `watchmedo auto-restart --directory=/workspace --pattern=*.py --recursive` to restart Celery on any Python change.
- `apps/api/database.py` — added `Path(_db_file).parent.mkdir(parents=True, exist_ok=True)` before engine creation so the SQLite directory is created automatically on first Docker start with a fresh `verseflow_data` volume.
- `apps/api/main.py` — lifespan hook now calls `Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)` and same for `EXPORT_DIR`, ensuring data dirs exist before the first upload hits a worker with an empty volume.

### Hot-reload details
- **API**: `uvicorn --reload` watches `/workspace/apps/api` (bind-mounted source)
- **Worker**: `watchmedo auto-restart` restarts Celery whenever any `.py` in `/workspace` changes (covers both `apps/api` and `apps/worker` since worker imports API models via `sys.path`)
- **Frontend**: Next.js dev server with `WATCHPACK_POLLING=true` + `CHOKIDAR_USEPOLLING=true` for reliable HMR through Docker Desktop on Windows/Mac

---

## [0.1.0] 2026-06-14

### Added

#### Infrastructure
- `.gitignore` — Python, Node, SQLite, uploads/exports dirs, OS and IDE files
- `.env` — all environment variables with sensible local defaults
- `docker/Dockerfile.api` — Python 3.12-slim image for FastAPI
- `docker/Dockerfile.worker` — Python 3.12-slim + FFmpeg image for Celery worker
- Docker backing services started: Redis (pre-existing), MinIO (`verseflow_minio`)
- MinIO bucket `verseflow` created with public download on `/exports`

#### API (`apps/api/`)
- `main.py` — FastAPI app with CORS, lifespan hook that auto-creates SQLite tables
- `database.py` — SQLAlchemy engine; defaults to `sqlite:///C:/openSource/VerseFlow/verseflow.db`, supports PostgreSQL via `DATABASE_URL` env var
- `deps.py` — `get_db()` dependency for request-scoped DB sessions
- `models/job.py` — `Job`, `Render`, `Asset` SQLAlchemy ORM models
- `schemas/job.py` — Pydantic v2 schemas: `JobOut`, `JobList`, `RenderOut`, `ProgressOut`
- `routers/uploads.py` — `POST /api/upload` — validates audio format, saves to disk, creates Job record, queues Celery task (best-effort)
- `routers/jobs.py` — `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/progress`, `GET /api/jobs/{id}/stream` (SSE), `DELETE /api/jobs/{id}`
- `routers/exports.py` — `GET /api/jobs/{id}/exports`, `GET /api/exports/{render_id}/download`
- `requirements.txt` — fastapi, uvicorn, sqlalchemy, pydantic, python-multipart, redis, celery
- Python venv created at `apps/api/.venv/`, dependencies installed

#### Worker (`apps/worker/`)
- `celery_app.py` — Celery configured with Redis broker/backend; 4 queues: `analysis_queue`, `asset_queue`, `render_queue`, `export_queue`
- `tasks/analyze.py` — `analyze_job` task: transcribe → align → mood → queue asset fetch
- `tasks/assets.py` — `fetch_assets` task: mood → search queries → (stub) → queue render
- `tasks/render.py` — `render_job` task: builds timelines, renders 4 outputs (`lyric_video`, `short_1–3`), writes `Render` DB records
- `tasks/export.py` — `export_job` stub (future: MinIO/R2 upload)
- `pipeline/transcribe.py` — faster-whisper integration with stub fallback when not installed
- `pipeline/align.py` — WhisperX word alignment with proportional fallback
- `pipeline/mood.py` — Ollama/Qwen mood+genre detection with stub fallback
- `pipeline/timeline.py` — builds timeline JSON for each render type
- `pipeline/captions.py` — converts word timestamps to ASS subtitle file
- `pipeline/ffmpeg_runner.py` — FFmpeg render command; creates byte stub when FFmpeg not on PATH
- `requirements.txt` — celery, redis, sqlalchemy, requests; ML packages commented out

#### Frontend (`apps/frontend/`)
- Scaffolded with `create-next-app@latest` (Next.js 16, TypeScript, Tailwind, App Router)
- `.env.local` — `NEXT_PUBLIC_API_URL=http://localhost:8000`
- `app/page.tsx` — Upload page: drag-and-drop zone, file validation, POST to API, redirect to job detail
- `app/jobs/page.tsx` — Jobs list: fetches all jobs, status badges, links to detail
- `app/jobs/[id]/page.tsx` — Job detail: SSE progress bar, renders list with download buttons, shows worker start command when job is pending

### Running services (session-started)
- API: `http://localhost:8000` (uvicorn, hot-reload)
- Frontend: `http://localhost:3000` (Next.js dev, Turbopack)
- MinIO console: `http://localhost:9001` (minioadmin / minioadmin)
- Redis: `localhost:6379`

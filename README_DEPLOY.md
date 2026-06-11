# BookForge — hosting guide

A web service that turns an uploaded `.docx` manuscript into a print-ready book PDF.
It wraps the BookForge engine with an upload page, a background render queue, and a
download endpoint.

```
bookforge/            the formatting engine (parser, layout, render) + bundled fonts
bookforge_service/    the web layer
  app.py              FastAPI routes
  jobs.py             background render workers (thread pool)
  storage.py          per-job filesystem storage
  templates/index.html  the upload page
Dockerfile            bakes in WeasyPrint's system libraries + fonts
docker-compose.yml    one-command local run
```

## Run it locally

```bash
docker compose up --build
# open http://localhost:8000
```

Or without Docker (you must install WeasyPrint's system libs first — see its docs):

```bash
pip install -r bookforge_service/requirements.txt
uvicorn bookforge_service.app:app --port 8000
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET  | `/` | upload page |
| POST | `/api/jobs` | multipart: `file` (.docx) + `title, subtitle, author, isbn, publisher, year, epigraph, mode, trim, crop_marks` → `202 {id,status}` |
| GET  | `/api/jobs/{id}` | poll job status → `queued \| rendering \| done \| error` |
| GET  | `/api/jobs/{id}/download` | the finished PDF |
| GET  | `/healthz` | liveness probe |

`mode` = `bw\|color` · `trim` = `6x9\|5.5x8.5\|5x8\|5.25x8\|8.5x11` · `crop_marks` = `true\|false`.
Env: `BOOKFORGE_MAX_MB` (default 25), `BOOKFORGE_DATA` (job storage dir), `PORT`.

## Deploy to a managed host

Any host that builds a Dockerfile works. The image is self-contained.

- **Render / Railway / Fly.io**: point at this repo, it detects the `Dockerfile`. Set
  a persistent disk mounted at `/data` (so in-flight jobs survive a restart). Health
  check path `/healthz`. These platforms inject `$PORT`, which the CMD already honors.
- **A VM**: `docker compose up -d` behind nginx/Caddy for TLS.

## Scaling out (what to change, and where)

The demo runs **one process with an in-memory job table**, so run a **single worker**.
The code is structured so the two pieces you'd swap are isolated:

1. **Job queue → Redis.** Replace `jobs.py` with Celery or RQ backed by Redis, and run
   N render workers separately from the web process. `app.py` only calls `submit()` and
   `get()`, so nothing else changes. This is required before running multiple web
   replicas (otherwise replica A can't see a job created on replica B).
2. **Storage → S3/GCS.** Implement the four methods in `storage.py` (`save_upload`,
   `output_path`, `job_dir`, `cleanup`) against object storage. Serve downloads via a
   short-lived presigned URL instead of `FileResponse`.

## Before real users (production checklist)

- **Accounts & auth.** Add a user table and protect `/api/jobs*` (API key per account
  or session auth). Attach `user_id` to each job.
- **Quotas & billing.** Rate-limit uploads; meter renders per plan.
- **Retention.** TTL job dirs (e.g. delete after 24h) — `storage.cleanup()` is ready;
  wire it to a scheduled sweep.
- **Upload safety.** Cap size (done), validate the .docx really unzips, and run an AV
  scan on uploads.
- **Print fidelity** (engine-side, see engine README): CMYK / PDF-X export, font-license
  checks, image-DPI validation, and a cover-wrap generator. The service exposes these as
  soon as the engine does.

## Notes

- Renders take a few seconds to ~30s depending on chapter count and `color` mode (image
  generation dominates) — that's why it's a background job, not a blocking request.
- Each `mode`/`trim`/`crop_marks` combination is a fresh render; nothing is cached yet.

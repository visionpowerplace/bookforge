"""BookForge cloud API.

Routes:
  GET  /                         upload page
  POST /api/jobs                 multipart: file (.docx) + metadata -> {id, status}
  GET  /api/jobs/{id}            job status (poll this)
  GET  /api/jobs/{id}/download   finished PDF
  GET  /healthz                  liveness
"""
import os
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

from bookforge.model import BookMeta
from bookforge.theme import Theme, TRIM_SIZES
from .storage import JobStore
from .jobs import JobManager

MAX_BYTES = int(os.environ.get("BOOKFORGE_MAX_MB", "25")) * 1024 * 1024
HERE = os.path.dirname(__file__)

app = FastAPI(title="BookForge", version="0.1.0")
store = JobStore()
jobs = JobManager(store)


@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "templates", "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    title: str = Form("Untitled"),
    subtitle: str = Form(""),
    author: str = Form(""),
    isbn: str = Form(""),
    publisher: str = Form(""),
    year: str = Form(""),
    epigraph: str = Form(""),
    mode: str = Form("bw"),
    trim: str = Form("6x9"),
    crop_marks: str = Form("false"),
):
    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(400, "Please upload a Word .docx file.")
    if mode not in ("bw", "color"):
        raise HTTPException(400, "mode must be 'bw' or 'color'.")
    if trim not in TRIM_SIZES:
        raise HTTPException(400, f"trim must be one of {list(TRIM_SIZES)}.")

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, f"File exceeds {MAX_BYTES // (1024*1024)} MB limit.")
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")

    job_id = store.new_job_id()
    docx_path = store.save_upload(job_id, file.filename, data)

    meta = BookMeta(title=title, subtitle=subtitle, author=author, isbn=isbn,
                    publisher=publisher, year=year, epigraph=epigraph)
    theme = Theme(trim=trim, mode=mode, crop_marks=(crop_marks.lower() == "true"))

    # render under the same id the upload was stored under
    job = jobs.submit(docx_path, meta, theme, job_id=job_id)
    return JSONResponse(job.public(), status_code=202)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "No such job.")
    return job.public()


@app.get("/api/jobs/{job_id}/download")
def job_download(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "No such job.")
    if job.status != "done" or not job.out_file:
        raise HTTPException(409, "Not ready yet.")
    path = store.output_path(job_id, job.out_file)
    if not os.path.exists(path):
        raise HTTPException(410, "Output expired.")
    fname = (job.title or "book").strip().replace(" ", "_") + ".pdf"
    return FileResponse(path, media_type="application/pdf", filename=fname)

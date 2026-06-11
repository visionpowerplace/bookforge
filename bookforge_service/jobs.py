"""Background render jobs.

WeasyPrint is CPU-bound and blocking, so renders run in a thread pool rather than
on the request. Job state lives in memory — fine for a single worker / demo. For
multi-worker production, replace this module with Celery/RQ backed by Redis and a
shared job table; app.py only touches submit() and get().
"""
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict

from .storage import JobStore
from bookforge.model import BookMeta
from bookforge.theme import Theme
from bookforge.build import build_book

MAX_WORKERS = 2          # WeasyPrint is heavy; keep this modest per CPU


@dataclass
class Job:
    id: str
    status: str = "queued"          # queued | rendering | done | error
    message: str = ""
    title: str = ""
    out_file: Optional[str] = None  # filename within out/
    pages: Optional[int] = None
    created: float = field(default_factory=time.time)

    def public(self) -> dict:
        d = asdict(self)
        d.pop("out_file", None)      # internal path detail
        d["download"] = f"/api/jobs/{self.id}/download" if self.status == "done" else None
        return d


class JobManager:
    def __init__(self, store: JobStore):
        self.store = store
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def submit(self, docx_path: str, meta: BookMeta, theme: Theme,
               job_id: Optional[str] = None) -> Job:
        job_id = job_id or self.store.new_job_id()
        job = Job(id=job_id, title=meta.title)
        with self._lock:
            self._jobs[job_id] = job
        self._pool.submit(self._run, job, docx_path, meta, theme)
        return job

    def _set(self, job: Job, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(job, k, v)

    def _run(self, job: Job, docx_path: str, meta: BookMeta, theme: Theme):
        self._set(job, status="rendering")
        try:
            out_name = "book.pdf"
            out_path = self.store.output_path(job.id, out_name)
            book = build_book(docx_path, out_path, meta, theme, verbose=False)
            self._set(job, status="done", out_file=out_name,
                      message=f"{len(book.chapters)} chapters formatted")
        except Exception as e:
            self._set(job, status="error",
                      message=f"{type(e).__name__}: {e}")
            traceback.print_exc()

"""In-memory batch job bookkeeping.

No DB, no task queue - this is a single local FastAPI process, and all routes are async,
so job-store reads/writes all happen on one event loop (no lock needed, unlike Sheet/
OcrCache which guard against being touched from a sync context). A server restart loses
this bookkeeping, but not the actual work: extracted accounts stay on disk and the OCR
cache is keyed by image hash, so a fresh job after a restart still skips what's done.
"""
import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

Status = Literal["queued", "running", "completed", "failed", "cancelling", "cancelled"]


@dataclass
class BatchJob:
    id: str
    status: Status = "queued"
    total: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0
    current_account: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    report_path: Path | None = None
    task: asyncio.Task | None = None  # not exposed in API responses


class JobStore:
    def __init__(self):
        self._jobs: dict[str, BatchJob] = {}

    def create(self) -> BatchJob:
        job = BatchJob(id=uuid.uuid4().hex[:12])
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> BatchJob | None:
        return self._jobs.get(job_id)

    def list(self) -> list[BatchJob]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def current_running_id(self) -> str | None:
        for job in self._jobs.values():
            if job.status in ("queued", "running", "cancelling"):
                return job.id
        return None

"""Whole-sheet batch processing as a background job.

A full run is ~2.5-4.5 hours (measured: 210 accounts x 4 images, ~10-20s/image), so this
can't be a synchronous POST. POST /batch/run launches it as an asyncio.Task and returns
immediately; GET /batch/{job_id} polls progress; GET /batch/{job_id}/report downloads the
CSV once there's something to download.

Cancellation is cooperative, not asyncio.Task.cancel(): the cancel endpoint just flips the
job's status to "cancelling", and the running loop (app.core.batch.run_batch, via its
is_cancelled callback) notices at the next account boundary and stops itself. That means
whatever account is currently mid-flight gets to finish - its OCR results land in the cache
either way - rather than a hard cancel aborting mid-request and wasting that work.
"""
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import get_batch_jobs, get_ocr_cache, get_ocr_semaphore, get_out_dir, get_sheet
from app.core.batch import BatchCancelled, run_batch
from app.core.jobs import BatchJob, JobStore
from app.config import settings
from app.schemas.batch import BatchJobList, BatchJobStatus, BatchRunRequest

router = APIRouter(prefix="/batch", tags=["batch"])

REPORT_NOT_READY_STATUSES = {"queued", "running", "cancelling"}


async def _execute(job: BatchJob, sheet, out_dir: Path, ocr_cache, semaphore, limit: int | None, force: bool) -> None:
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.report_path = out_dir / "batch_reports" / f"{job.id}.csv"

    rows = sheet.all_rows()
    job.total = min(len(rows), limit) if limit else len(rows)

    async def on_progress(account_no: str, tag: str) -> None:
        job.current_account = account_no
        if tag == "skip (done)":
            job.skipped += 1
        elif tag == "done":
            job.processed += 1
        else:  # "FAILED: ..."
            job.failed += 1

    def is_cancelled() -> bool:
        return job.status == "cancelling"

    try:
        await run_batch(
            rows, out_dir, settings.ollama_model, ocr_cache, semaphore, job.report_path,
            limit=limit, force=force, on_progress=on_progress, is_cancelled=is_cancelled,
        )
        job.status = "completed"
    except BatchCancelled:
        job.status = "cancelled"
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
    finally:
        job.finished_at = datetime.now(timezone.utc)
        job.current_account = None


@router.post("/run", response_model=BatchJobStatus, status_code=202)
async def start_batch(
    body: BatchRunRequest,
    jobs: JobStore = Depends(get_batch_jobs),
    sheet=Depends(get_sheet),
    out_dir: Path = Depends(get_out_dir),
    ocr_cache=Depends(get_ocr_cache),
    semaphore: asyncio.Semaphore = Depends(get_ocr_semaphore),
):
    if jobs.current_running_id() is not None:
        raise HTTPException(status_code=409, detail="A batch job is already running.")

    job = jobs.create()
    job.task = asyncio.create_task(_execute(job, sheet, out_dir, ocr_cache, semaphore, body.limit, body.force))
    return BatchJobStatus.model_validate(job)


@router.get("/", response_model=BatchJobList)
async def list_batches(jobs: JobStore = Depends(get_batch_jobs)):
    return BatchJobList(jobs=[BatchJobStatus.model_validate(j) for j in jobs.list()])


@router.get("/{job_id}", response_model=BatchJobStatus)
async def get_batch(job_id: str, jobs: JobStore = Depends(get_batch_jobs)):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No batch job '{job_id}'.")
    return BatchJobStatus.model_validate(job)


@router.post("/{job_id}/cancel", response_model=BatchJobStatus)
async def cancel_batch(job_id: str, jobs: JobStore = Depends(get_batch_jobs)):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No batch job '{job_id}'.")
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"Job '{job_id}' isn't running (status: {job.status}).")
    job.status = "cancelling"
    return BatchJobStatus.model_validate(job)


@router.get("/{job_id}/report")
async def get_batch_report(job_id: str, jobs: JobStore = Depends(get_batch_jobs)):
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No batch job '{job_id}'.")
    if job.status in REPORT_NOT_READY_STATUSES:
        raise HTTPException(status_code=409, detail=f"Job '{job_id}' hasn't produced a report yet (status: {job.status}).")
    if job.report_path is None or not job.report_path.exists():
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' has no report file.")
    return FileResponse(job.report_path, media_type="text/csv", filename=f"batch_report_{job_id}.csv")

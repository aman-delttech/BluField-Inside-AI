"""App-lifetime singletons (sheet, OCR cache, concurrency semaphore) and shared
per-request validation, wired via FastAPI's dependency injection."""
import asyncio
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile

from app.config import settings


def get_sheet(request: Request):
    return request.app.state.sheet


def get_ocr_cache(request: Request):
    return request.app.state.ocr_cache


def get_out_dir(request: Request) -> Path:
    return request.app.state.out_dir


def get_ocr_semaphore(request: Request) -> asyncio.Semaphore:
    return request.app.state.ocr_semaphore


def get_batch_jobs(request: Request):
    return request.app.state.batch_jobs


async def read_and_validate_image(upload: UploadFile) -> bytes:
    if upload.content_type not in settings.allowed_content_types:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported content type '{upload.content_type}'. Allowed: {', '.join(settings.allowed_content_types)}",
        )
    data = await upload.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Image too large ({len(data)} bytes). Max is {settings.max_upload_bytes} bytes.",
        )
    if not data:
        raise HTTPException(status_code=422, detail="Uploaded image is empty.")
    return data

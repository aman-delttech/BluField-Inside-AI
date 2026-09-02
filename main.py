import asyncio
import os
import uvicorn
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.api.routes import admin, batch, meters, verification
from app.config import settings
from app.core.jobs import JobStore
from app.core.sheet import Sheet
from app.storage import OcrCache


@asynccontextmanager
async def lifespan(app: FastAPI):
    out_dir = Path(settings.out_dir)
    app.state.out_dir = out_dir
    app.state.sheet = Sheet(settings.csv_path)
    app.state.ocr_cache = OcrCache(out_dir)
    app.state.ocr_semaphore = asyncio.Semaphore(settings.max_concurrent_ocr)
    app.state.batch_jobs = JobStore()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="NAMA Image AI OCR & Verification",
        description="Extracts meter identity/reading fields from meter images via local OCR, "
        "and verifies them against the NAMA Image AI sheet.",
        lifespan=lifespan,
    )
    app.include_router(admin.router)
    app.include_router(meters.router)
    app.include_router(verification.router)
    app.include_router(batch.router)
    
    os.makedirs("static", exist_ok=True)
    app.mount("/static", StaticFiles(directory="static"), name="static")

    @app.get("/")
    async def read_index():
        return FileResponse("static/index.html")

    return app


app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

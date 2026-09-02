from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import get_out_dir, get_sheet
from app.config import settings
from app.core.ocr import ollama_reachable
from app.core.sheet import validate_csv_bytes

router = APIRouter(tags=["admin"])


@router.get("/health")
async def health(sheet=Depends(get_sheet)):
    ollama_ok = await ollama_reachable()
    return {
        "status": "ok" if ollama_ok else "degraded",
        "ollama_reachable": ollama_ok,
        "sheet_rows": len(sheet),
    }


@router.post("/admin/reload-sheet")
async def reload_sheet(sheet=Depends(get_sheet)):
    row_count = sheet.reload()
    return {"reloaded": True, "sheet_rows": row_count}


@router.post("/admin/upload-sheet")
async def upload_sheet(
    file: UploadFile = File(..., description="Replacement sheet CSV"),
    sheet=Depends(get_sheet),
    out_dir: Path = Depends(get_out_dir),
):
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Uploaded file is empty.")
    if len(data) > settings.max_sheet_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({len(data)} bytes). Max is {settings.max_sheet_upload_bytes} bytes.",
        )
    try:
        row_count = validate_csv_bytes(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    csv_path = Path(settings.csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    # data/Cherry Data.csv is gitignored - there's no version history to fall back on,
    # so keep one backup of whatever this upload is about to replace.
    backup_path = None
    if csv_path.exists():
        backups_dir = out_dir / "sheet_backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = backups_dir / f"{stamp}_{csv_path.name}"
        backup_path.write_bytes(csv_path.read_bytes())

    tmp_path = csv_path.with_name(csv_path.name + ".tmp")
    tmp_path.write_bytes(data)
    tmp_path.replace(csv_path)  # atomic on the same filesystem - no half-written sheet on disk

    reloaded_count = sheet.reload()
    return {
        "uploaded": True,
        "filename": file.filename,
        "sheet_rows": reloaded_count,
        "validated_rows": row_count,
        "backup": str(backup_path) if backup_path else None,
    }

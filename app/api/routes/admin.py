from fastapi import APIRouter, Depends

from app.api.deps import get_sheet
from app.core.ocr import ollama_reachable

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

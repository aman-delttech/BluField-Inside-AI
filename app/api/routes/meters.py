from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.api.deps import get_ocr_cache, get_ocr_semaphore, get_out_dir, read_and_validate_image
from app.core.extraction import extract_meter
from app.core.ocr import OcrError
from app.schemas.extraction import ExtractionResponse
from app.storage import write_extraction

router = APIRouter(tags=["meters"])


async def _handle(
    is_new: bool,
    account_no: str,
    details_image: UploadFile,
    reading_image: UploadFile,
    ocr_cache,
    semaphore,
    out_dir,
) -> ExtractionResponse:
    details_bytes = await read_and_validate_image(details_image)
    reading_bytes = await read_and_validate_image(reading_image)

    async with semaphore:
        try:
            data = await extract_meter(account_no, details_bytes, reading_bytes, is_new, ocr_cache=ocr_cache)
        except OcrError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

    write_extraction(out_dir, account_no, data["meter"], data)
    return ExtractionResponse(**data)


@router.post("/old-meter", response_model=ExtractionResponse)
async def old_meter(
    account_no: str = Form(...),
    details_image: UploadFile = File(..., description="Nameplate photo: meter no., ICCID sticker, phase"),
    reading_image: UploadFile = File(..., description="LCD photo of the last reading"),
    ocr_cache=Depends(get_ocr_cache),
    semaphore=Depends(get_ocr_semaphore),
    out_dir=Depends(get_out_dir),
):
    return await _handle(False, account_no, details_image, reading_image, ocr_cache, semaphore, out_dir)


@router.post("/new-meter", response_model=ExtractionResponse)
async def new_meter(
    account_no: str = Form(...),
    details_image: UploadFile = File(..., description="Nameplate photo: meter no., ICCID sticker, phase"),
    reading_image: UploadFile = File(..., description="LCD photo of the initial reading"),
    ocr_cache=Depends(get_ocr_cache),
    semaphore=Depends(get_ocr_semaphore),
    out_dir=Depends(get_out_dir),
):
    return await _handle(True, account_no, details_image, reading_image, ocr_cache, semaphore, out_dir)

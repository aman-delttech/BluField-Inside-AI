from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_sheet
from app.core.verification import verify_meter
from app.schemas.verification import VerificationResponse, VerifyRequest

router = APIRouter(prefix="/verify", tags=["verification"])


def _verify(meter: str, body: VerifyRequest, sheet) -> VerificationResponse:
    row = sheet.get(body.account_no)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Account No '{body.account_no}' not found in the sheet.")
    result = verify_meter(meter, body.model_dump(), row)
    return VerificationResponse(**result)


@router.post("/old-meter", response_model=VerificationResponse)
async def verify_old_meter(body: VerifyRequest, sheet=Depends(get_sheet)):
    return _verify("old", body, sheet)


@router.post("/new-meter", response_model=VerificationResponse)
async def verify_new_meter(body: VerifyRequest, sheet=Depends(get_sheet)):
    return _verify("new", body, sheet)

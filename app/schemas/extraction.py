from typing import Literal

from pydantic import BaseModel


class ExtractionResponse(BaseModel):
    account_no: str
    meter: Literal["old", "new"]
    iccid: str | None = None
    meter_no: str | None = None
    meter_phase: str | None = None
    meter_reading: str | None = None
    needs_review: dict[str, list[str | None]] = {}
    sources: dict[str, str] = {}
    raw_ocr: dict[str, str] = {}

from pydantic import BaseModel, ConfigDict


class VerifyRequest(BaseModel):
    """Accepts exactly what /old-meter or /new-meter returned. Only these fields are
    read; extras (needs_review, sources, raw_ocr, ...) are ignored, so the whole
    extraction response can be pasted straight in."""

    model_config = ConfigDict(extra="ignore")

    account_no: str
    iccid: str | None = None
    meter_no: str | None = None
    meter_phase: str | None = None
    meter_reading: str | None = None


class FieldResult(BaseModel):
    extracted: str | None
    expected: str | None
    status: str
    similarity: float | None = None


class VerifySummary(BaseModel):
    match: int
    checked: int
    rate: float | None


class VerificationResponse(BaseModel):
    account_no: str | None
    meter: str
    all_match: bool
    fields: dict[str, FieldResult]
    summary: VerifySummary

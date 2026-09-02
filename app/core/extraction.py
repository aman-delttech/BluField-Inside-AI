"""Orchestrates OCR + parsing for one meter (two images -> one merged field set).

Both images are parsed for every field and cross-checked against each other, regardless
of which one is nominally "details" and which is "reading" - that cross-check is the main
defense against glm-ocr's occasional dropped digit on long serials/ICCIDs. The role split
only decides labeling in the response, not which fields get read from which image.
"""
import hashlib

from app.core.ocr import ocr_image_bytes
from app.core.parsing import merge, parse_dump


async def extract_meter(
    account_no: str,
    details_bytes: bytes,
    reading_bytes: bytes,
    is_new: bool,
    model: str | None = None,
    ocr_cache: dict | None = None,
) -> dict:
    """ocr_cache, if given, maps a cache key (e.g. sha256 of the image bytes) to an
    already-computed OCR dump, and is populated as a side effect - callers control the
    keying since it depends on how they want to dedupe (by content, by account, etc.)."""

    async def dump_for(key: str, image_bytes: bytes) -> str:
        if ocr_cache is not None and key in ocr_cache:
            return ocr_cache[key]
        text = await ocr_image_bytes(image_bytes, model)
        if ocr_cache is not None:
            ocr_cache[key] = text
        return text

    details_key = hashlib.sha256(details_bytes).hexdigest()
    reading_key = hashlib.sha256(reading_bytes).hexdigest()

    details_dump = await dump_for(details_key, details_bytes)
    reading_dump = await dump_for(reading_key, reading_bytes)

    fields_details = parse_dump(details_dump, is_new)
    fields_reading = parse_dump(reading_dump, is_new)
    merged, review = merge(fields_details, fields_reading)

    if is_new and merged.get("meter_no") and len(merged["meter_no"]) != 15:
        review.setdefault("meter_no", [merged["meter_no"]])

    return {
        "account_no": account_no,
        "meter": "new" if is_new else "old",
        **merged,
        "needs_review": review,
        "sources": {"details_image": f"sha256:{details_key[:12]}", "reading_image": f"sha256:{reading_key[:12]}"},
        "raw_ocr": {"details": details_dump, "reading": reading_dump},
    }

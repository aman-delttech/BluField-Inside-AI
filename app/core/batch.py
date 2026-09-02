"""Process every account in a sheet and write one CSV report.

Fetches each account's 4 meter images from the sheet's own URLs (OldMeterImage,
LastReadingImage, NewMeterImage, InitialReadingImage), runs them through the same
extraction + verification path the single-account endpoints use, and writes one row per
account to a CSV.

Framework-agnostic (no FastAPI imports) - app/api/routes/batch.py wraps run_batch() as a
background job; nothing here knows it's being called from a route.
"""
import asyncio
import csv
import json
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from app.core.extraction import extract_meter
from app.core.verification import FIELDS, verify_meter
from app.storage import write_extraction

IMAGE_COLUMNS = {
    "old": ("OldMeterImage", "LastReadingImage"),
    "new": ("NewMeterImage", "InitialReadingImage"),
}


class BatchCancelled(Exception):
    """Raised out of run_batch() when is_cancelled() returns true at an account boundary."""


def csv_fieldnames() -> list[str]:
    names = ["account_no", "status", "error"]
    for meter in ("old", "new"):
        for field in FIELDS:
            names += [f"{meter}_{field}", f"{meter}_{field}_expected", f"{meter}_{field}_status", f"{meter}_{field}_similarity"]
        names += [f"{meter}_all_match", f"{meter}_checked", f"{meter}_match", f"{meter}_rate"]
    return names


def already_extracted(account_no: str, out_dir: Path) -> tuple[dict, dict] | None:
    old_path = out_dir / f"{account_no}_old.json"
    new_path = out_dir / f"{account_no}_new.json"
    if old_path.exists() and new_path.exists():
        return json.loads(old_path.read_text()), json.loads(new_path.read_text())
    return None


async def fetch_image(client: httpx.AsyncClient, url: str) -> bytes:
    resp = await client.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


async def process_account(
    client: httpx.AsyncClient, account_no: str, row: dict, out_dir: Path, model: str, ocr_cache, semaphore: asyncio.Semaphore
) -> tuple[dict, dict]:
    old_details_url, old_reading_url = IMAGE_COLUMNS["old"]
    new_details_url, new_reading_url = IMAGE_COLUMNS["new"]
    old_details = await fetch_image(client, row[old_details_url])
    old_reading = await fetch_image(client, row[old_reading_url])
    new_details = await fetch_image(client, row[new_details_url])
    new_reading = await fetch_image(client, row[new_reading_url])

    # Same semaphore /old-meter and /new-meter use, so a batch job and a manual call
    # queue fairly against each other instead of one starving the other.
    async with semaphore:
        old_data = await extract_meter(account_no, old_details, old_reading, is_new=False, model=model, ocr_cache=ocr_cache)
    async with semaphore:
        new_data = await extract_meter(account_no, new_details, new_reading, is_new=True, model=model, ocr_cache=ocr_cache)

    write_extraction(out_dir, account_no, "old", old_data)
    write_extraction(out_dir, account_no, "new", new_data)
    return old_data, new_data


def build_row(account_no: str, old_result: dict, new_result: dict) -> dict:
    row = {"account_no": account_no, "status": "OK", "error": ""}
    for meter, result in (("old", old_result), ("new", new_result)):
        for field in FIELDS:
            r = result["fields"][field]
            row[f"{meter}_{field}"] = r["extracted"]
            row[f"{meter}_{field}_expected"] = r["expected"]
            row[f"{meter}_{field}_status"] = r["status"]
            row[f"{meter}_{field}_similarity"] = r.get("similarity", "")
        row[f"{meter}_all_match"] = result["all_match"]
        row[f"{meter}_checked"] = result["summary"]["checked"]
        row[f"{meter}_match"] = result["summary"]["match"]
        row[f"{meter}_rate"] = result["summary"]["rate"]
    return row


def error_row(account_no: str, error: str) -> dict:
    row = {name: "" for name in csv_fieldnames()}
    row["account_no"] = account_no
    row["status"] = "ERROR"
    row["error"] = error
    return row


async def run_batch(
    rows: dict[str, dict],
    out_dir: Path,
    model: str,
    ocr_cache,
    semaphore: asyncio.Semaphore,
    output_path: Path,
    *,
    limit: int | None = None,
    force: bool = False,
    on_progress: Callable[[str, str], Awaitable[None]] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> dict:
    """on_progress(account_no, tag) is awaited after each account ("skip (done)", "done",
    or "FAILED"). is_cancelled() is checked at the same account boundary; when it returns
    true, the loop stops and BatchCancelled is raised - the CSV keeps every row already
    written, same as a script would if killed at that point.

    Returns {"processed": int, "skipped": int, "failed": int, "total": int}.
    """
    accounts = list(rows.items())
    if limit:
        accounts = accounts[:limit]
    total = len(accounts)

    out_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = csv_fieldnames()

    processed = skipped = failed = 0

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        async with httpx.AsyncClient() as client:
            for account_no, row in accounts:
                if is_cancelled is not None and is_cancelled():
                    raise BatchCancelled

                existing = None if force else already_extracted(account_no, out_dir)
                if existing:
                    old_data, new_data = existing
                    skipped += 1
                    tag = "skip (done)"
                else:
                    try:
                        old_data, new_data = await process_account(client, account_no, row, out_dir, model, ocr_cache, semaphore)
                        processed += 1
                        tag = "done"
                    except Exception as e:
                        failed += 1
                        writer.writerow(error_row(account_no, str(e)))
                        f.flush()
                        if on_progress is not None:
                            await on_progress(account_no, f"FAILED: {e}")
                        continue

                old_result = verify_meter("old", old_data, row)
                new_result = verify_meter("new", new_data, row)
                writer.writerow(build_row(account_no, old_result, new_result))
                f.flush()

                if on_progress is not None:
                    await on_progress(account_no, tag)

    return {"processed": processed, "skipped": skipped, "failed": failed, "total": total}

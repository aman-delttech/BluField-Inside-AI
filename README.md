# Cherry Data — Meter OCR & Verification Service

A FastAPI service that reads meter identity/reading fields (ICCID, meter number, phase,
reading) out of photographed meter nameplates and LCDs using a local vision-OCR model on
[ollama](https://ollama.com), and verifies what it read against the Cherry Data sheet
(`data/Cherry Data.csv`).

Two meters are involved in every account: the **old** meter being removed and the **new**
meter replacing it. Each has its own extract/verify endpoint pair.

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Setup](#setup)
- [Running the service](#running-the-service)
- [Configuration](#configuration)
- [API reference](#api-reference)
- [Project layout](#project-layout)
- [The Cherry Data sheet](#the-cherry-data-sheet)
- [Known limitations](#known-limitations)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

## How it works

For one meter, the client uploads two photos:

- **`details_image`** — the nameplate: meter number, ICCID sticker (new meters only), phase
  rating.
- **`reading_image`** — the LCD showing the energy reading.

Both images are OCR'd with the local `glm-ocr` model on ollama, which is an OCR engine, not
an instruction-following model — it always returns a full-page text dump of everything it
sees, regardless of how the prompt is worded. All field extraction therefore happens in
Python, via regex/line-scanning against that dump (`app/core/parsing.py`).

Critically, **both images are parsed for every field**, not just their nominal role — the
details image is also scanned for a reading, the reading image is also scanned for a meter
number, and so on. The two independent reads are then cross-checked
(`app/core/parsing.py::merge`): where they agree, that's the answer; where they disagree,
the response flags it in `needs_review` with both candidates. This is the main defense
against the model's occasional dropped digit on long serials/ICCIDs — a flagged uncertainty
beats a confidently wrong one.

The result is a JSON extraction response. Posting that same JSON to the matching
`/verify/*` endpoint compares it, field by field, against the sheet's verified columns for
that account and reports `MATCH` / `MISMATCH` / `MISSING` / `NA` / `UNEXPECTED`, with a
similarity score on mismatches.

## Requirements

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) running locally with the OCR model pulled:
  ```
  ollama pull glm-ocr:latest
  ```
  (the app only talks to ollama's HTTP API — the desktop app or `ollama serve` both work)

## Setup

```
uv sync
cp .env.example .env   # optional; defaults work if ollama is on localhost:11434
```

`uv sync` installs both runtime and dev (pytest) dependencies from `pyproject.toml` into
`.venv`.

## Running the service

```
uv run uvicorn app.main:app --reload
```

Interactive docs (Swagger UI) at `http://localhost:8000/docs`; ReDoc at `/redoc`.

> If port 8000 is already taken by something else on your machine, run with `--port 8811`
> (or any free port) instead.

On startup the app loads `data/Cherry Data.csv` into memory and opens (or creates)
`out/_ocr_cache.json`. Nothing else needs to be running except ollama.

## Configuration

All settings are environment variables with a `METER_` prefix, loaded from `.env` if
present (see `.env.example`), otherwise defaulting as shown:

| Variable | Default | Meaning |
|---|---|---|
| `METER_OLLAMA_URL` | `http://localhost:11434/api/generate` | ollama's generate endpoint |
| `METER_OLLAMA_MODEL` | `glm-ocr:latest` | model tag to use for OCR |
| `METER_OLLAMA_TIMEOUT` | `300` | seconds to wait for one OCR call |
| `METER_CSV_PATH` | `data/Cherry Data.csv` | sheet loaded at startup / on reload |
| `METER_OUT_DIR` | `out` | where extraction JSON + the OCR cache are written |
| `METER_MAX_UPLOAD_BYTES` | `10485760` (10MB) | per-image upload limit |
| `METER_MAX_CONCURRENT_OCR` | `1` | max OCR calls in flight at once (see below) |

The accepted image content types (`image/jpeg`, `image/png`, `image/webp`) are set in
`app/config.py` and not listed above — they're a plain Python tuple there, not meant to be
overridden per-deployment the way the rest of this table is.

**Why `METER_MAX_CONCURRENT_OCR` defaults to 1:** ollama serves one model instance and
processes requests one at a time regardless of how many arrive concurrently. Without a
limit, simultaneous requests would all sit blocked inside ollama with no visibility into
the queue. The app instead queues them itself via an `asyncio.Semaphore`, so concurrent
callers wait predictably rather than everyone's request slowing down together.

## API reference

All endpoints are synchronous — an extract call blocks for the ~10–40s the OCR takes
(2 images × ~10–20s each). There is no async job/polling mode.

### `POST /old-meter`, `POST /new-meter`

Extract fields from one meter's two photos.

**Request** — `multipart/form-data`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `account_no` | form field | yes | Echoed into the response; used later by `/verify/*`. Kept as a string — leading zeros (`00519041`) and non-numeric account numbers (`R04615`) are both significant. |
| `details_image` | file | yes | Nameplate photo. |
| `reading_image` | file | yes | LCD reading photo. |

Accepted content types: `image/jpeg`, `image/png`, `image/webp`. Max size: 10MB (both
configurable, see above).

**Response** `200`:

```json
{
  "account_no": "00519041",
  "meter": "old",
  "iccid": null,
  "meter_no": "P0538433",
  "meter_phase": "Single Phase",
  "meter_reading": "9",
  "needs_review": {
    "meter_no": ["P0538433", "P2538433"]
  },
  "sources": {
    "details_image": "sha256:d5b8f5aba3c1",
    "reading_image": "sha256:07451116826b"
  },
  "raw_ocr": {
    "details": "...full text dump from the details image...",
    "reading": "...full text dump from the reading image..."
  }
}
```

- `iccid` is `null` for **every** old meter — old meters have no SIM. That's the correct
  extraction, not a failure.
- `needs_review` lists fields where the two images disagreed with each other, or where a
  format check failed (ICCID not exactly 19 digits, new-meter `meter_no` not exactly 15
  digits). Absence of a field here doesn't guarantee correctness, only agreement.
- `sources` identifies each image by the first 12 hex chars of its content sha256 (uploads
  have no URL to reference).
- `raw_ocr` is the full, unparsed text dump from each image — useful for manually checking a
  flagged field without re-running OCR.
- The response is also written to `out/<account_no>_<old|new>.json`.

**Errors:**

| Status | When |
|---|---|
| `415` | image content-type isn't jpeg/png/webp |
| `413` | image exceeds `METER_MAX_UPLOAD_BYTES` |
| `422` | an image field is present but empty |
| `503` | ollama is unreachable or returned something unusable |

Extraction does **not** require the account to exist in the sheet — it runs regardless, so
you can extract from an image before the sheet has a matching row.

### `POST /verify/old-meter`, `POST /verify/new-meter`

Compare an extraction response against the sheet.

**Request** — JSON body. Pass the **entire** response you got from `/old-meter` or
`/new-meter` straight back in; only `account_no`, `iccid`, `meter_no`, `meter_phase`, and
`meter_reading` are read, everything else (`needs_review`, `sources`, `raw_ocr`, `meter`) is
ignored.

**Response** `200`:

```json
{
  "account_no": "00519041",
  "meter": "old",
  "all_match": false,
  "fields": {
    "iccid": { "extracted": null, "expected": null, "status": "NA" },
    "meter_no": {
      "extracted": "P0538433", "expected": "P3S38433",
      "status": "MISMATCH", "similarity": 0.75
    },
    "meter_phase": { "extracted": "Single Phase", "expected": "Single Phase", "status": "MATCH" },
    "meter_reading": { "extracted": "9", "expected": "9", "status": "MATCH" }
  },
  "summary": { "match": 2, "checked": 3, "rate": 0.667 }
}
```

**Field statuses:**

| Status | Meaning |
|---|---|
| `MATCH` | normalized extracted value equals the sheet's |
| `MISMATCH` | both present, different — `similarity` (0–1, via `difflib`) says how close. A high similarity (e.g. 0.97, one dropped digit out of nineteen) points at an OCR slip; a low one (e.g. 0.3) means the model read something else entirely. |
| `MISSING` | OCR returned null but the sheet has a value |
| `NA` | `old.iccid` only — old meters have no SIM, so null is correct and this isn't counted as a check |
| `UNEXPECTED` | `old.iccid` only — a non-null value came back, meaning OCR hallucinated a SIM onto an old meter |

`summary.checked`/`rate` exclude `NA` fields. `all_match` is `true` only if every checked
field is `MATCH`.

Normalization before comparing (`app/core/verification.py::normalize`): strip surrounding
whitespace, remove *internal* whitespace (OCR sometimes splits a serial into groups, e.g.
`92 212 706`), uppercase. **Leading zeros are preserved** — they're significant in these
meter numbers.

**Errors:**

| Status | When |
|---|---|
| `404` | `account_no` isn't in the currently-loaded sheet |
| `422` | request body missing `account_no` or malformed |

### `GET /health`

```json
{ "status": "ok", "ollama_reachable": true, "sheet_rows": 210 }
```

`status` is `"degraded"` (not an HTTP error — still `200`) when `ollama_reachable` is
`false`. Extraction calls will fail with `503` while degraded.

### `POST /admin/reload-sheet`

Re-reads `METER_CSV_PATH` from disk into memory, without restarting the process. Use this
after editing the CSV.

```json
{ "reloaded": true, "sheet_rows": 210 }
```

There's no authentication on this (or any) endpoint currently — see
[Known limitations](#known-limitations).

## Project layout

```
app/
  main.py                    FastAPI app factory + lifespan (loads sheet, OCR cache, semaphore)
  config.py                  Settings (env-driven, METER_ prefix)
  api/
    deps.py                  Shared DI: sheet/cache/out_dir/semaphore accessors, upload validation
    routes/
      meters.py              POST /old-meter, /new-meter
      verification.py        POST /verify/old-meter, /verify/new-meter
      admin.py                GET /health, POST /admin/reload-sheet
  core/
    ocr.py                   ollama HTTP client (httpx), OcrError, reachability check
    parsing.py                OCR text dump -> structured fields; the cross-check merge
    extraction.py             Orchestrates: 2 images -> OCR -> parse -> merge -> response
    verification.py           Truth-column mapping, field comparison, summary
    sheet.py                  Thread-safe in-memory CSV cache, reloadable
  schemas/
    extraction.py             ExtractionResponse
    verification.py           VerifyRequest, FieldResult, VerificationResponse
  storage.py                  Writes out/<account>_<meter>.json; disk-backed OCR cache
tests/
  conftest.py                 Test fixtures: temp sheet CSV, mocked OCR, TestClient
  fixtures/ocr_dumps.py        Real glm-ocr dumps captured for account 00519041
  test_parsing.py             Parser tests against the real dumps
  test_verification.py        Comparison-logic tests across all five statuses
  test_api.py                  Endpoint tests (OCR mocked - offline, fast)
data/
  Cherry Data.csv              The sheet
out/                            Created at runtime: extraction JSON + OCR cache (gitignored)
```

## The Cherry Data sheet

`data/Cherry Data.csv` currently has **210 rows**, one per meter-replacement account, with
columns for both a "raw" value entered in the field and (for most fields) a corresponding
QC-reviewed column. **Which one is trustworthy is not the same answer for every field** —
this was established by profiling the sheet, not assumed, and it's why
`app/core/verification.py::TRUTH_COLUMN` doesn't just pick one column name and reuse it:

| Field | Verified against | Why |
|---|---|---|
| `old.meter_no` | `Old Meter No.` | no QC column exists for this one |
| `new.meter_no` | `QCNewMeterNo` | raw `New Meter No.` occasionally holds garbage (an ICCID fragment, seen on at least one row) |
| `*.meter_phase` | `QCPhaseCategory` | raw and QC disagree on a small number of rows |
| `new.iccid` | `QCICCID No` | raw `ICCID No` is malformed in roughly 60% of rows (wrong length, missing the `8996` prefix) — QC is clean throughout |
| `old.iccid` | *(none)* | old meters have no SIM; `null` is always the correct extraction |
| `*.meter_reading` | **raw** `Old Meter Reading` / `InitialReading` | this one **inverts** the usual pattern — where raw and QC disagree, the QC reading column is almost always `0` or blank while the raw column holds the real value. Confirmed visually: account `00519041`'s LCD reads `9`, matching the raw column, not QC's `0`. |

Account numbers are matched as **strings**, never parsed as integers — some are non-numeric
(`R04615`, `S19424`) and leading zeros are significant throughout.

## Known limitations

- **glm-ocr is not fully deterministic even at `temperature: 0`.** Re-OCRing the identical
  image bytes twice, on two different runs, has produced different digit strings (e.g. an
  LCD reading of `9` came back as `300` on a later run — a value/unit split across two OCR
  lines the parser resolved differently on the borderline case). The two-image cross-check
  and `needs_review` flag are the mitigation; they surface the disagreement rather than
  silently picking one.
- **Long digit strings drop digits.** ICCID (19 digits) and long meter serials are where
  this shows up most — expect a small number of `MISMATCH`es at very high similarity (0.9+)
  even on a correct read. `new.meter_reading` specifically has a low correct-read rate: the
  model frequently reads a load-current figure off the LCD instead of the cumulative energy
  register, and `InitialReading` is `0` in the overwhelming majority of rows.
- **No batch/whole-sheet endpoint.** Each call handles one account's images, supplied by the
  caller. There's no way to point the service at the CSV's own S3 image URLs and walk every
  row — that capability existed in an earlier CLI-script version of this project and was
  deliberately dropped when it became an API. Re-adding it means either an async job
  endpoint (a full-sheet run takes on the order of hours) or a separate offline script.
- **No auth, no CORS, no rate limiting.** Fine for local/trusted-network use; add before
  exposing this beyond that.
- **Single-process state.** The sheet cache, OCR cache, and concurrency semaphore all live
  in one process's memory (the OCR cache is also persisted to disk). Running multiple
  instances behind a load balancer would need each to reload independently and wouldn't
  share OCR caching or the concurrency limit across instances.
- **`MeterTerminalImage`** (a column in the CSV) is never used by this service.

## Testing

```
uv run pytest
```

29 tests, all offline (no ollama, no network) — OCR is mocked in `tests/conftest.py` with
the real captured dumps from `tests/fixtures/ocr_dumps.py`, so parsing and endpoint behavior
are exercised against real model output without the ~15s-per-image cost of calling ollama.

- `test_parsing.py` — the regex/line-scan heuristics, including two regression cases
  (grabbing a nameplate's type code instead of the serial; a reading value split across two
  OCR lines).
- `test_verification.py` — all five field statuses, and specifically that `meter_reading`
  and `iccid`/`meter_no` pull from *different* columns (raw vs. QC).
- `test_api.py` — the full HTTP surface: extraction, verification round-trips, persistence
  to `out/`, and all four error paths (404/413/415/503).

To exercise real OCR end-to-end (slow — this is what the mocked tests intentionally avoid),
run the server and post real images from the sheet:

```
uv run uvicorn app.main:app --port 8811 &
curl -X POST http://localhost:8811/old-meter \
  -F "account_no=00519041" \
  -F "details_image=@om.jpg;type=image/jpeg" \
  -F "reading_image=@lr.jpg;type=image/jpeg"
```

## Troubleshooting

**`/health` shows `"ollama_reachable": false`** — confirm ollama is running
(`curl http://localhost:11434/`, should return `Ollama is running`) and that
`METER_OLLAMA_URL` in `.env` matches where it's listening.

**Extraction returns `503`** — same cause as above; check `/health` first. Note that a
request for **image bytes already OCR'd before** returns instantly from
`out/_ocr_cache.json` regardless of whether ollama is currently reachable — the cache is
keyed purely by image content hash, so this is by design, not a bug, if you're testing
against a stopped ollama with previously-seen images.

**`/verify/*` returns `404`** — the `account_no` in the request body isn't in the
currently-loaded sheet. Check spelling/leading zeros, or `POST /admin/reload-sheet` if the
CSV was edited after the server started.

**Port 8000 already in use** — pick another port with `--port`; nothing here assumes 8000
specifically.

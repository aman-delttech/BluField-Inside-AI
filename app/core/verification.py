"""Compare extracted meter fields against the CSV's verified columns.

Which CSV column is "truth" is not the same column for every field - see the two notes
below, both established by profiling the actual sheet rather than assumed:

- iccid / meter_no (new meter) / meter_phase: the raw CSV columns are unreliable (e.g. raw
  ICCID No is malformed in 132 of 210 rows - values like '10500149'), while the QC* columns
  are clean throughout. So these compare against the QC columns.
- meter_reading inverts that rule: where Old Meter Reading and QCOldMeterReading disagree,
  QCOldMeterReading is almost always 0 or blank while Old Meter Reading holds the real value
  (visually confirmed against account 00519041's LCD, which reads 9 - matching the raw
  column, not QC's 0). So readings compare against the raw reading columns.
- old.iccid has no truth column at all: old meters carry no SIM, so null is the correct
  extraction, not a gap.
"""
import difflib
import re

WS_RE = re.compile(r"\s+")

FIELDS = ("iccid", "meter_no", "meter_phase", "meter_reading")

# (meter, field) -> CSV column holding the verified value.
TRUTH_COLUMN = {
    ("old", "meter_no"): "Old Meter No.",
    ("old", "meter_phase"): "QCPhaseCategory",
    ("old", "meter_reading"): "Old Meter Reading",
    ("new", "meter_no"): "QCNewMeterNo",
    ("new", "meter_phase"): "QCPhaseCategory",
    ("new", "meter_reading"): "InitialReading",
    ("new", "iccid"): "QCICCID No",
}

STATUSES = ("MATCH", "MISMATCH", "MISSING", "NA", "UNEXPECTED")


def normalize(v: str | None) -> str | None:
    if v is None:
        return None
    return WS_RE.sub("", v.strip().upper())


def compare_field(meter: str, field: str, extracted, row: dict) -> dict:
    if meter == "old" and field == "iccid":
        return {"extracted": extracted, "expected": None, "status": "UNEXPECTED" if extracted else "NA"}

    expected_raw = row[TRUTH_COLUMN[(meter, field)]]
    extracted_n, expected_n = normalize(extracted), normalize(expected_raw)

    if extracted_n == expected_n:
        status = "MATCH"
    elif extracted_n is None:
        status = "MISSING"
    else:
        status = "MISMATCH"

    result = {"extracted": extracted, "expected": expected_raw, "status": status}
    if status == "MISMATCH":
        result["similarity"] = round(difflib.SequenceMatcher(None, extracted_n, expected_n).ratio(), 3)
    return result


def verify_meter(meter: str, extracted: dict, row: dict) -> dict:
    """extracted: dict with iccid/meter_no/meter_phase/meter_reading keys (an extraction
    response, or any dict that has at least those keys - extras are ignored)."""
    fields = {f: compare_field(meter, f, extracted.get(f), row) for f in FIELDS}
    checked = [r for r in fields.values() if r["status"] != "NA"]
    match = sum(1 for r in checked if r["status"] == "MATCH")
    return {
        "account_no": extracted.get("account_no"),
        "meter": meter,
        "all_match": bool(checked) and match == len(checked),
        "fields": fields,
        "summary": {
            "match": match,
            "checked": len(checked),
            "rate": round(match / len(checked), 3) if checked else None,
        },
    }

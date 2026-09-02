"""Turn a glm-ocr text dump into structured meter fields.

glm-ocr ignores instructions - it returns a full-page text dump of everything it sees no
matter how the prompt is worded. So the OCR prompt just asks it to read everything, and all
the field extraction happens here in Python via regex/line scanning.

These heuristics were tuned against real captured dumps for account 00519041 and verified
against a second account (01141303) to confirm nothing was overfit to the first. See
tests/test_parsing.py for the fixtures.
"""
import re

BANNER_RE = re.compile(r"^\s*\[.*?\]\s*$", re.MULTILINE)  # burned-in [Account] [Date] [Lat:] [Long:] lines
ICCID_RE = re.compile(r"\b89\d{15,20}\b")
NEW_METER_NO_RE = re.compile(r"\b\d{15}\b")

# Old meter serials in this dataset run 5-12 chars, either pure digits ('29953') or
# letter+digit mixes ('P3S38433'). The nameplate also prints a *type* code in the same
# shape ('E1C106') right after a "Type:" label, plus brand/standard boilerplate - so we
# scan line by line and skip any line carrying that boilerplate rather than matching
# the whole dump at once.
OLD_METER_NO_TOKEN_RE = re.compile(r"\b[A-Z0-9]{5,12}\b")
OLD_METER_NO_SKIP_LINE_RE = re.compile(
    r"type|iec|mjec|secur|meters|limited|made in|property|imp/kwh|credit|\bkw\b|\bkwh\b", re.IGNORECASE
)
OLD_METER_NO_NOISE = {"SECURE", "MJEC", "TYPE"}

DIGIT_RUN_RE = re.compile(r"\d[\d.]*\d|\d")


def strip_banner(text: str) -> str:
    return BANNER_RE.sub("", text)


def parse_iccid(text: str) -> str | None:
    matches = ICCID_RE.findall(text)
    return max(matches, key=len) if matches else None


def parse_meter_no(text: str, is_new: bool) -> str | None:
    if is_new:
        matches = NEW_METER_NO_RE.findall(text)
        return matches[0] if matches else None
    for line in text.splitlines():
        if OLD_METER_NO_SKIP_LINE_RE.search(line):
            continue
        for m in OLD_METER_NO_TOKEN_RE.finditer(line.upper()):
            tok = m.group()
            if tok in OLD_METER_NO_NOISE:
                continue
            return tok
    return None


def parse_phase(text: str) -> str | None:
    t = text.lower()
    if re.search(r"\b1p\b|\b2w\b|single phase|single\s*ph", t):
        return "Single Phase"
    if re.search(r"\b3p\b|\b4w\b|three phase|three\s*ph", t):
        return "Three Phase"
    return None


def parse_reading(text: str) -> str | None:
    # The LCD reading is what the device shows front-and-center, so it's what OCR
    # transcribes first; the meter's own serial/spec numbers come later in the dump.
    # Stay on the matching line only - pulling in neighbouring lines drags in the
    # serial number sitting right next to it, which is longer and looks "better".
    lines = text.splitlines()
    best = None
    for i, line in enumerate(lines):
        if not re.search(r"kW\s*h", line, re.IGNORECASE):
            continue
        # usually the value sits on this same line ("000009 kW h"); occasionally OCR
        # splits it onto its own line just above the unit ("300" / "kW h") - check one
        # line back, but no further, so we don't drift into the serial number above it.
        candidates = list(DIGIT_RUN_RE.finditer(line))
        if not candidates and i > 0:
            candidates = list(DIGIT_RUN_RE.finditer(lines[i - 1]))
        for m in candidates:
            candidate = m.group()
            if best is None or len(candidate.replace(".", "")) > len(best.replace(".", "")):
                best = candidate
        break  # first kWh-bearing line only
    if best is None:
        return None
    if "." in best:
        whole, _, frac = best.partition(".")
        whole = whole.lstrip("0") or "0"
        return f"{whole}.{frac}"
    stripped = best.lstrip("0")
    return stripped or "0"


def parse_dump(text: str, is_new: bool) -> dict:
    clean = strip_banner(text)
    return {
        "iccid": parse_iccid(clean),
        "meter_no": parse_meter_no(clean, is_new),
        "meter_phase": parse_phase(clean),
        "meter_reading": parse_reading(clean),
    }


def merge(a: dict, b: dict) -> tuple[dict, dict]:
    """Merge two field-dicts from independent images of the same meter.
    Returns (merged, needs_review)."""
    merged = {}
    review = {}
    for key in ("iccid", "meter_no", "meter_phase", "meter_reading"):
        va, vb = a.get(key), b.get(key)
        if va and vb:
            if va == vb:
                merged[key] = va
            else:
                merged[key] = va
                review[key] = [va, vb]
        else:
            merged[key] = va or vb
    if merged.get("iccid") and len(merged["iccid"]) != 19:
        review.setdefault("iccid", [merged["iccid"]])
    return merged, review

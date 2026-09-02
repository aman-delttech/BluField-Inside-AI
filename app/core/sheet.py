"""In-memory cache of the CSV sheet, keyed by Account No."""
import csv
import io
import threading

# Every column actually read somewhere in this codebase: account/verification truth
# columns (app/core/verification.py::TRUTH_COLUMN) plus the four image URL columns
# extraction and batch processing fetch from (app/core/extraction.py, app/core/batch.py).
REQUIRED_SHEET_COLUMNS = (
    "Account No",
    "Old Meter No.",
    "QCPhaseCategory",
    "Old Meter Reading",
    "QCNewMeterNo",
    "InitialReading",
    "QCICCID No",
    "OldMeterImage",
    "LastReadingImage",
    "NewMeterImage",
    "InitialReadingImage",
)


def load_rows(csv_path: str) -> dict[str, dict]:
    """Account No -> CSV row, keyed as a string (leading zeros, and non-numeric
    account numbers like 'R04615', are both significant)."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        return {r["Account No"]: r for r in csv.DictReader(f)}


def validate_csv_bytes(data: bytes) -> int:
    """Raises ValueError with a client-facing message if data isn't a usable sheet.
    Returns the row count on success. Deliberately doesn't check content-type - CSV
    MIME types are inconsistent across clients/browsers, so parseability + the columns
    every other module actually reads is the real check."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ValueError(f"File isn't valid UTF-8 text: {e}") from e

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames or []
    missing = [c for c in REQUIRED_SHEET_COLUMNS if c not in fieldnames]
    if missing:
        raise ValueError(f"Missing required column(s): {', '.join(missing)}")

    rows = list(reader)
    if not rows:
        raise ValueError("CSV has no data rows.")
    return len(rows)


class Sheet:
    """Thread-safe holder for the loaded rows, reloadable without restarting the process."""

    def __init__(self, csv_path: str):
        self._csv_path = csv_path
        self._lock = threading.Lock()
        self._rows: dict[str, dict] = {}
        self.reload()

    def reload(self) -> int:
        rows = load_rows(self._csv_path)
        with self._lock:
            self._rows = rows
        return len(rows)

    def get(self, account_no: str) -> dict | None:
        with self._lock:
            return self._rows.get(account_no)

    def all_rows(self) -> dict[str, dict]:
        """A snapshot copy, safe to iterate even if reload() runs concurrently."""
        with self._lock:
            return dict(self._rows)

    def __len__(self) -> int:
        with self._lock:
            return len(self._rows)

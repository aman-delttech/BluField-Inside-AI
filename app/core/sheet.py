"""In-memory cache of the CSV sheet, keyed by Account No."""
import csv
import threading


def load_rows(csv_path: str) -> dict[str, dict]:
    """Account No -> CSV row, keyed as a string (leading zeros, and non-numeric
    account numbers like 'R04615', are both significant)."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        return {r["Account No"]: r for r in csv.DictReader(f)}


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

    def __len__(self) -> int:
        with self._lock:
            return len(self._rows)

"""Persists extraction results and caches OCR output across requests.

Layout under out_dir:
    <account>_old.json, <account>_new.json   - extraction responses, as the CLI wrote them
    _ocr_cache.json                          - sha256(image bytes) -> OCR text dump

The OCR cache is keyed by content hash rather than URL (the CLI's scheme) since uploads
have no URL: re-posting the same image, even under a different account or meter, skips
the ~10-20s model call.
"""
import json
import threading
from pathlib import Path


def write_extraction(out_dir: Path, account_no: str, meter: str, data: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{account_no}_{meter}.json"
    path.write_text(json.dumps(data, indent=2))
    return path


class OcrCache:
    """Thread-safe, disk-backed. Safe to share across a whole app lifetime."""

    def __init__(self, out_dir: Path):
        self._path = out_dir / "_ocr_cache.json"
        self._lock = threading.Lock()
        self._data: dict[str, str] = json.loads(self._path.read_text()) if self._path.exists() else {}

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def __getitem__(self, key: str) -> str:
        with self._lock:
            return self._data[key]

    def __setitem__(self, key: str, value: str) -> None:
        with self._lock:
            self._data[key] = value
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2))

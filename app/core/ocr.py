"""Thin client for the local ollama OCR model."""
import base64

import httpx

from app.config import settings

OCR_PROMPT = "Read all text visible in this image, including barcode stickers and LCD display digits."


class OcrError(RuntimeError):
    """Raised when the OCR backend can't be reached or returns something unusable."""


async def ocr_image_bytes(image_bytes: bytes, model: str | None = None) -> str:
    b64 = base64.b64encode(image_bytes).decode()
    body = {
        "model": model or settings.ollama_model,
        "prompt": OCR_PROMPT,
        "images": [b64],
        "stream": False,
        "options": {"temperature": 0},
    }
    try:
        async with httpx.AsyncClient(timeout=settings.ollama_timeout) as client:
            resp = await client.post(settings.ollama_url, json=body)
            resp.raise_for_status()
            return resp.json()["response"]
    except httpx.HTTPError as e:
        raise OcrError(f"OCR backend unreachable or errored: {e}") from e
    except (KeyError, ValueError) as e:
        raise OcrError(f"OCR backend returned an unexpected response: {e}") from e


async def ollama_reachable() -> bool:
    base = settings.ollama_url.rsplit("/api/", 1)[0]
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(base)
            return resp.status_code < 500
    except httpx.HTTPError:
        return False

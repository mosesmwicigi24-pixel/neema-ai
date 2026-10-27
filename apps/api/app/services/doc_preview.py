"""A shared document, drawn the way WhatsApp draws it (owner, 2026-10-27).

The inbox showed a document as a one-line link — "The Quotation for 52
Stole… ⬇" — where WhatsApp shows the top of its first page, its name, and
"236 pages · 772 KB · pdf". This renders that preview once per stored file
and remembers it next to the file:

  <name>.p1.jpg    the first page, PREVIEW_WIDTH px wide (PDF only)
  <name>.info.json {"ext", "bytes", "pages", "preview"}

Rendering is pdfium (pypdfium2, BSD/Apache) — page one only, never the whole
file, and never a file over MAX_RENDER_BYTES. Anything that can't be rendered
(a Word file, a damaged PDF) still has its size and type: the card shows
those and simply has no picture.
"""
from __future__ import annotations

import json
import logging
import os

_log = logging.getLogger("neema.media")

PREVIEW_WIDTH = 640
MAX_RENDER_BYTES = 40 * 1024 * 1024


def _ext(path: str) -> str:
    return os.path.splitext(path)[1].lstrip(".").lower()


def preview_path(filepath: str) -> str:
    return filepath + ".p1.jpg"


def _info_path(filepath: str) -> str:
    return filepath + ".info.json"


def _write_atomic(path: str, data: bytes) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def _render_pdf(filepath: str) -> tuple[int | None, bool]:
    """(page count, whether a first-page preview was written)."""
    import io

    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(filepath)
    try:
        pages = len(pdf)
        if not pages:
            return 0, False
        page = pdf[0]
        try:
            width = page.get_width() or PREVIEW_WIDTH
            image = page.render(scale=max(0.1, min(4.0, PREVIEW_WIDTH / width))).to_pil()
        finally:
            page.close()
        buf = io.BytesIO()
        image.convert("RGB").save(buf, "JPEG", quality=80, optimize=True)
        _write_atomic(preview_path(filepath), buf.getvalue())
        return pages, True
    finally:
        pdf.close()


def document_info(filepath: str) -> dict:
    """What the card says about a stored document, computed once.

    {"ext": "pdf", "bytes": 791204, "pages": 236, "preview": True}. Pages is
    None when the type has none we can count; preview is False when there is
    no picture (not a PDF, too large, or unreadable)."""
    cached = _info_path(filepath)
    try:
        if os.path.getmtime(cached) >= os.path.getmtime(filepath):
            with open(cached, encoding="utf-8") as f:
                return json.load(f)
    except (OSError, ValueError):
        pass
    size = os.path.getsize(filepath)
    info = {"ext": _ext(filepath), "bytes": size, "pages": None, "preview": False}
    if info["ext"] == "pdf" and size <= MAX_RENDER_BYTES:
        try:
            info["pages"], info["preview"] = _render_pdf(filepath)
        except Exception as exc:          # a damaged PDF is still a document
            _log.info("doc preview failed for %s: %s", os.path.basename(filepath), exc)
    try:
        _write_atomic(cached, json.dumps(info).encode())
    except OSError:
        pass
    return info

# app/routers/media.py
import httpx
import logging
import mimetypes
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from app.routers.admin import get_current_agent  # ← correct path
from app.core.config import settings
from app.core import media_urls

router = APIRouter()
_log = logging.getLogger("neema.media")

# The on-disk store. Defined once in Settings (see media_dir) — never a literal
# here. Creating it is deliberately NOT an import-time side effect: importing a
# module must not touch the filesystem, or the app is unimportable for anyone
# without write access to the path's parent (that broke CI during pytest
# *collection*). Creation happens at startup in app/main.py's lifespan, and
# again next to every write below so a writer never depends on that having run.
MEDIA_DIR = settings.media_dir

# The file types we store, by extension. The slim Python image has no
# /etc/mime.types, so the stdlib can't name .ogg / .m4a / .webp / .docx …
# and FileResponse served every one as text/plain (verified in production
# 2026-10-05) — Safari won't play a voice note labelled text/plain, and Meta
# fetches outbound media by URL and checks its type. We know what we write,
# so these win over any host table; .webm/.mp4 stay with the platform (one
# extension holds both call audio and uploaded video).
_MEDIA_TYPES = {
    ".ogg": "audio/ogg", ".oga": "audio/ogg", ".opus": "audio/ogg",
    ".m4a": "audio/mp4", ".aac": "audio/aac", ".amr": "audio/amr",
    ".wav": "audio/wav", ".webp": "image/webp", ".3gp": "video/3gpp",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _register_media_types() -> None:
    for ext, mime in _MEDIA_TYPES.items():
        mimetypes.add_type(mime, ext)


_register_media_types()


@router.post("/admin/media/download")
async def download_media(
    body: dict,
    request: Request,
    agent=Depends(get_current_agent),
):
    """
    Called by n8n after extracting media info.
    Downloads the file from WhatsApp and stores it locally.
    Returns a stable internal URL.
    """
    media_url = body.get("media_url")
    media_id  = body.get("media_id")
    mime_type = body.get("mime_type", "application/octet-stream")

    if not media_url or not media_id:
        raise HTTPException(status_code=400, detail="media_url and media_id required")

    # Derive extension from mime_type
    ext = _mime_to_ext(mime_type)
    filename = f"{media_id}{ext}"
    filepath = os.path.join(MEDIA_DIR, filename)

    # Skip download if already saved (idempotent)
    if not os.path.exists(filepath):
        os.makedirs(MEDIA_DIR, exist_ok=True)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                media_url,
                headers={"Authorization": f"Bearer {settings.waba_token}"},
                follow_redirects=True,
            )
            if not resp.is_success:
                raise HTTPException(
                    status_code=502,
                    detail=f"WhatsApp media fetch failed: {resp.status_code}"
                )
            with open(filepath, "wb") as f:
                f.write(resp.content)

    # Return stable internal URL
    base_url = str(request.base_url).rstrip("/")
    stable_url = f"{base_url}/api/media/serve/{filename}"

    return {
        "ok":         True,
        "filename":   filename,
        "media_id":   media_id,
        "stable_url": stable_url,
        "mime_type":  mime_type,
    }


# @router.get("/media/serve/{filename}")
@router.get("/admin/media/{filename}")
async def serve_media(filename: str, exp: str | None = None, sig: str | None = None,
                      request: Request = None):
    """Serve a stored media file — to a holder of a valid signed link.

    Links are signed at read time (app/core/media_urls.py): ?exp=&sig= over
    the file name. A request carrying a signature is ALWAYS checked; one
    without is refused when MEDIA_SIGNED_URLS_REQUIRED is on, and served (and
    logged `media.unsigned`) while it is off — the rollout window. Every
    refusal is the same 404 as a missing file: never confirm a name exists.

    Only a regular, non-hidden file directly inside MEDIA_DIR: routing keeps
    '/' out of `filename` today, but this handler must not depend on that
    (".." used to raise a 500 on a directory; `{filename:path}` would have
    made it a reader of any file the process can open)."""
    if exp is not None or sig is not None:
        if not media_urls.verify(filename, exp, sig):
            raise HTTPException(status_code=404, detail="File not found")
    elif settings.media_signed_urls_required:
        raise HTTPException(status_code=404, detail="File not found")
    else:
        ua = (request.headers.get("user-agent", "") if request is not None else "")[:80]
        _log.info("media.unsigned served %s (ua=%s)", filename[:80], ua)
    root = os.path.realpath(MEDIA_DIR)
    filepath = os.path.realpath(os.path.join(root, filename))
    if (filename.startswith(".") or os.path.dirname(filepath) != root
            or not os.path.isfile(filepath)):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(filepath)


def _mime_to_ext(mime: str) -> str:
    # Strip codec qualifiers e.g. "audio/ogg; codecs=opus" → "audio/ogg"
    mime = mime.split(";")[0].strip()
    return {
        "image/jpeg":      ".jpg",
        "image/png":       ".png",
        "image/webp":      ".webp",
        "image/gif":       ".gif",
        "video/mp4":       ".mp4",
        "video/3gpp":      ".3gp",
        "audio/ogg":       ".ogg",
        "audio/aac":       ".aac",
        "audio/mpeg":      ".mp3",
        "audio/mp4":       ".m4a",
        "audio/amr":       ".amr",
        "audio/opus":      ".ogg",
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }.get(mime, ".bin")
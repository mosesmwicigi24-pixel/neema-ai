# app/routers/media.py
import httpx
import uuid
import os
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from app.core.config import settings
from app.auth import get_current_agent

router = APIRouter()

MEDIA_DIR = "/var/neema/media"
os.makedirs(MEDIA_DIR, exist_ok=True)


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


@router.get("/media/serve/{filename}")
async def serve_media(filename: str):
    """Serve a stored media file."""
    filepath = os.path.join(MEDIA_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(filepath)


def _mime_to_ext(mime: str) -> str:
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
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }.get(mime, ".bin")
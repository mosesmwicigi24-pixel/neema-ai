"""Outbound video normalisation — what WhatsApp's own app does on send.

The Cloud API hard-caps videos at 16 MB and only plays MP4/3GPP with H.264 +
AAC. Operators shouldn't have to know that: they attach the 150 MB .mov/.hevc
straight off an iPhone, and this module downscales/re-encodes it to a
universally-playable H.264 MP4 that fits the limit (bitrate computed from the
clip's duration, capped at 1280px wide).

Passthrough when the file is already an H.264 MP4 under the cap.
Requires ffmpeg/ffprobe in the image (added to the api Dockerfile).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

_log = logging.getLogger("neema.video")

TARGET_BYTES = int(15.5 * 1024 * 1024)      # safety margin under WhatsApp's 16 MB
AUDIO_KBPS = 96
MAX_WIDTH = 1280
FFMPEG_TIMEOUT = 480                        # seconds — a veryfast 2-pass-free encode


def target_video_kbps(duration_s: float, target_bytes: int = TARGET_BYTES,
                      audio_kbps: int = AUDIO_KBPS) -> int:
    """The video bitrate (kbps) that lands the clip at ~target_bytes.
    Clamped: never below 250 kbps (unwatchable) nor above 4000 (pointless)."""
    if duration_s <= 0:
        return 1200
    total_kbps = (target_bytes * 8) / duration_s / 1000
    return max(250, min(4000, int(total_kbps - audio_kbps)))


async def probe(path: str) -> dict:
    """{duration, codec, size} via ffprobe — {} on any failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name",
            "-show_entries", "format=duration,size",
            "-of", "json", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        data = json.loads(out or b"{}")
        streams = data.get("streams") or [{}]
        fmt = data.get("format") or {}
        return {
            "codec": (streams[0] or {}).get("codec_name"),
            "duration": float(fmt.get("duration") or 0),
            "size": int(fmt.get("size") or 0),
        }
    except Exception as exc:
        _log.warning("ffprobe failed for %s: %s", path, exc)
        return {}


def needs_transcode(ext: str, codec: str | None, size: int) -> bool:
    """Send as-is ONLY for an H.264 .mp4/.3gp under the cap — everything else
    (.mov/.hevc containers, HEVC/other codecs, oversized files) is re-encoded."""
    if size > TARGET_BYTES:
        return True
    if ext.lower() not in (".mp4", ".3gp", ".3gpp"):
        return True
    return codec != "h264"


async def to_whatsapp_video(src_path: str) -> str | None:
    """Return a path to a WhatsApp-ready H.264 MP4 (the original when already
    compliant, else a new transcoded file next to it). None when conversion
    fails — the caller decides how to degrade."""
    ext = os.path.splitext(src_path)[1]
    info = await probe(src_path)
    size = info.get("size") or (os.path.getsize(src_path) if os.path.exists(src_path) else 0)
    if info and not needs_transcode(ext, info.get("codec"), size):
        return src_path

    duration = float(info.get("duration") or 0)
    kbps = target_video_kbps(duration)
    out_path = os.path.splitext(src_path)[0] + ".wa.mp4"
    cmd = [
        "ffmpeg", "-y", "-i", src_path,
        "-vf", f"scale='min({MAX_WIDTH},iw)':-2",
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", f"{kbps}k", "-maxrate", f"{kbps}k", "-bufsize", f"{kbps * 2}k",
        "-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k",
        "-movflags", "+faststart",
        out_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await asyncio.wait_for(proc.communicate(), timeout=FFMPEG_TIMEOUT)
        if proc.returncode != 0:
            _log.warning("ffmpeg failed (%s): %s", proc.returncode, (err or b"")[-400:])
            return None
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            return None
        if os.path.getsize(out_path) > 16 * 1024 * 1024:
            _log.warning("transcode still over 16MB for %s", src_path)
            return None
        return out_path
    except asyncio.TimeoutError:
        _log.warning("ffmpeg timed out for %s", src_path)
        try:
            proc.kill()
        except Exception:
            pass
        return None
    except FileNotFoundError:
        _log.error("ffmpeg not installed in this image — large/non-mp4 video rejected")
        return None

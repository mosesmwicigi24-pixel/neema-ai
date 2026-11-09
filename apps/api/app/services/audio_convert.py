"""Outbound voice notes — what each channel actually plays.

A browser records a voice note as WebM/Opus (Chrome, Edge, Android), MP4/AAC
(Safari, iPhone) or Ogg/Opus (Firefox). None of the first two is something
WhatsApp takes as a voice note, so a recording is re-encoded once on the way
out (owner, 2026-11-09: the composer's microphone):

  whatsapp                        → Ogg/Opus, mono — WhatsApp shows it as a
                                    voice note (the play-and-waveform bubble)
  messenger / facebook / instagram → M4A (AAC), mono — the format Meta's
                                    Send API plays inline on every client

An uploaded audio FILE (mp3 / aac / ogg the agent attaches) is not touched:
only recordings (or containers no channel takes) go through here.
Requires ffmpeg in the image (already there for video_convert).
"""
from __future__ import annotations

import asyncio
import logging
import os

_log = logging.getLogger("neema.audio")

FFMPEG_TIMEOUT = 120                     # a voice note is minutes, not hours
MAX_BYTES = 16 * 1024 * 1024             # WhatsApp's (and Meta's) audio cap

META_CHANNELS = ("messenger", "facebook", "instagram")

# Containers a recorder produces that no channel accepts as they are.
RECORDER_TYPES = {"audio/webm", "audio/mp4", "audio/x-m4a", "audio/m4a", "video/webm"}


def target_for(channel: str | None) -> tuple[str, str]:
    """(extension, mime) the channel's voice note is sent as."""
    if (channel or "whatsapp") in META_CHANNELS:
        return ".m4a", "audio/mp4"
    return ".ogg", "audio/ogg"


def needs_convert(content_type: str, voice: bool) -> bool:
    """A recording (voice=True) always gets the channel's own format; any other
    audio only when its container is one no channel takes as-is."""
    return voice or (content_type or "").split(";")[0].strip().lower() in RECORDER_TYPES


def ffmpeg_args(src: str, dst: str, channel: str | None) -> list[str]:
    ext, _ = target_for(channel)
    codec = ["-c:a", "aac", "-b:a", "64k"] if ext == ".m4a" else ["-c:a", "libopus", "-b:a", "32k"]
    return ["ffmpeg", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "48000" if ext == ".ogg" else "44100",
            *codec, dst]


async def to_channel_voice(src_path: str, channel: str | None) -> tuple[str, str] | None:
    """Re-encode a recording for the channel. Returns (path, mime), or None when
    it could not be converted — the caller refuses the send rather than
    delivering something the customer cannot play."""
    ext, mime = target_for(channel)
    out_path = os.path.splitext(src_path)[0] + ".voice" + ext
    try:
        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_args(src_path, out_path, channel),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, err = await asyncio.wait_for(proc.communicate(), timeout=FFMPEG_TIMEOUT)
        if proc.returncode != 0:
            _log.warning("voice convert failed (%s): %s", proc.returncode, (err or b"")[-400:])
            return None
        if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
            return None
        if os.path.getsize(out_path) > MAX_BYTES:
            _log.warning("voice note still over 16MB for %s", src_path)
            return None
        return out_path, mime
    except asyncio.TimeoutError:
        _log.warning("voice convert timed out for %s", src_path)
        try:
            proc.kill()
        except Exception:
            pass
        return None
    except FileNotFoundError:
        _log.error("ffmpeg not installed in this image — voice note refused")
        return None

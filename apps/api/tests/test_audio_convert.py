"""Outbound voice notes — each channel gets a format it plays (audio_convert)."""
import asyncio
import os
import shutil
import subprocess

import pytest

from app.services.audio_convert import ffmpeg_args, needs_convert, target_for, to_channel_voice


def test_whatsapp_gets_ogg_opus_and_meta_gets_m4a():
    assert target_for("whatsapp") == (".ogg", "audio/ogg")
    assert target_for(None) == (".ogg", "audio/ogg")
    for ch in ("messenger", "facebook", "instagram"):
        assert target_for(ch) == (".m4a", "audio/mp4")


def test_only_recordings_and_unplayable_containers_are_converted():
    assert needs_convert("audio/webm;codecs=opus", False)      # Chrome recording
    assert needs_convert("audio/mp4", False)                   # Safari recording
    assert needs_convert("audio/mpeg", True)                   # anything marked as a voice note
    assert not needs_convert("audio/mpeg", False)              # an attached mp3 file goes as it is
    assert not needs_convert("audio/ogg", False)


def test_ffmpeg_is_mono_with_the_channels_codec():
    wa = ffmpeg_args("in.webm", "out.ogg", "whatsapp")
    assert "libopus" in wa and wa[wa.index("-ac") + 1] == "1"
    ig = ffmpeg_args("in.webm", "out.m4a", "instagram")
    assert "aac" in ig and "libopus" not in ig


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
@pytest.mark.parametrize("channel,ext", [("whatsapp", ".ogg"), ("instagram", ".m4a")])
def test_a_webm_recording_converts(tmp_path, channel, ext):
    src = tmp_path / "rec.webm"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                    "-c:a", "libopus", str(src)], check=True, capture_output=True)
    out = asyncio.run(to_channel_voice(str(src), channel))
    assert out is not None
    path, mime = out
    assert path.endswith(".voice" + ext) and os.path.getsize(path) > 0
    assert mime == target_for(channel)[1]


def test_garbage_is_refused_not_sent(tmp_path):
    bad = tmp_path / "rec.webm"
    bad.write_bytes(b"not audio")
    assert asyncio.run(to_channel_voice(str(bad), "whatsapp")) is None

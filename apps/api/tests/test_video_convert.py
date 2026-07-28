"""Outbound video normalisation — bitrate targeting + transcode decisions."""
from app.services.video_convert import needs_transcode, target_video_kbps, TARGET_BYTES


def test_compliant_mp4_under_cap_passes_through():
    assert not needs_transcode(".mp4", "h264", 10 * 1024 * 1024)
    assert not needs_transcode(".3gp", "h264", 5 * 1024 * 1024)


def test_everything_else_transcodes():
    assert needs_transcode(".mov", "h264", 1024)            # wrong container
    assert needs_transcode(".mp4", "hevc", 1024)            # wrong codec
    assert needs_transcode(".mp4", "h264", TARGET_BYTES + 1)  # oversized
    assert needs_transcode(".hevc", None, 1024)


def test_bitrate_targets_the_cap():
    # 60s clip: (15.5MB*8/60s) ≈ 2066 kbps total → ~1970 video after 96k audio
    kbps = target_video_kbps(60)
    assert 1800 <= kbps <= 2100
    # long clip clamps at the floor, tiny clip at the ceiling
    assert target_video_kbps(3600) == 250
    assert target_video_kbps(5) == 4000
    assert target_video_kbps(0) == 1200                     # unknown duration default

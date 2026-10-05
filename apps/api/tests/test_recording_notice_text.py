"""The recording notice's wording is the owner's (2026-10-05): English, then
Swahili — both lines, in that order, and switched on in production compose."""
import os

from app.core.config import Settings


def test_default_notice_is_english_then_swahili():
    text = Settings.model_fields["call_recording_notice_text"].default
    en = "Just so you know: calls with Bethany House may be recorded"
    sw = "Kwa taarifa yako: simu na Bethany House zinaweza kurekodiwa"
    assert en in text and sw in text and text.index(en) < text.index(sw)
    assert "\n\n" in text


def test_production_compose_switches_the_notice_on():
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docker-compose.vps.yml")
    src = open(path, encoding="utf-8").read()
    assert 'CALL_RECORDING_NOTICE_ENABLED: "true"' in src
    assert 'CALL_META_TRANSCRIPTION: "false"' in src     # the spoken notice stays off

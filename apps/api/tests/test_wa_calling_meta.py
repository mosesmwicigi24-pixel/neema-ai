"""WhatsApp calling — the Graph side, without a database.

What Meta's answers are turned into (permission shape, error table), which
requests may be repeated (terminate / permission read: once, on 429 / 5xx /
network; connect / accept: never — a duplicate would place a second call),
the exact request shapes (opaque data, recording / transcription objects, the
calling API version), the transcript parser and the Graph-version probe.
"""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.services import wa_calling


# ── A scripted Graph ─────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self.is_success = 200 <= status < 300
        self._body = body if body is not None else {}
        self.content = json.dumps(self._body).encode()
        self.text = json.dumps(self._body)
        self.headers = {}

    def json(self):
        return self._body


class _Graph:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def client(self, *a, **k):
        graph = self

        class _C:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def _next(self, method, url, **kw):
                graph.calls.append((method, url, kw))
                step = graph.script.pop(0)
                if isinstance(step, Exception):
                    raise step
                return step

            async def post(self, url, headers=None, json=None, timeout=None):
                return await self._next("POST", url, json=json)

            async def get(self, url, headers=None, params=None, timeout=None):
                return await self._next("GET", url, params=params)
        return _C()


@pytest.fixture
def graph(monkeypatch):
    monkeypatch.setattr(settings, "waba_token", "T", raising=False)
    monkeypatch.setattr(settings, "waba_phone_number_id", "PNID", raising=False)
    monkeypatch.setattr(settings, "waba_api_version", "v21.0", raising=False)
    monkeypatch.setattr(settings, "waba_calling_api_version", "v23.0", raising=False)
    monkeypatch.setattr(settings, "call_meta_recording", False, raising=False)
    monkeypatch.setattr(settings, "call_meta_transcription", False, raising=False)
    monkeypatch.setattr(wa_calling, "RETRY_JITTER", (0, 0))

    def make(*script):
        g = _Graph(script)
        monkeypatch.setattr(wa_calling.httpx, "AsyncClient", g.client)
        return g
    return make


def _err(code, status=400):
    return _Resp(status, {"error": {"message": "x", "type": "OAuthException" if code == 190 else "x",
                                    "code": code}})


# ── C5/C1 retry policy ───────────────────────────────────────────────────────

def test_terminate_retries_once_on_5xx_and_429(graph):
    g = graph(_Resp(503), _Resp(200, {"success": True}))
    assert asyncio.run(wa_calling.terminate("wacid.1")) == {"success": True}
    assert len(g.calls) == 2
    g = graph(_Resp(429), _Resp(429))
    with pytest.raises(wa_calling.MetaError) as e:
        asyncio.run(wa_calling.terminate("wacid.1"))
    assert e.value.status == 429 and len(g.calls) == 2         # once more, never a loop


def test_terminate_does_not_retry_a_4xx(graph):
    g = graph(_err(138004, 400))
    with pytest.raises(wa_calling.MetaError):
        asyncio.run(wa_calling.terminate("wacid.1"))
    assert len(g.calls) == 1


@pytest.mark.parametrize("first", [_Resp(503), _Resp(429), OSError("connection reset")])
def test_connect_and_accept_never_retry(graph, first):
    g = graph(first)
    with pytest.raises(wa_calling.MetaError):
        asyncio.run(wa_calling.connect("+254700", "v=0"))
    assert len(g.calls) == 1
    g = graph(first)
    with pytest.raises(wa_calling.MetaError):
        asyncio.run(wa_calling.accept("wacid.1", "v=0"))
    assert len(g.calls) == 1


def test_permission_read_retries_once_then_answers(graph):
    body = {"permission": {"status": "permanent"}, "actions": []}
    g = graph(_Resp(500), _Resp(200, body))
    p = asyncio.run(wa_calling.get_call_permission("+254700"))
    assert p["status"] == "granted" and p["permanent"] is True
    method, url, kw = g.calls[-1]
    assert method == "GET" and url == "https://graph.facebook.com/v23.0/PNID/call_permissions"
    assert kw["params"] == {"user_wa_id": "254700"}


def test_permission_read_network_failure_is_a_meta_error(graph):
    graph(TimeoutError("slow"), TimeoutError("slow"))
    with pytest.raises(wa_calling.MetaError) as e:
        asyncio.run(wa_calling.get_call_permission("254700"))
    assert e.value.status == 0
    assert wa_calling.classify_error(e.value)["action"] == "retry"


def test_not_configured_never_reaches_meta(graph, monkeypatch):
    g = graph()
    monkeypatch.setattr(settings, "waba_token", "", raising=False)
    with pytest.raises(wa_calling.MetaError) as e:
        asyncio.run(wa_calling.get_call_permission("254700"))
    assert g.calls == [] and wa_calling.classify_error(e.value)["code"] == "not_configured"


# ── C4/C6/C7 request shapes ──────────────────────────────────────────────────

def test_connect_sends_opaque_data_on_the_calling_version(graph):
    g = graph(_Resp(200, {"calls": [{"id": "wacid.9"}]}))
    op = wa_calling.opaque("agent-1", "conv-1")
    asyncio.run(wa_calling.connect("+254700", "v=0", biz_opaque=op))
    method, url, kw = g.calls[0]
    assert url == "https://graph.facebook.com/v23.0/PNID/calls"
    assert kw["json"]["biz_opaque_callback_data"] == '{"a":"agent-1","c":"conv-1"}'
    assert "recording" not in kw["json"] and "transcription" not in kw["json"]
    assert wa_calling.parse_opaque(op) == {"agent_id": "agent-1", "conversation_id": "conv-1"}
    assert wa_calling.parse_opaque("order-7") == {} and wa_calling.parse_opaque(None) == {}


def test_recording_and_transcription_objects_when_switched_on(graph, monkeypatch):
    monkeypatch.setattr(settings, "call_meta_recording", True, raising=False)
    monkeypatch.setattr(settings, "call_meta_transcription", True, raising=False)
    monkeypatch.setattr(settings, "call_recording_purpose", "x" * 300, raising=False)
    monkeypatch.setattr(settings, "call_recording_language", "sw", raising=False)
    g = graph(_Resp(200, {"calls": [{"id": "w"}]}), _Resp(200, {}))
    asyncio.run(wa_calling.connect("254700", "v=0"))
    asyncio.run(wa_calling.accept("wacid.1", "v=0", biz_opaque="{}"))
    for _, _, kw in g.calls:
        for key in ("recording", "transcription"):
            assert kw["json"][key] == {"status": "ENABLED", "purpose": "x" * 250, "announcement_language": "sw"}


def test_permission_messages_use_the_calling_version(graph):
    g = graph(_Resp(200, {}), _Resp(200, {}))
    asyncio.run(wa_calling.request_call_permission("+254700"))
    asyncio.run(wa_calling.request_call_permission_template("+254700", "call_ok", "en", ["Grace"]))
    assert all(c[1] == "https://graph.facebook.com/v23.0/PNID/messages" for c in g.calls)
    free, tpl = g.calls[0][2]["json"], g.calls[1][2]["json"]
    assert free["interactive"]["type"] == "call_permission_request"
    assert tpl["type"] == "template" and tpl["template"] == {
        "name": "call_ok", "language": {"code": "en"},
        "components": [{"type": "body", "parameters": [{"type": "text", "text": "Grace"}]}]}


def test_template_params_follow_the_setting(monkeypatch):
    monkeypatch.setattr(settings, "call_permission_template_params", "first_name, name, Bethany", raising=False)
    assert wa_calling.template_params("Grace", "Grace Njeri") == ["Grace", "Grace Njeri", "Bethany"]
    assert wa_calling.template_params(None, None) == ["there", "there", "Bethany"]
    monkeypatch.setattr(settings, "call_permission_template_params", "", raising=False)
    assert wa_calling.template_params("Grace", None) == []


def test_media_download_fetches_the_url_at_once_with_the_token(graph):
    g = graph(_Resp(200, {"url": "https://lookaside.fbsbx.com/x", "mime_type": "audio/ogg"}),
              _Resp(200, {"ok": 1}))
    content, mime = asyncio.run(wa_calling.download_media("m1"))
    assert g.calls[0][1] == "https://graph.facebook.com/v23.0/m1" and g.calls[1][1] == "https://lookaside.fbsbx.com/x"
    assert mime == "audio/ogg" and json.loads(content) == {"ok": 1}


# ── C1 permission normalisation ──────────────────────────────────────────────

def test_normalize_handles_missing_and_odd_shapes():
    assert wa_calling.normalize_permission({})["status"] == "unknown"
    assert wa_calling.normalize_permission(None)["meta_status"] == "no_permission"
    iso = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0).isoformat()
    p = wa_calling.normalize_permission({"permission": {"status": "temporary", "expiration": iso}})
    assert p["status"] == "granted" and p["expires_at"] == iso
    assert p["can_call"] is True and p["can_request"] is False    # defaults follow the grant
    # Top-level limits (no action name) count as the request limits.
    ts = int((datetime.now(timezone.utc) + timedelta(hours=3)).timestamp())
    p = wa_calling.normalize_permission({
        "permission": {"status": "no_permission"},
        "actions": [{"action_name": "send_call_permission_request", "can_perform_action": False}],
        "limits": [{"time_period": "PT24H", "max_allowed": 1, "current_usage": 1, "limit_expiration_time": ts}]})
    assert p["request_available_at"] == datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    # A limit not yet reached never produces a date.
    p = wa_calling.normalize_permission({"actions": [
        {"action_name": "send_call_permission_request", "can_perform_action": False,
         "limits": [{"time_period": "P7D", "max_allowed": 2, "current_usage": 1, "limit_expiration_time": ts}]}]})
    assert p["request_available_at"] is None


# ── C5 the error table ───────────────────────────────────────────────────────

BRIEF_CODES = ["100", "613", "131009", "131026", "131030", "131044", "131055", "138000", "138001",
               "138002", "138003", "138004", "138005", "138006", "138007", "138009", "138012",
               "138013", "138014", "138015", "138017", "138018", "138019", "138020", "138021",
               "138022", "138023", "190"]


@pytest.mark.parametrize("code", BRIEF_CODES)
def test_every_documented_code_has_a_reason_and_an_action(code):
    info = wa_calling.classify_error(f'WA call connect failed (400): {{"error":{{"code":{code}}}}}')
    assert info["code"] == code and info["reason"]
    assert info["action"] in ("retry", "request_permission", "wait", "admin", "none")
    assert "Couldn't reach" not in info["reason"]


def test_classify_the_cases_meta_gives_no_code_for():
    assert wa_calling.classify_error("Error validating access token: Session has expired")["code"] == "190"
    assert "access token expired" in wa_calling.friendly_error(wa_calling.MetaError("x", status=401, code=190))
    assert wa_calling.classify_error(wa_calling.MetaError("x", status=429))["action"] == "wait"
    assert wa_calling.classify_error(wa_calling.MetaError("x", status=502))["action"] == "retry"
    assert wa_calling.classify_error("WA call connect failed (network): reset")["code"] == "meta_unavailable"
    assert wa_calling.classify_error("something odd")["reason"] == "Couldn't reach the customer on WhatsApp right now."
    # Existing wording kept for the codes the clients already show.
    assert "can't take calls" in wa_calling.friendly_error("... 138001 ...")
    assert wa_calling.classify_error('{"error":{"code":138006}}')["action"] == "request_permission"


# ── C7 transcript parsing ────────────────────────────────────────────────────

def test_transcript_words_are_grouped_by_speaker():
    from app.services.call_transcribe import parse_meta_transcript
    doc = {"transcription": {"detected_language": "en", "words": [
        {"word": "Hello", "channel": 1, "start_ms": 100},
        {"word": "there", "channel": 1, "start_ms": 300},
        {"word": "Hi", "channel": 0, "start_ms": 900},
        {"word": "Grace", "channel": 0, "start_ms": 1100}]}}
    assert parse_meta_transcript(doc) == ("Customer: Hello there\nAgent: Hi Grace", "en")
    assert parse_meta_transcript({"text": "plain words"}) == ("plain words", None)
    assert parse_meta_transcript({"results": [{"channel": 2, "text": "x"}]})[0] == "Speaker 2: x"
    assert parse_meta_transcript([]) == ("", None)


def test_media_id_is_found_where_meta_puts_it():
    from app.services.call_transcribe import media_id_of
    assert media_id_of({"transcription": {"id": "t1"}}, "transcription") == "t1"
    assert media_id_of({"recording": {"media_id": "r1"}}, "recording") == "r1"
    assert media_id_of({"media": {"id": "m1"}}, "recording") == "m1"
    assert media_id_of({"media_id": "x"}, "recording") == "x"
    assert media_id_of({}, "recording") is None


# ── C6 Graph version expiry ──────────────────────────────────────────────────

def test_graph_version_probe(monkeypatch):
    from app.services import selfcheck as sc
    monkeypatch.setattr(settings, "waba_api_version", "v21.0", raising=False)
    monkeypatch.setattr(settings, "waba_calling_api_version", "v23.0", raising=False)
    assert sc.graph_version_findings(date(2026, 9, 27)) == []            # 116 days left
    out = sc.graph_version_findings(date(2026, 11, 1))
    assert len(out) == 1 and "WABA_API_VERSION=v21.0 expires on 2027-01-21" in out[0]
    monkeypatch.setattr(settings, "waba_api_version", "v20.0", raising=False)
    out = sc.graph_version_findings(date(2026, 9, 27))
    assert "EXPIRED" in out[0]
    monkeypatch.setattr(settings, "waba_calling_api_version", "v23.0", raising=False)
    assert any("WABA_CALLING_API_VERSION" in f for f in sc.graph_version_findings(date(2027, 8, 1)))
    monkeypatch.setattr(settings, "waba_api_version", "v99.0", raising=False)   # unknown: no guess
    assert sc.graph_version_findings(date(2026, 9, 27)) == []
    assert "graph_versions" in [n for n, _ in sc.PROBES]

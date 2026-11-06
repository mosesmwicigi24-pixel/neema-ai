"""STAGE 8 — the audit's access gaps closed from the dashboard side: an
admin-only trace endpoint, an admin-only view of the stored prompt inputs, a
Basic-auth login so a proxy-held credential can mint a token, and the
experience scenarios for the model-in-the-loop eval."""
import asyncio
import base64
import inspect
import types

import pytest
from fastapi import HTTPException


def run(coro):
    return asyncio.run(coro)


def test_the_audit_routes_exist_and_are_admin_only():
    from app.routers import crm
    paths = {(rt.path, tuple(sorted(rt.methods or []))) for rt in crm.router.routes}
    assert ("/outreach/trace", ("GET",)) in paths and ("/settings/prompt-inputs", ("GET",)) in paths
    assert "_admin_only(agent)" in inspect.getsource(crm.outreach_trace_view)
    assert "_admin_only(agent)" in inspect.getsource(crm.prompt_inputs_view)
    with pytest.raises(HTTPException) as e:
        crm._admin_only(types.SimpleNamespace(role="agent", is_superuser=False))
    assert e.value.status_code == 403
    crm._admin_only(types.SimpleNamespace(role="admin", is_superuser=False))     # no raise


def test_basic_login_mints_the_same_tokens_and_refuses_everything_else():
    from app.core.security import decode_token, hash_password
    from app.routers import auth

    agent = types.SimpleNamespace(id="a1", email="owner@example.com", role="admin", is_superuser=True,
                                  password_hash=hash_password("correct horse"))

    class _R:
        def __init__(self, row): self.row = row
        def scalar_one_or_none(self): return self.row

    class _DB:
        async def execute(self, q):
            return _R(agent if "owner@example.com" in str(q.compile(compile_kwargs={"literal_binds": True})) else None)

    def req(header):
        return types.SimpleNamespace(headers={"authorization": header} if header else {})

    def basic(user, pw):
        return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()

    out = run(auth.login_basic(req(basic("owner@example.com", "correct horse")), _DB()))
    assert out["token_type"] == "bearer" and out["role"] == "admin" and out["agent_id"] == "a1"
    assert decode_token(out["access_token"])["sub"] == "a1"
    for bad in (None, "Bearer x", basic("owner@example.com", "wrong"), basic("nobody@example.com", "x"),
                basic("owner@example.com", ""), "Basic not-base64!"):
        with pytest.raises(HTTPException) as e:
            run(auth.login_basic(req(bad), _DB()))
        assert e.value.status_code == 401


def test_the_experience_set_is_in_the_eval_and_the_checks_read_the_transcript():
    from app.jobs import agent_eval as ev
    titles = [t for _, t, _ in ev.EXPERIENCE]
    assert any("Judas" in t for t in titles) and any("Willy" in t for t in titles) \
        and any("Emmanuel" in t for t in titles) and any("seven statements" in t for t in titles)
    assert all(wa in ev.EVAL_IDS for wa, _, _ in ev.EXPERIENCE)        # cleaned up afterwards
    assert ev.experience_checks("Which day should we check back with you?", "Let me compare prices.",
                                after_hold=True) == ["RE-ASKED FOR A DATE"]
    assert "PITCH AFTER A REQUEST FOR TIME" in ev.experience_checks(
        "Shall I start the order for you?", "I need to consult my bishop.", after_hold=False)
    assert "REPLY NOT IN HINDI" in ev.experience_checks("Hello, the cope is $450.", "नमस्ते, कीमत?", after_hold=False)
    assert ev.experience_checks("ठीक है, हम पुष्टि कर रहे हैं।", "नमस्ते, कीमत?", after_hold=False) == []
    assert any("ANSWERED A CLOSER" in f for f in ev.experience_checks("You're welcome!", "Asante sana 🙏", after_hold=False))
    assert ev.experience_checks("", "Asante sana 🙏", after_hold=False) == []


def test_the_eval_workflow_refuses_to_run_without_the_secret():
    import pathlib
    wf = pathlib.Path(__file__).resolve().parents[3] / ".github" / "workflows" / "agent-eval.yml"
    text = wf.read_text()
    assert "workflow_dispatch" in text and "secrets.ANTHROPIC_API_KEY" in text
    assert "Refuse to run without a key" in text and "upload-artifact" in text

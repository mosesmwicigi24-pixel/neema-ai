"""In-memory stand-ins for the actions engine's atomic claim.

The scheduler tests drive process_due over fake sessions that replay canned
results; the conditional UPDATEs behind claim()/finish() (and the
interrupted-send sweep) are pinned against a real database-shaped fake in
test_action_claims.py. Here they act on the in-memory row, with the same
rule: only a row still in one of the expected statuses is claimed.
"""
from app.services import actions as act


def install(monkeypatch):
    async def claim(db, action, from_statuses, to_status="sending"):
        if action.status in tuple(from_statuses):
            action.status = to_status
            return True
        return False

    async def finish(db, action, status, draft=None):
        action.status = status
        if draft is not None:
            action.draft = draft

    async def no_sweep(db, now):
        return 0

    monkeypatch.setattr(act, "claim", claim)
    monkeypatch.setattr(act, "finish", finish)
    monkeypatch.setattr(act, "_recover_interrupted", no_sweep)

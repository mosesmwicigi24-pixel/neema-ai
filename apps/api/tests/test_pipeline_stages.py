"""Operator-added pipeline stage labels — Settings-backed, admin-saved.

Customs render between Proposal and Won in every pipeline view; the canonical
stages stay fixed because the AI classifier and lead signals reason about them.
"""
import asyncio
import types

import pytest
from fastapi import HTTPException

from app.routers.crm import get_pipeline_stages, put_pipeline_stages


class _Admin:
    is_superuser = True
    role = "admin"


class _Agent:
    is_superuser = False
    role = "agent"


def _patched_store(monkeypatch):
    store = {}

    async def fake_get(db, key):
        return store.get(key, "")

    async def fake_set(db, key, value):
        store[key] = value

    import app.services.app_settings as s
    monkeypatch.setattr(s, "get_value", fake_get)
    monkeypatch.setattr(s, "set_value", fake_set)
    return store


def test_save_then_read_round_trips(monkeypatch):
    _patched_store(monkeypatch)
    out = asyncio.run(put_pipeline_stages(
        {"stages": ["Sampling", "Fitting"]}, db=None, agent=_Admin()))
    assert out["stages"] == ["Sampling", "Fitting"]
    got = asyncio.run(get_pipeline_stages(db=None, agent=_Agent()))
    assert got["stages"] == ["Sampling", "Fitting"]


def test_canonical_names_and_duplicates_are_dropped(monkeypatch):
    _patched_store(monkeypatch)
    out = asyncio.run(put_pipeline_stages(
        {"stages": ["Won", "  ", "Sampling", "sampling", "Proposal"]},
        db=None, agent=_Admin()))
    # "Won"/"Proposal" are canonical, blank and case-duplicates collapse.
    assert out["stages"] == ["Sampling"]


def test_the_list_is_capped(monkeypatch):
    _patched_store(monkeypatch)
    with pytest.raises(HTTPException) as e:
        asyncio.run(put_pipeline_stages(
            {"stages": ["A", "B", "C", "D", "E"]}, db=None, agent=_Admin()))
    assert e.value.status_code == 422


def test_only_an_admin_can_reshape_the_pipeline(monkeypatch):
    _patched_store(monkeypatch)
    with pytest.raises(HTTPException) as e:
        asyncio.run(put_pipeline_stages(
            {"stages": ["Sampling"]}, db=None, agent=_Agent()))
    assert e.value.status_code == 403


def test_a_corrupt_setting_reads_as_empty(monkeypatch):
    store = _patched_store(monkeypatch)
    store["pipeline_custom_stages"] = "{not json"
    got = asyncio.run(get_pipeline_stages(db=None, agent=_Agent()))
    assert got["stages"] == []

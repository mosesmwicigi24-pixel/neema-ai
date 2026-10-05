"""Cycle 9 — hostile audit: the media route (/api/admin/media/{name}).

Who can read a stored recording / voice note, and whether a crafted name can
leave the media directory. Raw ASGI requests — httpx folds '..' away before
sending, which would hide what the server does.
"""
import asyncio

import pytest
from fastapi import HTTPException


def run(coro):
    return asyncio.run(coro)


# ── 1. the media route ───────────────────────────────────────────────────────

@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    import app.routers.media as media_router
    d = tmp_path / "media"
    d.mkdir()
    (d / "call_0123456789abcdef0123456789abcdef.webm").write_bytes(b"RECORDING")
    (d / ".write_check").write_text("probe")
    (tmp_path / "outside.txt").write_text("SECRET OUTSIDE THE MEDIA DIR")
    monkeypatch.setattr(media_router, "MEDIA_DIR", str(d))
    return d


def _asgi_get(app, path):
    """A raw ASGI request — no client-side path normalisation (httpx folds
    '..' away before sending, which would hide what the server does)."""
    out = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        out.append(m)

    scope = {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": [], "http_version": "1.1", "scheme": "http",
             "server": ("t", 80), "client": ("c", 1), "root_path": ""}

    async def go():
        await app(scope, receive, send)
    try:
        run(go())
    except Exception as exc:                      # an unhandled error = a 500 in production
        return 500, repr(exc).encode()
    start = next(m for m in out if m["type"] == "http.response.start")
    return start["status"], b"".join(m.get("body", b"") for m in out if m["type"] == "http.response.body")


@pytest.fixture
def media_app(media_dir):
    from fastapi import FastAPI
    from app.routers import media
    a = FastAPI()
    a.include_router(media.router, prefix="/api")
    return a


def test_media_files_are_served_without_a_login_by_design(media_app):
    """FINDING (owner decision): /api/admin/media/{name} has no bearer check —
    <audio>/<img> tags can't send one, and Meta fetches outbound media links
    itself. Superseded by signed, expiring links (test_media_signed_urls.py):
    an UNSIGNED request like this one is served only while
    MEDIA_SIGNED_URLS_REQUIRED is off (the rollout default)."""
    status, body = _asgi_get(media_app, "/api/admin/media/call_0123456789abcdef0123456789abcdef.webm")
    assert status == 200 and body == b"RECORDING"


@pytest.mark.parametrize("name", ["..", "."])
def test_a_dot_name_is_a_404_not_a_server_error(media_app, name):
    status, _ = _asgi_get(media_app, f"/api/admin/media/{name}")
    assert status == 404


def test_a_hidden_file_in_the_media_dir_is_not_served(media_app):
    status, _ = _asgi_get(media_app, "/api/admin/media/.write_check")
    assert status == 404


def test_the_handler_never_reads_outside_the_media_dir(media_dir):
    """Routing keeps '/' out of {filename} today; the handler must not depend
    on that (a future `{filename:path}` would turn it into a file reader)."""
    from app.routers.media import serve_media
    with pytest.raises(HTTPException) as e:
        run(serve_media("../outside.txt"))
    assert e.value.status_code == 404


def test_an_encoded_traversal_never_matches_the_route(media_app):
    # uvicorn hands the route the DECODED path; a '/' inside it never matches
    for p in ("/api/admin/media/../outside.txt", "/api/admin/media/..%2Foutside.txt"):
        status, body = _asgi_get(media_app, p)
        assert status == 404 and b"SECRET" not in body


# ── 2. content types without a host mime table (the slim image) ──────────────

PROD_UNKNOWN = [   # production's answer, 2026-10-05: guess_type(...) is None
    (".ogg", "audio/ogg"), (".m4a", "audio/mp4"), (".amr", "audio/amr"),
    (".webp", "image/webp"), (".docx",
     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
]


@pytest.mark.parametrize("ext,mime", PROD_UNKNOWN)
def test_stored_media_is_served_with_its_real_type_on_the_slim_image(media_dir, ext, mime):
    """Production's image has no /etc/mime.types: the stdlib named none of
    these and FileResponse fell back to text/plain (2026-10-05)."""
    import mimetypes
    import app.routers.media as media_router
    mimetypes.init(files=[])                 # what production has: no table,
    for e in [x for x, _ in PROD_UNKNOWN]:   # and a stdlib that names none of these
        mimetypes.types_map.pop(e, None)
    assert mimetypes.guess_type(f"wa_123{ext}")[0] is None
    try:
        media_router._register_media_types()
        (media_dir / f"wa_123{ext}").write_bytes(b"x")
        resp = run(media_router.serve_media(f"wa_123{ext}"))
        assert resp.media_type == mime
    finally:
        mimetypes.init()
        media_router._register_media_types()

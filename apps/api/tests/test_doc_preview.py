"""A shared document is drawn like WhatsApp draws it (owner, 2026-10-27):
the top of its first page, its name, "N pages · size · pdf" — computed once
per stored file, behind the same signed link as the file itself."""
import io
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main  # noqa: F401 — registers all SQLAlchemy models
from app.core import media_urls
from app.services import doc_preview


def _pdf(pages: int = 3) -> bytes:
    from PIL import Image, ImageDraw
    first = Image.new("RGB", (600, 800), "white")
    ImageDraw.Draw(first).rectangle([40, 40, 560, 160], fill="#b91c1c")
    rest = [Image.new("RGB", (600, 800), "white") for _ in range(pages - 1)]
    buf = io.BytesIO()
    first.save(buf, "PDF", save_all=True, append_images=rest)
    return buf.getvalue()


@pytest.fixture
def store(tmp_path, monkeypatch):
    from app.routers import media
    monkeypatch.setattr(media, "MEDIA_DIR", str(tmp_path))
    api = FastAPI()
    api.include_router(media.router, prefix="/api")
    return tmp_path, TestClient(api)


def _signed(name: str, suffix: str = "") -> str:
    url = media_urls.sign_media_url(f"/api/admin/media/{name}")
    path, q = url.split("?", 1)
    return f"{path}{suffix}?{q}"


def test_a_pdf_has_its_pages_size_and_a_first_page_preview(store):
    root, client = store
    (root / "quote.pdf").write_bytes(_pdf(3))
    info = client.get(_signed("quote.pdf", "/info")).json()
    assert info["ext"] == "pdf" and info["pages"] == 3 and info["preview"] is True
    assert info["bytes"] == os.path.getsize(root / "quote.pdf")
    r = client.get(_signed("quote.pdf", "/preview"))
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    from PIL import Image
    img = Image.open(io.BytesIO(r.content))
    assert img.width == doc_preview.PREVIEW_WIDTH
    red = img.convert("RGB").getpixel((img.width // 2, int(img.height * 0.12)))
    assert red[0] > 150 and red[1] < 90                     # it IS page one: the red band


def test_it_is_rendered_once_and_kept(store, monkeypatch):
    root, client = store
    (root / "once.pdf").write_bytes(_pdf(2))
    client.get(_signed("once.pdf", "/info"))
    monkeypatch.setattr(doc_preview, "_render_pdf",
                        lambda p: (_ for _ in ()).throw(AssertionError("rendered twice")))
    assert client.get(_signed("once.pdf", "/info")).json()["pages"] == 2
    assert client.get(_signed("once.pdf", "/preview")).status_code == 200


def test_a_word_file_or_a_damaged_pdf_is_still_a_document_without_a_picture(store):
    root, client = store
    (root / "brief.docx").write_bytes(b"PK\x03\x04 not really")
    (root / "broken.pdf").write_bytes(b"%PDF-1.4 garbage")
    for name, ext in (("brief.docx", "docx"), ("broken.pdf", "pdf")):
        info = client.get(_signed(name, "/info")).json()
        assert info["ext"] == ext and info["preview"] is False and info["bytes"] > 0
        assert client.get(_signed(name, "/preview")).status_code == 404


def test_the_preview_is_behind_the_file_s_own_signature(store, monkeypatch):
    from app.core.config import settings
    root, client = store
    (root / "private.pdf").write_bytes(_pdf(1))
    monkeypatch.setattr(settings, "media_signed_urls_required", True, raising=False)
    assert client.get("/api/admin/media/private.pdf/preview").status_code == 404
    assert client.get("/api/admin/media/private.pdf/info?exp=1&sig=" + "0" * 64).status_code == 404
    assert client.get(_signed("private.pdf", "/preview")).status_code == 200
    import time
    exp = int(time.time()) + 600                 # a valid signature over a path that climbs out
    sig = media_urls.signature("../private.pdf", exp)
    assert client.get(f"/api/admin/media/..%2Fprivate.pdf/info?exp={exp}&sig={sig}").status_code == 404

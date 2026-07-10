"""Tests for Tier 2 image loading (native Claude vision) — pure, no DB/network."""
import base64

import app.agent.media as media


def test_load_image_block_reads_local_file(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_DIR", str(tmp_path))
    (tmp_path / "123.jpg").write_bytes(b"\xff\xd8\xff\xe0jpegdata")
    block = media.load_image_block("http://neema/api/admin/media/123.jpg")
    assert block["type"] == "image"
    assert block["source"]["type"] == "base64"
    assert block["source"]["media_type"] == "image/jpeg"
    assert base64.standard_b64decode(block["source"]["data"]) == b"\xff\xd8\xff\xe0jpegdata"


def test_load_image_block_png_and_webp(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_DIR", str(tmp_path))
    (tmp_path / "a.png").write_bytes(b"png")
    (tmp_path / "b.webp").write_bytes(b"webp")
    assert media.load_image_block("http://x/api/admin/media/a.png")["source"]["media_type"] == "image/png"
    assert media.load_image_block("http://x/api/admin/media/b.webp")["source"]["media_type"] == "image/webp"


def test_load_image_block_none_for_missing_nonimage_and_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_DIR", str(tmp_path))
    assert media.load_image_block("http://x/api/admin/media/nope.jpg") is None  # missing file
    (tmp_path / "doc.pdf").write_bytes(b"pdf")
    assert media.load_image_block("http://x/api/admin/media/doc.pdf") is None   # not an image
    (tmp_path / "clip.mp4").write_bytes(b"mp4")
    assert media.load_image_block("http://x/api/admin/media/clip.mp4") is None  # video
    assert media.load_image_block(None) is None
    assert media.load_image_block("") is None


def test_load_image_block_rejects_oversized(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(media, "_MAX_BYTES", 10)
    (tmp_path / "big.jpg").write_bytes(b"x" * 100)
    assert media.load_image_block("http://x/api/admin/media/big.jpg") is None


# ── Remote fetch: Meta CDN attachments & post thumbnails ─────────────────────

class _FakeResp:
    def __init__(self, content=b"jpegbytes", ct="image/jpeg", ok=True):
        self.content = content
        self.headers = {"content-type": ct}
        self.is_success = ok
        self.status_code = 200 if ok else 404


def test_remote_url_is_fetched_when_not_local(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(media, "MEDIA_DIR", str(tmp_path))   # nothing on disk
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _FakeResp())
    block = media.load_image_block("https://scontent.xx.fbcdn.net/v/t1/photo.jpg?oh=sig")
    assert block["source"]["media_type"] == "image/jpeg"
    assert base64.standard_b64decode(block["source"]["data"]) == b"jpegbytes"


def test_local_file_wins_over_remote_fetch(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(media, "MEDIA_DIR", str(tmp_path))
    (tmp_path / "meta_messenger_m1.jpg").write_bytes(b"localbytes")
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("no fetch")))
    block = media.load_image_block("https://cdn.neema/api/admin/media/meta_messenger_m1.jpg")
    assert base64.standard_b64decode(block["source"]["data"]) == b"localbytes"


def test_remote_fetch_guards(tmp_path, monkeypatch):
    import httpx
    monkeypatch.setattr(media, "MEDIA_DIR", str(tmp_path))
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _FakeResp(ct="text/html"))
    assert media.load_image_block("https://x.example/page.jpg") is None      # not an image
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _FakeResp(ok=False))
    assert media.load_image_block("https://x.example/gone.jpg") is None      # 404
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _FakeResp(content=b"x" * 5_000_000))
    assert media.load_image_block("https://x.example/huge.jpg") is None      # oversized
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(httpx.ConnectError("boom")))
    assert media.load_image_block("https://x.example/err.jpg") is None       # network error
    assert media.load_image_block("ftp://x.example/a.jpg") is None           # non-http scheme

"""Importing the app must not touch the filesystem.

`app/routers/media.py` and `app/services/meta_media.py` used to run
`os.makedirs("/var/neema/media")` at MODULE scope, so merely importing the app
wrote to a hardcoded absolute path. Any non-root user importing it got
`PermissionError: [Errno 13] Permission denied: '/var/neema'` — which is
exactly how CI died during pytest *collection*, and why three CI jobs carried a
`sudo mkdir -p /var/neema/media` workaround.

The guard below is a subprocess on purpose: by the time this module runs, the
app is already imported in-process, so the only honest way to observe import
side effects is a fresh interpreter.
"""
import os
import subprocess
import sys

from app.core.config import settings

API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _import_in_subprocess(media_dir: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "MEDIA_DIR": media_dir}
    return subprocess.run(
        [sys.executable, "-c", "import app.main, app.agent.media, app.services.meta_media"],
        cwd=API_ROOT, env=env, capture_output=True, text=True, timeout=180,
    )


def test_importing_the_app_creates_no_directories(tmp_path):
    # A path whose PARENT does not exist either — so a stray makedirs shows up
    # as a created tree, not just a created leaf.
    target = tmp_path / "no-such-parent" / "media"

    proc = _import_in_subprocess(str(target))

    assert proc.returncode == 0, f"import failed:\n{proc.stderr}"
    assert not target.exists(), f"import created {target} — filesystem side effect is back"
    assert not target.parent.exists()


def test_media_dir_is_configurable_and_defaults_to_production(monkeypatch):
    from app.core.config import Settings

    assert Settings.model_fields["media_dir"].default == "/var/neema/media"

    monkeypatch.setenv("MEDIA_DIR", "/tmp/somewhere-else")
    assert Settings().media_dir == "/tmp/somewhere-else"


def test_every_media_module_derives_its_dir_from_the_one_setting():
    """No module may re-hardcode the literal — one definition, in Settings."""
    from app.agent import media as agent_media
    from app.routers import media as router_media
    from app.services import meta_media

    for mod in (router_media, agent_media, meta_media):
        assert mod.MEDIA_DIR == settings.media_dir, mod.__name__

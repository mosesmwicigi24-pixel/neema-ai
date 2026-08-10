"""Undefined names (ruff F821) are latent NameError/UnboundLocalError crashes,
not style nits — and this codebase wraps a lot of best-effort work in bare
`except Exception`, so they fail SILENTLY. Two shipped examples:

  · app/main.py used `os` in the boot-time media-writability probe without
    importing it. The probe never ran; worse, its `except` printed the alarming
    "Media dir NOT writable — uploads and inbound media WILL fail" on EVERY
    boot, with `Error: name 'os' is not defined` as the cause.

  · wa_native._ingest_guarded read `select` at the reply-quote lookup, but the
    only `from sqlalchemy import select` sat LOWER in the same function — which
    makes `select` a function-local, so the read raised UnboundLocalError. It
    was swallowed into `quoted = None`, so inbound reply-quotes never resolved.

Note the second case is why "just add a module-level import" is not enough on
its own: a later function-local import re-shadows the global and the bug
survives. F821 catches both shapes, so gate on it directly.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff not installed")
def test_no_undefined_names_anywhere_in_app():
    proc = subprocess.run(
        ["ruff", "check", str(APP_DIR), "--select", "F821",
         "--output-format", "json"],
        capture_output=True, text=True,
    )
    findings = json.loads(proc.stdout or "[]")
    assert findings == [], "undefined names (each one a latent crash):\n" + "\n".join(
        f"  {f['filename']}:{f['location']['row']}: {f['message']}" for f in findings
    )


def test_main_imports_os_for_the_media_probe():
    """The boot probe calls os.makedirs/os.path.join/os.remove."""
    import app.main

    assert getattr(app.main, "os", None) is not None


def test_wa_native_resolves_select_at_module_scope():
    import app.services.wa_native as wn

    assert getattr(wn, "select", None) is not None


def test_no_name_is_read_before_a_function_local_import_binds_it():
    """The wa_native shape, generalised — and the reason F821 alone is not a
    sufficient gate.

    A function-local `import x` makes `x` local for the WHOLE function, so any
    read above it raises UnboundLocalError. Ruff reports F821 only when nothing
    binds the name at module scope; add a module-level import and the bug goes
    silent while behaving identically. This walks every function in app/ and
    fails on a read that precedes the earliest local import of that name.
    """
    import ast

    offenders = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            bound = {}
            for node in ast.walk(fn):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        nm = alias.asname or alias.name.split(".")[0]
                        bound[nm] = min(bound.get(nm, node.lineno), node.lineno)
            if not bound:
                continue
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                    continue
                at = bound.get(node.id)
                if at is not None and node.lineno < at:
                    offenders.append(
                        f"  {path.name}:{node.lineno}: reads `{node.id}` in "
                        f"{fn.name}() but its local import is at line {at}"
                    )

    assert not offenders, (
        "read-before-local-import (UnboundLocalError at runtime):\n"
        + "\n".join(sorted(set(offenders)))
    )

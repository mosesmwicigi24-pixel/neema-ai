"""The affordability overhaul (owner, 2026-08-18) — every claim verifiable.

The Aug 17 bill was $54.52, of which $53.14 was Sonnet and $1.29 Haiku — on a
system whose telemetry said every turn ran the configured model, whose images
went to the vision model at full phone resolution, and whose most common
comment ("How much?") paid for a complete agent turn even on posts the system
had already identified down to the exact hub price.
"""
import io

import app.main  # noqa: F401


# ── 1. telemetry tells the truth ─────────────────────────────────────────────

def test_usage_logs_the_model_that_actually_served(monkeypatch):
    """settings.tier2_model recorded every Haiku-routed turn as Sonnet — the
    per-model split in the standup was fiction. The row must carry llm._model."""
    import inspect
    from app.agent import runtime
    src = inspect.getsource(runtime.run_turn)
    assert 'getattr(llm, "_model", None) or settings.tier2_model' in src
    assert "settings.tier2_model, totals)" not in src        # the old lie


def test_usage_rows_carry_where_the_money_went():
    import inspect
    from app.agent import runtime
    from app.services.n8n_bridge import log_agent_usage
    src = inspect.getsource(runtime.run_turn)
    assert 'f"{channel}:comment" if public_comment else channel' in src
    assert "node" in inspect.signature(log_agent_usage).parameters


# ── 2. images are shrunk before they are billed ──────────────────────────────

def _png_bytes(w, h):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def test_large_images_are_downscaled_to_the_vision_sweet_spot():
    from PIL import Image
    from app.agent.media import _shrink, _MAX_EDGE
    raw, mime = _shrink(_png_bytes(4000, 3000), "image/png")
    img = Image.open(io.BytesIO(raw))
    assert max(img.size) <= _MAX_EDGE == 1092
    assert mime == "image/jpeg"
    # aspect preserved (4:3)
    assert abs(img.size[0] / img.size[1] - 4 / 3) < 0.02


def test_small_images_pass_through_untouched():
    from app.agent.media import _shrink
    raw = _png_bytes(600, 400)
    out, mime = _shrink(raw, "image/png")
    assert out == raw and mime == "image/png"


def test_a_broken_image_never_costs_the_turn():
    from app.agent.media import _shrink
    out, mime = _shrink(b"not an image at all", "image/png")
    assert out == b"not an image at all" and mime == "image/png"


# ── 3. the free path: a bare price-ask on an identified post ─────────────────

def test_bare_price_asks_are_recognised():
    from app.agent.runtime import is_bare_price_ask
    for t in ("How much?", "how much is it", "Price?", "price please",
              "Bei gani?", "bei", "ngapi", "pesa ngapi", "Cost?"):
        assert is_bare_price_ask(t), t


def test_anything_more_than_a_price_ask_keeps_the_model():
    from app.agent.runtime import is_bare_price_ask
    for t in ("How much for 5 trays?",          # digits → quantities → cart math
              "how much and do you deliver to Lagos",
              "is this available in gold? how much",
              "cuánto cuesta",                   # other languages keep the model
              "combien",
              "this is wrong",                   # never the pool for displeasure
              ""):
        assert not is_bare_price_ask(t), t


def test_free_path_skips_the_model_and_spares_the_cap():
    """The gate short-circuits: identified post + bare ask never touches the
    daily cap counter, so free replies don't spend the model budget."""
    import inspect
    from app.agent import runtime
    src = inspect.getsource(runtime._run_comment_engage)
    assert 'free_ask = bool(_known_product.get("name")) and is_bare_price_ask(prompt_text)' in src
    assert "skip_model = free_ask or await _post_over_cap" in src
    assert "if not skip_model:" in src


def test_identified_posts_stop_buying_the_picture():
    """The earlier leak, pinned: the thumbnail rides only while the post is
    unidentified — once our records name the product, the comment rule says
    never re-guess from the frame, so the image would be paid for and ignored."""
    import inspect
    from app.agent import runtime
    src = inspect.getsource(runtime._run_comment_engage)
    assert 'if thumb and not _known_product.get("name") else None' in src


# ── 4. comment turns are capped at half the loop budget ──────────────────────

def test_comment_turns_get_half_the_iteration_budget():
    import inspect
    from app.agent import runtime
    src = inspect.getsource(runtime.run_turn)
    assert "min(settings.tier2_max_iterations, 4) if public_comment" in src
    assert "for _ in range(_max_iter):" in src

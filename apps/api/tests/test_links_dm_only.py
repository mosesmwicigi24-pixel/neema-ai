"""Links live in DMs; the public square stays link-free (owner, 2026-08-08,
made ABSOLUTE 2026-08-10).

Meta suppresses the reach of posts AND comments that carry external links —
link posts lose roughly half their reach, and the Sept-2025 ranking change
extended that scoring to links dropped in comments. Neema was posting the
storefront link in every public comment reply, quietly taxing the reach of
exactly the posts that were selling.

The 2026-08-08 fix moved the link into the DM but kept three "the buyer would
otherwise be stranded" escape hatches, and production promptly proved they were
not edge cases: over-cap comment replies went out reading "Karibu SelfieAnne 🙏
You can see it and order here 👉 https://bethanyhouse.co.ke/product/refiller
?ref=E14E0D". So the hatches are closed:

  * When the private reply (DM) opens, the storefront link rides THERE —
    answer, "Order here 👉 <product page>", warm continue line.
  * The public comment carries the answer + an invitation to the inbox. No URL,
    in ANY branch — `_comment_public_reply` is not even given one to paste.
  * `meta_send.reply_to_comment` strips URLs at the send boundary, so a model
    slip or a future template cannot publish one either.
"""
import inspect

import app.main  # noqa: F401 — registers all SQLAlchemy models
import app.agent.runtime as rt


_LINK = "https://bethanyhouse.co.ke/product/aluminium-tray?ref=AB12CD"


# ── the DM carries the link ──────────────────────────────────────────────────

def test_dm_carries_the_product_link():
    dm = rt._dm_text("The Aluminium Tray is $70, cups included.", _LINK, "seedX")
    assert f"Order here 👉 {_LINK}" in dm
    assert dm.startswith("The Aluminium Tray is $70, cups included.")
    # …and still ends on the warm continue line that sells inside the DM.
    assert any(dm.endswith(line) for line in rt._DM_CONTINUE_POOL)


def test_dm_without_a_product_stays_clean():
    dm = rt._dm_text("Karibu! What size do you need?", "", "seedX")
    assert "Order here" not in dm and "http" not in dm
    assert any(dm.endswith(line) for line in rt._DM_CONTINUE_POOL)


# ── the public square stays link-free when the DM landed ─────────────────────

def test_public_reply_is_link_free_when_the_dm_landed():
    out = rt._comment_public_reply(
        "The Aluminium Tray is $70.", dm_sent=True, name_tag=" Grace", seed="g",
        product_known=True, product_name="Aluminium Tray")
    assert "http" not in out            # no storefront link, no wa.me fallback
    assert out == "The Aluminium Tray is $70."      # the answer IS the reply


def test_nudge_pool_itself_is_link_free():
    for line in rt._DM_NUDGE_POOL + rt._COMMENT_INVITE_POOL:
        assert "http" not in line and "wa.me" not in line


def test_public_reply_is_link_free_when_the_dm_did_NOT_open():
    """The old escape hatch, closed. A DM failure is not a licence to publish a
    link — we answered them, so we invite them to write to us."""
    out = rt._comment_public_reply("The Aluminium Tray is $70.", dm_sent=False,
                                   name_tag="", seed="g",
                                   product_known=True, product_name="Aluminium Tray")
    assert "http" not in out and "bethanyhouse" not in out
    assert out == "The Aluminium Tray is $70."      # DM failure appends nothing

    # Over the per-post cap (no answer at all) → still no link, ever.
    over = rt._comment_public_reply("", dm_sent=False, name_tag=" Grace", seed="g",
                                    product_known=True, product_name="Aluminium Tray")
    assert "http" not in over and "bethanyhouse" not in over
    assert "Aluminium Tray" in over


def test_the_public_composer_cannot_be_handed_a_url_at_all():
    """Structural guarantee: no parameter of `_comment_public_reply` carries a
    URL, so no branch of it can paste one — a link has to be *invented* to leak,
    not merely forwarded."""
    params = set(inspect.signature(rt._comment_public_reply).parameters)
    assert not (params & {"link", "product_link", "url", "order_link"})


def test_no_public_comment_template_contains_a_link():
    """Every canned line that can reach the public square, swept in one place —
    the leak was a template, so templates are what this pins."""
    pools = (rt._DM_NUDGE_POOL + rt._COMMENT_INVITE_POOL + rt._OVER_CAP_POOL
             + rt._NEUTRAL_ACK_POOL + rt._THANKS_POOL + rt._GOODWILL_POOL)
    for line in pools:
        low = line.lower()
        assert "http" not in low
        assert "{link}" not in low
        assert ".co.ke" not in low and ".com" not in low
        assert "wa.me" not in low
        assert "order here" not in low


def test_the_send_boundary_guard_backs_all_of_this_up():
    """Belt and braces: even if a template regressed, the wire strips it."""
    from app.services import meta_send
    out, removed = meta_send.sanitize_public_comment(
        f"The tray is $70. Order here 👉 {_LINK}")
    assert removed == [_LINK] and "http" not in out


# ── the flow: product resolved BEFORE the DM, so the link can ride it ────────

def test_comment_flow_builds_the_dm_after_the_product():
    src = inspect.getsource(rt._run_comment_engage)
    assert "_dm_text(answer, product_link, ext)" in src
    # The product/link resolution must happen ABOVE the DM send — otherwise
    # there is no link to put in the message.
    dm_call = src.index("await send_private_reply(")   # the call, not the import
    assert src.index("_resolve_post_product") < dm_call
    assert src.index("_storefront_product_link") < dm_call

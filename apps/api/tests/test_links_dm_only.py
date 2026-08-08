"""Links live in DMs; the public square stays link-free (owner, 2026-08-08).

Meta suppresses the reach of posts AND comments that carry external links —
link posts lose roughly half their reach, and the Sept-2025 ranking change
extended that scoring to links dropped in comments. Neema was posting the
storefront link in every public comment reply, quietly taxing the reach of
exactly the posts that were selling. The fix:

  * When the private reply (DM) opens, the storefront link rides THERE —
    answer, "Order here 👉 <product page>", warm continue line.
  * The public comment then carries only the answer + an inbox nudge. No URL.
  * The public link appears ONLY when the DM could not open (over the
    per-post cap, or DM delivery failed) — a real buyer is never stranded,
    and the algorithm only ever sees a link when there was no other door.
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
        "The Aluminium Tray is $70.", dm_sent=True,
        link="https://neema.example/api/o/ABC", name_tag=" Grace", seed="g",
        product_link=_LINK)
    assert "http" not in out            # no storefront link, no wa.me fallback
    assert out.startswith("The Aluminium Tray is $70.")
    assert out != "The Aluminium Tray is $70."      # inbox nudge appended


def test_nudge_pool_itself_is_link_free():
    for line in rt._DM_NUDGE_POOL:
        assert "http" not in line and "wa.me" not in line


def test_public_link_returns_only_when_the_dm_did_not_open():
    # DM failed with a known product → the page is their only door.
    out = rt._comment_public_reply("The Aluminium Tray is $70.", dm_sent=False,
                                   link="", name_tag="", seed="g",
                                   product_link=_LINK)
    assert _LINK in out
    # Over the per-post cap (no answer at all) → the canned line still links.
    over = rt._comment_public_reply("", dm_sent=False, link="", name_tag=" Grace",
                                    seed="g", product_link=_LINK)
    assert _LINK in over


# ── the flow: product resolved BEFORE the DM, so the link can ride it ────────

def test_comment_flow_builds_the_dm_after_the_product():
    src = inspect.getsource(rt._run_comment_engage)
    assert "_dm_text(answer, product_link, ext)" in src
    # The product/link resolution must happen ABOVE the DM send — otherwise
    # there is no link to put in the message.
    dm_call = src.index("await send_private_reply(")   # the call, not the import
    assert src.index("_resolve_post_product") < dm_call
    assert src.index("_storefront_product_link") < dm_call

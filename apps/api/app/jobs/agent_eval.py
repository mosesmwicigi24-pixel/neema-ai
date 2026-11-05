"""Behavioral eval: run scripted customer conversations through the REAL agent
pipeline (real prompt, real model, real catalogue, real cart) and print the
transcripts — so prompt changes are judged on evidence, not hope.

Nothing is sent to any customer: replies are printed, then persisted only to
throwaway eval contacts (wa_ids below) so multi-turn history works, and those
contacts are deleted afterwards (pass --keep to inspect them in the inbox).
Scenarios deliberately STOP BEFORE final order confirmation so no hub order is
ever created. Costs a few cents of model tokens per run.

    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.agent_eval            # run + cleanup
    docker compose ... exec -T api python -m app.jobs.agent_eval --keep

Checks worth eyeballing in the output:
- Kenya vestment: overlay base-garment question first, colour→gender→set order,
  customer-led quantities, KES prices, "delivery or pickup?" at cart close.
- International: USD prices, courier talk (never "delivery or pickup?"),
  Western Union/Mukuru discovery on payment intent — never the KES link.
- Drift: after 3 off-topic turns → one kind close + the pause cooldown SET.
"""
from __future__ import annotations

import argparse
import asyncio
import logging

# Full model registry so mappers configure standalone.
import app.models.agent      # noqa: F401
import app.models.catalog    # noqa: F401
import app.models.conversation  # noqa: F401
import app.models.intercept  # noqa: F401
import app.models.message    # noqa: F401
import app.models.order_event  # noqa: F401
import app.models.person     # noqa: F401
import app.models.user       # noqa: F401

from sqlalchemy import delete, select

from app.core.config import settings
from app.database import AsyncSessionLocal
from app.models.message import Message, MsgDirection, MsgSender
from app.models.person import Person, Identity
from app.models.user import User

_log = logging.getLogger("neema.eval")

# Throwaway contacts — prefixes chosen to resolve real countries (KE / ZA).
SCENARIOS = [
    ("254700000901", "Kenya — chasuble discovery", [
        "Hi, I need a chasuble",
        "It will go over a cassock",
        "Purple with gold trim, for a gentleman",
        "Just the chasuble for now",
        "Two of them. That's all",
    ]),
    ("27650000901", "South Africa — shirt + stole to cart close", [
        "How much is a clerical shirt?",
        "Add two white ones, size 42",
        "Also add one stole",
        "That's all — how do I pay?",
    ]),
    ("254700000902", "Kenya — non-buying drift → pause", [
        "What are the legal requirements to register a church in Kenya?",
        "And how do I structure the board of my ministry?",
        "What about getting a certificate from the registrar?",
    ]),
    # ── The audit set (2026-11-05): Mama Beth's chat, anonymised, and the shapes
    # it exposed. Judge each reply on: words vs the ask, a set's contents said
    # once, no "hub"/"system"/"hold", no invented custom, prices = hub rows.
    ("254700000903", "Kenya — the Bishop's set (Mama Beth, anonymised)", [
        "How much is bishop man complete clothes",
        "Even the fible",
        "I mean rod",
        "Is it included there",
        "Ok.. that's nice but we can bargain the price",
        "What of the lady reverend",
        "Complete. Clothes",
        "Lady reverend is grey shirt with green n white",
        "Which particular colour for lady rev",
        "Plz assist for pentacost churches",
        "Mlisema Kuna bargain. Ya hizi prices ya bishop. M reverend",
        "What about sacrament bowl +nugi ile ya kuchoma ufumba",
    ]),
    ("254700000904", "Kenya — a short price ask, then yes/no", [
        "How much is the incense burner?",
        "Is it in stock?",
        "Ok",
    ]),
    ("254700000905", "Kenya — what's in the set, asked twice", [
        "What's in the cassock set?",
        "And how much?",
        "Sorry what did you say it comes with?",
        "Which colours do you have?",
    ]),
    ("254700000906", "Kenya — correction and a mis-typed word", [
        "I want a stole",
        "I mean the double sided one",
        "do you have it in purpel",
    ]),
    ("27650000902", "South Africa — denomination colour question", [
        "Hi, I need a cassock for our pastor",
        "We are Pentecostal, which colour should she wear?",
        "What else goes with it?",
    ]),
]

EVAL_IDS = [s[0] for s in SCENARIOS]

_INTERNAL_WORDS = ("hub", "our system", "search", "look it up", "reserve", "hold the", "hold these")


def judge(text: str, user_text: str, tools: list | None) -> dict:
    """What to eyeball per reply: words, sentences, questions, the length
    target the writer was given, internal talk, and whether every money figure
    in the reply is a hub figure from this turn's own search."""
    from app.agent import reply_length as rl
    from app.agent.review import money_figures, figures_in_results, _close
    m = rl.measure(text)
    target = rl.target_for(user_text)
    facts = figures_in_results(tools or [])
    said = money_figures(text or "")
    unverified = [f for f in said if not any(_close(f, v) for v in facts)]
    low = (text or "").lower()
    return {**m, "target": target["words"], "kind": target["kind"],
            "over": m["words"] > target["words"] * 1.5,
            "internal": [w for w in _INTERNAL_WORDS if w in low],
            "figures": said, "unverified": unverified}


async def _cleanup(redis) -> None:
    async with AsyncSessionLocal() as db:
        for wa_id in EVAL_IDS:
            await db.execute(delete(Message).where(Message.wa_id == wa_id))
            user = (await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()
            if user is not None:
                await db.delete(user)
            ident = (await db.execute(select(Identity).where(
                Identity.channel == "whatsapp", Identity.external_id == wa_id))).scalar_one_or_none()
            if ident is not None:
                pid = ident.person_id
                await db.delete(ident)
                others = (await db.execute(select(Identity).where(
                    Identity.person_id == pid))).scalars().first()
                if others is None:
                    person = await db.get(Person, pid)
                    if person is not None:
                        await db.delete(person)
        await db.commit()
    if redis is not None:
        for wa_id in EVAL_IDS:
            try:
                await redis.delete(f"agent:pause:whatsapp:{wa_id}")
            except Exception:
                pass


async def run(keep: bool) -> None:
    logging.basicConfig(level=logging.INFO,
                        format="    %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set — run this on the box.")
        return

    import redis.asyncio as aioredis
    from app.agent.runtime import run_turn, build_llm
    from app.services.messaging import provision_user

    try:
        redis = aioredis.from_url(settings.redis_url, decode_responses=True,
                                  socket_connect_timeout=5, socket_timeout=5)
        await redis.ping()
    except Exception:
        redis = None

    await _cleanup(redis)                        # fresh slate (idempotent re-runs)

    for wa_id, title, turns in SCENARIOS:
        print(f"\n{'=' * 62}\nSCENARIO: {title}  ({wa_id})\n{'=' * 62}")
        async with AsyncSessionLocal() as db:
            await provision_user(db, wa_id)      # realistic: user + country + identity
            await db.commit()
        for text in turns:
            print(f"\nCUSTOMER: {text}")
            async with AsyncSessionLocal() as db:
                db.add(Message(wa_id=wa_id, channel="whatsapp",
                               direction=MsgDirection.inbound, sender=MsgSender.user,
                               text=text))
                await db.commit()
            facts: dict = {}
            async with AsyncSessionLocal() as db:
                try:
                    reply = await run_turn(db, redis, wa_id, text, build_llm(purpose="job:eval"),
                                           turn_facts=facts)
                except Exception as exc:
                    print(f"NEEMA  : <turn failed: {exc}>")
                    break
            print(f"NEEMA  : {reply}")
            j = judge(reply, text, facts.get("tools"))
            flags = []
            if j["over"]:
                flags.append(f"LONG {j['words']}w > {j['target']}w ({j['kind']})")
            if j["internal"]:
                flags.append("INTERNAL " + ",".join(j["internal"]))
            if j["unverified"]:
                flags.append("UNVERIFIED " + ",".join(str(f) for f in j["unverified"]))
            print(f"[judge] {j['words']}w {j['sentences']}s {j['questions']}? target {j['target']} "
                  f"review={facts.get('review')}" + (" | " + "; ".join(flags) if flags else ""))
            totals = run.totals = getattr(run, "totals", {"turns": 0, "words": 0, "over": 0,
                                                           "internal": 0, "unverified": 0,
                                                           "rewritten": 0})
            totals["turns"] += 1
            totals["words"] += j["words"]
            totals["over"] += int(j["over"])
            totals["internal"] += int(bool(j["internal"]))
            totals["unverified"] += int(bool(j["unverified"]))
            totals["rewritten"] += int(facts.get("review") in ("rewritten", "soft", "held"))
            async with AsyncSessionLocal() as db:
                db.add(Message(wa_id=wa_id, channel="whatsapp",
                               direction=MsgDirection.outbound, sender=MsgSender.ai,
                               text=reply))
                await db.commit()
        if redis is not None and wa_id.endswith("902"):
            paused = await redis.get(f"agent:pause:whatsapp:{wa_id}")
            print(f"\n[check] pause cooldown set: {'YES' if paused else 'NO'}")

    t = getattr(run, "totals", None)
    if t and t["turns"]:
        print(f"\n{'=' * 62}\nSUMMARY: {t['turns']} replies · mean {t['words'] / t['turns']:.0f} words · "
              f"{t['over']} over target · {t['internal']} with internal talk · "
              f"{t['unverified']} with an unverified figure · {t['rewritten']} not passed first draft")
    if keep:
        print("\n--keep: eval contacts left in the inbox for inspection.")
    else:
        await _cleanup(redis)
        print("\nEval contacts cleaned up.")
    if redis is not None:
        try:
            await redis.aclose()
        except Exception:
            pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run scripted conversations through the real agent.")
    ap.add_argument("--keep", action="store_true",
                    help="keep the eval contacts/messages for inbox inspection")
    asyncio.run(run(keep=ap.parse_args().keep))

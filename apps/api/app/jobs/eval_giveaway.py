"""THE GIVEAWAY THREAD, with the model in the loop (owner, 2026-11-14: "can you
test it?").

agent_eval drives WhatsApp conversations only; what Neema says UNDER A POST —
the cassock giveaway of the owner's screenshots — had never been run with the
real model. This job feeds comments through the same path a real comment
takes (the webhook's capture → `_run_comment_engage` → `run_turn`), with the
real prompt and the real model, and records what would have been posted.

Nothing reaches Facebook: the three sends (`reply_to_comment`,
`send_private_reply`, `like_comment`) are recorders for the length of the run,
the post is read from the cache this job seeds, and the job refuses to start
against anything but a local throwaway database.

Each turn is checked by plain rules written from the owner's directive of
2026-11-10 — a reply or none, phrases that must not appear (a price under a
gift, the welcome and the selection procedure a second time, a request for a
phone number), a length. The transcript is the real evidence; the checks only
point at it.

    python -m app.jobs.eval_giveaway --out giveaway-eval.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from datetime import datetime, timezone

POST_ID = "evalpost_cassock_giveaway"
PAGE_ID = "EVALPAGE"

CAPTION = (
    "Would You Love Us to Gift Your Pastor a Beautiful Cassock?\n"
    "Bethany House is giving away a beautifully custom-made cassock to one deserving pastor!\n"
    "We want to hear from you. Tell us why your pastor deserves this special gift. Your story could be "
    "the reason we choose them!\n"
    "Who can participate?\n- Open to everyone, both in Kenya and abroad.\n"
    "- Tell us why your pastor should be selected.\n- Bethany House will choose the recipient.\n"
    "- The cassock is completely FREE! The selected recipient will only cover delivery costs within "
    "Kenya or international shipping costs outside Kenya.\n"
    "Nominate your pastor in the comments! We can't wait to read your stories.")

# A money figure, or an invitation to buy the gift.
PRICE = r"(?:KES|Ksh|USD|ZMW|\$)\s?\d|\d[\d,]{3,}\s?(?:KES|shillings|bob)|13,000"
SELL = r"place your order|if you(?:'d| would) like one|to buy one|purchase one|order one"
CONTEST = r"\b(?:winner|winning|you(?:'ve| have) won|lucky|good luck|all the best|vote)\b"
PRIVATE = r"\b(?:phone|mobile|whatsapp number|your number|email|e-mail|home address|postal address)\b"
WELCOME = r"welcome to bethany house"
PROCEDURE = r"select(?:ing)? one recipient|will be selecting|only cover(?:s)? the shipping|follow us"
EXTRA_ASK = r"(?:which|what|his|her|their|your)\s+(?:church|town|full name)|church and town|full name"
# On a later turn of a thread: the reflex opener, the terms once more, and
# the nominee's name used for the person writing (run 43585505682).
OPENER = r"^\s*(?:thank\s+you|thanks|asante)\b(?!\s+for\b)"
TERMS_AGAIN = r"cover(?:s|ing)?\s+(?:only\s+)?(?:the\s+|that\s+)?(?:shipping|delivery)|completely free"
WRONG_NAME = r"(?:thank\s+you|thanks|hello|hi|dear),?\s+thokozani"

CASES = [
    {"id": "give-001", "who": "Siyethemba Khumasta",
     "about": "the owner's screenshot: a nomination, then the details that followed it",
     "turns": [
         {"text": "I nominate my Pastor Rev TP From South Africa. He is a loving, caring and a patient "
                  "father that 1. Moreover he totally loves a cassock but doesn't own one, it would be "
                  "great for him to have it",
          "expect": "reply", "must_not": [PRICE, SELL, CONTEST, PRIVATE, EXTRA_ASK]},
         {"text": "Bethany House Pentecostal Holiness Church ( Potters House) around Nongoma KZN",
          "thread": True, "expect": "any", "max_words": 30,
          "must_not": [PRICE, SELL, CONTEST, PRIVATE, WELCOME, PROCEDURE, OPENER, TERMS_AGAIN,
                       r"bethany house pentecostal"]},
         {"text": "Thokozani Ndwandwe", "thread": True, "expect": "any", "max_words": 30,
          "must_not": [PRICE, SELL, CONTEST, PRIVATE, WELCOME, PROCEDURE, OPENER, TERMS_AGAIN,
                       WRONG_NAME]},
         {"text": "Thank you", "thread": True, "expect": "silent"},
     ]},
    {"id": "give-002", "who": "Pstr Irene",
     "about": "the owner's screenshot: asking to receive the gift herself, in Swahili and English",
     "turns": [
         {"text": "Hii labda nijiongee Mimi mwenyewe pls gift me the one I had the bishop who gave it "
                  "alikujia the whole. Cussock sinanga na sijafanikiwa kupata pesa ya kushona",
          "expect": "reply", "must_not": [PRICE, SELL, CONTEST, PRIVATE]},
     ]},
    {"id": "give-003", "who": "Oguchi Obichere",
     "about": "a casual compliment, then a bare acknowledgement",
     "turns": [
         {"text": "Very nice 👍", "expect": "reply", "max_words": 30, "must_not": [PRICE, SELL, PRIVATE]},
         {"text": "Amen", "thread": True, "expect": "silent"},
     ]},
    {"id": "give-004", "who": "Grace Wanjiru",
     "about": "a price ask under a gift",
     "turns": [
         {"text": "How much is this cassock?", "expect": "reply",
          "must": [r"gift|free|zawadi|bure"], "must_not": [PRICE, CONTEST, PRIVATE]},
     ]},
    {"id": "give-005", "who": "Daniel Otieno",
     "about": "a nomination, then a real question that must be answered",
     "turns": [
         {"text": "I nominate Pastor Mary Achieng of Kisumu, she has served our church for 20 years "
                  "without a cassock of her own.",
          "expect": "reply", "must_not": [PRICE, SELL, CONTEST, PRIVATE, EXTRA_ASK]},
         {"text": "When will you choose the pastor?", "thread": True, "expect": "reply",
          "must_not": [PRICE, SELL, CONTEST, PRIVATE, WELCOME, OPENER,
                       r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|"
                       r"march|april|may \d|june|july|august|september|october|november|december)\b"]},
     ]},
    {"id": "give-006", "who": "Peter Kamau",
     "about": "a grievance under the giveaway is still a grievance",
     "turns": [
         {"text": "I ordered a stole from you last month and I have never received it.",
          "expect": "reply", "must_not": [PRICE, SELL, CONTEST]},
     ]},
]


def words(text: str) -> int:
    return len(re.findall(r"[^\W_]+(?:['’][^\W_]+)?", text or "", re.UNICODE))


def check_turn(turn: dict, reply: str) -> list[str]:
    """What is wrong with this turn's public reply — [] when nothing is."""
    r = (reply or "").strip()
    out: list[str] = []
    expect = turn.get("expect", "reply")
    if expect == "silent":
        if r:
            out.append("answered where nothing was needed")
        return out
    if expect == "reply" and not r:
        return ["no reply where one was needed"]
    for pat in turn.get("must_not", []):
        m = re.search(pat, r, re.IGNORECASE)
        if m:
            out.append(f"said what it should not: “{m.group(0)}”")
    for pat in turn.get("must", []):
        if not re.search(pat, r, re.IGNORECASE):
            out.append(f"missing: {pat}")
    if r and turn.get("max_words") and words(r) > int(turn["max_words"]):
        out.append(f"too long: {words(r)} words (target {turn['max_words']})")
    return out


def summarise(results: list[dict]) -> dict:
    turns = [t for c in results for t in c["turns"]]
    kinds: dict[str, int] = {}
    for t in turns:
        for f in t["failures"]:
            k = f.split(":")[0]
            kinds[k] = kinds.get(k, 0) + 1
    return {"turns": len(turns), "passed": sum(1 for t in turns if not t["failures"]),
            "replies": sum(1 for t in turns if t["reply"]),
            "silent": sum(1 for t in turns if not t["reply"]),
            "words": sum(words(t["reply"]) for t in turns),
            "failure_kinds": kinds}


def _local_db_only() -> None:
    """Refuse a database that is not a local throwaway: this job writes
    conversations and messages for people who do not exist."""
    from app.core.config import settings
    url = str(getattr(settings, "database_url", "") or "")
    if not re.search(r"@(?:127\.0\.0\.1|localhost)[:/]", url):
        raise SystemExit("eval_giveaway runs against a local throwaway database only "
                         "(DATABASE_URL must point at 127.0.0.1 or localhost).")


async def run(out_path: str | None = None, only: str | None = None) -> dict:
    _local_db_only()
    import redis.asyncio as aioredis
    import app.main  # noqa: F401 — registers the models
    from app.agent import runtime as rt
    from app.core.config import settings
    from app.database import AsyncSessionLocal
    from app.routers import meta_webhook as mw
    from app.services import meta_send

    redis = aioredis.from_url(settings.redis_url)
    stamp = datetime.now(timezone.utc).strftime("%H%M%S")
    sent: dict = {"public": [], "dm": [], "liked": []}
    queued: list[dict] = []

    async def reply_to_comment(cid, text, page_id=None, channel=None):
        sent["public"].append((cid, text))
        return {"id": f"eval_reply_{cid}"}

    async def send_private_reply(cid, text, page_id=None, channel=None):
        sent["dm"].append((cid, text))
        return True

    async def like_comment(cid, page_id=None, channel=None):
        sent["liked"].append(cid)
        return True

    async def live_video_ids(redis=None):
        return set()

    def schedule(redis_, channel, comment, own):
        queued.append(comment)

    saved = {(meta_send, n): getattr(meta_send, n) for n in
             ("reply_to_comment", "send_private_reply", "like_comment", "live_video_ids")}
    saved[(rt, "schedule_comment_engage")] = rt.schedule_comment_engage
    saved_settings = {k: getattr(settings, k, None) for k in ("meta_comment_reply", "meta_page_id", "meta_comment_like")}
    meta_send.reply_to_comment, meta_send.send_private_reply = reply_to_comment, send_private_reply
    meta_send.like_comment, meta_send.live_video_ids = like_comment, live_video_ids
    rt.schedule_comment_engage = schedule
    settings.meta_comment_reply, settings.meta_page_id, settings.meta_comment_like = True, PAGE_ID, True

    post_id = f"{POST_ID}_{stamp}"
    await redis.set(f"meta:postctx:v2:facebook:{post_id}", json.dumps({
        "post_id": post_id, "title": CAPTION[:200], "caption": CAPTION,
        "permalink": "https://www.facebook.com/eval/posts/1", "thumb": "", "media_type": "photo"}), ex=3600)

    record: dict = {"started": datetime.now(timezone.utc).isoformat(), "post": "the cassock giveaway",
                    "models": {"producer": settings.tier2_model, "light": settings.tier2_model_light},
                    "results": []}
    try:
        for n, case in enumerate(c for c in CASES if not only or c["id"].startswith(only)):
            ext = f"evalg{stamp}{n:02d}"
            res = {"id": case["id"], "about": case["about"], "turns": []}
            first_cid = ""
            for i, turn in enumerate(case["turns"]):
                cid = f"{post_id}_c{n:02d}{i:02d}"
                first_cid = first_cid or cid
                value = {"item": "comment", "verb": "add", "comment_id": cid, "post_id": post_id,
                         "parent_id": (first_cid if turn.get("thread") else post_id),
                         "message": turn["text"], "from": {"id": ext, "name": case["who"]}}
                payload = {"entry": [{"id": PAGE_ID, "changes": [{"field": "feed", "value": value}]}]}
                before = {k: len(v) for k, v in sent.items()}
                queued.clear()
                t0 = time.monotonic()
                error = None
                try:
                    async with AsyncSessionLocal() as db:
                        await mw._capture_comment_events(db, "page", payload, redis=redis)
                    for c in list(queued):
                        await rt._run_comment_engage(redis, "facebook", c, {PAGE_ID})
                except Exception as exc:                      # a crash is a result, not a stop
                    error = f"{type(exc).__name__}: {exc}"[:300]
                reply = "\n".join(t for _, t in sent["public"][before["public"]:])
                dm = "\n".join(t for _, t in sent["dm"][before["dm"]:])
                failures = check_turn(turn, reply) + ([f"crashed: {error}"] if error else [])
                res["turns"].append({
                    "i": i, "comment": turn["text"], "expect": turn.get("expect", "reply"),
                    "reply": reply, "private_message": dm, "liked": len(sent["liked"]) > before["liked"],
                    "words": words(reply), "latency_s": round(time.monotonic() - t0, 2), "failures": failures})
                mark = "ok " if not failures else "FAIL"
                print(f"[{mark}] {case['id']} t{i} ({turn.get('expect', 'reply')}) {words(reply)}w"
                      + (" +like" if res["turns"][-1]["liked"] else "")
                      + (" +dm" if dm else "") + (f"  ← {'; '.join(failures)}" if failures else ""))
                print(f"       THEM: {turn['text'][:160]}")
                print(f"       US:   {reply or '(nothing posted)'}")
            record["results"].append(res)
    finally:
        for (mod, name), fn in saved.items():
            setattr(mod, name, fn)
        for k, v in saved_settings.items():
            setattr(settings, k, v)
        try:
            await redis.aclose()
        except Exception:
            pass
    record["finished"] = datetime.now(timezone.utc).isoformat()
    record["summary"] = summarise(record["results"])
    s = record["summary"]
    print(f"\nSUMMARY  turns {s['passed']}/{s['turns']} · replies {s['replies']} · silent {s['silent']} · "
          f"{s['words']} words posted · failure kinds: {json.dumps(s['failure_kinds'], ensure_ascii=False)}")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=1)
        print(f"written {out_path}")
    return record


def main() -> None:
    ap = argparse.ArgumentParser(description="The giveaway thread with the model in the loop")
    ap.add_argument("--out", help="write the run record (JSON) here")
    ap.add_argument("--only", help="case id prefix, e.g. give-001")
    args = ap.parse_args()
    asyncio.run(run(args.out, args.only))


if __name__ == "__main__":
    main()

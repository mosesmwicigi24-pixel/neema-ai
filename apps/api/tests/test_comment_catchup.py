"""One holding line, then one answer (owner, 2026-11-25) — driven through the
real comment handler, with Meta's sends, the model and the database faked."""
import asyncio
import json

import app.agent.runtime as rt
from app.core.config import settings
from app.services import comment_catchup as cc
from app.services import comment_ledger as ledger

Q = {"intent": "high", "kind": "question", "severity": 0, "ask": "the price"}
KEY = "facebook:p1:u1"


class _Redis:
    """The few redis calls the catch-up uses; anything else is a quiet no-op."""

    def __init__(self):
        self.kv, self.lists, self.sets = {}, {}, {}

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def get(self, k):
        return self.kv.get(k)

    async def incr(self, k):
        self.kv[k] = int(self.kv.get(k, 0)) + 1
        return self.kv[k]

    async def delete(self, *ks):
        for k in ks:
            self.kv.pop(k, None)
            self.lists.pop(k, None)

    async def rpush(self, k, v):
        self.lists.setdefault(k, []).append(v)

    async def lrange(self, k, a, b):
        return list(self.lists.get(k, []))

    async def lrem(self, k, n, v):
        self.lists[k] = [x for x in self.lists.get(k, []) if x != v]

    async def llen(self, k):
        return len(self.lists.get(k, []))

    async def sadd(self, k, v):
        self.sets.setdefault(k, set()).add(v)

    async def srem(self, k, v):
        self.sets.get(k, set()).discard(v)

    async def smembers(self, k):
        return set(self.sets.get(k, set()))

    def __getattr__(self, name):
        async def _noop(*a, **k):
            return None
        return _noop


class _DB:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class World:
    """Everything outside the handler, in one place the tests can steer. The
    comments and their reply state live in `rows` — the database's part."""

    def __init__(self, monkeypatch, *, identity=None):
        import app.database as dbmod
        import app.services.agent_health as ah
        from app.services import meta_send, messaging, post_catalog
        self.r = _Redis()
        self.rows = {}                 # comment id → the stored comment (text, post, reply state)
        self.staff_ids = set()         # comment ids a colleague replied under
        self.ai_ids = set()            # comment ids Neema's reply is threaded under
        self.public, self.liked, self.turns, self.followups, self.human, self.noted = [], [], [], [], [], []
        self.saved = []                # replies written to the inbox: (comment id, text, raw_meta)
        self.model = "down"            # "down" | "up" | "held"
        self.answer = "Here is your answer."
        self.reject_sends = 0          # how many of the next public sends Meta refuses
        self.send_error = None         # raised by the next public send, once
        self.over_cap = False
        self.during_turn = None        # a hook run while the model is composing
        ident = dict(identity or {})
        w = self

        async def read_comment(t, redis=None, **kw):
            return dict(Q)

        async def run_turn(db, redis, **kw):
            w.turns.append(kw)
            if w.during_turn:
                await w.during_turn()
            if w.model == "down":
                raise RuntimeError("credit balance is too low")
            if w.model == "held":
                kw["turn_facts"]["held"] = ["a figure the hub does not hold"]
                return ""
            return w.answer

        async def reply_to_comment(cid, t, page_id=None, channel=None):
            if w.send_error is not None:
                err, w.send_error = w.send_error, None
                raise err
            if w.reject_sends > 0:
                w.reject_sends -= 1
                raise RuntimeError("meta refused the reply")
            w.public.append((cid, t))
            w.ai_ids.add(str(cid))

        async def like_comment(cid, page_id=None, channel=None):
            w.liked.append(cid)
            return True

        async def none(*a, **k):
            return None

        async def false(*a, **k):
            return False

        async def over(redis, post_id):
            return w.over_cap

        async def recall(redis, channel, post_id):
            return dict(ident)

        async def resolve(redis, channel, ext, post_ctx, sink):
            if ident:
                sink.append(dict(ident))

        async def market(db, channel, key):
            return ("KES", {}, "", None)

        async def thread_parent(pid):
            return {}

        async def route_human(channel, ext, t, **kw):
            w.human.append(t)

        async def note_silent(channel, ext, cid, why):
            w.noted.append((cid, why))

        async def followup(redis, channel, ext, key, items, state, why="", ring=False):
            w.followups.append({"state": state, "why": why, "ring": ring,
                                "texts": [i["comment"]["text"] for i in items]})
            return "updated"

        async def ai_down(redis):
            return "credit" if w.model == "down" else None

        # ── the ledger, in memory (the real one is proved on Postgres in
        # test_comment_ledger_db.py) ──
        def _view(cid):
            row = w.rows[cid]
            b = row["reply"]
            return {"cid": cid, "at": row["at"], "state": b.get("state"), "decided": bool(b.get("decided")),
                    "reason": b.get("reason") or "", "why": b.get("why") or "", "followup": b.get("followup"),
                    "own_pages": list(b.get("own_pages") or []), "page_id": b.get("page_id"),
                    "parent_id": b.get("parent_id"), "post_id": row["post_id"], "text": row["text"],
                    "post_context": dict(row["post_context"])}

        async def mark(channel, ext, ids, *, create=False, only_undecided=False, **fields):
            n = 0
            for cid in [str(i) for i in (ids or [])]:
                row = w.rows.get(cid)
                if row is None or (row.get("reply") is None and not create):
                    continue
                b = row.get("reply") or {}
                if only_undecided and (b.get("decided") or b.get("state") != ledger.OWED):
                    continue
                row["reply"] = {**b, **fields}
                n += 1
            return n

        async def unresolved(channel, ext, post_id, **kw):
            return [_view(c) for c, row in sorted(w.rows.items(), key=lambda kv: kv[1]["at"])
                    if row.get("reply") and row["reply"].get("state") in ledger.OPEN
                    and row["post_id"] == str(post_id)]

        async def keys_owed(**kw):
            return sorted({("facebook", "u1", row["post_id"]) for row in w.rows.values()
                           if (row.get("reply") or {}).get("state") == ledger.OWED})

        async def state_of(channel, ext, cid):
            return _view(str(cid)) if str(cid) in w.rows and w.rows[str(cid)].get("reply") else None

        async def existing(channel, ext, ids):
            return {str(i) for i in ids if str(i) in w.rows}

        async def replied_ids(channel, ext, ids, *, staff_only=False):
            have = set(w.staff_ids) if staff_only else (set(w.staff_ids) | set(w.ai_ids))
            return have & {str(i) for i in ids}

        async def followup_id(channel, ext, post_id, **kw):
            return None

        for n, f in (("mark", mark), ("unresolved", unresolved), ("keys_owed", keys_owed),
                     ("state_of", state_of), ("existing", existing), ("replied_ids", replied_ids),
                     ("followup_id", followup_id)):
            monkeypatch.setattr(ledger, n, f)
        monkeypatch.setattr(settings, "meta_comment_like", True, raising=False)
        monkeypatch.setattr(dbmod, "AsyncSessionLocal", lambda: _DB())
        monkeypatch.setattr(meta_send, "reply_to_comment", reply_to_comment)
        monkeypatch.setattr(meta_send, "send_private_reply", none)
        monkeypatch.setattr(meta_send, "like_comment", like_comment)
        async def save_outbound(db, redis, channel, ext, t, reply_to_comment_id=None, raw_meta=None):
            w.saved.append((reply_to_comment_id, t, raw_meta))

        monkeypatch.setattr(messaging, "save_outbound_channel_message", save_outbound)
        monkeypatch.setattr(post_catalog, "identity_trusted",
                            lambda rec: bool((rec or {}).get("name")) and (rec or {}).get("source") == "caption")
        monkeypatch.setattr(ah, "ai_down", ai_down)
        monkeypatch.setattr(ah, "record_turn_failure", none)
        monkeypatch.setattr(cc, "followup", followup)
        monkeypatch.setattr(asyncio, "sleep", none)
        for n, f in (("read_comment", read_comment), ("run_turn", run_turn),
                     ("_route_comment_to_human", route_human), ("_note_silent_decision", note_silent),
                     ("_recall_post_product", recall), ("_resolve_post_product", resolve),
                     ("_remember_post_product", none), ("_storefront_product_link", none),
                     ("_post_over_cap", over), ("_person_over_cap", false), ("_first_contact", false),
                     ("_meta_market", market), ("_thread_parent", thread_parent),
                     ("_private_complaint_message", false)):
            monkeypatch.setattr(rt, n, f)
        monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: object())

    def comment(self, cid, text, caption="Vesting cassock with stole and chasuble", post="p1"):
        return {"comment_id": cid, "from_id": "u1", "from_name": "Ruben Matacha", "text": text,
                "post_id": post, "page_id": "PAGE",
                "post_context": {"post_id": post, "title": caption, "caption": caption, "thumb": ""}}

    def record(self, cid, text, **kw):
        """The webhook saved this comment, stamped as owed, before any handler ran."""
        import time
        c = self.comment(cid, text, **kw)
        self.rows[cid] = {"text": text, "post_id": c["post_id"], "post_context": c["post_context"],
                          "at": time.time(), "reply": ledger.opening({"PAGE"}, "PAGE", None, c["post_id"])}
        return c

    def says(self, cid, text, **kw):
        """The webhook saves it, then the scheduled handler runs to its end."""
        asyncio.run(rt._engage_and_settle(self.r, "facebook", self.record(cid, text, **kw), {"PAGE"}))

    def age(self, seconds=700):
        """Time passes: every stored comment is that much older."""
        for row in self.rows.values():
            row["at"] -= seconds

    def sweep(self):
        self.r.kv.pop("comment:catchup:backoff:" + KEY, None)   # the next pass, ten minutes on
        return asyncio.run(cc.sweep(self.r))

    def waiting(self):
        return [i["comment"]["text"] for i in asyncio.run(cc.waiting(self.r, KEY))]

    def state(self, cid):
        return (self.rows[cid]["reply"] or {}).get("state")

    def staff_reply(self, cid):
        """A colleague's public reply under this comment (send_agent_reply)."""
        self.staff_ids.add(cid)
        return asyncio.run(cc.staff_replied(self.r, "facebook", "u1", cid))


def test_a_refused_holding_line_is_tried_again_and_lands_once(monkeypatch):
    w = World(monkeypatch)
    w.reject_sends = 1
    w.says("c1", "Hiyo nguo ni sh. Ngapi")                 # Meta refuses the line
    assert w.public == [] and "comment:hold_said:" + KEY not in w.r.kv
    assert "comment:hold_claim:" + KEY not in w.r.kv       # the claim is freed for a retry
    w.says("c2", "Nipo Tanzania Tarime")                   # the retry lands
    assert len(w.public) == 1 and w.public[0][0] == "c2"
    w.says("c3", "Bethany House ni sh. Ngapi kwanza")      # they have it: seen, not repeated
    w.says("c4", "Nataka hizo nguo")
    assert len(w.public) == 1 and w.liked[-2:] == ["c3", "c4"]
    assert "shortly" not in w.public[0][1] and "karibuni" not in w.public[0][1]
    assert w.waiting() == ["Hiyo nguo ni sh. Ngapi", "Nipo Tanzania Tarime",
                           "Bethany House ni sh. Ngapi kwanza", "Nataka hizo nguo"]


def test_the_sweep_says_a_refused_holding_line_once_while_the_model_is_down(monkeypatch):
    w = World(monkeypatch)
    w.reject_sends = 1
    w.says("c1", "How much is the cassock?")
    assert w.public == []
    w.age()
    assert w.sweep() == 0 and len(w.public) == 1 and w.public[0][0] == "c1"
    assert w.sweep() == 0 and len(w.public) == 1           # said: not again
    assert w.turns and len(w.turns) == 1                   # and no model call was spent on it


def test_two_sends_at_once_cannot_both_say_the_line():
    r = _Redis()

    async def go():
        assert await cc.hold_state(r, KEY) == "send"       # the first claims it
        assert await cc.hold_state(r, KEY) == "busy"       # the second waits
        await cc.hold_confirm(r, KEY)
        assert await cc.hold_state(r, KEY) == "said"
    asyncio.run(go())


def test_a_refused_recovery_reply_keeps_the_comments_until_one_lands(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.says("c2", "I am in Tarime, Tanzania")
    assert len(w.public) == 1
    w.model, w.answer = "up", "The set is KES 45,000, and we deliver to Tarime by DHL."
    w.age()
    w.reject_sends = 1
    w.sweep()                                              # composed, but Meta refuses the post
    assert len(w.public) == 1 and len(w.waiting()) == 2
    w.sweep()                                              # the next pass lands
    assert w.public[-1] == ("c2", "The set is KES 45,000, and we deliver to Tarime by DHL.")
    assert w.waiting() == [] and "comment:hold_said:" + KEY not in w.r.kv
    assert w.followups[-1]["state"] == cc.CLOSED
    before = len(w.public)
    w.sweep()
    assert len(w.public) == before                         # answered once


def test_a_comment_that_arrives_during_recovery_stays_waiting(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.model = "up"
    w.age()

    async def arrives():
        w.during_turn = None
        await cc.keep(w.r, "facebook", w.record("c9", "And do you deliver to Uganda?"), {"PAGE"}, cc.MODEL)
    w.during_turn = arrives
    w.sweep()
    assert w.public[-1][0] == "c1"                         # the reply covered what it read …
    assert w.waiting() == ["And do you deliver to Uganda?"]          # … and the new one is still owed
    assert w.followups[-1]["state"] == cc.WAITING and w.followups[-1]["texts"] == ["And do you deliver to Uganda?"]


def test_a_colleagues_reply_answers_the_comment_it_was_made_to_and_no_other(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.says("c2", "Do you deliver to Tarime?")
    w.says("x1", "Is the chalice in stock?", post="p2")    # the same person, waiting under ANOTHER post
    assert w.staff_reply("c1") is True                     # a colleague replies under c1
    assert w.state("c1") == ledger.RESOLVED and w.rows["c1"]["reply"]["by"] == "staff"
    assert w.waiting() == ["Do you deliver to Tarime?"]    # c2 is still owed
    assert w.state("x1") == ledger.OWED                    # the other post untouched
    assert w.followups[-1]["state"] == cc.WAITING and w.followups[-1]["texts"] == ["Do you deliver to Tarime?"]
    w.model, w.answer = "up", "Yes, we deliver to Tarime by DHL."
    w.age()
    w.sweep()
    asked = [t["user_text"] for t in w.turns[3:]]
    assert "Do you deliver to Tarime?" in asked and not any("How much is the cassock?" in a for a in asked)
    assert ("c2", "Yes, we deliver to Tarime by DHL.") in w.public and w.waiting() == []
    assert w.staff_reply("zzz") is False                   # a reply to a comment we do not hold


def test_a_colleague_who_answers_while_the_reply_is_composed_is_not_answered_over(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.says("c2", "Do you deliver to Tarime?")
    w.model = "up"
    w.age()

    async def colleague():
        w.during_turn = None
        w.staff_ids = {"c2"}                               # they reply under c2 mid-compose
    w.during_turn = colleague
    public = len(w.public)
    w.sweep()
    assert len(w.public) == public                         # the composed reply is not posted
    assert w.waiting() == ["How much is the cassock?"]     # c1 is still owed; c2 is the colleague's
    w.sweep()
    assert w.turns[-1]["user_text"] == "How much is the cassock?" and w.public[-1][0] == "c1"


def test_the_staff_reply_path_names_the_comment_it_answered(monkeypatch):
    import inspect
    import types
    from app.services import conversation as cs, meta_send
    sent_to = []

    async def reply_to_comment(cid, t, channel=None, page_id=None):
        sent_to.append(cid)

    async def latest_inbound(db, conv_id):
        return types.SimpleNamespace(waba_msg_id="c7", comment_context={"post_id": "p1"})

    async def window(db, conv):
        return {"mode": "closed"}
    monkeypatch.setattr(meta_send, "reply_to_comment", reply_to_comment)
    monkeypatch.setattr(cs, "_latest_inbound", latest_inbound)
    monkeypatch.setattr(cs, "messaging_window", window)
    conv = types.SimpleNamespace(id="k", channel="facebook", external_id="u1", wa_id=None)
    asyncio.run(cs._deliver_agent_reply(None, conv, "It is KES 45,000."))
    assert sent_to == ["c7"] and conv._replied_comment_id == "c7"
    src = inspect.getsource(cs.send_agent_reply)
    assert 'comment_context=({"reply_to": _replied} if _replied else None)' in src
    assert "await comment_catchup.staff_replied(redis, conv.channel" in src


def test_a_cap_during_recovery_leaves_every_question_with_staff(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.says("c2", "Can you make it in purple?")
    w.model, w.over_cap = "up", True
    w.age()
    turns, public = len(w.turns), len(w.public)
    w.sweep()
    assert len(w.turns) == turns and len(w.public) == public          # no call, nothing posted
    last = w.followups[-1]
    assert last["state"] == cc.STAFF and "limit" in last["why"]
    assert last["texts"] == ["How much is the cassock?", "Can you make it in purple?"]
    assert w.waiting() == last["texts"]                    # still visible, not dropped
    w.sweep()
    assert len(w.turns) == turns                           # a colleague's now: no more tries


def test_a_held_draft_during_recovery_goes_to_staff_with_the_reason(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.model = "held"
    w.age()
    w.sweep()
    assert w.followups[-1]["state"] == cc.STAFF and "reviewer" in w.followups[-1]["why"]
    assert w.waiting() == ["How much is the cassock?"] and len(w.public) == 1


def test_three_tries_that_do_not_succeed_hand_it_to_staff(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.age()

    async def not_down(redis):
        return None
    import app.services.agent_health as ah
    monkeypatch.setattr(ah, "ai_down", not_down)           # health says up, yet the call still fails
    for _ in range(4):
        w.sweep()
    assert w.state("c1") == ledger.STAFF
    assert w.followups[-1]["state"] == cc.STAFF and "three tries" in w.followups[-1]["why"]
    assert w.followups[-1]["ring"] is True                 # the team hears that it is theirs now
    turns = len(w.turns)
    w.sweep()
    assert len(w.turns) == turns


def test_a_verified_price_question_is_still_answered_without_the_model(monkeypatch):
    shoe = {"name": "Clergy Oxford Shoe", "source": "caption", "confidence": 1.0,
            "price_kes": 4500, "price_usd": 35, "slug": "clergy-oxford-shoe", "product_type": "simple"}
    w = World(monkeypatch, identity=shoe)
    w.says("c1", "How much?", caption="Clergy Oxford Shoe, in stock")
    assert w.turns == []                                   # no model call
    assert len(w.public) == 1 and "4,500" in w.public[0][1] and "Clergy Oxford Shoe" in w.public[0][1]
    assert w.waiting() == [] and w.followups == []         # a real answer: nothing kept, no hold


def test_rubens_four_comments_become_one_request_with_tanzania_in_it(monkeypatch):
    w = World(monkeypatch)
    for cid, text in (("c1", "Hiyo nguo ni sh. Ngapi"), ("c2", "Nipo Tanzania Tarime Mimi ni Mchungaji so ni sh. Ngapi"),
                      ("c3", "Bethany House Ni sh. Ngapi kwanza"), ("c4", "Nataka hizo nguo ila bei ndiyo kitu Cha msingi")):
        w.says(cid, text)
    assert len(w.public) == 1                              # one holding line, not four
    assert w.followups[-1]["state"] == cc.WAITING and len(w.followups[-1]["texts"]) == 4
    assert w.human == []                                   # one follow-up, not a flag per comment
    w.model, w.answer = "up", "Mchungaji, seti kamili ni TZS … tunatuma Tarime kwa DHL."
    w.age()
    w.sweep()
    asked = w.turns[-1]["user_text"]
    assert "ONE reply" in asked and "sh. Ngapi" in asked and "Tanzania Tarime" in asked
    assert "bei ndiyo kitu Cha msingi" in asked
    assert len(w.public) == 2 and w.public[-1][0] == "c4"  # one answer, under the latest comment
    assert w.waiting() == []


def test_afias_request_is_read_in_her_words_not_the_posts(monkeypatch):
    w = World(monkeypatch)
    kettle = "Silver refiller kettle, made to make communion easier to serve."
    w.says("c1", "I won't offering bowl stand for churches", caption=kettle)
    w.says("c2", "please i won't to buy Offering bowl stand for churches can you show me how to buy it "
                 "from your shop thank you.", caption=kettle)
    assert len(w.public) == 1
    w.model = "up"
    w.age()
    w.sweep()
    asked = w.turns[-1]["user_text"]
    assert "Offering bowl stand" in asked and "how to buy it" in asked
    assert "THEIR words, even where the post shows another item" in asked
    assert w.public[-1][0] == "c2"


def test_a_new_comment_gathers_what_is_waiting_once_the_model_is_back(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.model, w.answer = "up", "It is KES 45,000 and yes, we make it in purple."
    w.says("c2", "Can you make it in purple?")             # arrives before any sweep ran
    assert "How much is the cassock?" in w.turns[-1]["user_text"]
    assert "Can you make it in purple?" in w.turns[-1]["user_text"]
    assert w.public[-1] == ("c2", "It is KES 45,000 and yes, we make it in purple.")
    assert w.waiting() == []


# ── the pure parts ───────────────────────────────────────────────────────────
def _item(cid, text, at, state=ledger.OWED, decided=True, reason=cc.MODEL):
    return {"at": at, "cid": cid, "state": state, "decided": decided, "reason": reason, "own_pages": ["PAGE"],
            "comment": {"comment_id": cid, "from_id": "u1", "post_id": "p1", "text": text}}


def test_the_plan_for_what_is_waiting():
    now = 1_000_000.0
    items = [_item("c1", "price?", now - 3000), _item("c2", "price?", now - 2000),
             _item("c3", "I am in Tarime", now - 200)]
    p = cc.plan(items, now=now)
    assert p["answer"]["comment"]["comment_id"] == "c3"
    assert p["answer"]["comment"]["catch_up"] == ["price?", "I am in Tarime"]      # the same words read once
    assert p["answer"]["comment"]["catch_up_ids"] == ["c1", "c2", "c3"]           # but every id is covered
    assert cc.plan([_item("c1", "x", now - 10)], now=now)["answer"] is None         # too fresh
    old = cc.plan([_item("c1", "x", now - cc.WINDOW_S - 5)], now=now)
    assert old["expired"] == ["c1"] and old["answer"] is None                       # a day on: a colleague's
    assert cc.plan([_item("c1", "x", now - 500, ledger.STAFF)], now=now)["answer"] is None      # staff's alone
    assert cc.plan([_item("c1", "x", now - 500, ledger.VERIFY)], now=now)["answer"] is None     # never re-sent
    mixed = cc.plan([_item("c1", "a", now - 900, ledger.STAFF), _item("c2", "b", now - 500)], now=now)
    assert mixed["answer"]["comment"]["catch_up"] == ["b"]                      # a colleague's stays theirs
    assert mixed["answer"]["comment"]["catch_up_ids"] == ["c2"]
    # a comment no handler decided on: left alone while a live handler may still be on it …
    fresh = cc.plan([_item("c1", "x", now - 200, decided=False)], now=now)
    assert fresh["answer"] is None and fresh["orphans"] == []
    # … and picked up once it is plainly orphaned (a restart after the save)
    orphan = cc.plan([_item("c1", "x", now - 700, decided=False)], now=now)
    assert orphan["orphans"] == ["c1"] and orphan["answer"]["comment"]["catch_up"] == ["x"]


def test_the_follow_up_says_what_staff_need_to_know():
    items = [_item("c1", "How much?", 1), _item("c2", "Do you deliver to Uganda?", 2)]
    w = cc.followup_note(items, cc.WAITING)
    assert "(2)" in w and "1. How much?" in w and "2. Do you deliver to Uganda?" in w and "one reply" in w
    s = cc.followup_note(items, cc.STAFF, "a reply limit was reached")
    assert "will NOT answer" in s and "a reply limit was reached" in s and "a colleague must reply" in s
    assert "answered" in cc.followup_note([], cc.CLOSED)


def test_a_hold_line_that_is_our_last_word_is_not_said_again():
    from app.agent.runtime import hold_line_stands
    assert hold_line_stands(["hold_line"]) is True
    assert hold_line_stands([None]) is False                   # we answered since
    assert hold_line_stands([]) is False


# ── the second review: deletion ──────────────────────────────────────────────
def test_nothing_a_customer_wrote_is_kept_outside_the_database(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "Hiyo nguo ni sh. Ngapi")
    w.says("c2", "Nipo Tanzania Tarime")
    blob = json.dumps([w.r.kv, w.r.lists, [sorted(v) for v in w.r.sets.values()]], default=str)
    assert "Ngapi" not in blob and "Tarime" not in blob and "Ruben" not in blob
    assert w.r.lists == {} and w.r.sets == {}              # no queue, no index: nothing to expire


def test_a_comment_deleted_while_it_waits_is_never_answered(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.says("c2", "Do you deliver to Tarime?")
    w.model = "up"
    w.age()
    del w.rows["c1"]                                       # a data-deletion request removed it
    w.sweep()
    assert w.turns[-1]["user_text"] == "Do you deliver to Tarime?"      # only what still exists is read
    assert w.waiting() == []
    w2 = World(monkeypatch)
    w2.says("c1", "How much is the cassock?")
    w2.model = "up"
    w2.age()
    w2.rows.clear()                                        # everything they wrote is gone
    turns, public = len(w2.turns), len(w2.public)
    w2.sweep()
    assert len(w2.turns) == turns and len(w2.public) == public          # no call, no reply


def test_a_comment_deleted_while_the_reply_is_composed_is_not_answered(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.says("c2", "Do you deliver to Tarime?")
    w.model = "up"
    w.age()

    async def deletion():
        w.during_turn = None
        del w.rows["c1"]
    w.during_turn = deletion
    public = len(w.public)
    w.sweep()
    assert len(w.public) == public                         # the reply that read c1 is not posted
    assert w.waiting() == ["Do you deliver to Tarime?"]
    w.sweep()
    assert w.turns[-1]["user_text"] == "Do you deliver to Tarime?" and w.public[-1][0] == "c2"


# ── the third review: a customer is never lost track of ──────────────────────
def test_a_restart_right_after_the_comment_is_saved_loses_nothing(monkeypatch):
    w = World(monkeypatch)
    w.model = "up"
    w.record("c1", "How much is the cassock?")             # saved by the webhook … and the process dies:
    assert w.state("c1") == ledger.OWED                    # no handler ever ran, yet it is owed, on the record
    assert w.sweep() == 0                                  # too soon to call it orphaned: a handler may be on it
    assert w.turns == []
    w.age()                                                # ten minutes on, nobody has decided on it
    w.answer = "The set is KES 45,000."
    assert w.sweep() == 1
    assert w.public == [("c1", "The set is KES 45,000.")] and w.state("c1") == ledger.RESOLVED


def test_a_restart_during_an_outage_still_gets_the_one_line_and_a_clear_owner(monkeypatch):
    w = World(monkeypatch)                                 # the model is down
    w.record("c1", "How much is the cassock?")             # saved, never handled
    w.age()
    w.sweep()
    assert len(w.public) == 1 and w.public[0][0] == "c1"                # they hear the holding line, once
    assert w.public[0][1] in [x.replace("{name}", "") for x in rt._NEUTRAL_ACK_POOL]
    assert w.rows["c1"]["reply"]["decided"] is True and w.state("c1") == ledger.OWED
    assert w.followups[-1]["state"] == cc.WAITING and w.followups[-1]["texts"] == ["How much is the cassock?"]
    w.sweep()
    assert len(w.public) == 1


def test_an_orphan_that_already_has_a_reply_is_not_answered_twice(monkeypatch):
    w = World(monkeypatch)
    w.model = "up"
    w.record("c1", "How much is the cassock?")
    w.ai_ids.add("c1")                                     # the reply went out; the process died before settling
    w.age()
    assert w.sweep() == 0 and w.turns == [] and w.public == []
    assert w.state("c1") == ledger.RESOLVED and w.rows["c1"]["reply"]["by"] == "replied"


def test_a_handler_that_crashes_leaves_the_comment_owed(monkeypatch):
    w = World(monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("handler crashed")
    monkeypatch.setattr(rt, "read_comment", boom)
    try:
        w.says("c1", "How much is the cassock?")
    except RuntimeError:
        pass
    assert w.state("c1") == ledger.OWED and w.rows["c1"]["reply"]["decided"] is False


def test_an_answered_comment_is_settled_and_never_touched_again(monkeypatch):
    w = World(monkeypatch)
    w.model, w.answer = "up", "It is KES 45,000."
    w.says("c1", "How much is the cassock?")
    assert w.state("c1") == ledger.RESOLVED and w.rows["c1"]["reply"]["by"] == "handled"
    w.age()
    assert w.sweep() == 0 and len(w.turns) == 1


def test_losing_every_redis_key_while_a_customer_waits_loses_nothing(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.says("c2", "Do you deliver to Tarime?")
    w.r.kv.clear()                                         # Redis expires, or is wiped
    w.r.lists.clear()
    w.r.sets.clear()
    assert w.waiting() == ["How much is the cassock?", "Do you deliver to Tarime?"]
    w.model, w.answer = "up", "KES 45,000, and yes, by DHL."
    w.age()
    assert w.sweep() == 1
    assert w.public[-1] == ("c2", "KES 45,000, and yes, by DHL.") and w.waiting() == []
    assert w.followups[-1]["state"] == cc.CLOSED


def test_when_the_day_runs_out_the_question_moves_to_staff_and_the_inbox_says_so(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    assert w.followups[-1]["state"] == cc.WAITING          # "Neema will answer …"
    w.r.kv.clear()                                         # and the Redis side is gone as well
    w.age(cc.WINDOW_S + 60)                                # a day passes, still no model
    public = len(w.public)
    w.sweep()
    assert w.state("c1") == ledger.STAFF and "day" in w.rows["c1"]["reply"]["why"]
    last = w.followups[-1]
    assert last["state"] == cc.STAFF and "day" in last["why"] and last["ring"] is True
    assert last["texts"] == ["How much is the cassock?"]   # still visible, with its owner
    assert len(w.public) == public
    w.model = "up"
    assert w.sweep() == 0                                  # a colleague's: Neema does not answer over them


def test_the_live_handler_and_the_sweep_never_both_compose_the_reply(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.model = "up"
    w.age()

    async def live_comment():                              # arrives while the sweep is composing
        w.during_turn = None
        await rt._run_comment_engage(w.r, "facebook", w.record("c9", "Do you have it in purple?"), {"PAGE"})
    w.during_turn = live_comment
    w.sweep()
    asked = [t["user_text"] for t in w.turns]
    assert sum("How much is the cassock?" in a for a in asked[1:]) == 1    # gathered by ONE composer
    assert [cid for cid, _t in w.public].count("c1") == 2               # the holding line, then one answer
    # and the other way round: while the live handler holds the claim the sweep stands back
    w3 = World(monkeypatch)
    w3.says("c1", "How much is the cassock?")
    w3.model = "up"
    w3.age()
    assert asyncio.run(cc.claim_answer(w3.r, KEY)) is True
    turns = len(w3.turns)
    assert w3.sweep() == 0 and len(w3.turns) == turns


def test_a_holding_line_with_an_unknown_outcome_is_never_sent_again(monkeypatch):
    from app.services.messaging import SendOutcomeUnknown
    w = World(monkeypatch)
    w.send_error = SendOutcomeUnknown("ReadTimeout: reply to comment outcome unknown")
    w.says("c1", "How much is the cassock?")
    assert w.public == [] and "comment:hold_said:" + KEY in w.r.kv      # it MAY be up: counted as said
    assert "did not confirm" in w.followups[-1]["why"]                  # and a colleague is told to look
    w.says("c2", "Hello?")
    w.age()
    w.sweep()
    assert w.public == []                                               # not by a comment, not by the sweep


def test_a_recovery_reply_with_an_unknown_outcome_goes_to_staff_not_to_a_retry(monkeypatch):
    from app.services.messaging import SendOutcomeUnknown
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.model = "up"
    w.age()
    w.send_error = SendOutcomeUnknown("ReadTimeout: reply to comment outcome unknown")
    w.sweep()
    last = w.followups[-1]
    assert last["state"] == cc.STAFF and "check the thread" in last["why"]
    assert last["texts"] == ["How much is the cassock?"] and w.waiting() == last["texts"]
    turns, public = len(w.turns), len(w.public)
    w.sweep()
    w.sweep()
    assert len(w.turns) == turns and len(w.public) == public            # nobody posts another


# ── the fourth review ────────────────────────────────────────────────────────
def test_a_fresh_reply_meta_rejects_is_not_settled_as_answered(monkeypatch):
    w = World(monkeypatch)
    w.model, w.answer = "up", "It is KES 45,000."
    w.reject_sends = 1
    w.says("c1", "How much is the cassock?")               # written, and Meta refuses the post
    assert w.public == [] and w.saved == []                # nothing shown in the inbox as sent
    assert w.state("c1") == ledger.OWED and w.rows["c1"]["reply"]["reason"] == cc.SEND
    assert w.followups[-1]["state"] == cc.WAITING          # visible, and Neema's to answer
    w.age()
    assert w.sweep() == 1                                  # the next pass answers it
    assert w.public == [("c1", "It is KES 45,000.")] and w.state("c1") == ledger.RESOLVED
    assert w.saved == [("c1", "It is KES 45,000.", None)]


def test_a_fresh_reply_that_times_out_goes_to_verify_not_to_a_retry(monkeypatch):
    from app.services.messaging import SendOutcomeUnknown
    w = World(monkeypatch)
    w.model, w.answer = "up", "It is KES 45,000."
    w.send_error = SendOutcomeUnknown("ReadTimeout: reply to comment outcome unknown")
    w.says("c1", "How much is the cassock?")
    assert w.state("c1") == ledger.VERIFY and "check the thread" in w.rows["c1"]["reply"]["why"]
    assert w.saved == [("c1", "It is KES 45,000.", {"v": 1, "delivery": "unknown"})]   # shown as unconfirmed
    assert w.followups[-1]["state"] == cc.STAFF and w.followups[-1]["ring"] is True
    w.age()
    turns = len(w.turns)
    assert w.sweep() == 0 and len(w.turns) == turns and w.public == []        # nobody posts another


def test_a_canned_reply_meta_rejects_stays_owed_too(monkeypatch):
    shoe = {"name": "Clergy Oxford Shoe", "source": "caption", "confidence": 1.0,
            "price_kes": 4500, "price_usd": 35, "slug": "clergy-oxford-shoe", "product_type": "simple"}
    w = World(monkeypatch, identity=shoe)
    w.reject_sends = 1
    w.says("c1", "How much?", caption="Clergy Oxford Shoe, in stock")
    assert w.public == [] and w.state("c1") == ledger.OWED and w.rows["c1"]["reply"]["reason"] == cc.SEND


def test_the_sweep_reads_its_batch_only_after_it_holds_the_claim(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.model, w.answer = "up", "KES 45,000, and yes in purple."
    w.age()
    real = cc.claim_answer

    fired = []

    async def claim(redis, key):
        # the live handler answers c1 (with a new comment) just before the sweep's claim lands
        if not fired:
            fired.append(1)
            await rt._engage_and_settle(w.r, "facebook", w.record("c2", "Is it made in purple?"), {"PAGE"})
        return await real(redis, key)
    monkeypatch.setattr(cc, "claim_answer", claim)
    turns_before = len(w.turns)
    w.sweep()
    assert [cid for cid, _t in w.public] == ["c1", "c2"]   # the holding line, then ONE answer — no second
    assert len(w.turns) == turns_before + 1                # the sweep made no call for the answered batch
    assert w.state("c1") == ledger.RESOLVED and w.state("c2") == ledger.RESOLVED


def test_the_claim_is_held_until_the_outcome_is_recorded(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.model = "up"
    w.age()
    seen = []
    real_resolve = cc.resolve

    async def resolve(redis, key, ids, by="neema"):
        seen.append(bool(await redis.get("comment:catchup:claim:" + key)))   # still claimed while recording
        return await real_resolve(redis, key, ids, by=by)
    monkeypatch.setattr(cc, "resolve", resolve)
    w.sweep()
    assert seen == [True] and "comment:catchup:claim:" + KEY not in w.r.kv    # and released after


def test_a_new_question_stays_pending_and_a_staff_question_stays_with_staff(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")               # owed (the model failed)
    w.over_cap = True
    w.says("c2", "Can I pay in instalments?")              # a limit: a colleague's from the start
    assert w.state("c2") == ledger.STAFF
    w.over_cap, w.model = False, "up"
    w.age()

    async def arrives():
        w.during_turn = None
        await cc.keep(w.r, "facebook", w.record("c9", "And the stole?"), {"PAGE"}, cc.MODEL)
    w.during_turn = arrives
    w.sweep()
    assert w.turns[-1]["user_text"] == "How much is the cassock?"       # only what Neema owed
    assert w.state("c1") == ledger.RESOLVED
    assert w.state("c2") == ledger.STAFF                   # the colleague's question is still theirs
    assert w.state("c9") == ledger.OWED                    # the new one is still pending
    assert w.followups[-1]["texts"] == ["Can I pay in instalments?", "And the stole?"]


def test_a_staff_reply_goes_under_the_comment_staff_selected(monkeypatch):
    import types
    from app.services import conversation as cs, meta_send
    sent_to = []

    async def reply_to_comment(cid, t, channel=None, page_id=None):
        sent_to.append(cid)

    async def latest_inbound(db, conv_id):                 # a NEWER comment exists
        return types.SimpleNamespace(waba_msg_id="c-new", comment_context={"post_id": "p1"})

    async def window(db, conv):
        return {"mode": "closed"}
    monkeypatch.setattr(meta_send, "reply_to_comment", reply_to_comment)
    monkeypatch.setattr(cs, "_latest_inbound", latest_inbound)
    monkeypatch.setattr(cs, "messaging_window", window)
    conv = types.SimpleNamespace(id="k", channel="facebook", external_id="u1", wa_id=None)
    chosen = types.SimpleNamespace(waba_msg_id="c-old", direction=types.SimpleNamespace(value="inbound"),
                                   comment_context={"post_id": "p1"})
    asyncio.run(cs._deliver_agent_reply(None, conv, "It is KES 45,000.", quoted=chosen))
    assert sent_to == ["c-old"] and conv._replied_comment_id == "c-old"       # posted AND resolved by that id
    # with nothing selected, the latest comment, as before
    conv2 = types.SimpleNamespace(id="k", channel="facebook", external_id="u1", wa_id=None)
    asyncio.run(cs._deliver_agent_reply(None, conv2, "Hello"))
    assert sent_to[-1] == "c-new" and conv2._replied_comment_id == "c-new"
    # one of OUR messages selected is not a comment to reply under
    ours = types.SimpleNamespace(waba_msg_id="m1", direction=types.SimpleNamespace(value="outbound"),
                                 comment_context={"reply_to": "c-old"})
    conv3 = types.SimpleNamespace(id="k", channel="facebook", external_id="u1", wa_id=None)
    asyncio.run(cs._deliver_agent_reply(None, conv3, "Hello", quoted=ours))
    assert sent_to[-1] == "c-new"


def test_a_holding_line_is_not_sent_under_a_comment_deleted_after_it_was_loaded(monkeypatch):
    w = World(monkeypatch)                                 # the model is down
    w.reject_sends = 1
    w.says("c1", "How much is the cassock?")               # the first holding line was refused
    w.age()
    real = ledger.existing

    async def existing(channel, ext, ids):
        w.rows.pop("c1", None)                             # deleted after the worker loaded it …
        return await real(channel, ext, ids)
    monkeypatch.setattr(ledger, "existing", existing)
    w.sweep()
    assert w.public == []                                  # … so nothing reaches Meta
    assert "comment:hold_said:" + KEY not in w.r.kv and "comment:hold_claim:" + KEY not in w.r.kv


def test_a_backlog_waiting_in_the_old_queue_is_adopted_at_rollout(monkeypatch):
    import time
    w = World(monkeypatch)
    w.model, w.answer = "up", "KES 45,000, by DHL."
    now = time.time()
    for cid, text in (("c1", "How much is the cassock?"), ("c2", "Do you deliver to Tarime?")):
        w.record(cid, text)
        w.rows[cid]["reply"] = None                        # saved before the state existed
    w.record("c3", "Can I pay later?")
    w.rows["c3"]["reply"] = None
    q = "comment:catchup:q:" + KEY
    w.r.lists[q] = [json.dumps({"at": now - 900, "cid": "c1", "reason": "model", "own_pages": ["PAGE"],
                                "post_id": "p1", "page_id": "PAGE", "parent_id": None}),
                    json.dumps({"at": now - 800, "cid": "c2", "reason": "model", "own_pages": ["PAGE"],
                                "post_id": "p1", "page_id": "PAGE", "parent_id": None}),
                    json.dumps({"at": now - 700, "cid": "c3", "reason": "cap", "own_pages": ["PAGE"],
                                "post_id": "p1", "page_id": "PAGE", "parent_id": None})]
    w.r.sets["comment:catchup:index"] = {KEY}
    w.age()
    assert w.sweep() == 1
    assert w.turns[-1]["user_text"].count("How much is the cassock?") == 1
    assert "Do you deliver to Tarime?" in w.turns[-1]["user_text"]
    assert w.public == [("c2", "KES 45,000, by DHL.")]
    assert w.state("c1") == ledger.RESOLVED and w.state("c2") == ledger.RESOLVED
    assert w.state("c3") == ledger.STAFF                   # a limit: it was, and stays, a colleague's
    assert w.r.lists.get(q, []) == [] and KEY not in w.r.sets["comment:catchup:index"]   # the old queue is retired
    assert asyncio.run(cc.adopt_old_queue(w.r)) == 0       # and adopting again changes nothing


def test_a_comment_saved_without_post_context_is_still_recovered(monkeypatch):
    w = World(monkeypatch)
    w.model, w.answer = "up", "It is KES 45,000."
    w.record("c1", "How much is the cassock?")
    w.rows["c1"]["post_context"] = {}                      # the post lookup failed at the webhook
    assert w.rows["c1"]["reply"]["post_id"] == "p1"        # the webhook's own id is on the state
    w.age()
    assert w.sweep() == 1
    assert w.public == [("c1", "It is KES 45,000.")] and w.state("c1") == ledger.RESOLVED

"""One holding line, then one answer (owner, 2026-11-25) — driven through the
real comment handler, with Meta's sends, the model and the database faked."""
import asyncio
import json

import app.agent.runtime as rt
from app.core.config import settings
from app.services import comment_catchup as cc

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
    """Everything outside the handler, in one place the tests can steer."""

    def __init__(self, monkeypatch, *, identity=None):
        import app.database as dbmod
        import app.services.agent_health as ah
        from app.services import meta_send, messaging, post_catalog
        self.r = _Redis()
        self.public, self.liked, self.turns, self.followups, self.human, self.noted = [], [], [], [], [], []
        self.model = "down"            # "down" | "up" | "held"
        self.answer = "Here is your answer."
        self.reject_sends = 0          # how many of the next public sends Meta refuses
        self.over_cap = False
        self.records = {}              # the database's comments, by id
        self.staff_ids = set()         # comment ids a colleague replied under
        self.send_error = None         # raised by the next public send, once
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

        async def staff_ids(channel, ext, ids):
            return set(w.staff_ids) & {str(i) for i in ids}

        async def load_records(channel, ext, ids):
            return {str(i): dict(w.records[str(i)]) for i in ids if str(i) in w.records}

        async def followup(redis, channel, ext, key, items, state, why=""):
            w.followups.append({"state": state, "why": why,
                                "texts": [i["comment"]["text"] for i in items]})
            return "updated"

        async def ai_down(redis):
            return "credit" if w.model == "down" else None

        monkeypatch.setattr(settings, "meta_comment_like", True, raising=False)
        monkeypatch.setattr(dbmod, "AsyncSessionLocal", lambda: _DB())
        monkeypatch.setattr(meta_send, "reply_to_comment", reply_to_comment)
        monkeypatch.setattr(meta_send, "send_private_reply", none)
        monkeypatch.setattr(meta_send, "like_comment", like_comment)
        monkeypatch.setattr(messaging, "save_outbound_channel_message", none)
        monkeypatch.setattr(post_catalog, "identity_trusted",
                            lambda rec: bool((rec or {}).get("name")) and (rec or {}).get("source") == "caption")
        monkeypatch.setattr(ah, "ai_down", ai_down)
        monkeypatch.setattr(ah, "record_turn_failure", none)
        monkeypatch.setattr(cc, "followup", followup)
        monkeypatch.setattr(cc, "load_records", load_records)
        monkeypatch.setattr(asyncio, "sleep", none)
        for n, f in (("read_comment", read_comment), ("run_turn", run_turn),
                     ("_route_comment_to_human", route_human), ("_note_silent_decision", note_silent),
                     ("_recall_post_product", recall), ("_resolve_post_product", resolve),
                     ("_remember_post_product", none), ("_storefront_product_link", none),
                     ("_post_over_cap", over), ("_person_over_cap", false), ("_first_contact", false),
                     ("_meta_market", market), ("_thread_parent", thread_parent),
                     ("_private_complaint_message", false), ("_staff_replied_ids", staff_ids)):
            monkeypatch.setattr(rt, n, f)
        monkeypatch.setattr(rt, "build_llm", lambda model=None, **kw: object())

    def comment(self, cid, text, caption="Vesting cassock with stole and chasuble"):
        return {"comment_id": cid, "from_id": "u1", "from_name": "Ruben Matacha", "text": text,
                "post_id": "p1", "page_id": "PAGE",
                "post_context": {"post_id": "p1", "title": caption, "caption": caption, "thumb": ""}}

    def record(self, cid, text, **kw):
        """The webhook stored this comment before the handler ran."""
        c = self.comment(cid, text, **kw)
        self.records[cid] = {"text": text, "post_context": c["post_context"]}
        return c

    def says(self, cid, text, **kw):
        asyncio.run(rt._run_comment_engage(self.r, "facebook", self.record(cid, text, **kw), {"PAGE"}))

    def age(self, seconds=600):
        """Make every kept comment old enough for the sweep to look at it."""
        q = "comment:catchup:q:" + KEY
        self.r.lists[q] = [json.dumps(dict(json.loads(x), at=json.loads(x)["at"] - seconds))
                           for x in self.r.lists.get(q, [])]

    def sweep(self):
        self.r.kv.pop("comment:catchup:backoff:" + KEY, None)   # the next pass, ten minutes on
        return asyncio.run(cc.sweep(self.r))

    def waiting(self):
        return [i["comment"]["text"] for i in asyncio.run(cc.waiting(self.r, KEY))]


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
    # the same person, waiting under ANOTHER post as well
    other = dict(w.record("x1", "Is the chalice in stock?"), post_id="p2")
    asyncio.run(cc.keep(w.r, "facebook", other, {"PAGE"}, cc.MODEL))
    # a colleague replies under c1 (services/conversation.send_agent_reply → staff_replied)
    assert asyncio.run(cc.staff_replied(w.r, "facebook", "u1", "c1")) is True
    assert w.waiting() == ["Do you deliver to Tarime?"]                # c2 still owed
    assert len(asyncio.run(cc.waiting_ids(w.r, "facebook:p2:u1"))) == 1   # the other post untouched
    assert w.followups[-1]["state"] == cc.WAITING and w.followups[-1]["texts"] == ["Do you deliver to Tarime?"]
    w.model, w.answer = "up", "Yes, we deliver to Tarime by DHL."
    w.age()
    w.sweep()
    assert w.turns[-1]["user_text"] == "Do you deliver to Tarime?"       # only what is still owed
    assert w.public[-1] == ("c2", "Yes, we deliver to Tarime by DHL.") and w.waiting() == []
    # a reply to a comment that was not waiting changes nothing
    assert asyncio.run(cc.staff_replied(w.r, "facebook", "u1", "zzz")) is False


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
    sent: dict = {}
    asyncio.run(cs._deliver_agent_reply(None, conv, "It is KES 45,000.", sent=sent))
    assert sent_to == ["c7"] and sent == {"comment_id": "c7"}
    src = inspect.getsource(cs.send_agent_reply)
    assert 'comment_context=({"reply_to": _sent["comment_id"]} if _sent.get("comment_id") else None)' in src
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


def test_three_failed_tries_hand_it_to_staff(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.age()

    async def not_down(redis):
        return None
    import app.services.agent_health as ah
    monkeypatch.setattr(ah, "ai_down", not_down)           # health says up, yet the call still fails
    for _ in range(3):
        w.sweep()
    assert w.followups[-1]["state"] == cc.STAFF and "three tries" in w.followups[-1]["why"]
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
def _item(cid, text, at, reason=cc.MODEL):
    return {"at": at, "cid": cid, "reason": reason, "own_pages": ["PAGE"],
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
    assert old["expired"] == ["c1"] and old["answer"] is None
    assert cc.plan([_item("c1", "x", now - 500, cc.CAP)], now=now)["answer"] is None            # a cap: staff's
    assert cc.plan(items, now=now, staff_cut=now - 100)["answer"] is None                       # handed to staff
    mixed = cc.plan([_item("c1", "a", now - 900, cc.CAP), _item("c2", "b", now - 500)], now=now)
    assert mixed["answer"]["comment"]["catch_up"] == ["a", "b"]                 # one answer covers all


def test_only_ids_are_kept_and_words_come_from_the_database():
    items = [{"at": 1, "cid": "c1", "reason": cc.MODEL, "post_id": "p1", "page_id": "PAGE", "own_pages": ["PAGE"]},
             {"at": 2, "cid": "c2", "reason": cc.MODEL, "post_id": "p1", "page_id": "PAGE", "own_pages": ["PAGE"]}]
    live, gone = cc.hydrate("facebook", "u1", items, {"c1": {"text": "How much?", "post_context": {"post_id": "p1"}}})
    assert gone == ["c2"] and [i["comment"]["text"] for i in live] == ["How much?"]
    assert live[0]["comment"]["comment_id"] == "c1" and live[0]["comment"]["from_id"] == "u1"
    assert "from_name" not in live[0]["comment"]


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


# ── the second review's four failures ────────────────────────────────────────
def test_nothing_a_customer_wrote_is_stored_in_the_queue(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "Hiyo nguo ni sh. Ngapi")
    w.says("c2", "Nipo Tanzania Tarime")
    blob = json.dumps([w.r.kv, w.r.lists, [sorted(v) for v in w.r.sets.values()]], default=str)
    assert "Ngapi" not in blob and "Tarime" not in blob and "Ruben" not in blob
    assert [i["cid"] for i in asyncio.run(cc.waiting_ids(w.r, KEY))] == ["c1", "c2"]
    assert set(asyncio.run(cc.waiting_ids(w.r, KEY))[0]) == {
        "at", "cid", "reason", "own_pages", "post_id", "page_id", "parent_id"}


def test_a_comment_deleted_while_it_waits_is_never_answered(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.says("c2", "Do you deliver to Tarime?")
    w.model = "up"
    w.age()
    del w.records["c1"]                                    # a data-deletion request removed it
    w.sweep()
    assert w.turns[-1]["user_text"] == "Do you deliver to Tarime?"      # only what still exists is read
    assert [i["cid"] for i in asyncio.run(cc.waiting_ids(w.r, KEY))] == []
    w2 = World(monkeypatch)
    w2.says("c1", "How much is the cassock?")
    w2.model = "up"
    w2.age()
    w2.records.clear()                                     # everything they wrote is gone
    turns, public = len(w2.turns), len(w2.public)
    w2.sweep()
    assert len(w2.turns) == turns and len(w2.public) == public          # no call, no reply
    assert asyncio.run(cc.waiting_ids(w2.r, KEY)) == [] and KEY not in w2.r.sets.get("comment:catchup:index", set())


def test_a_comment_deleted_while_the_reply_is_composed_is_not_answered(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    w.says("c2", "Do you deliver to Tarime?")
    w.model = "up"
    w.age()

    async def deletion():
        w.during_turn = None
        del w.records["c1"]
    w.during_turn = deletion
    public = len(w.public)
    w.sweep()
    assert len(w.public) == public                         # the reply that read c1 is not posted
    assert w.waiting() == ["Do you deliver to Tarime?"]
    w.sweep()
    assert w.turns[-1]["user_text"] == "Do you deliver to Tarime?" and w.public[-1][0] == "c2"


def test_a_comment_arriving_between_the_read_and_the_cleanup_is_not_lost(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    real, fired = w.r.lrange, []

    async def lrange(k, a, b):
        rows = await real(k, a, b)
        if not fired:                                      # the worker has read the queue …
            fired.append(1)
            await cc.keep(w.r, "facebook", w.record("c9", "And the stole?"), {"PAGE"}, cc.MODEL)
        return rows                                        # … and a comment arrives before it cleans up
    w.r.lrange = lrange
    left = asyncio.run(cc.resolve(w.r, KEY, ["c1"]))
    w.r.lrange = real
    assert left == 1 and w.waiting() == ["And the stole?"]
    assert KEY in w.r.sets["comment:catchup:index"]        # and the sweep will still find it


def test_a_comment_arriving_after_the_count_keeps_its_place_in_the_index(monkeypatch):
    w = World(monkeypatch)
    w.says("c1", "How much is the cassock?")
    real, n = w.r.llen, []

    async def llen(k):
        v = await real(k)
        n.append(1)
        if len(n) == 1:                                    # counted empty, then one arrives
            await cc.keep(w.r, "facebook", w.record("c9", "And the stole?"), {"PAGE"}, cc.MODEL)
        return v
    w.r.llen = llen
    asyncio.run(cc.resolve(w.r, KEY, ["c1"]))
    w.r.llen = real
    assert w.waiting() == ["And the stole?"] and KEY in w.r.sets["comment:catchup:index"]


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

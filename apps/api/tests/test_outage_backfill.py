"""The comments a credit outage left with a set reply (owner, 2026-11-26)."""
from app.services import outage_backfill as ob

NOW = ob.CUTOFF.timestamp() + 1800          # half an hour after the reply state went live
H = 3600.0


def _in(cid, at, post="p1", has_state=False):
    return {"dir": "inbound", "sender": "user", "cid": cid, "post": post, "text": "x",
            "at": NOW - at, "has_state": has_state}


def _out(reply_to, text, at, sender="ai", note=False):
    return {"dir": "outbound", "sender": sender, "reply_to": reply_to, "text": text,
            "at": NOW - at, "note": note}


SET_EN = "Thank you for reaching out Afia 🙏 One of our team will come back to you right here shortly."
SET_SW = "Mungu akubariki Ruben! 🙏 Tunayo Cassock + Double sided stole + Chasuble — tutumie ujumbe na tutashughulikia maelezo na usafirishaji 💛"
REAL = "The full set is KES 45,000, Mchungaji, and we deliver to Tarime by DHL. Which colour would you like?"


def test_the_set_lines_are_recognised_and_a_real_answer_is_not():
    assert ob.is_set_reply(SET_EN) and ob.is_set_reply(SET_SW)
    assert ob.is_set_reply("Thank you 🙏 We're here — one of us will reply to you right here.")
    assert ob.is_set_reply("Thank you John 🙏 Noted: more designs for ladies. One of our team will "
                           "send you the options right here shortly.")
    assert ob.is_set_reply("Asante Ruben 🙏 Swali zuri — mmoja wa timu yetu atakujibu hapa hivi karibuni.")
    assert not ob.is_set_reply(REAL)
    assert not ob.is_set_reply("Thank you John 🙏 The Clergy Oxford Shoe is KES 4,500, and we ship worldwide by DHL.")
    assert not ob.is_set_reply("")


def test_rubens_four_set_replies_become_one_thing_to_answer():
    rows = []
    for n, at in enumerate((10 * H, 9.9 * H, 9.8 * H, 9.7 * H), 1):
        rows += [_in(f"c{n}", at), _out(f"c{n}", SET_SW, at - 30)]
    s = ob.select(rows, now=NOW)
    assert s["adopt"] == {"p1": ["c1", "c2", "c3", "c4"]}      # every comment, one post: ONE reply later


def test_a_later_comment_that_was_only_liked_is_gathered_too():
    rows = [_in("c1", 9 * H), _out("c1", SET_EN, 9 * H - 20), _in("c2", 8 * H)]     # c2: no words back at all
    assert ob.select(rows, now=NOW)["adopt"] == {"p1": ["c1", "c2"]}
    # a comment with no reply and NO set reply near it is not the outage's: left to the ordinary path
    assert ob.select([_in("c1", 9 * H)], now=NOW)["adopt"] == {}


def test_someone_already_attended_to_is_left_alone():
    base = [_in("c1", 9 * H), _out("c1", SET_EN, 9 * H - 20)]
    staff = base + [_out(None, "Hello, the set is KES 45,000.", 6 * H, sender="human_agent")]
    s = ob.select(staff, now=NOW)
    assert s["adopt"] == {} and s["skipped"]["a_colleague_replied_since"] == 1
    answered = base + [_in("c2", 5 * H), _out("c2", REAL, 5 * H - 20)]
    s = ob.select(answered, now=NOW)
    assert s["adopt"] == {} and s["skipped"]["neema_answered_since"] == 1
    # a colleague's INTERNAL note is not a reply to the customer
    noted = base + [_out(None, "note: call him", 6 * H, sender="human_agent", note=True)]
    assert ob.select(noted, now=NOW)["adopt"] == {"p1": ["c1"]}
    # an answer under ANOTHER post does not settle this one
    other = base + [_in("x1", 5 * H, post="p2"), _out("x1", REAL, 5 * H - 20)]
    assert ob.select(other, now=NOW)["adopt"] == {"p1": ["c1"]}


def test_only_what_is_still_inside_the_window_and_before_the_cutoff():
    old = [_in("c1", 30 * H), _out("c1", SET_EN, 30 * H - 20)]
    s = ob.select(old, now=NOW)
    assert s["adopt"] == {} and s["skipped"]["older_than_the_window"] == 1
    mixed = old + [_in("c2", 20 * H), _out("c2", SET_EN, 20 * H - 20)]
    assert ob.select(mixed, now=NOW)["adopt"] == {"p1": ["c2"]}            # the one still in the window
    # a comment saved after the reply state went live carries its own state: never adopted here
    live = [_in("c1", 9 * H), _out("c1", SET_EN, 9 * H - 20), _in("c2", 600, has_state=True)]
    assert ob.select(live, now=NOW)["adopt"] == {"p1": ["c1"]}
    after = [_in("c1", -600), _out("c1", SET_EN, -620)]                    # saved after the cutoff
    assert ob.select(after, now=NOW + 3600)["adopt"] == {}


def test_the_backfill_stops_by_itself(monkeypatch):
    import asyncio
    from datetime import datetime as real_dt, timedelta

    class Later(real_dt):
        @classmethod
        def now(cls, tz=None):
            return ob.CUTOFF + timedelta(hours=27)
    called = []

    async def find(now=None):
        called.append(1)
        return {"keys": [], "skipped": {}}
    monkeypatch.setattr(ob, "datetime", Later)
    monkeypatch.setattr(ob, "find", find)
    assert asyncio.run(ob.adopt(None)) == 0 and called == []

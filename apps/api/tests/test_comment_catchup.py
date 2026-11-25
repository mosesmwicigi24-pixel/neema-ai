"""One holding line, then one answer (owner, 2026-11-25)."""
import asyncio
import json

from app.services import comment_catchup as cc


class _Redis:
    def __init__(self):
        self.kv, self.lists, self.sets = {}, {}, {}

    async def set(self, k, v, nx=False, ex=None):
        if nx and k in self.kv:
            return None
        self.kv[k] = v
        return True

    async def get(self, k):
        return self.kv.get(k)

    async def rpush(self, k, v):
        self.lists.setdefault(k, []).append(v)

    async def expire(self, k, s):
        return True

    async def sadd(self, k, v):
        self.sets.setdefault(k, set()).add(v)

    async def srem(self, k, v):
        self.sets.get(k, set()).discard(v)

    async def smembers(self, k):
        return set(self.sets.get(k, set()))

    async def lrange(self, k, a, b):
        return list(self.lists.get(k, []))

    async def delete(self, *ks):
        for k in ks:
            self.kv.pop(k, None)
            self.lists.pop(k, None)


def _c(cid, text):
    return {"comment_id": cid, "from_id": "p1", "post_id": "post9", "text": text, "from_name": "Ruben M"}


def test_the_holding_line_is_said_once_per_person_per_post():
    r = _Redis()

    async def go():
        assert await cc.first_hold(r, "facebook", "post9", "p1") is True
        assert await cc.first_hold(r, "facebook", "post9", "p1") is False
        assert await cc.first_hold(r, "facebook", "post9", "p2") is True      # another person
        assert await cc.first_hold(r, "facebook", "post8", "p1") is True      # another post
        await cc.clear(r, "facebook", "post9", "p1")                          # answered
        assert await cc.first_hold(r, "facebook", "post9", "p1") is True
        assert await cc.first_hold(None, "facebook", "post9", "p1") is True   # no redis: as before
    asyncio.run(go())


def test_everything_they_wrote_becomes_one_comment_to_answer():
    now = 1_000_000.0
    items = [{"at": now - 3000, "own_pages": ["pg"], "comment": _c("c1", "Hiyo nguo ni sh. Ngapi")},
             {"at": now - 2900, "own_pages": ["pg"], "comment": _c("c2", "Nipo Tanzania Tarime")},
             {"at": now - 2800, "own_pages": ["pg"], "comment": _c("c3", "hiyo nguo ni sh.  ngapi")},
             {"at": now - 200, "own_pages": ["pg"], "comment": _c("c4", "Nataka hizo nguo")}]
    one = cc.combine(items, now)
    assert one["comment"]["comment_id"] == "c4"            # answered under their latest comment
    assert one["comment"]["catch_up"] == ["Hiyo nguo ni sh. Ngapi", "Nipo Tanzania Tarime", "Nataka hizo nguo"]
    assert one["own_pages"] == {"pg"}
    prompt = cc.catch_up_prompt(one["comment"]["catch_up"])
    assert "ONE reply" in prompt and "3. Nataka hizo nguo" in prompt
    assert cc.catch_up_prompt(["How much?"]) == "How much?"


def test_too_fresh_or_older_than_a_day_is_not_answered():
    now = 1_000_000.0
    assert cc.combine([{"at": now - 10, "comment": _c("c1", "price?")}], now) is None
    assert cc.combine([{"at": now - cc.WINDOW_S - 5, "comment": _c("c1", "price?")}], now) is None
    kept = cc.combine([{"at": now - cc.WINDOW_S - 5, "comment": _c("c1", "old")},
                       {"at": now - 500, "comment": _c("c2", "new")}], now)
    assert kept["comment"]["catch_up"] == ["new"]


def test_the_sweep_waits_while_the_model_is_down_then_answers_once(monkeypatch):
    r = _Redis()
    calls = []

    async def engage(redis, channel, comment, own_pages):
        calls.append((channel, comment["comment_id"], comment["catch_up"]))
        await cc.clear(redis, channel, "post9", "p1")

    down = {"v": "credit"}

    async def ai_down(redis):
        return down["v"]

    import app.agent.runtime as rt
    import app.services.agent_health as ah
    monkeypatch.setattr(rt, "_run_comment_engage", engage)
    monkeypatch.setattr(ah, "ai_down", ai_down)

    async def go():
        await cc.keep(r, "facebook", _c("c1", "How much is the cassock"), {"pg"})
        await cc.keep(r, "facebook", _c("c2", "I am in Tarime"), {"pg"})
        for row in r.lists["comment:catchup:q:facebook:post9:p1"]:
            assert "catch_up" not in json.loads(row)["comment"]
        r.lists["comment:catchup:q:facebook:post9:p1"] = [
            json.dumps(dict(json.loads(x), at=json.loads(x)["at"] - 600))
            for x in r.lists["comment:catchup:q:facebook:post9:p1"]]
        assert await cc.sweep(r) == 0 and calls == []          # out of credit: wait
        down["v"] = None
        assert await cc.sweep(r) == 1
        assert calls == [("facebook", "c2", ["How much is the cassock", "I am in Tarime"])]
        assert await cc.sweep(r) == 0                          # answered once, not again
    asyncio.run(go())


def test_a_hold_line_that_is_our_last_word_is_not_said_again():
    from app.agent.runtime import hold_line_stands
    assert hold_line_stands(["hold_line"]) is True
    assert hold_line_stands([None]) is False                   # we answered since
    assert hold_line_stands([]) is False

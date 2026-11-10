// A human reply showed as two bubbles until refresh (owner, 2026-11-09): the
// optimistic bubble was never retired when the saved row arrived.
// Run: node --test apps/web/tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { mergeThread, retireOptimistic, isOptimistic } from "../src/lib/thread.ts";

const opt = (n, text, at = "2026-11-09T20:00:05.000Z") =>
    ({ id: `optimistic-${n}`, direction: "outbound", sender: "human_agent", text, created_at: at });
const real = (id, text, at = "2026-11-09T20:00:06.000Z", direction = "outbound") =>
    ({ id, direction, sender: "human_agent", text, created_at: at });
const old = real("m1", "Hello", "2026-11-09T19:00:00.000Z", "inbound");

test("the refetch after a send leaves one bubble, the saved one", () => {
    const out = mergeThread([old, opt(1, "We deliver tomorrow")], [old, real("m2", "We deliver tomorrow")]);
    assert.deepEqual(out.map((m) => m.id), ["m1", "m2"]);
});

test("the live event retires the optimistic bubble; the refetch then adds nothing", () => {
    const live = real("m2", "We deliver tomorrow ");            // the server trimmed or padded it
    const afterEvent = [...retireOptimistic([old, opt(1, "We deliver tomorrow")], [live]), live];
    assert.deepEqual(afterEvent.map((m) => m.id), ["m1", "m2"]);
    assert.deepEqual(mergeThread(afterEvent, [old, live]).map((m) => m.id), ["m1", "m2"]);
});

test("a second reply still on its way keeps its bubble", () => {
    const out = mergeThread([old, opt(1, "One"), opt(2, "Two", "2026-11-09T20:00:07.000Z")], [real("m2", "One")]);
    assert.deepEqual(out.map((m) => m.id), ["m1", "m2", "optimistic-2"]);
});

test("two identical quick replies stay two", () => {
    const start = [opt(1, "Okay"), opt(2, "Okay", "2026-11-09T20:00:07.000Z")];
    const first = mergeThread(start, [real("m2", "Okay")]);
    assert.equal(first.filter(isOptimistic).length, 1);
    const second = mergeThread(first, [real("m2", "Okay"), real("m3", "Okay", "2026-11-09T20:00:08.000Z")]);
    assert.deepEqual(second.map((m) => m.id), ["m2", "m3"]);
});

test("an earlier identical message already on screen retires nothing", () => {
    const earlier = real("m0", "Okay", "2026-11-09T18:00:00.000Z");
    const out = mergeThread([earlier, opt(1, "Okay")], [earlier]);          // a poll that has not seen the new row yet
    assert.deepEqual(out.map((m) => m.id), ["m0", "optimistic-1"]);
});

test("the customer's own words never retire a team bubble; empty text retires nothing", () => {
    const list = [opt(1, "Okay"), opt(2, "")];
    assert.equal(retireOptimistic(list, [real("m5", "Okay", undefined, "inbound")]), list);
    assert.equal(retireOptimistic(list, [real("m6", "")]).length, 2);
});

test("with no optimistic bubble the merge is the plain union by id, in time order", () => {
    const out = mergeThread([real("b", "2", "2026-11-09T20:00:02Z")], [real("a", "1", "2026-11-09T20:00:01Z"), real("b", "2 edited", "2026-11-09T20:00:02Z")]);
    assert.deepEqual(out.map((m) => [m.id, m.text]), [["a", "1"], ["b", "2 edited"]]);
});

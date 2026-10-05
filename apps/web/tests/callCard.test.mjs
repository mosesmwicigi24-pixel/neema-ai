// Cycle 3 (2026-10-05): every call in the conversation reads as a card —
// direction, outcome, who took it, when, how long, and "Call back" only when
// the customer is owed one and the app can place it.
// Run: node --test apps/web/tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { callCardView, canCallBack, actionItems, fmtDuration, whenText, transcriptSlot, mediaSrc, callBackHandle, nearestCallId }
    from "../src/lib/callCard.ts";

const call = (o) => ({ status: "completed", direction: "inbound", agent_name: null, duration: null,
    channel: "whatsapp", follow_up_open: false, follow_up_done_at: null, wa_id: "254700111222",
    external_id: "254700111222", ...o });

test("1 inbound answered: who took it and for how long", () => {
    const v = callCardView(call({ agent_name: "Everlyne Achieng", duration: 76 }));
    assert.deepEqual([v.title, v.outcome, v.who, v.duration, v.tone], ["Incoming call", "Answered", "Answered by Everlyne", "1:16", "good"]);
});

test("2 inbound missed: owed, no one took it, call back offered on WhatsApp", () => {
    const c = call({ status: "missed", follow_up_open: true });
    const v = callCardView(c);
    assert.deepEqual([v.title, v.outcome, v.who, v.owed, v.duration], ["Missed call", "Missed", null, true, null]);
    assert.equal(canCallBack(c, false), true);
});

test("3 missed but already returned: no button, says returned", () => {
    const c = call({ status: "missed", follow_up_open: false, follow_up_done_at: "2026-10-05T10:00:00Z" });
    assert.equal(callCardView(c).returned, true);
    assert.equal(canCallBack(c, true), false);
});

test("4 callback requested by an agent", () => {
    const v = callCardView(call({ status: "callback", agent_name: "Ann W", follow_up_open: true }));
    assert.deepEqual([v.outcome, v.who, v.owed], ["Callback requested", "Ann chose to call back", true]);
});

test("5 declined by an agent", () => {
    const v = callCardView(call({ status: "declined", agent_name: "Ben" }));
    assert.deepEqual([v.title, v.outcome, v.who], ["Incoming call", "Declined", "Declined by Ben"]);
});

test("6 outbound completed / no answer / declined by customer / failed", () => {
    assert.equal(callCardView(call({ direction: "outbound", agent_name: "Ben", duration: 182 })).who, "Called by Ben");
    assert.equal(callCardView(call({ direction: "outbound", agent_name: "Ben", duration: 182 })).duration, "3:02");
    assert.equal(callCardView(call({ direction: "outbound", status: "no_answer" })).outcome, "No answer");
    assert.equal(callCardView(call({ direction: "outbound", status: "rejected" })).outcome, "Declined by customer");
    assert.equal(callCardView(call({ direction: "outbound", status: "failed" })).outcome, "Didn't go through");
    // An outbound call nobody answered is not a follow-up the customer is owed.
    assert.equal(canCallBack(call({ direction: "outbound", status: "no_answer" }), true), false);
});

test("7 Messenger: badge, and call back only while Messenger can place calls", () => {
    const c = call({ status: "missed", channel: "messenger", wa_id: null, external_id: "6123456789012345", follow_up_open: true });
    assert.equal(callCardView(c).app, "Messenger");
    assert.equal(canCallBack(c, false), false);
    assert.equal(canCallBack(c, true), true);
    assert.equal(callBackHandle(c), "6123456789012345");
});

test("8 live calls pulse and owe nothing", () => {
    const r = callCardView(call({ status: "ringing" }));
    const a = callCardView(call({ status: "answered", agent_name: "Ann" }));
    assert.equal(r.live && a.live, true);
    assert.equal(a.who, "Answered by Ann");
    assert.equal(r.owed || a.owed, false);
});

test("9 legacy 'ended' reads as answered with its duration", () => {
    const v = callCardView(call({ status: "ended", duration: 3725 }));
    assert.deepEqual([v.outcome, v.duration], ["Answered", "1:02:05"]);
});

test("10 action items: future action_items win, else commitments; blanks dropped", () => {
    assert.deepEqual(actionItems({ action_items: ["Send the cope photo", " "], commitments: ["x"] }), ["Send the cope photo"]);
    assert.deepEqual(actionItems({ commitments: ["Deliver Friday"] }), ["Deliver Friday"]);
    assert.deepEqual(actionItems(null), []);
});

test("11 transcript slot states", () => {
    assert.equal(transcriptSlot("done"), "ready");
    assert.equal(transcriptSlot("processing"), "working");
    assert.equal(transcriptSlot("failed"), "failed");
    assert.equal(transcriptSlot("recorded"), "none");
});

test("12 when: clock today, waiting time for a missed call", () => {
    const now = new Date("2026-10-05T12:00:00").getTime();
    const at = new Date("2026-10-05T10:00:00").toISOString();
    assert.match(whenText(at, now, true), /· 2 h ago$/);
    assert.match(whenText(new Date("2026-10-04T09:30:00").toISOString(), now), /^Yesterday /);
    assert.equal(whenText(null), "");
});

test("13 recording src: absolute kept, bare file name under the API, anything else refused", () => {
    assert.equal(mediaSrc("https://neema.x/api/admin/media/call_ab.webm", "https://api"), "https://neema.x/api/admin/media/call_ab.webm");
    assert.equal(mediaSrc("call_ab.webm", "https://neema.x/api/"), "https://neema.x/api/admin/media/call_ab.webm");
    assert.equal(mediaSrc("../../etc/passwd", "https://api"), null);
    assert.equal(mediaSrc("", "https://api"), null);
});

test("14 durations", () => {
    assert.equal(fmtDuration(0), null);
    assert.equal(fmtDuration(9), "0:09");
});

test("15 a call notice folds into the nearest call within 15 minutes, else stays its own line", () => {
    const calls = [
        { call_id: "A", started_at: "2026-10-05T10:00:00Z", ended_at: "2026-10-05T10:01:16Z" },
        { call_id: "B", started_at: "2026-10-05T12:00:00Z", ended_at: null },
    ];
    assert.equal(nearestCallId("2026-10-05T10:03:00Z", calls), "A");    // just after A ended
    assert.equal(nearestCallId("2026-10-05T10:00:30Z", calls), "A");    // during A
    assert.equal(nearestCallId("2026-10-05T11:55:00Z", calls), "B");    // just before B rang
    assert.equal(nearestCallId("2026-10-05T11:00:00Z", calls), null);   // nowhere near a call
    assert.equal(nearestCallId(null, calls), null);
});

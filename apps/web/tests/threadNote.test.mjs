// The thread note (owner, 2026-11-15): notes were "too many and too long".
// Run: node --test apps/web/tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { noteKind, splitNotes, parseBrief, oneLine, barSummary, unseenCount, clip } from "../src/lib/threadNote.ts";

const at = (min) => new Date(Date.UTC(2026, 10, 15, 20, min)).toISOString();

// The texts below are the ones on Bayanda's thread in the owner's screenshots.
const briefNew = {
    id: "b2", sender: "human_agent", created_at: at(50),
    text: "🤝 Handoff briefing\n\nStatus: Cart $777, unpaid, no order created. 2 Golden Trays, 2 Gold Bread Trays…\n"
        + "Next: Quote DHL to Durban, give rand equivalent, get payment yes, then create order.\n"
        + "Avoid: Rand conversion is still unanswered.\nSay: Hello Bayanda, I'm taking over. Let me confirm your DHL cost to Durban.",
};
const briefOld = {
    id: "b1", sender: "human_agent", created_at: at(1),
    text: "🤝 Handoff briefing\n\n- Order settled: 2x Golden Communion Tray ($220 ea). Total = $777 USD.\n"
        + "- Customer (Bayanda, South Africa) asked for the ZAR equivalent — no rate.\n- Avoid: inventing an exchange rate.",
};
const returnedOld = {
    id: "r1", sender: "human_agent", created_at: at(10),
    text: "↩ Returned to Neema automatically — no colleague reply for 45 minutes, and Neema answered the customer’s last message, so nobody is left waiting. Neema will answer their next message; take the thread back any time.",
};
const returnedNew = {
    id: "r2", sender: "human_agent", created_at: at(20),
    text: "↩ Back to Neema — no colleague reply in 45 min; a colleague answered the customer's last message.",
};
const staff = { id: "s1", sender: "human_agent", agent_name: "Alex", created_at: at(30), text: "Customer prefers DHL.\nCall after 5pm." };
const unclaimed = { id: "u1", sender: "ai", created_at: at(40), text: "⏳ Unclaimed 20 min — only a person can answer this. Please pick it up." };

test("each note is read for what it is", () => {
    assert.equal(noteKind(briefNew), "brief");
    assert.equal(noteKind(briefOld), "brief");
    assert.equal(noteKind(returnedOld), "return");
    assert.equal(noteKind(returnedNew), "return");
    assert.equal(noteKind(staff), "staff");
    assert.equal(noteKind(unclaimed), "unclaimed");
    assert.equal(noteKind({ text: "Escalated: the customer asked for a call." }), "system");
});

test("only the newest briefing shows; everything else is history, newest first", () => {
    const { brief, history } = splitNotes([briefOld, returnedOld, returnedNew, staff, unclaimed, briefNew]);
    assert.equal(brief.id, "b2");
    assert.deepEqual(history.map((n) => n.id), ["u1", "s1", "r2", "r1"]);
    assert.deepEqual(splitNotes([]), { brief: null, history: [] });
});

test("a briefing reads as labelled rows, without the heading or markdown", () => {
    const rows = parseBrief(briefNew.text);
    assert.deepEqual(rows.map((r) => r.label), ["Status", "Next", "Avoid", "Say"]);
    assert.ok(rows[3].text.startsWith("Hello Bayanda"));
    const old = parseBrief(briefOld.text);
    assert.equal(old[0].label, "Order settled");
    assert.equal(old[1].label, "");                     // a label with brackets stays as text
    assert.equal(old[2].label, "Avoid");
    assert.deepEqual(parseBrief("**Status:** paid\n\n# x"), [{ label: "Status", text: "paid" }, { label: "", text: "x" }]);
    assert.deepEqual(parseBrief(null), []);
});

test("history lines are short and keep the facts", () => {
    assert.equal(oneLine(returnedOld), "Back to Neema after 45 min quiet — Neema answered the customer’s last message");
    assert.equal(oneLine(returnedNew), "Back to Neema after 45 min quiet — a colleague answered the customer's last message");
    assert.equal(oneLine(unclaimed), "Unclaimed 20 min — needs a person");
    assert.equal(oneLine(staff), "Customer prefers DHL. Call after 5pm.");
    assert.ok(oneLine({ text: "word ".repeat(80) }, 40).length <= 41);
});

test("the folded bar shows the team's note first, else the brief's status and next step", () => {
    assert.deepEqual(barSummary("  Paid —  ship Monday ", briefNew), { icon: "📌", text: "Paid — ship Monday" });
    const b = barSummary("", briefNew);
    assert.equal(b.icon, "🤝");
    assert.ok(b.text.startsWith("Cart $777, unpaid") && b.text.includes(" · Next: Quote DHL"));
    assert.equal(barSummary(null, null), null);
});

test("new notes are counted from the last time the note was opened, never on a first visit", () => {
    const all = [briefOld, returnedOld, staff, briefNew];
    assert.equal(unseenCount(all, null), 0);
    assert.equal(unseenCount(all, at(15)), 2);
    assert.equal(unseenCount(all, "garbage"), 0);
});

test("clip cuts on a word", () => {
    assert.equal(clip("one two three four", 9), "one two…");
    assert.equal(clip("short", 9), "short");
});

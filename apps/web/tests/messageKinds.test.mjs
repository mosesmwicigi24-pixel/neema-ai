// Cycle 2 (2026-10-05): every non-plain message kind renders as words a person
// reads; no row ever shows a bare "can't be displayed" warning again.
// Run: node --test apps/web/tests/   (Node ≥ 22.18 strips the .ts types itself)
import { test } from "node:test";
import assert from "node:assert/strict";
import { kindView, legacyMeta, viewForRow, mapsHref, unsupportedTitle } from "../src/lib/messageKinds.ts";

test("location: a map link built only from the coordinates", () => {
    const v = kindView({ kind: "location", lat: -1.2864, lng: 36.8172, name: "Bethany House", address: "Moi Ave",
        url: "javascript:alert(1)" });
    assert.equal(v.title, "Shared a location");
    assert.deepEqual(v.lines, ["Bethany House · Moi Ave"]);
    assert.equal(v.link.href, "https://www.google.com/maps/search/?api=1&query=-1.2864,36.8172");
    assert.equal(mapsHref(91, 0), null);            // out of range → no link
    assert.equal(mapsHref("1", 2), null);           // strings never reach an href
});

test("contacts: name, number and how many", () => {
    const v = kindView({ kind: "contacts", contacts: [{ name: "Fr. Peter", phones: ["+254 722 000 111"] },
        { name: "Sr. Mary", phones: [] }] });
    assert.equal(v.title, "Shared 2 contacts");
    assert.deepEqual(v.lines, ["Fr. Peter · +254 722 000 111", "Sr. Mary"]);
});

test("reaction: names what was reacted to; removal said in words", () => {
    assert.equal(kindView({ kind: "reaction", emoji: "❤️", to_text: "The brass chalice is KES 12,000" }).title,
        "Reacted ❤️ to “The brass chalice is KES 12,000”");
    assert.equal(kindView({ kind: "reaction", emoji: "👍" }).title, "Reacted 👍 to your message");
    assert.equal(kindView({ kind: "reaction", emoji: "" }).title, "Removed their reaction");
});

test("call permission: a centred, call-family line", () => {
    const yes = kindView({ kind: "call_permission", response: "accept", permanent: true });
    assert.equal(yes.title, "Allowed WhatsApp calls — permanently");
    assert.equal(yes.centred, true);
    assert.equal(kindView({ kind: "call_permission", response: "reject" }).title, "Declined WhatsApp calls");
    assert.match(kindView({ kind: "call_permission", response: "accept", expires_at: 1760000000 }).lines[0], /^Until /);
});

test("order, form, system, welcome, deleted, edited each read in words", () => {
    assert.equal(kindView({ kind: "order", count: 3, total: "KES 12,000",
        items: [{ sku: "ALB-01", qty: 2 }, { sku: "STO-RED", qty: 1 }] }).title, "Sent a cart — 3 items · KES 12,000");
    assert.deepEqual(kindView({ kind: "form", name: "flow", fields: { size: "XL" } }).lines, ["size: XL"]);
    assert.equal(kindView({ kind: "system", subtype: "user_changed_number", new_wa_id: "254711000222" }).lines[0],
        "New number: +254711000222");
    assert.equal(kindView({ kind: "welcome" }).centred, true);
    assert.equal(kindView({ kind: "deleted" }).title, "Deleted a message");
    assert.equal(kindView({ kind: "edited" }).title, "Edited an earlier message");
});

test("unsupported: names the feature, keeps Meta's reason as small print, never a warning", () => {
    const v = kindView({ kind: "unsupported", type: "unsupported", subtype: "view_once",
        label: "view-once photo or video", advice: "WhatsApp never delivers view-once media to businesses.",
        errors: [{ code: 131051, title: "Message type unknown" }] });
    assert.equal(v.title, "Sent something WhatsApp doesn't let us show here — a view-once photo or video.");
    assert.equal(v.details, "type “unsupported” · 131051 Message type unknown");
    assert.ok(!v.title.includes("⚠️"));
    assert.equal(unsupportedTitle({ kind: "unsupported", app: "Instagram" }),
        "Sent something Instagram doesn't let us show here.");
});

test("legacy rows: the old warnings and empty rows become the calm card", () => {
    const native = legacyMeta("⚠️ Sent a message we can't display here (unsupported type) — ask them to resend as text.", false);
    assert.deepEqual(native, { kind: "unsupported", type: "unsupported", legacy: true });
    assert.equal(kindView(native).title, "Sent something WhatsApp doesn't let us show here.");
    const poll = legacyMeta("⚠️ Sent a message we can't display here (poll type) — ask them to resend as text.", false);
    assert.equal(kindView(poll).title, "Sent something WhatsApp doesn't let us show here — a poll.");
    assert.deepEqual(legacyMeta("⚠️ Sent a message we can't display here — ask them to resend as text.", false),
        { kind: "unsupported", legacy: true });
    assert.deepEqual(legacyMeta("[unsupported message]", false), { kind: "unsupported", legacy: true });
    const empty = viewForRow({ text: "", media_type: null, meta: null });
    assert.equal(empty.title, "Sent something WhatsApp doesn't let us show here.");
    assert.equal(empty.lines[0], "This came in before we recorded message types.");
});

test("ordinary rows stay ordinary", () => {
    assert.equal(viewForRow({ text: "how much is the alb?", media_type: null, meta: null }), null);
    assert.equal(viewForRow({ text: "", media_type: "audio", meta: null }), null);   // media renders itself
    assert.equal(kindView({ kind: "plain", errors: [{ code: 131052 }] }), null);
    assert.equal(kindView(null), null);
});

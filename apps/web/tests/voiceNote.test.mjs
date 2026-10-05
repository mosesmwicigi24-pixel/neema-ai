// The words under a voice note (thread bubble + a call card's voicemail):
// one state per server status, never "Transcribing…" forever, never our own
// bracketed placeholder shown as the customer's words.
// Run: node --test apps/web/tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { voiceNoteState, voiceWords } from "../src/lib/voiceNote.ts";

test("every server status has a state", () => {
    assert.equal(voiceNoteState("queued", null), "working");
    assert.equal(voiceNoteState("processing", null), "working");
    assert.equal(voiceNoteState("pending", null), "working");
    assert.equal(voiceNoteState("silent", null), "silent");
    assert.equal(voiceNoteState("failed:over_budget", null), "failed");
    assert.equal(voiceNoteState("failed", null), "failed");
    assert.equal(voiceNoteState("done", "Nataka shati mbili"), "ready");
});

test("no status: words read as ready (n8n-era rows), nothing reads as nothing", () => {
    assert.equal(voiceNoteState(null, "hello"), "ready");
    assert.equal(voiceNoteState(null, null), "none");
    assert.equal(voiceNoteState("done", "  "), "none");
    assert.equal(voiceNoteState("none", null), "none");
});

test("placeholders are never words", () => {
    assert.equal(voiceWords("[audio]"), null);
    assert.equal(voiceWords("  "), null);
    assert.equal(voiceWords(null), null);
    assert.equal(voiceWords(" Bei gani? "), "Bei gani?");
});

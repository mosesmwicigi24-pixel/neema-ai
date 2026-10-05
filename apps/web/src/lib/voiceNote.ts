// A voice note's transcription state, in one word (API services/voice_notes:
// transcript_status none | queued | processing | done | silent |
// failed:<reason>; legacy "pending" = queued). Pure — tests/voiceNote.test.mjs.
//
// A row with NO status but words (a note transcribed by the n8n era, or a
// typed caption) reads as ready; a row with no status and no words reads as
// nothing to show — never "Transcribing…" forever.
export type VoiceNoteState = "working" | "ready" | "silent" | "failed" | "none";

export function voiceNoteState(status: string | null | undefined, transcription: string | null | undefined): VoiceNoteState {
    const s = (status ?? "").trim();
    if (s === "queued" || s === "processing" || s === "pending") return "working";
    if (s === "silent") return "silent";
    if (s === "failed" || s.startsWith("failed:")) return "failed";
    if ((transcription ?? "").trim()) return "ready";
    return "none";
}

/** A voice note's words from its stored text — never our own bracketed
 *  placeholders ("[audio]", "[voice note]"). */
export function voiceWords(text: string | null | undefined): string | null {
    const t = (text ?? "").trim();
    return t && !t.startsWith("[") ? t : null;
}

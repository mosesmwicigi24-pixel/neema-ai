// The words under a customer's voice note — in the thread's audio bubble AND
// inside a call card's voicemail (calls & audio programme, cycles 5 + 3,
// joined at integration 2026-10-05). One component so both read the same:
//   queued / processing → "Transcribing…"
//   silent              → "No speech heard …"
//   failed:<reason>     → "Couldn't transcribe … — <why>"
//   done                → the words; when it wasn't English, the English with
//                          "Translated from Swahili" and the original a tap away.
// The words are the server's (voice_notes writes the verbatim transcript into
// the message text); nothing here guesses.
import React from "react";
import { voiceNoteState } from "@/lib/voiceNote";

export function VoiceNoteText({ status, note, transcription, translation, translatedFrom, label = "voice note" }: {
    status?: string | null;
    note?: string | null;
    transcription: string | null;
    translation?: string | null;
    translatedFrom?: string | null;
    /** "voice note" / "voicemail" — the noun in the status lines. */
    label?: string;
}) {
    const [showOriginal, setShowOriginal] = React.useState(false);
    const state = voiceNoteState(status, transcription);
    if (state === "working") {
        return (
            <p className="text-[11px] px-1 text-[#699a32] flex items-center gap-1.5" aria-live="polite">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#699a32] animate-pulse motion-reduce:animate-none" />
                Transcribing…
            </p>
        );
    }
    if (state === "silent" || state === "failed") {
        return (
            <p className="text-[11px] px-1 text-stone-500 leading-relaxed">
                {state === "silent"
                    ? `No speech heard in this ${label}.`
                    : `Couldn’t transcribe this ${label}${note ? ` — ${note}` : ""}.`}
            </p>
        );
    }
    if (state !== "ready" || !transcription) return null;
    return (
        <div className="px-1 flex flex-col gap-0.5">
            <p className="text-[12.5px] leading-relaxed whitespace-pre-wrap text-[#1c2917]">
                {translation || transcription}
            </p>
            {translation && (
                <>
                    <div className="flex items-center gap-2 flex-wrap text-[10px] text-stone-500">
                        <span>
                            <span className="select-none mr-1" aria-hidden>🌐</span>
                            Translated{translatedFrom ? ` from ${translatedFrom}` : ""}
                        </span>
                        <button
                            type="button"
                            onClick={() => setShowOriginal((o) => !o)}
                            aria-expanded={showOriginal}
                            className="font-medium text-[#699a32] hover:text-[#427425] underline-offset-2 hover:underline min-h-6"
                        >
                            {showOriginal ? "Hide original" : "Show original"}
                        </button>
                    </div>
                    {showOriginal && (
                        <p className="text-[11.5px] leading-relaxed whitespace-pre-wrap italic text-[#3a5c28]/80 border-l-2 border-[#d9e8c9] pl-2">
                            {transcription}
                        </p>
                    )}
                </>
            )}
        </div>
    );
}

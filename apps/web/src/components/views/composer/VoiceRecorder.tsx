"use client";

// Voice notes from the composer (owner, 2026-11-09). Record → preview →
// delete or send, like WhatsApp. The browser records what it can (WebM/Opus
// on Chrome/Android, MP4 on Safari/iPhone, Ogg on Firefox); the API
// re-encodes it to what the channel plays (services/audio_convert.py), so the
// customer always gets a playable voice note.

import { useCallback, useEffect, useRef, useState } from "react";

export type VoiceState = "idle" | "recording" | "preview";

const MAX_SECONDS = 5 * 60;          // a voice note, not a podcast — and well under 16 MB

function pickMime(): string {
    if (typeof MediaRecorder === "undefined") return "";
    for (const m of ["audio/ogg;codecs=opus", "audio/webm;codecs=opus", "audio/webm", "audio/mp4"]) {
        try { if (MediaRecorder.isTypeSupported(m)) return m; } catch { /* old Safari */ }
    }
    return "";
}

export function voiceSupported(): boolean {
    return typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
}

export function fmtSeconds(s: number): string {
    const m = Math.floor(s / 60);
    return `${m}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

export function useVoiceRecorder(onError: (msg: string) => void) {
    const [state, setState] = useState<VoiceState>("idle");
    const [seconds, setSeconds] = useState(0);
    const [file, setFile] = useState<File | null>(null);
    const [url, setUrl] = useState<string | null>(null);
    const rec = useRef<MediaRecorder | null>(null);
    const chunks = useRef<Blob[]>([]);
    const stream = useRef<MediaStream | null>(null);
    const timer = useRef<number | null>(null);
    const discardOnStop = useRef(false);

    const stopTracks = () => {
        stream.current?.getTracks().forEach((t) => t.stop());
        stream.current = null;
        if (timer.current) { window.clearInterval(timer.current); timer.current = null; }
    };

    const reset = useCallback(() => {
        if (url) URL.revokeObjectURL(url);
        setUrl(null); setFile(null); setSeconds(0); setState("idle");
    }, [url]);

    const stop = useCallback(() => {
        if (rec.current && rec.current.state !== "inactive") rec.current.stop();
    }, []);

    const start = useCallback(async () => {
        if (!voiceSupported()) { onError("This browser can't record voice notes."); return; }
        try {
            const s = await navigator.mediaDevices.getUserMedia({ audio: true });
            stream.current = s;
            const mime = pickMime();
            const r = mime ? new MediaRecorder(s, { mimeType: mime }) : new MediaRecorder(s);
            chunks.current = [];
            discardOnStop.current = false;
            r.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
            r.onstop = () => {
                stopTracks();
                if (discardOnStop.current) { setState("idle"); setSeconds(0); return; }
                const type = (r.mimeType || mime || "audio/webm").split(";")[0];
                const blob = new Blob(chunks.current, { type });
                if (!blob.size) { setState("idle"); onError("Nothing was recorded — try again."); return; }
                const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
                const f = new File([blob], `voice-note-${Date.now()}.${ext}`, { type });
                setFile(f);
                setUrl(URL.createObjectURL(blob));
                setState("preview");
            };
            rec.current = r;
            r.start(250);
            setSeconds(0);
            setState("recording");
            const t0 = Date.now();
            timer.current = window.setInterval(() => {
                const s2 = Math.floor((Date.now() - t0) / 1000);
                setSeconds(s2);
                if (s2 >= MAX_SECONDS && r.state !== "inactive") r.stop();
            }, 250);
        } catch (e: unknown) {
            stopTracks();
            setState("idle");
            onError((e as { name?: string } | null)?.name === "NotAllowedError"
                ? "Microphone access was blocked — allow it in the browser's site settings."
                : "Couldn't start the microphone.");
        }
    }, [onError]);

    const cancel = useCallback(() => {
        if (state === "recording") { discardOnStop.current = true; stop(); return; }
        reset();
    }, [state, stop, reset]);

    // Leaving the chat (or the page) never leaves the microphone on.
    useEffect(() => () => {
        discardOnStop.current = true;
        try { if (rec.current && rec.current.state !== "inactive") rec.current.stop(); } catch { /* already stopped */ }
        stopTracks();
    }, []);

    return { state, seconds, file, url, start, stop, cancel, reset };
}

/** The bar that replaces the text field while recording or previewing. */
export function VoiceBar({ v, sending, onSend }: {
    v: ReturnType<typeof useVoiceRecorder>; sending: boolean; onSend: () => void;
}) {
    return (
        <div className="flex-1 flex items-center gap-2 min-h-[44px] px-2 rounded-2xl bg-[#f6f7f5] border border-[#e5e8e2]">
            <button type="button" onClick={v.cancel} disabled={sending} title="Delete"
                    className="h-9 w-9 rounded-xl flex items-center justify-center text-[#b42318] hover:bg-[#fdecec] disabled:opacity-40">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6M9 7V4a1 1 0 011-1h4a1 1 0 011 1v3M4 7h16" />
                </svg>
            </button>
            {v.state === "recording" ? (
                <>
                    <span className="relative flex h-2.5 w-2.5" aria-hidden="true">
                        <span className="absolute inline-flex h-full w-full rounded-full bg-[#ef4444] opacity-60 animate-ping" />
                        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[#ef4444]" />
                    </span>
                    <span className="text-sm tabular-nums text-[#1c2917]">{fmtSeconds(v.seconds)}</span>
                    <span className="text-xs text-stone-400 truncate">Recording…</span>
                    <button type="button" onClick={v.stop} title="Stop and listen"
                            className="ml-auto h-9 px-3 rounded-xl text-xs font-semibold text-[#1c2917] bg-white border border-[#e5e8e2] hover:bg-[#f3f5f0]">
                        Stop
                    </button>
                </>
            ) : (
                <>
                    <audio src={v.url ?? undefined} controls className="h-9 flex-1 min-w-0" />
                    <button type="button" onClick={onSend} disabled={sending} title="Send voice note"
                            className="h-9 px-3 rounded-xl text-xs font-semibold text-white bg-[#f59e0b] hover:bg-[#d97706] disabled:opacity-50 inline-flex items-center gap-1.5">
                        {sending ? <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" /> : null}
                        Send
                    </button>
                </>
            )}
        </div>
    );
}

"use client";

// The call surface — WhatsApp calls look like WhatsApp calls (docs/CALLING_UX.md §5).
//
//  • CallStage: the full card, rendered INSIDE the dashboard content area
//    (absolute overlay) so the sidebar stays visible. Avatar, name, "WhatsApp
//    voice call", the phase's own words, controls in a bottom bar — Decline
//    left, Answer right and largest, as on a phone. After the call, the
//    wrap-up: the outcome in words and the next action.
//  • CallBar: the minimised call (§6) — a slim bar at the top of the content
//    area, in the layout flow so it never covers the view under it. Also the
//    "{First} allowed calls · Call now" banner.
//
// Reads all state/actions from CallProvider; renders nothing when idle. Never
// shows what the WhatsApp API can't do: no video, hold, transfer, conference.
import React, { useEffect, useRef, useState } from "react";
import {
    useCall, callerLabel, firstName, isLivePhase, YOU_ELSEWHERE,
    type CallOutcome, type CallPhase,
} from "@/lib/callContext";

const WA = {
    bg: "#0B141A", bg2: "#111B21", panel: "#202C33", text: "#E9EDEF", muted: "#8696A0",
    green: "#25D366", greenDeep: "#00A884", red: "#EA0038", amber: "#FFB02E",
};

const ICONS: Record<string, React.ReactElement> = {
    phone: <path d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />,
    "phone-off": <path d="M3.7 13.6c-.5-.5-.5-1.3 0-1.8C6.2 9.4 9 8.2 12 8.2s5.8 1.2 8.3 3.6c.5.5.5 1.3 0 1.8l-1.9 1.9c-.4.4-1.1.5-1.6.1l-2-1.5c-.3-.2-.5-.6-.5-1v-1.9a10.4 10.4 0 00-4.6 0v1.9c0 .4-.2.8-.5 1l-2 1.5c-.5.4-1.2.3-1.6-.1l-1.9-1.9z" />,
    callback: <path d="M9 14l-4-4 4-4M5 10h11a4 4 0 014 4v3" />,
    mic: <><path d="M12 2a3 3 0 00-3 3v6a3 3 0 006 0V5a3 3 0 00-3-3z" /><path d="M5 10v1a7 7 0 0014 0v-1M12 18v3" /></>,
    "mic-off": <><path d="M3 3l18 18" /><path d="M9 5a3 3 0 016 0v5m-1.3 2.7A3 3 0 019 11V9" /><path d="M5 10v1a7 7 0 0010.7 5.9M19 10v1a6.9 6.9 0 01-.3 2M12 18v3" /></>,
    audio: <><path d="M3 18v-6a9 9 0 0118 0v6" /><path d="M21 19a2 2 0 01-2 2h-1v-6h3v4zM3 19a2 2 0 002 2h1v-6H3v4z" /></>,
    chat: <path d="M21 11.5a8.4 8.4 0 01-9 8.4 8.6 8.6 0 01-3.8-.9L3 21l1.9-5.2a8.4 8.4 0 01-.9-3.8 8.5 8.5 0 018.5-8.5h.5a8.5 8.5 0 018 8v.5z" />,
    minimise: <path d="M6 9l6 6 6-6" />,
    x: <path d="M18 6L6 18M6 6l12 12" />,
    alert: <><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" /></>,
    "wifi-off": <><path d="M1 1l22 22M16.7 11.1A10.9 10.9 0 0119 12.6M5 12.6a10.9 10.9 0 015.2-2.5M10.7 5A16 16 0 0122.6 9M1.4 9a16 16 0 014.3-2.8M8.5 16.1a5 5 0 017 0M12 20h.01" /></>,
    check: <path d="M20 6L9 17l-5-5" />,
    in: <path d="M17 7L7 17M7 17h7M7 17v-7" />,
    out: <path d="M7 17L17 7M17 7h-7M17 7v7" />,
};

function Icon({ name, size = 22, stroke = 2, fill }: { name: string; size?: number; stroke?: number; fill?: string }) {
    return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill={fill ?? "none"} stroke="currentColor" strokeWidth={stroke}
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
            {ICONS[name]}
        </svg>
    );
}

/** The WhatsApp glyph (speech bubble + handset), for "WhatsApp voice call". */
export function WhatsAppGlyph({ size = 14, color = WA.green }: { size?: number; color?: string }) {
    return (
        <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
            <path fill={color} d="M12 2a10 10 0 00-8.6 15.1L2 22l5-1.3A10 10 0 1012 2zm0 1.8a8.2 8.2 0 11-4.2 15.3l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 0112 3.8z" />
            <path fill={color} d="M8.9 7.3c-.2-.4-.4-.4-.6-.4h-.5a1 1 0 00-.7.3 3 3 0 00-.9 2.2 5.2 5.2 0 001.1 2.7 11.8 11.8 0 004.6 4c2.3.9 2.7.7 3.2.7a2.7 2.7 0 001.8-1.3 2.2 2.2 0 00.2-1.3c-.1-.1-.3-.2-.6-.3l-1.9-.9c-.3-.1-.5-.2-.7.1l-.8 1a.5.5 0 01-.7.1 6.8 6.8 0 01-2-1.2 7.5 7.5 0 01-1.4-1.7.4.4 0 01.1-.6l.4-.5.3-.5a.5.5 0 000-.4l-.9-2z" />
        </svg>
    );
}

export const fmtDuration = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;

// mm:ss from the moment media connected — a clock, not a counter that drifts.
function Elapsed({ since }: { since: number }) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const t = setInterval(() => setNow(Date.now()), 500);
        return () => clearInterval(t);
    }, [since]);
    return <>{fmtDuration(Math.max(0, Math.floor((now - since) / 1000)))}</>;
}

// The phase's own words (§3 table).
const PHASE_WORDS: Partial<Record<CallPhase, string>> = {
    incoming: "Incoming…",
    placing: "Calling…",
    ringing_out: "Ringing…",
    connecting: "Connecting…",
    reconnecting: "Reconnecting…",
    ending: "Ending…",
};

function outcomeWords(o: CallOutcome | null, c: ReturnType<typeof useCall>): string {
    if (!c) return "";
    const first = firstName(c.call);
    const d = c.duration ? ` · ${fmtDuration(c.duration)}` : "";
    switch (o) {
        case "completed": return `Call ended${d}`;
        case "answered_elsewhere":
            return c.byAgent === YOU_ELSEWHERE ? "Answered on your other device" : `Answered by ${c.byAgent || "a colleague"}`;
        case "declined": return c.byAgent ? `Declined by ${c.byAgent}` : "Call declined";
        case "missed": return "Missed call";
        case "callback": return c.byAgent ? `${c.byAgent} saved it to call back — find it under Calls`
            : "Saved to call back — find it under Calls";
        case "no_answer": return "No answer";
        case "cancelled": return "Call cancelled";
        case "connection_lost": return `Call dropped${d} — the connection was lost`;
        case "failed": return c.reason || "The call couldn't be connected";
        case "permission_needed": return `${first} hasn't allowed WhatsApp calls yet`;
        case "permission_requested": return `Call request sent — you'll be told when ${first} taps Allow`;
        case "mic_blocked": return "Microphone blocked — allow it in settings";
        default: return "Call ended";
    }
}

// Neutral wrap-ups close themselves; ones that leave the agent owing the
// customer something (missed, no answer, dropped, failed, permission) never do.
const AUTO_CLOSE: Partial<Record<CallOutcome, number>> = {
    answered_elsewhere: 4000,
    cancelled: 2000,
    callback: 4000,
    declined: 5000,
    permission_requested: 6000,
    completed: 8000,
};

type Action = { label: string; onClick: () => void; primary?: boolean; busy?: boolean };

function wrapUpActions(c: NonNullable<ReturnType<typeof useCall>>, showHelp: () => void): Action[] {
    // Done is a calm, deliberate tap — the one moment we ask (once ever) to
    // notify about calls that ring while Neema is in a background tab.
    const done: Action = { label: "Done", onClick: () => { c.dismiss(); c.offerNotifications(); } };
    const chat = (label: string, primary = false): Action => ({ label, onClick: c.openChat, primary });
    const inbound = c.call?.direction === "inbound";
    switch (c.outcome) {
        case "completed": return [chat("Open chat", true), { label: "Call again", onClick: c.redial }, done];
        case "answered_elsewhere": return [done];
        case "declined": return [chat("Message"), done];
        case "missed": return [{ label: "Call back", onClick: c.redial, primary: true }, chat("Message"), done];
        case "callback": return [done];
        case "no_answer": return [{ label: "Call again", onClick: c.redial, primary: true }, chat("Message"), done];
        case "cancelled": return [done];
        case "connection_lost": return [{ label: "Call again", onClick: c.redial, primary: true }, chat("Open chat"), done];
        case "failed": return [{ label: inbound ? "Call back" : "Try again", onClick: c.redial, primary: true }, chat("Message"), done];
        case "permission_needed": return [
            { label: c.permissionBusy ? "Sending…" : "Send call request", onClick: c.requestPermission, primary: true, busy: c.permissionBusy },
            chat("Message"), { label: "Cancel", onClick: c.dismiss }];
        case "permission_requested": return [chat("Message"), done];
        case "mic_blocked": return [{ label: "How to allow it", onClick: showHelp, primary: true }, done];
        default: return [done];
    }
}

function RoundBtn({ label, icon, onClick, color, fg = "#fff", size = 60, pressed, btnRef, disabled }: {
    label: string; icon: string; onClick: () => void; color: string; fg?: string; size?: number;
    pressed?: boolean; btnRef?: React.Ref<HTMLButtonElement>; disabled?: boolean;
}) {
    return (
        <button ref={btnRef} type="button" onClick={onClick} disabled={disabled} aria-label={label}
            aria-pressed={pressed}
            className="cs-btn flex flex-col items-center gap-1.5 disabled:opacity-50" style={{ minWidth: 64 }}>
            <span className="rounded-full flex items-center justify-center"
                style={{ width: size, height: size, backgroundColor: color, color: fg, boxShadow: "0 6px 16px rgba(0,0,0,0.35)" }}>
                <Icon name={icon} size={Math.round(size * 0.4)} />
            </span>
            <span aria-hidden="true" style={{ fontSize: 12.5, color: WA.muted, lineHeight: 1.2 }}>{label}</span>
        </button>
    );
}

function Avatar({ label, size, pulse }: { label: string; size: string; pulse: boolean }) {
    const initials = label.replace("+", "").split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || "?";
    return (
        <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
            {pulse && (
                <>
                    <span className="cs-pulse absolute inset-0 rounded-full" style={{ background: WA.greenDeep }} />
                    <span className="cs-pulse cs-pulse2 absolute inset-0 rounded-full" style={{ background: WA.greenDeep }} />
                </>
            )}
            <div className="relative rounded-full flex items-center justify-center font-semibold select-none"
                style={{ width: size, height: size, backgroundColor: "#2A3942", color: WA.text, fontSize: `calc(${size} * 0.36)` }}>
                {/^\d/.test(initials) ? <Icon name="phone" size={40} /> : initials}
            </div>
        </div>
    );
}

// Microphone / speaker picker — only what this browser can actually switch.
function AudioMenu({ onClose }: { onClose: () => void }) {
    const c = useCall();
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
        c?.refreshDevices();
        const onDown = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
        const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
        document.addEventListener("mousedown", onDown);
        document.addEventListener("keydown", onKey, true);
        ref.current?.querySelector<HTMLButtonElement>("button")?.focus();
        return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey, true); };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
    if (!c) return null;
    const Row = ({ label, selected, onClick }: { label: string; selected: boolean; onClick: () => void }) => (
        <button type="button" role="menuitemradio" aria-checked={selected} onClick={onClick}
            className="w-full flex items-center gap-2 px-3 text-left rounded-lg hover:bg-white/5"
            style={{ minHeight: 44, fontSize: 14, color: WA.text }}>
            <span style={{ width: 18, color: WA.green }}>{selected ? <Icon name="check" size={16} /> : null}</span>
            <span className="truncate">{label}</span>
        </button>
    );
    return (
        <div ref={ref} role="menu" aria-label="Audio devices"
            className="absolute bottom-full mb-3 left-1/2 -translate-x-1/2 w-[min(300px,calc(100vw-32px))] rounded-2xl p-2 z-10"
            style={{ backgroundColor: WA.panel, boxShadow: "0 12px 40px rgba(0,0,0,0.5)", border: "1px solid rgba(255,255,255,0.06)" }}>
            <div className="px-3 pt-1 pb-1" style={{ fontSize: 12, color: WA.muted }}>Microphone</div>
            <Row label="System default" selected={!c.inputId} onClick={() => { c.selectInput(""); onClose(); }} />
            {c.inputs.map((d) => (
                <Row key={d.deviceId} label={d.label} selected={c.inputId === d.deviceId} onClick={() => { c.selectInput(d.deviceId); onClose(); }} />
            ))}
            {c.canPickOutput && c.outputs.length > 0 && (
                <>
                    <div className="px-3 pt-2 pb-1" style={{ fontSize: 12, color: WA.muted }}>Speaker</div>
                    <Row label="System default" selected={!c.outputId} onClick={() => { c.selectOutput(""); onClose(); }} />
                    {c.outputs.map((d) => (
                        <Row key={d.deviceId} label={d.label} selected={c.outputId === d.deviceId} onClick={() => { c.selectOutput(d.deviceId); onClose(); }} />
                    ))}
                </>
            )}
        </div>
    );
}

// "Grace is also calling" — no hold in the API, so answering means ending this one.
function WaitingBanner({ compact }: { compact?: boolean }) {
    const c = useCall();
    if (!c?.waiting) return null;
    const who = callerLabel(c.waiting);
    const btn = "rounded-full px-3 font-semibold";
    return (
        <div role="alert" className={`flex flex-wrap items-center gap-2 ${compact ? "px-3 py-2" : "px-4 py-3 rounded-2xl"}`}
            style={{ backgroundColor: WA.panel, color: WA.text }}>
            <span className="flex items-center gap-2 min-w-0 flex-1" style={{ fontSize: 14 }}>
                <WhatsAppGlyph size={16} />
                <span className="truncate"><b className="font-semibold">{who}</b> is also calling</span>
            </span>
            <span className="flex flex-wrap gap-2">
                <button type="button" onClick={c.declineWaiting} aria-label={`Decline ${who}'s call`}
                    className={btn} style={{ minHeight: 44, fontSize: 13, backgroundColor: WA.red, color: "#fff" }}>Decline</button>
                <button type="button" onClick={c.callbackWaiting}
                    className={btn} style={{ minHeight: 44, fontSize: 13, backgroundColor: "rgba(255,255,255,0.08)", color: WA.text }}>Call back later</button>
                <button type="button" onClick={c.endAndAnswerWaiting}
                    className={btn} style={{ minHeight: 44, fontSize: 13, backgroundColor: WA.greenDeep, color: "#fff" }}>
                    {c.phase === "incoming" ? "Answer instead" : "End & answer"}
                </button>
            </span>
        </div>
    );
}

const STYLES = `
.cs-btn > span:first-child { transition: transform .15s ease, filter .15s ease; }
.cs-btn:hover:not(:disabled) > span:first-child { filter: brightness(1.08); }
.cs-btn:active:not(:disabled) > span:first-child { transform: scale(.95); }
.cs-btn:focus-visible { outline: none; }
.cs-btn:focus-visible > span:first-child { outline: 3px solid #E9EDEF; outline-offset: 3px; }
@keyframes csPulse { 0% { transform: scale(1); opacity: .35 } 100% { transform: scale(1.9); opacity: 0 } }
.cs-pulse { animation: csPulse 1.8s ease-out infinite; }
.cs-pulse2 { animation-delay: .9s; }
@keyframes csSpin { to { transform: rotate(360deg) } }
.cs-spin { animation: csSpin .9s linear infinite; }
@keyframes csIn { from { opacity: 0 } to { opacity: 1 } }
.cs-in { animation: csIn .16s ease-out; }
@media (prefers-reduced-motion: reduce) {
  .cs-pulse, .cs-spin, .cs-in { animation: none !important; }
  .cs-pulse { display: none; }
}`;

/** Where an agent is sent to fix a blocked microphone (web: the site's permission). */
const MIC_HELP = "Click the lock or tune icon left of the address bar → Site settings → Microphone → Allow, then call again.";

export function CallStage({ onOpenConversation }: { onOpenConversation?: (key: string) => void }): React.ReactElement | null {
    const c = useCall();
    const answerRef = useRef<HTMLButtonElement>(null);
    const cardRef = useRef<HTMLDivElement>(null);
    // Per-screen UI state, keyed so a new phase / call starts clean without an
    // effect resetting it: the audio menu belongs to one phase of one call,
    // the mic how-to and the auto-close hold to one call.
    const [audioOpenFor, setAudioOpenFor] = useState<string | null>(null);
    const [holdFor, setHoldFor] = useState<string | null>(null);
    const [micHelpFor, setMicHelpFor] = useState<string | null>(null);

    // The dashboard tells the call how to open a customer's chat.
    const setChatOpener = c?.setChatOpener;
    const openerRef = useRef(onOpenConversation);
    useEffect(() => { openerRef.current = onOpenConversation; }, [onOpenConversation]);
    useEffect(() => {
        if (!setChatOpener) return;
        setChatOpener((wa) => openerRef.current?.(wa));
        return () => setChatOpener(null);
    }, [setChatOpener]);

    const phase = c?.phase ?? "idle";
    const callId = c?.call?.callId;
    const minimised = !!c?.minimised;
    const screenKey = `${phase}:${callId ?? ""}`;
    const audioOpen = audioOpenFor === screenKey;
    const setAudioOpen = (open: boolean) => setAudioOpenFor(open ? screenKey : null);
    const hold = holdFor === screenKey;
    const setHold = (on: boolean) => setHoldFor(on ? screenKey : null);
    const micHelp = !!callId && micHelpFor === callId;

    // Focus lands on Answer the moment a call rings.
    useEffect(() => {
        if (phase === "incoming" && !minimised) answerRef.current?.focus({ preventScroll: true });
    }, [phase, callId, minimised]);

    // The wrap-up's main action takes focus, so Enter does the obvious next thing.
    const primaryRef = useRef<HTMLButtonElement>(null);
    useEffect(() => {
        if (phase === "ended" && !minimised) primaryRef.current?.focus({ preventScroll: true });
    }, [phase, callId, minimised, c?.outcome]);

    // Escape minimises a live call (the audio menu takes Escape first).
    const minimise = c?.minimise;
    useEffect(() => {
        if (!minimise || minimised || !["connecting", "active", "reconnecting", "placing", "ringing_out"].includes(phase)) return;
        const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !audioOpen) minimise(); };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [phase, minimised, audioOpen, minimise]);


    // Neutral wrap-ups close on their own — paused while the pointer or focus is on the card.
    const outcome = c?.outcome ?? null;
    const dismiss = c?.dismiss;
    const recordingNote = c?.recordingNote;
    useEffect(() => {
        if (phase !== "ended" || !outcome || !dismiss || hold) return;
        let ms = AUTO_CLOSE[outcome];
        if (!ms) return;
        if (recordingNote && ms < 8000) ms = 8000;   // long enough to read the recording line
        const t = setTimeout(dismiss, ms);
        return () => clearTimeout(t);
    }, [phase, outcome, dismiss, hold, callId, recordingNote]);

    if (!c || phase === "idle" || minimised) return null;

    const who = callerLabel(c.call);
    const live = isLivePhase(phase);
    const inCall = phase === "active" || phase === "reconnecting";
    const ended = phase === "ended";
    const ringingHere = phase === "incoming";
    const pulse = ringingHere || phase === "placing" || phase === "ringing_out";
    const audioSupported = typeof navigator !== "undefined" && !!navigator.mediaDevices?.enumerateDevices;

    // Status line — the phase's own words; the timer only while connected.
    let status: React.ReactNode;
    if (phase === "active" && c.answeredAt) {
        status = (
            <span className="flex items-center gap-3">
                {/* The ticking clock stays out of the live region (it would be read out every second). */}
                <span className="sr-only">Connected</span>
                <span aria-hidden="true" className="tabular-nums" style={{ fontSize: 17, color: WA.text }}><Elapsed since={c.answeredAt} /></span>
                {c.recording && (
                    <span className="flex items-center gap-1.5" style={{ fontSize: 13, color: "#FF6B81" }}>
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: "#FF3B5C" }} aria-hidden="true" /> Recording
                    </span>
                )}
            </span>
        );
    } else if (phase === "reconnecting") {
        status = (
            <span className="flex items-center gap-1.5" style={{ color: WA.amber }}>
                <Icon name="wifi-off" size={16} /> Reconnecting…
            </span>
        );
    } else if (phase === "connecting" || phase === "ending") {
        status = (
            <span className="flex items-center gap-2">
                <span className="cs-spin inline-block w-3.5 h-3.5 rounded-full border-2" aria-hidden="true"
                    style={{ borderColor: "rgba(233,237,239,0.25)", borderTopColor: WA.text }} />
                {PHASE_WORDS[phase]}
            </span>
        );
    } else if (ended) {
        status = outcomeWords(c.outcome, c);
    } else {
        status = PHASE_WORDS[phase] ?? "";
    }
    const endedTone = ended && ["missed", "no_answer", "connection_lost", "failed", "mic_blocked", "permission_needed"].includes(c.outcome ?? "");

    const actions = ended ? wrapUpActions(c, () => setMicHelpFor(callId ?? null)) : [];

    return (
        <div ref={cardRef}
            className="cs-in absolute inset-0 z-50 flex flex-col overflow-y-auto"
            style={{ background: `linear-gradient(180deg, ${WA.bg} 0%, ${WA.bg2} 100%)`, color: WA.text }}
            role="dialog" aria-modal="false" aria-label={`WhatsApp voice call with ${who}`}
            onMouseEnter={() => setHold(true)} onMouseMove={() => { if (!hold) setHold(true); }}
            onMouseLeave={() => setHold(false)} onKeyDown={() => { if (!hold) setHold(true); }}>
            <style>{STYLES}</style>

            {/* Top: minimise / close + the waiting banner and device notices */}
            <div className="w-full max-w-lg mx-auto px-4 pt-3 flex flex-col gap-2">
                <div className="flex items-center justify-between" style={{ minHeight: 44 }}>
                    {live ? (
                        <button type="button" onClick={c.minimise} aria-label="Minimise call"
                            className="rounded-full flex items-center justify-center hover:bg-white/5"
                            style={{ width: 44, height: 44, color: WA.muted }}>
                            <Icon name="minimise" />
                        </button>
                    ) : <span />}
                    {ended && (
                        <button type="button" onClick={c.dismiss} aria-label="Close"
                            className="rounded-full flex items-center justify-center hover:bg-white/5"
                            style={{ width: 44, height: 44, color: WA.muted }}>
                            <Icon name="x" />
                        </button>
                    )}
                </div>
                <WaitingBanner />
                {c.deviceNotice && (
                    <div role="status" className="rounded-xl px-3 py-2 flex items-center gap-2"
                        style={{ backgroundColor: WA.panel, fontSize: 13 }}>
                        <Icon name="audio" size={16} /> {c.deviceNotice}
                    </div>
                )}
            </div>

            {/* Middle: who + what's happening */}
            <div className="flex-1 flex flex-col items-center justify-center text-center px-4 py-4 min-h-0">
                <Avatar label={who} size="clamp(72px, 20vh, 128px)" pulse={pulse} />
                <h2 className="mt-5 font-semibold leading-tight max-w-full break-words"
                    style={{ fontSize: "clamp(22px, 5vw, 28px)" }}>{who}</h2>
                {c.call?.name && c.call.from && (
                    <div className="mt-1 tabular-nums" style={{ fontSize: 14, color: WA.muted }}>+{c.call.from}</div>
                )}
                <div className="mt-2 flex items-center gap-1.5" style={{ fontSize: 14, color: WA.muted }}>
                    <WhatsAppGlyph size={15} /> WhatsApp voice call
                </div>
                <div aria-live="polite" aria-atomic="true"
                    className="mt-3 flex items-center justify-center gap-2 max-w-md"
                    style={{ fontSize: 15, color: endedTone ? "#FFD1D9" : WA.text, minHeight: 24 }}>
                    {ended && endedTone && <Icon name={c.outcome === "missed" ? "in" : "alert"} size={16} />}
                    {status}
                </div>
                {ended && c.outcome === "missed" && c.reason && (
                    <div className="mt-1" style={{ fontSize: 13, color: WA.muted }}>{c.reason}</div>
                )}
                {ended && c.outcome === "permission_needed" && c.reason && (
                    <div role="alert" className="mt-2" style={{ fontSize: 13, color: "#FFB3C0" }}>{c.reason}</div>
                )}
                {ended && c.outcome === "permission_needed" && !c.reason && (
                    <div className="mt-2 max-w-sm" style={{ fontSize: 13, color: WA.muted }}>
                        WhatsApp only lets a business call someone who allowed it. The request is a WhatsApp message with an Allow button.
                    </div>
                )}
                {ended && c.outcome === "mic_blocked" && micHelp && (
                    <div className="mt-3 max-w-sm rounded-xl px-3 py-2" style={{ fontSize: 13, backgroundColor: WA.panel }}>{MIC_HELP}</div>
                )}
                {ended && c.recordingNote && (
                    <div className="mt-3 flex items-center gap-1.5" style={{ fontSize: 13, color: WA.muted }}>
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: WA.muted }} aria-hidden="true" />
                        {c.recordingNote}
                    </div>
                )}
                {ringingHere && c.notice && (
                    <div role="alert" className="mt-3 flex items-center gap-1.5 rounded-full px-3 py-1.5"
                        style={{ fontSize: 13, backgroundColor: "rgba(255,176,46,0.14)", color: WA.amber }}>
                        <Icon name="wifi-off" size={15} /> {c.notice}
                    </div>
                )}
            </div>

            {/* Bottom: the controls */}
            <div className="w-full max-w-lg mx-auto px-4 pb-6 pt-2">
                {ringingHere && (
                    <div className="flex flex-col items-center gap-3">
                        <div className="w-full flex items-end justify-between px-2 sm:px-8">
                            <RoundBtn label="Decline" icon="phone-off" color={WA.red} size={60}
                                onClick={c.decline} />
                            <RoundBtn label="Answer" icon="phone" color={WA.greenDeep} size={72}
                                onClick={c.answer} btnRef={answerRef} />
                        </div>
                        <button type="button" onClick={c.callbackLater}
                            className="rounded-full px-4 hover:bg-white/5 flex items-center gap-1.5"
                            style={{ minHeight: 44, fontSize: 14, color: WA.text }}>
                            <Icon name="callback" size={16} /> Call back later
                        </button>
                    </div>
                )}

                {(live || phase === "ending") && (
                    <div className="relative rounded-[28px] px-2 py-3 flex items-start justify-around gap-1 flex-wrap"
                        style={{ backgroundColor: WA.panel }}>
                        <RoundBtn label={c.muted ? "Unmute" : "Mute"} icon={c.muted ? "mic-off" : "mic"} size={56}
                            color={c.muted ? WA.text : "rgba(255,255,255,0.08)"} fg={c.muted ? WA.bg : WA.text}
                            pressed={c.muted} onClick={c.toggleMute} disabled={phase === "ending"} />
                        {(phase === "connecting" || inCall) && audioSupported && (
                            <div className="relative">
                                <RoundBtn label="Audio" icon="audio" size={56} color="rgba(255,255,255,0.08)" fg={WA.text}
                                    pressed={audioOpen} onClick={() => setAudioOpen(!audioOpen)} />
                                {audioOpen && <AudioMenu onClose={() => setAudioOpen(false)} />}
                            </div>
                        )}
                        {inCall && (
                            <RoundBtn label="Chat" icon="chat" size={56} color="rgba(255,255,255,0.08)" fg={WA.text}
                                onClick={c.openChat} />
                        )}
                        {inCall && (
                            <RoundBtn label="Minimise" icon="minimise" size={56} color="rgba(255,255,255,0.08)" fg={WA.text}
                                onClick={c.minimise} />
                        )}
                        <RoundBtn label="End" icon="phone-off" size={56} color={WA.red} onClick={c.hangup}
                            disabled={phase === "ending"} />
                    </div>
                )}

                {ended && (
                    <div className="flex flex-wrap items-center justify-center gap-2">
                        {actions.map((a, i) => (
                            <button key={a.label} type="button" onClick={a.onClick} disabled={a.busy}
                                ref={i === 0 ? primaryRef : undefined}
                                className="rounded-full px-5 font-semibold disabled:opacity-60"
                                style={{
                                    minHeight: 48, fontSize: 15,
                                    backgroundColor: a.primary ? WA.greenDeep : "rgba(255,255,255,0.08)",
                                    color: a.primary ? "#fff" : WA.text,
                                }}>
                                {a.label}
                            </button>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

// ── The minimised call + the "allowed calls" banner — a slim strip in the
// layout flow at the top of the content area (never over a toast or the composer).
export function CallBar(): React.ReactElement | null {
    const c = useCall();
    if (!c) return null;
    const phase = c.phase;

    if (phase === "idle" || (phase === "ended" && !c.minimised)) {
        if (!c.granted || phase !== "idle") return null;
        const first = firstName({ name: c.granted.name, from: c.granted.waId });
        return (
            <div role="status" className="flex items-center gap-3 px-4 flex-shrink-0"
                style={{ minHeight: 48, backgroundColor: WA.bg2, color: WA.text }}>
                <WhatsAppGlyph size={18} />
                <span className="flex-1 min-w-0 truncate" style={{ fontSize: 14 }}>
                    <b className="font-semibold">{first}</b> allowed calls
                </span>
                <button type="button" onClick={c.callGranted}
                    className="rounded-full px-4 font-semibold flex items-center gap-1.5"
                    style={{ minHeight: 36, fontSize: 13, backgroundColor: WA.greenDeep, color: "#fff" }}>
                    <Icon name="phone" size={15} /> Call now
                </button>
                <button type="button" onClick={c.dismissGranted} aria-label="Dismiss"
                    className="rounded-full flex items-center justify-center hover:bg-white/5"
                    style={{ width: 44, height: 44, color: WA.muted }}>
                    <Icon name="x" size={18} />
                </button>
            </div>
        );
    }
    if (!c.minimised) return null;

    const who = callerLabel(c.call);
    if (phase === "ended") {
        // A wrap-up that arrived while minimised: the words + its main action.
        const primary = wrapUpActions(c, c.expand).find((a) => a.primary);
        return (
            <div role="status" className="flex items-center gap-2 px-3 flex-shrink-0"
                style={{ minHeight: 48, backgroundColor: WA.bg2, color: WA.text }}>
                <button type="button" onClick={c.expand} className="flex-1 min-w-0 flex items-center gap-2 text-left"
                    style={{ minHeight: 44 }} aria-label={`Show call with ${who}`}>
                    <WhatsAppGlyph size={16} color={WA.muted} />
                    <span className="truncate" style={{ fontSize: 14 }}>
                        <b className="font-semibold">{who}</b>
                        <span style={{ color: WA.muted }}> · {outcomeWords(c.outcome, c)}</span>
                    </span>
                </button>
                {primary && (
                    <button type="button" onClick={primary.onClick} disabled={primary.busy}
                        className="rounded-full px-3 font-semibold flex-shrink-0"
                        style={{ minHeight: 36, fontSize: 13, backgroundColor: WA.greenDeep, color: "#fff" }}>{primary.label}</button>
                )}
                <button type="button" onClick={c.dismiss}
                    className="rounded-full px-3 flex-shrink-0 hover:bg-white/5"
                    style={{ minHeight: 44, fontSize: 13, color: WA.text }}>Done</button>
            </div>
        );
    }

    const reconnecting = phase === "reconnecting";
    const dot = reconnecting ? WA.amber : WA.green;
    return (
        <div className="flex-shrink-0" style={{ backgroundColor: WA.bg2, color: WA.text }}>
            <div className="flex items-center gap-1 pl-3 pr-2" style={{ minHeight: 48 }}>
                <button type="button" onClick={c.expand} aria-label={`Show call with ${who}`}
                    className="flex-1 min-w-0 flex items-center gap-2 text-left" style={{ minHeight: 44 }}>
                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: dot }} aria-hidden="true" />
                    <span className="truncate font-semibold" style={{ fontSize: 14 }}>{who}</span>
                    <span className="flex items-center gap-1 flex-shrink-0 tabular-nums"
                        style={{ fontSize: 13, color: reconnecting ? WA.amber : WA.muted }}>
                        {reconnecting && <Icon name="wifi-off" size={14} />}
                        <span className="sr-only" aria-live="polite">{phase === "active" ? "Connected" : PHASE_WORDS[phase]}</span>
                        {phase === "active" && c.answeredAt
                            ? <span aria-hidden="true"><Elapsed since={c.answeredAt} /></span>
                            : <span aria-hidden="true">{PHASE_WORDS[phase]}</span>}
                        {phase === "active" && c.recording && <span className="ml-1" style={{ color: "#FF6B81" }}>● Rec</span>}
                    </span>
                </button>
                <button type="button" onClick={c.toggleMute} aria-label={c.muted ? "Unmute" : "Mute"} aria-pressed={c.muted}
                    disabled={phase === "ending"}
                    className="rounded-full flex items-center justify-center flex-shrink-0"
                    style={{ width: 44, height: 44, backgroundColor: c.muted ? WA.text : "transparent", color: c.muted ? WA.bg : WA.text }}>
                    <Icon name={c.muted ? "mic-off" : "mic"} size={18} />
                </button>
                <button type="button" onClick={c.hangup} aria-label="End call" disabled={phase === "ending"}
                    className="rounded-full flex items-center justify-center flex-shrink-0"
                    style={{ width: 44, height: 44, backgroundColor: WA.red, color: "#fff" }}>
                    <Icon name="phone-off" size={18} />
                </button>
            </div>
            <WaitingBanner compact />
        </div>
    );
}

// A call where it happened in the conversation — a designed card, not a
// divider (calls & audio programme, cycle 3, 2026-10-05). It answers what the
// person picking the thread up needs: which way, what happened, who took it,
// when, how long; the recording to play; the voicemail; the transcript, the AI
// summary and the action items when they exist (a later cycle fills those —
// the slots render the moment they do); and, for a call the customer is still
// owed, "Call back" through the normal calling flow (WhatsApp's permission and
// 24-hour rules apply there, not here). Words: lib/callCard.ts.
import React, { useCallback, useState } from "react";
import type { Message } from "@/types";
import { callsApi, type CallTranscriptResp } from "@/lib/api";
import { callStatus, CALL_ICON_PATH, speakerTurns } from "@/lib/callStatus";
import { callCardView, canCallBack, callBackHandle, actionItems, transcriptSlot, whenText, mediaSrc, type CallTone } from "@/lib/callCard";
import { useCallPresence } from "@/lib/callContext";
import { ChannelGlyph } from "@/components/CallStage";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api";

const TONE: Record<CallTone, { ink: string; chip: string; border: string }> = {
    good: { ink: "#128C4B", chip: "#E7F6EC", border: "#d7ecd9" },
    bad: { ink: "#C62828", chip: "#FDECEC", border: "#f3c7c7" },
    warn: { ink: "#A15C00", chip: "#FFF6E5", border: "#f3d9a4" },
    muted: { ink: "#57534e", chip: "#f5f5f4", border: "#e2e8e0" },
    live: { ink: "#128C4B", chip: "#E7F6EC", border: "#b7e4c7" },
};

export function CallCard({ msg, voicemail, onUseReply, composerReady = true, onToast }: {
    msg: Message;
    /** The WhatsApp voicemail audio for this call, folded in from the thread. */
    voicemail?: Message | null;
    onUseReply?: (text: string) => void;
    composerReady?: boolean;
    onToast?: (text: string, type?: "success" | "error" | "warning") => void;
}) {
    const call = msg.call;
    const presence = useCallPresence();
    const [details, setDetails] = useState<CallTranscriptResp | null>(null);
    const [loading, setLoading] = useState<"" | "play" | "transcript">("");
    const [loadErr, setLoadErr] = useState<string | null>(null);
    const [playing, setPlaying] = useState(false);
    const [showTranscript, setShowTranscript] = useState(false);
    const [more, setMore] = useState(false);
    const [used, setUsed] = useState(false);

    // Recording URL + transcript come from the authorised per-call endpoint —
    // never shipped in the thread payload. Fetched once, on first need.
    const loadDetails = useCallback(async (why: "play" | "transcript") => {
        if (!call) return null;
        if (details) return details;
        setLoading(why); setLoadErr(null);
        try {
            const d = await callsApi.transcript(call.call_id);
            setDetails(d);
            return d;
        } catch {
            setLoadErr(why === "play" ? "Couldn't load the recording — try again." : "Couldn't load the transcript — try again.");
            return null;
        } finally { setLoading(""); }
    }, [call, details]);

    if (!call) {
        // An item without its row (never expected): the words alone.
        return (
            <div className="flex justify-center my-2">
                <span className="text-[11px] font-semibold px-3 py-1 rounded-full border bg-white" style={{ borderColor: "#e2e8e0", color: "#1c2917" }}>{msg.text || "Call"}</span>
            </div>
        );
    }

    const v = callCardView(call);
    const st = callStatus(call);
    const t = TONE[v.tone];
    const messengerOut = !!presence?.channels?.messenger?.outbound;
    const offerCallBack = canCallBack(call, messengerOut);
    const busy = !!presence?.busy;
    const ins = call.insights ?? null;
    const summary = (call.summary || "").trim() || null;
    const items = actionItems(ins);
    const facts = ([["Products", ins?.products], ["Objections", ins?.objections]] as const)
        .filter(([, x]) => Array.isArray(x) && x.length > 0) as [string, string[]][];
    const followUp = ins?.follow_up_message?.trim() || null;
    const slot = transcriptSlot(call.transcript_status);
    const at = call.started_at || msg.created_at;
    const recSrc = mediaSrc(details?.recording_url, API_BASE);
    const vmSrc = voicemail?.media_url ? mediaSrc(voicemail.media_url, API_BASE) : null;
    const vmText = (voicemail?.media_caption || "").trim() || null;
    const long = !!summary && summary.length > 220;

    const callBack = async () => {
        if (!presence) return onToast?.("Calling unavailable", "error");
        const ch = v.app === "Messenger" ? "messenger" : "whatsapp";
        const r = await presence.initiateCall(callBackHandle(call), call.name, call.conversation_id ?? null, { channel: ch });
        if (!r.ok) onToast?.(r.error || "Couldn't place the call", "error");
    };
    const play = async () => {
        const d = await loadDetails("play");
        if (d?.recording_url) setPlaying(true);
        else if (d) setLoadErr("No recording was saved for this call.");
    };
    const toggleTranscript = async () => {
        if (!showTranscript) await loadDetails("transcript");
        setShowTranscript((x) => !x);
    };

    // A live call: the compact pill (the call console carries the controls).
    if (v.live) {
        return (
            <div className="flex items-center gap-2 w-full my-2.5" data-call-card="live">
                <div className="flex-1 h-px bg-stone-200" />
                <div className="flex items-center gap-1.5 px-3 py-1 rounded-full border bg-white" style={{ borderColor: t.border }}>
                    <span className="w-2 h-2 rounded-full animate-pulse motion-reduce:animate-none" style={{ backgroundColor: "#25D366" }} aria-hidden="true" />
                    <span className="text-[11px] font-semibold" style={{ color: "#1c2917" }}>{v.title} · {v.outcome}</span>
                    {v.who && <span className="text-[10px]" style={{ color: "#57534e" }}>· {v.who}</span>}
                </div>
                <div className="flex-1 h-px bg-stone-200" />
            </div>
        );
    }

    const turns = showTranscript && details?.transcript ? speakerTurns(details.transcript) : null;

    return (
        <div className="flex justify-center my-3" data-call-card={call.status}>
            <section aria-label={`${v.app} call — ${v.outcome}`}
                className="w-full max-w-[92%] sm:max-w-md rounded-2xl border bg-white px-3.5 py-3 shadow-[0_1px_2px_rgba(28,41,23,0.04)]"
                style={{ borderColor: t.border }}>
                {/* Header: direction icon · title · app · time */}
                <div className="flex items-center gap-2.5">
                    <span className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0" style={{ backgroundColor: t.chip }}>
                        <svg width={15} height={15} viewBox="0 0 24 24" fill="none" stroke={st.light} strokeWidth={2.4}
                            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                            <path d={CALL_ICON_PATH[st.icon]} />
                        </svg>
                    </span>
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5 flex-wrap">
                            <h3 className="text-[13px] font-semibold leading-5" style={{ color: "#1c2917" }}>{v.title}</h3>
                            <span data-call-channel={v.app.toLowerCase()}
                                className="inline-flex items-center gap-1 text-[10px] font-semibold rounded-full pl-0.5 pr-1.5"
                                style={{ color: v.app === "Messenger" ? "#0066D6" : "#128C4B", backgroundColor: v.app === "Messenger" ? "#EAF3FF" : "#E7F6EC" }}>
                                <ChannelGlyph channel={v.app === "Messenger" ? "messenger" : "whatsapp"} size={11} color={v.app === "Messenger" ? undefined : "#128C4B"} />
                                {v.app}
                            </span>
                        </div>
                        <div className="flex items-center gap-1.5 flex-wrap text-[11px] leading-4 mt-0.5">
                            <span className="font-semibold rounded-full px-1.5" style={{ color: t.ink, backgroundColor: t.chip }}>{v.outcome}</span>
                            {v.who && <span style={{ color: "#57534e" }}>{v.who}</span>}
                            {v.duration && <span className="tabular-nums" style={{ color: "#57534e" }}>· {v.duration}</span>}
                        </div>
                    </div>
                    {at && (
                        <time dateTime={at} className="text-[10px] tabular-nums self-start mt-0.5 flex-shrink-0" style={{ color: "#78716c" }}
                            title={new Date(at).toLocaleString()}>
                            {whenText(at)}
                        </time>
                    )}
                </div>

                {/* A missed call: when they called, and the way back */}
                {(v.owed || (v.returned && (call.status === "missed" || call.status === "callback"))) && (
                    <div className="mt-2.5 flex items-center gap-2 flex-wrap">
                        <span className="text-xs" style={{ color: "#57534e" }}>
                            {call.name ? `${call.name.split(/\s+/)[0]} called` : "They called"} {whenText(at, Date.now(), true)}
                        </span>
                        {v.owed && offerCallBack && (
                            <button type="button" onClick={callBack} disabled={busy}
                                title={busy ? "End the current call first" : `Call back on ${v.app}`}
                                className="ml-auto inline-flex items-center gap-1.5 h-9 px-3.5 rounded-full text-xs font-semibold text-white active:scale-95 disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#128C4B]"
                                style={{ backgroundColor: v.app === "Messenger" ? "#0066D6" : "#008069" }}>
                                <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                                    <path d={CALL_ICON_PATH.live} />
                                </svg>
                                {busy ? "On a call" : "Call back"}
                            </button>
                        )}
                        {v.returned && (
                            <span className="ml-auto text-[11px] font-semibold" style={{ color: "#128C4B" }}>✓ Followed up</span>
                        )}
                    </div>
                )}

                {/* Recording */}
                {call.has_recording && (
                    <div className="mt-2.5">
                        {playing && recSrc ? (
                            <audio src={recSrc} controls autoPlay preload="none" className="w-full h-9" aria-label="Call recording" />
                        ) : (
                            <button type="button" onClick={play} disabled={loading === "play"}
                                className="inline-flex items-center gap-1.5 h-9 px-3 rounded-full text-xs font-semibold border hover:brightness-95 disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#128C4B]"
                                style={{ color: "#128C4B", borderColor: "#b7e4c7", backgroundColor: "#fff" }}>
                                <span aria-hidden="true">▶</span>
                                {loading === "play" ? "Loading…" : `Play recording${v.duration ? ` · ${v.duration}` : ""}`}
                            </button>
                        )}
                    </div>
                )}

                {/* WhatsApp voicemail for this call */}
                {voicemail && (
                    <div className="mt-2.5 rounded-xl px-2.5 py-2" style={{ backgroundColor: "#f5f7f2" }}>
                        <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: "#57534e" }}>Voicemail</div>
                        {vmSrc ? <audio src={vmSrc} controls preload="none" className="w-full h-9" aria-label="Voicemail" />
                            : <p className="text-xs" style={{ color: "#57534e" }}>The voicemail audio couldn&apos;t be fetched.</p>}
                        {vmText && <p className="text-xs leading-relaxed whitespace-pre-wrap mt-1" style={{ color: "#334155" }}>{vmText}</p>}
                    </div>
                )}

                {/* Transcript slot */}
                {slot === "working" && (
                    <p className="mt-2.5 text-xs" style={{ color: "#A15C00" }} aria-live="polite">Transcribing the call…</p>
                )}
                {slot === "failed" && (
                    <p className="mt-2.5 text-xs" style={{ color: "#78716c" }}>The transcript couldn&apos;t be made for this call.</p>
                )}

                {/* AI summary · next step · action items */}
                {(summary || ins?.next_action || items.length > 0 || facts.length > 0) && (
                    <div className="mt-2.5 pt-2.5 border-t" style={{ borderColor: "#eef2ea" }}>
                        <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: "#128C4B" }}>Call summary</div>
                        {summary && (
                            <>
                                <p className={`text-xs leading-relaxed whitespace-pre-wrap ${long && !more ? "line-clamp-3" : ""}`} style={{ color: "#1c2917" }}>{summary}</p>
                                {long && (
                                    <button type="button" onClick={() => setMore((x) => !x)} aria-expanded={more}
                                        className="text-[11px] font-semibold mt-0.5 min-h-6" style={{ color: "#128C4B" }}>
                                        {more ? "Show less" : "Show more"}
                                    </button>
                                )}
                            </>
                        )}
                        {ins?.next_action && (
                            <p className="text-xs leading-relaxed mt-1.5" style={{ color: "#1c2917" }}>
                                <span className="font-semibold">Next: </span>{ins.next_action}
                            </p>
                        )}
                        {items.length > 0 && (
                            <div className="mt-1.5">
                                <div className="text-[11px] font-semibold" style={{ color: "#57534e" }}>Action items</div>
                                <ul className="mt-0.5 space-y-0.5">
                                    {items.map((x, i) => (
                                        <li key={i} className="flex gap-1.5 text-xs leading-snug" style={{ color: "#334155" }}>
                                            <span aria-hidden="true" style={{ color: "#128C4B" }}>☐</span>{x}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}
                        {facts.length > 0 && (
                            <dl className="mt-1.5 space-y-0.5 text-[11px] leading-snug">
                                {facts.map(([k, x]) => (
                                    <div key={k} className="flex gap-1.5">
                                        <dt className="font-semibold flex-shrink-0" style={{ color: "#57534e" }}>{k}:</dt>
                                        <dd className="min-w-0" style={{ color: "#334155" }}>{x.join(" · ")}</dd>
                                    </div>
                                ))}
                            </dl>
                        )}
                        {followUp && (
                            <div className="mt-2 rounded-lg px-2.5 py-2" style={{ backgroundColor: "#f3f8f1" }}>
                                <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "#57534e" }}>Suggested reply</div>
                                <p className="text-xs leading-relaxed whitespace-pre-wrap mt-0.5" style={{ color: "#334155" }}>{followUp}</p>
                                {onUseReply && (
                                    <div className="mt-1.5 flex items-center gap-2 flex-wrap">
                                        <button type="button" onClick={() => { onUseReply(followUp); setUsed(true); }}
                                            className="h-9 px-3 rounded-lg text-xs font-semibold text-white active:scale-95 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#128C4B]"
                                            style={{ backgroundColor: "#128C4B" }}>
                                            Use as reply
                                        </button>
                                        <span className="text-[11px]" style={{ color: "#57534e" }} aria-live="polite">
                                            {!composerReady ? (used ? "Saved — pick up the chat to send it" : "Pick up the chat to send it — nothing is sent")
                                                : used ? "In the reply box — edit, then send" : "Goes in the reply box — not sent"}
                                        </span>
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}

                {/* Full transcript, on demand */}
                {slot === "ready" && (
                    <div className="mt-2">
                        <button type="button" onClick={toggleTranscript} aria-expanded={showTranscript}
                            disabled={loading === "transcript"}
                            className="text-[11px] font-semibold min-h-8" style={{ color: "#128C4B" }}>
                            {loading === "transcript" ? "Loading…" : showTranscript ? "Hide transcript"
                                : `Show transcript${details?.language ? ` · ${details.language}` : ""}`}
                        </button>
                        {showTranscript && details?.transcript && (turns ? (
                            <ol aria-label="Transcript" className="mt-1 space-y-1.5 max-h-72 overflow-y-auto pr-1">
                                {turns.map((x, i) => (
                                    <li key={i} className={`flex ${x.who === "Agent" ? "justify-end" : "justify-start"}`}>
                                        <div className="rounded-xl px-2.5 py-1.5 max-w-[88%]" style={{ backgroundColor: x.who === "Agent" ? "#E7F6EC" : "#f5f5f4" }}>
                                            <div className="text-[10px] font-semibold" style={{ color: x.who === "Agent" ? "#128C4B" : "#57534e" }}>{x.who}</div>
                                            <div className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: "#1c2917" }}>{x.text}</div>
                                        </div>
                                    </li>
                                ))}
                            </ol>
                        ) : (
                            <p className="mt-1 text-xs leading-relaxed whitespace-pre-wrap max-h-72 overflow-y-auto" style={{ color: "#334155" }}>{details.transcript}</p>
                        ))}
                    </div>
                )}

                {loadErr && <p className="mt-1.5 text-[11px]" role="alert" style={{ color: "#C62828" }}>{loadErr}</p>}
            </section>
        </div>
    );
}

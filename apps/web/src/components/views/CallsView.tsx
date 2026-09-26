"use client";

// Calls — the WhatsApp call log (docs/CALLING_UX.md §7). A dark call console:
// All · Follow-ups filter, rows grouped Today / Yesterday / date, each with the
// direction icon + the outcome in colour AND words, duration, agent, time and a
// one-tap call-back. A row opens its details: the call's timeline (rang →
// answered by → ended), recording / transcript / summary / insights, and Call
// back · Open chat · Mark follow-up done — with the caller's full CRM panel
// beside it. Live: call events merge rows in place (no reload per event).
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { callsApi, type ApiCall, type CallTranscriptResp } from "@/lib/api";
import { useWs } from "@/lib/websocket";
import { useCall } from "@/lib/callContext";
import { callStatus, fmtCallDuration, upsertCall, CALL_ICON_PATH } from "@/lib/callStatus";
import type { SharedViewProps } from "@/types";
import { CustomerSidebar } from "@/components/ui/CustomerSidebar";

const C = {
    text: "#e9edef", sub: "#9fb3a8", faint: "#6b8577", line: "rgba(255,255,255,0.06)",
    green: "#2ad17f", greenBtn: "#00A884", red: "#ff6b70",
};

const AV = ["#3b6ea5", "#a5417d", "#b5892f", "#3c8c5a", "#8a4fc4", "#b24a4a"];
const avatarColor = (s: string) => AV[[...(s || "?")].reduce((a, c) => a + c.charCodeAt(0), 0) % AV.length];
const whoOf = (c: ApiCall) => c.name || (c.wa_id ? `+${c.wa_id}` : "Unknown caller");
const initialsOf = (who: string) =>
    who.replace("+", "").split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase() || "?";

const clock = (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "";

function dayLabel(iso: string | null): string {
    if (!iso) return "Earlier";
    const d = new Date(iso);
    const today = new Date();
    const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
    const diff = Math.round((startOf(today) - startOf(d)) / 86_400_000);
    if (diff === 0) return "Today";
    if (diff === 1) return "Yesterday";
    return d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short",
        ...(d.getFullYear() !== today.getFullYear() ? { year: "numeric" } : {}) });
}

function CallIcon({ c, size = 13 }: { c: ApiCall; size?: number }) {
    const st = callStatus(c);
    return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={st.dark} strokeWidth={2.2}
            strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="flex-shrink-0">
            <path d={CALL_ICON_PATH[st.icon]} />
        </svg>
    );
}

const PhoneGlyph = ({ size = 16 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d={CALL_ICON_PATH.live} />
    </svg>
);

interface CallsViewProps extends SharedViewProps {
    onOpenConversation?: (key: string) => void;
    /** Deep-link (e.g. from the hub's order page): focus this customer's calls. */
    focusWaId?: string | null;
    onConsumeFocus?: () => void;
}

// The transcript + AI summary + insights for one call. Lazily fetches the
// transcript, offers on-demand transcription (the free path — CPU is spent
// only when you ask), and polls while it runs.
function CallTranscript({ call, onOpenChat }: { call: ApiCall; onOpenChat?: () => void }): React.ReactElement {
    const callId = call.call_id;
    const [data, setData] = useState<CallTranscriptResp | null>(null);
    const [failed, setFailed] = useState(false);
    const [showFull, setShowFull] = useState(false);
    const [busy, setBusy] = useState(false);
    const [err, setErr] = useState<string | null>(null);

    const load = useCallback(() => {
        callsApi.transcript(callId)
            .then((d) => { setData(d); setFailed(false); })
            .catch(() => setFailed(true));
    }, [callId]);
    // Reload when the live row says the transcript moved (call_update).
    useEffect(() => { load(); }, [load, call.transcript_status, call.summary]);
    useEffect(() => {
        if (!data || (data.status !== "pending" && data.status !== "processing")) return;
        // A transcription job takes ~1-2 min — 5s resolution is plenty, and a
        // hidden tab shouldn't keep polling for it.
        const t = setInterval(() => {
            if (typeof document === "undefined" || document.visibilityState === "visible") load();
        }, 5000);
        return () => clearInterval(t);
    }, [data, load]);

    const runTranscribe = useCallback(async () => {
        setBusy(true); setErr(null);
        try { await callsApi.transcribe(callId); await load(); }
        catch (e) {
            setErr(String((e as Error)?.message || "").includes("409")
                ? "Turn on transcription on the server first (WHISPER_ENABLED)."
                : "Couldn't start transcription.");
        } finally { setBusy(false); }
    }, [callId, load]);

    const label: React.CSSProperties = { fontSize: 11, textTransform: "uppercase", letterSpacing: 0.6, color: C.green, marginBottom: 4 };
    if (failed && !data) {
        return (
            <div style={{ fontSize: 13, color: C.sub }}>
                Couldn&apos;t load the recording details.{" "}
                <button type="button" onClick={load} style={{ color: C.green, textDecoration: "underline", minHeight: 32 }}>Retry</button>
            </div>
        );
    }
    if (!data) return <div style={{ color: C.faint, fontSize: 13 }}>Loading recording…</div>;
    const st = data.status;
    const ins = data.insights ?? call.insights ?? null;
    const list = (title: string, items?: string[]) => items && items.length > 0 && (
        <div style={{ marginTop: 8 }}>
            <div style={{ fontSize: 12, color: C.sub, fontWeight: 600 }}>{title}</div>
            <ul style={{ margin: "2px 0 0 16px", listStyle: "disc", fontSize: 13, color: C.text, lineHeight: 1.5 }}>
                {items.map((x, i) => <li key={i}>{x}</li>)}
            </ul>
        </div>
    );

    return (
        <div className="space-y-2">
            {(data.summary || ins) && (
                <div style={{ background: "rgba(37,211,102,0.06)", border: "1px solid rgba(37,211,102,0.15)", borderRadius: 12, padding: "10px 12px" }}>
                    <div style={label}>Call summary</div>
                    {data.summary && <div style={{ fontSize: 13, color: "#cfe9d9", whiteSpace: "pre-wrap", lineHeight: 1.5 }}>{data.summary}</div>}
                    {ins?.next_action && (
                        <div style={{ fontSize: 13, color: C.text, marginTop: 8 }}>
                            <span style={{ fontWeight: 600 }}>Next: </span>{ins.next_action}
                        </div>
                    )}
                    {list("Products", ins?.products)}
                    {list("Objections", ins?.objections)}
                    {list("Commitments", ins?.commitments)}
                    {ins?.follow_up_message && (
                        <div style={{ marginTop: 10, background: "rgba(255,255,255,0.04)", borderRadius: 10, padding: "8px 10px" }}>
                            <div style={{ fontSize: 12, color: C.sub, fontWeight: 600 }}>Suggested follow-up</div>
                            <div style={{ fontSize: 13, color: C.text, whiteSpace: "pre-wrap", lineHeight: 1.5, marginTop: 2 }}>{ins.follow_up_message}</div>
                            {onOpenChat && (
                                <button type="button" onClick={onOpenChat}
                                    className="mt-2 rounded-full px-3 font-semibold"
                                    style={{ minHeight: 36, fontSize: 12, color: "#0b1410", background: C.green }}>
                                    Open chat
                                </button>
                            )}
                        </div>
                    )}
                </div>
            )}
            {st === "done" && data.transcript && (
                <>
                    <button type="button" onClick={() => setShowFull((v) => !v)}
                        style={{ fontSize: 12, color: C.sub, minHeight: 32 }}>
                        {showFull ? "Hide" : "Show"} full transcript{data.language ? ` · ${data.language}` : ""}
                    </button>
                    {showFull && (
                        <div style={{ fontSize: 12, color: C.sub, whiteSpace: "pre-wrap", lineHeight: 1.6 }}>{data.transcript}</div>
                    )}
                </>
            )}
            {(st === "pending" || st === "processing") && (
                <div style={{ fontSize: 13, color: "#f5c451" }}>Transcribing… this runs on our server, usually ~1–2 min.</div>
            )}
            {st === "recorded" && (
                <div className="flex items-center gap-3 flex-wrap">
                    <span style={{ fontSize: 13, color: C.sub }}>Recording saved.</span>
                    <button type="button" onClick={runTranscribe} disabled={busy}
                        style={{ fontSize: 13, fontWeight: 600, color: "#0b1410", background: C.green, borderRadius: 999, padding: "0 16px", minHeight: 40, opacity: busy ? 0.6 : 1 }}>
                        {busy ? "Starting…" : "Transcribe & summarise"}
                    </button>
                </div>
            )}
            {st === "failed" && (
                <div style={{ fontSize: 13, color: C.red }}>
                    Transcription failed.{" "}
                    <button type="button" onClick={runTranscribe} disabled={busy}
                        style={{ color: C.green, textDecoration: "underline", minHeight: 32 }}>Retry</button>
                </div>
            )}
            {(st === "none" || !st) && !data.has_recording && (
                <div style={{ fontSize: 13, color: C.faint }}>No recording was captured for this call.</div>
            )}
            {err && <div style={{ fontSize: 13, color: C.red }}>{err}</div>}
        </div>
    );
}

// rang → answered by → ended, with the waits and the talk time.
function Timeline({ c }: { c: ApiCall }) {
    const out = c.direction === "outbound";
    const st = callStatus(c);
    const secs = (a?: string | null, b?: string | null) =>
        a && b ? Math.max(0, Math.round((new Date(b).getTime() - new Date(a).getTime()) / 1000)) : null;
    const rang = secs(c.started_at, c.answered_at ?? c.ended_at);
    const steps: { label: string; at?: string | null; color: string }[] = [
        { label: out ? `Called${c.agent_name ? ` by ${c.agent_name}` : ""}` : "Rang the team", at: c.started_at, color: C.sub },
    ];
    if (c.answered_at) {
        steps.push({
            label: `${out ? "Customer answered" : `Answered${c.agent_name ? ` by ${c.agent_name}` : ""}`}${rang !== null ? ` · after ${rang}s` : ""}`,
            at: c.answered_at, color: C.green,
        });
    }
    if (st.live) {
        steps.push({ label: st.word, color: C.green });
    } else {
        const talk = c.duration ?? secs(c.answered_at, c.ended_at);
        const words = c.answered_at
            ? `Ended${talk ? ` · ${fmtCallDuration(talk)} talk time` : ""}`
            : `${st.word}${rang !== null && !c.answered_at ? ` · rang ${rang}s` : ""}`
              + (c.agent_name && ["declined", "callback", "cancelled"].includes(c.status) ? ` · ${c.agent_name}` : "");
        steps.push({ label: words, at: c.ended_at, color: st.dark });
    }
    return (
        <ol className="relative" style={{ marginLeft: 6 }}>
            {steps.map((s, i) => (
                <li key={i} className="relative flex items-start gap-3" style={{ paddingBottom: i < steps.length - 1 ? 12 : 0 }}>
                    {i < steps.length - 1 && <span className="absolute" style={{ left: 3, top: 12, bottom: 0, width: 2, background: C.line }} />}
                    <span className="rounded-full flex-shrink-0" style={{ width: 8, height: 8, marginTop: 5, background: s.color }} />
                    <span className="flex-1 min-w-0" style={{ fontSize: 13, color: C.text }}>{s.label}</span>
                    {s.at && <span className="flex-shrink-0 tabular-nums" style={{ fontSize: 12, color: C.faint }}>{clock(s.at)}</span>}
                </li>
            ))}
        </ol>
    );
}

function CallDetail({ c, onBack, onCallBack, onOpenChat, onFollowUpDone, busyDone, isMobile }: {
    c: ApiCall; onBack: () => void; onCallBack?: () => void; onOpenChat?: () => void;
    onFollowUpDone: () => void; busyDone: boolean; isMobile: boolean;
}) {
    const who = whoOf(c);
    const st = callStatus(c);
    return (
        <div className="rounded-2xl overflow-hidden"
            style={{ background: "#0b1410", border: "1px solid rgba(37,211,102,0.14)", color: C.text }}>
            <div className="px-4 pt-3 pb-4" style={{ borderBottom: `1px solid ${C.line}` }}>
                <div className="flex items-center justify-between" style={{ minHeight: 44 }}>
                    <button type="button" onClick={onBack} className="flex items-center gap-1 rounded-full px-2 -ml-2"
                        style={{ minHeight: 44, fontSize: 13, color: C.sub }} aria-label={isMobile ? "Back to all calls" : "Close call details"}>
                        {isMobile ? "← All calls" : "Close"}
                    </button>
                    {c.follow_up_open && (
                        <span className="rounded-full px-2.5 py-1" style={{ fontSize: 12, fontWeight: 600, color: "#ffb3b5", background: "rgba(242,85,90,0.16)" }}>
                            Follow-up open
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-3 mt-1">
                    <div className="flex items-center justify-center rounded-full flex-shrink-0"
                        style={{ width: 48, height: 48, backgroundColor: avatarColor(who), color: "#fff", fontSize: 16, fontWeight: 600 }}>
                        {initialsOf(who)}
                    </div>
                    <div className="min-w-0">
                        <div className="truncate" style={{ fontSize: 18, fontWeight: 600 }}>{who}</div>
                        <div className="flex items-center gap-1.5 flex-wrap" style={{ fontSize: 13, color: st.dark }}>
                            <CallIcon c={c} />
                            <span>{st.word}{c.direction === "outbound" ? " · outgoing" : " · incoming"}</span>
                            {c.duration ? <span style={{ color: C.sub }}>· {fmtCallDuration(c.duration)}</span> : null}
                            {c.name && c.wa_id && <span style={{ color: C.faint }}>· +{c.wa_id}</span>}
                        </div>
                    </div>
                </div>
                <div className="flex flex-wrap gap-2 mt-4">
                    {onCallBack && (
                        <button type="button" onClick={onCallBack}
                            className="flex items-center gap-1.5 rounded-full px-4 font-semibold"
                            style={{ minHeight: 44, fontSize: 14, background: C.greenBtn, color: "#fff" }}>
                            <PhoneGlyph /> Call back
                        </button>
                    )}
                    {onOpenChat && (
                        <button type="button" onClick={onOpenChat}
                            className="rounded-full px-4 font-semibold"
                            style={{ minHeight: 44, fontSize: 14, background: "rgba(255,255,255,0.08)", color: C.text }}>
                            Open chat
                        </button>
                    )}
                    {c.follow_up_open && (
                        <button type="button" onClick={onFollowUpDone} disabled={busyDone}
                            className="rounded-full px-4 font-semibold disabled:opacity-60"
                            style={{ minHeight: 44, fontSize: 14, background: "rgba(255,255,255,0.08)", color: C.text }}>
                            {busyDone ? "Saving…" : "Mark follow-up done"}
                        </button>
                    )}
                </div>
            </div>
            <div className="px-4 py-4" style={{ borderBottom: `1px solid ${C.line}` }}>
                <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.6, color: C.faint, marginBottom: 8 }}>Timeline</div>
                <Timeline c={c} />
            </div>
            <div className="px-4 py-4">
                <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.6, color: C.faint, marginBottom: 8 }}>Recording &amp; notes</div>
                {c.has_recording || c.summary || (c.transcript_status && c.transcript_status !== "none")
                    ? <CallTranscript call={c} onOpenChat={onOpenChat} />
                    : <div style={{ fontSize: 13, color: C.faint }}>
                          {st.live ? "The call is still going." : c.answered_at ? "No recording was captured for this call." : "Not connected — nothing was recorded."}
                      </div>}
            </div>
        </div>
    );
}

function Skeleton() {
    return (
        <div aria-busy="true" aria-label="Loading calls">
            {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-5 py-3.5" style={{ borderTop: `1px solid ${C.line}` }}>
                    <div className="rounded-full animate-pulse" style={{ width: 40, height: 40, background: "rgba(255,255,255,0.07)" }} />
                    <div className="flex-1 space-y-2">
                        <div className="rounded animate-pulse" style={{ height: 11, width: "45%", background: "rgba(255,255,255,0.08)" }} />
                        <div className="rounded animate-pulse" style={{ height: 9, width: "30%", background: "rgba(255,255,255,0.05)" }} />
                    </div>
                </div>
            ))}
        </div>
    );
}

export function CallsView({ isMobile, onOpenConversation, onToast, focusWaId, onConsumeFocus }: CallsViewProps): React.ReactElement {
    const ws = useWs();
    const callCtx = useCall();
    const [calls, setCalls] = useState<ApiCall[] | null>(null);
    const [loadError, setLoadError] = useState(false);
    const [filter, setFilter] = useState<"all" | "follow_up">("all");
    const [followUps, setFollowUps] = useState<ApiCall[] | null>(null);
    // Clicking a call opens its details + the caller's FULL CRM panel right
    // here (profile, lead score, orders) — no bouncing to the inbox.
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [busyDone, setBusyDone] = useState<string | null>(null);
    const [online, setOnline] = useState(true);
    const [notifyHidden, setNotifyHidden] = useState(true);

    const load = useCallback(() => {
        setLoadError(false);
        Promise.all([callsApi.list({ limit: 100 }), callsApi.list({ view: "follow_up", limit: 100 })])
            .then(([all, fu]) => { setCalls(all); setFollowUps(fu); })
            .catch(() => setLoadError(true));
    }, []);
    useEffect(() => {
        load();
        // Live events keep the list current; this is only the missed-event
        // fallback, so a slow cadence is enough.
        const t = setInterval(() => {
            if (typeof document === "undefined" || document.visibilityState === "visible") load();
        }, 60000);
        return () => clearInterval(t);
    }, [load]);

    useEffect(() => {
        const sync = () => setOnline(navigator.onLine);
        sync();
        const back = () => { sync(); load(); };
        window.addEventListener("online", back);
        window.addEventListener("offline", sync);
        return () => { window.removeEventListener("online", back); window.removeEventListener("offline", sync); };
    }, [load]);

    // Offer background-tab call notifications once, here where calls are the topic.
    useEffect(() => {
        try { setNotifyHidden(!!localStorage.getItem("neema:call-notify-dismissed")); } catch { setNotifyHidden(false); }
    }, []);

    // Live: rows change in place. call_update carries the full row; the other
    // events patch the fields they know about.
    const patchRow = useCallback((callId: string, fields: Partial<ApiCall>) => {
        const apply = (list: ApiCall[] | null) =>
            list ? list.map((c) => (c.call_id === callId ? { ...c, ...fields } : c)) : list;
        setCalls(apply);
        setFollowUps(apply);
    }, []);
    const reloadSoon = useRef<ReturnType<typeof setTimeout> | null>(null);
    useEffect(() => {
        if (!ws) return;
        const on = (e: { type?: string; call?: ApiCall; call_id?: string; outcome?: string; duration?: number | null;
                         agent_name?: string | null; agent_id?: string | null; direction?: string }) => {
            if (e?.type === "call_update" && e.call) {
                const row = e.call;
                setCalls((prev) => (prev ? upsertCall(prev, row) : prev));
                setFollowUps((prev) => {
                    if (!prev) return prev;
                    const rest = prev.filter((c) => c.call_id !== row.call_id);
                    return row.follow_up_open ? upsertCall(rest, row) : rest;
                });
            } else if (e?.type === "call_ended" && e.call_id) {
                patchRow(e.call_id, {
                    status: e.outcome || "completed",
                    ...(e.duration != null ? { duration: e.duration } : {}),
                    ...(e.agent_name ? { agent_name: e.agent_name } : {}),
                    ended_at: new Date().toISOString(),
                });
                // Follow-up flags are decided server-side — re-read them once, quietly.
                if (e.outcome === "missed" || e.outcome === "callback") {
                    if (reloadSoon.current) clearTimeout(reloadSoon.current);
                    reloadSoon.current = setTimeout(load, 1500);
                }
            } else if (e?.type === "call_answered" && e.call_id) {
                patchRow(e.call_id, { status: "answered", answered_at: new Date().toISOString(),
                    ...(e.agent_name ? { agent_name: e.agent_name } : {}) });
            }
        };
        ws.on("event", on);
        return () => { ws.off("event", on); if (reloadSoon.current) clearTimeout(reloadSoon.current); };
    }, [ws, patchRow, load]);

    // Deep-link focus: once the log has loaded, open the caller panel for the
    // customer the link named. Waits for `calls` so a cold navigation from the
    // hub doesn't consume the key against an empty list.
    useEffect(() => {
        if (!focusWaId || calls === null) return;
        const key = focusWaId.replace(/^\+/, "");
        const match = [...calls]
            .sort((a, b) => (b.started_at ?? "").localeCompare(a.started_at ?? ""))
            .find((c) => c.wa_id === key);
        if (match) setSelectedId(match.call_id);
        else onToast?.("No calls with this customer yet — showing the full call log.", "warning");
        onConsumeFocus?.();
    }, [focusWaId, calls, onConsumeFocus, onToast]);

    const shown = filter === "follow_up" ? followUps : calls;
    const followCount = followUps?.length ?? 0;
    const selected = useMemo(
        () => (selectedId ? (calls ?? []).find((c) => c.call_id === selectedId)
            ?? (followUps ?? []).find((c) => c.call_id === selectedId) ?? null : null),
        [selectedId, calls, followUps]);

    const groups = useMemo(() => {
        const out: { label: string; rows: ApiCall[] }[] = [];
        for (const c of shown ?? []) {
            const label = dayLabel(c.started_at);
            const last = out[out.length - 1];
            if (last && last.label === label) last.rows.push(c);
            else out.push({ label, rows: [c] });
        }
        return out;
    }, [shown]);

    const callBack = useCallback(async (c: ApiCall) => {
        if (!c.wa_id) return;
        if (!callCtx) return onToast("Calling unavailable", "error");
        const r = await callCtx.initiateCall(c.wa_id, c.name, c.conversation_id ?? null);
        if (!r.ok) onToast(r.error || "Couldn't place the call", "error");
    }, [callCtx, onToast]);

    const markDone = useCallback(async (c: ApiCall) => {
        setBusyDone(c.call_id);
        patchRow(c.call_id, { follow_up_open: false, follow_up_done_at: new Date().toISOString() });
        setFollowUps((prev) => (prev ? prev.filter((x) => x.call_id !== c.call_id) : prev));
        try { await callsApi.followUpDone(c.call_id); onToast("Follow-up marked done"); }
        catch {
            patchRow(c.call_id, { follow_up_open: true, follow_up_done_at: null });
            setFollowUps((prev) => (prev ? upsertCall(prev, { ...c, follow_up_open: true }) : prev));
            onToast("Couldn't mark it done — try again", "error");
        } finally { setBusyDone(null); }
    }, [patchRow, onToast]);

    // The caller panel: a synthetic conversation handle is enough — the sidebar
    // fetches the real CRM profile by wa_id itself.
    const selConv = selected?.wa_id
        ? ({
              id: `call:${selected.call_id}`,
              wa_id: selected.wa_id,
              external_id: selected.wa_id,
              channel: "whatsapp",
              name: selected.name,
              last_message_at: selected.started_at,
          } as unknown as React.ComponentProps<typeof CustomerSidebar>["conversation"])
        : null;

    const showList = !isMobile || !selected;
    const notifyOffer = !notifyHidden && callCtx?.notifyPermission === "default";

    return (
        <div className="h-full overflow-y-auto w-full" style={{ backgroundColor: "#f6f7f2" }}>
            <div className={`mx-auto px-3 sm:px-6 py-4 sm:py-6 flex gap-6 ${selected ? "justify-center" : ""}`}
                 style={{ maxWidth: selected && !isMobile ? 1100 : 600 }}>
            {showList && (
            <div className="flex-1 min-w-0" style={{ maxWidth: 600 }}>
                <div className="rounded-2xl overflow-hidden"
                    style={{ background: "radial-gradient(120% 60% at 50% 0%, #123626 0%, #0b1410 60%)", border: "1px solid rgba(37,211,102,0.14)", boxShadow: "0 20px 50px rgba(0,0,0,0.25)" }}>

                    <div className="px-5 pt-5 pb-3">
                        <div className="text-white" style={{ fontSize: 22, fontWeight: 500 }}>Calls</div>
                        <div style={{ fontSize: 13, color: "#7f9b8b", marginTop: 2 }}>WhatsApp voice calls</div>
                        <div role="tablist" aria-label="Filter calls" className="flex gap-2 mt-4">
                            {([["all", "All"], ["follow_up", "Follow-ups"]] as const).map(([id, label]) => {
                                const on = filter === id;
                                return (
                                    <button key={id} type="button" role="tab" aria-selected={on} onClick={() => setFilter(id)}
                                        className="rounded-full px-4 flex items-center gap-1.5"
                                        style={{ minHeight: 40, fontSize: 13, fontWeight: 600,
                                                 background: on ? "rgba(37,211,102,0.2)" : "rgba(255,255,255,0.05)",
                                                 color: on ? C.green : C.sub,
                                                 border: on ? "1px solid rgba(37,211,102,0.4)" : "1px solid transparent" }}>
                                        {label}
                                        {id === "follow_up" && followCount > 0 && (
                                            <span className="rounded-full px-1.5" style={{ fontSize: 11, background: "rgba(242,85,90,0.25)", color: "#ffb3b5" }}>
                                                {followCount}
                                            </span>
                                        )}
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {!online && (
                        <div role="status" className="mx-5 mb-3 rounded-xl px-3 py-2" style={{ fontSize: 13, background: "rgba(245,182,66,0.12)", color: "#f5c451" }}>
                            You&apos;re offline — showing the last loaded calls. Calls can&apos;t ring here until you&apos;re back.
                        </div>
                    )}
                    {notifyOffer && (
                        <div className="mx-5 mb-3 rounded-xl px-3 py-2 flex items-center gap-2 flex-wrap" style={{ background: "rgba(255,255,255,0.05)" }}>
                            <span className="flex-1 min-w-0" style={{ fontSize: 13, color: C.text }}>
                                Get told about calls while Neema is in another tab.
                            </span>
                            <button type="button" onClick={() => callCtx?.requestNotifications()}
                                className="rounded-full px-3 font-semibold" style={{ minHeight: 36, fontSize: 12, background: C.greenBtn, color: "#fff" }}>
                                Turn on
                            </button>
                            <button type="button" onClick={() => {
                                setNotifyHidden(true);
                                try { localStorage.setItem("neema:call-notify-dismissed", "1"); } catch { /* private mode */ }
                            }} className="rounded-full px-2" style={{ minHeight: 36, fontSize: 12, color: C.sub }}>
                                Not now
                            </button>
                        </div>
                    )}

                    <div>
                        {shown === null && loadError ? (
                            <div className="px-6 py-12 text-center">
                                <div style={{ color: "#cfe9d9", fontSize: 15, fontWeight: 500 }}>Couldn&apos;t load calls</div>
                                <button type="button" onClick={load} className="mt-3 rounded-full px-5 font-semibold"
                                    style={{ minHeight: 44, fontSize: 14, background: C.greenBtn, color: "#fff" }}>Retry</button>
                            </div>
                        ) : shown === null ? (
                            <Skeleton />
                        ) : shown.length === 0 ? (
                            <div className="px-6 py-14 text-center">
                                <div style={{ color: "#cfe9d9", fontSize: 15, fontWeight: 500 }}>
                                    {filter === "follow_up" ? "No follow-ups — every caller has been called back" : "No calls yet — incoming WhatsApp calls ring here"}
                                </div>
                                {filter === "all" && (
                                    <div style={{ color: "#7f9b8b", fontSize: 13, marginTop: 6 }}>
                                        Keep Neema open — a call takes over the screen when it rings.
                                    </div>
                                )}
                            </div>
                        ) : (
                            <>
                            {loadError && (
                                <div className="mx-5 mb-2 flex items-center gap-2" style={{ fontSize: 12, color: "#f5c451" }}>
                                    Couldn&apos;t refresh the list.
                                    <button type="button" onClick={load} style={{ color: C.green, textDecoration: "underline", minHeight: 32 }}>Retry</button>
                                </div>
                            )}
                            {groups.map((g) => (
                                <section key={g.label} aria-label={g.label}>
                                    <div className="px-5 pt-3 pb-1.5" style={{ fontSize: 12, fontWeight: 600, color: C.faint, textTransform: "uppercase", letterSpacing: 0.6 }}>
                                        {g.label}
                                    </div>
                                    {g.rows.map((c) => {
                                        const st = callStatus(c);
                                        const who = whoOf(c);
                                        const sel = selected?.call_id === c.call_id;
                                        const hasNote = !!c.summary;
                                        return (
                                            <div key={c.call_id} className="flex items-center gap-3 px-5 py-2.5 transition-colors hover:bg-white/[0.03]"
                                                style={{ borderTop: `1px solid ${C.line}`, backgroundColor: sel ? "rgba(37,211,102,0.08)" : undefined }}>
                                                <button type="button" onClick={() => setSelectedId(c.call_id)}
                                                    className="flex-1 min-w-0 flex items-center gap-3 text-left"
                                                    style={{ minHeight: 48 }} aria-label={`${who}, ${st.word}, details`}>
                                                    <span className="flex items-center justify-center rounded-full flex-shrink-0"
                                                        style={{ width: 40, height: 40, backgroundColor: avatarColor(who), color: "#fff", fontSize: 13, fontWeight: 500 }}>
                                                        {initialsOf(who)}
                                                    </span>
                                                    <span className="flex-1 min-w-0">
                                                        <span className="flex items-center gap-1.5">
                                                            <span className="truncate" style={{ fontSize: 14, fontWeight: 500, color: st.icon === "missed" ? st.dark : C.text }}>{who}</span>
                                                            {c.follow_up_open && (
                                                                <span className="flex-shrink-0 rounded-full px-1.5" style={{ fontSize: 10, fontWeight: 600, background: "rgba(242,85,90,0.2)", color: "#ffb3b5" }}>
                                                                    Follow up
                                                                </span>
                                                            )}
                                                        </span>
                                                        <span className="flex items-center gap-1.5 flex-wrap" style={{ fontSize: 12, color: st.dark, marginTop: 1 }}>
                                                            <CallIcon c={c} />
                                                            <span>{st.word}</span>
                                                            {c.duration ? <span style={{ color: "#7f9b8b" }}>· {fmtCallDuration(c.duration)}</span> : null}
                                                            {c.agent_name ? <span style={{ color: "#7f9b8b" }}>· {c.agent_name.split(" ")[0]}</span> : null}
                                                            {(c.has_recording || hasNote) && (
                                                                <span title={hasNote ? "Has a call summary" : "Recorded"} style={{ color: hasNote ? C.green : "#7f9b8b" }}>
                                                                    · {hasNote ? "Summary" : "Recorded"}
                                                                </span>
                                                            )}
                                                        </span>
                                                    </span>
                                                    <span className="flex-shrink-0 tabular-nums" style={{ fontSize: 12, color: C.faint }}>{clock(c.started_at)}</span>
                                                </button>
                                                {c.wa_id && (
                                                    <button type="button" onClick={() => callBack(c)}
                                                        aria-label={`Call ${who} back on WhatsApp`} title="Call back on WhatsApp"
                                                        disabled={!!callCtx && callCtx.phase !== "idle" && callCtx.phase !== "ended"}
                                                        className="flex-shrink-0 flex items-center justify-center rounded-full transition-transform hover:scale-105 disabled:opacity-40"
                                                        style={{ width: 44, height: 44, backgroundColor: "rgba(37,211,102,0.16)", color: C.green, border: "1px solid rgba(37,211,102,0.3)" }}>
                                                        <PhoneGlyph size={17} />
                                                    </button>
                                                )}
                                            </div>
                                        );
                                    })}
                                </section>
                            ))}
                            <div style={{ height: 8 }} />
                            </>
                        )}
                    </div>
                </div>
            </div>
            )}

            {/* ── The call's details + the caller's full CRM panel ─────────────── */}
            {selected && (
                <div className={isMobile ? "flex-1 min-w-0 space-y-3" : "sticky top-6 self-start flex-shrink-0 space-y-3"}
                     style={isMobile ? undefined : { width: 420 }}>
                    <CallDetail
                        c={selected}
                        isMobile={!!isMobile}
                        onBack={() => setSelectedId(null)}
                        onCallBack={selected.wa_id ? () => callBack(selected) : undefined}
                        onOpenChat={selected.wa_id && onOpenConversation ? () => onOpenConversation(selected.wa_id!) : undefined}
                        onFollowUpDone={() => markDone(selected)}
                        busyDone={busyDone === selected.call_id}
                    />
                    {selConv && (
                        <div className="rounded-2xl overflow-hidden shadow-xl"
                             style={{ border: "1px solid #e7e5e4",
                                      maxHeight: isMobile ? undefined : "calc(100vh - 160px)", display: "flex" }}>
                            <CustomerSidebar
                                conversation={selConv}
                                onToast={onToast}
                                onClose={() => setSelectedId(null)}
                                onOpenIdentity={(channel, externalId) => onOpenConversation?.(externalId)}
                                className="w-full flex flex-col overflow-hidden bg-white"
                            />
                        </div>
                    )}
                </div>
            )}
            </div>
        </div>
    );
}

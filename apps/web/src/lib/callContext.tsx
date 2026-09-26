"use client";

// Shared WhatsApp-call state + WebRTC, lifted to context so the call UI can
// render INSIDE the dashboard content area (sidebar stays visible) instead of a
// full-screen blackout. CallProvider owns the socket listener, the peer
// connection, the ringtone and the audio elements; useCall() exposes the state
// + actions to whatever renders the card (CallStage) or starts a call (the
// customer panel, the Calls view).
//
// The phases, outcomes and words are the contract in docs/CALLING_UX.md §3/§4:
//
//   idle → incoming ─answer→ connecting → active ⇄ reconnecting → ending → ended
//   idle → placing ─connect→ ringing_out ─customer answers→ connecting → active …
//
// Exactly one phase at a time, and every path — a colleague answering, the
// caller giving up, a dropped connection, a failed request — lands on `ended`
// with an `outcome` the card turns into words and a next action. The server is
// the source of truth: the live events (ws:channel:calls) move us at once, and
// a re-read of GET /admin/calls/{id} corrects us after the socket or the tab
// comes back.
import React, {
    createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, ReactNode,
} from "react";
import { useSession } from "next-auth/react";
import { useWs } from "@/lib/websocket";
import {
    callsApi, apiErrorStatus, apiErrorDetail, isNetworkError,
    type ApiCall, type CallIceConfig,
} from "@/lib/api";

export type CallPhase =
    | "idle"
    | "incoming"      // ringing this device (inbound)
    | "placing"       // outbound: building the offer / asking Meta ("Calling…")
    | "ringing_out"   // outbound: Meta is ringing the customer ("Ringing…")
    | "connecting"    // answered, media not flowing yet
    | "active"        // media flowing; the timer runs from answeredAt
    | "reconnecting"  // media path dropped; ≤ 10 s to recover
    | "ending"        // hang-up sent — a moment at most
    | "ended";        // wrap-up card: `outcome` + next actions

export type CallOutcome =
    | "completed"
    | "answered_elsewhere"
    | "declined"
    | "missed"
    | "callback"
    | "no_answer"
    | "cancelled"
    | "connection_lost"
    | "failed"
    | "permission_needed"
    | "permission_requested"
    | "mic_blocked";

export interface CallState {
    /** Meta's call id; "pending" while an outbound call has not got one yet. */
    callId: string;
    /** The customer's WhatsApp number (digits, no +). */
    from: string;
    name?: string | null;
    direction: "inbound" | "outbound";
    conversationId?: string | null;
    personId?: string | null;
}

/** A second call ringing while this device is on one (no hold in the API). */
export interface WaitingCall { callId: string; from: string; name?: string | null; }

export interface AudioDevice { deviceId: string; label: string; }

interface CallCtx {
    phase: CallPhase;
    call: CallState | null;
    outcome: CallOutcome | null;
    /** The server's words (a failed call), or an error to show under the status. */
    reason: string | null;
    /** Who answered / declined when it was not this agent. */
    byAgent: string | null;
    /** Seconds connected, for the wrap-up. */
    duration: number | null;
    /** Date.now() at the moment media connected — the timer's zero. */
    answeredAt: number | null;
    /** Inline notice on the live card, e.g. "No connection — can't answer yet". */
    notice: string | null;
    minimised: boolean;
    outbound: boolean;   // true while we placed the call (ringing THEM)
    muted: boolean;
    /** True only while a MediaRecorder is actually running. */
    recording: boolean;
    /** After the call: "Recording saved — summary in a minute" etc. (§7). */
    recordingNote: string | null;
    waiting: WaitingCall | null;
    /** A customer this agent asked just allowed calls. */
    granted: { waId: string; name?: string | null } | null;
    permissionBusy: boolean;
    // Audio devices (only where the browser supports choosing them).
    inputs: AudioDevice[];
    outputs: AudioDevice[];
    inputId: string;        // "" = the system default
    outputId: string;
    canPickOutput: boolean;
    deviceNotice: string | null;
    /** Browser notification permission for rings in a background tab. */
    notifyPermission: NotificationPermission | "unsupported";

    answer: () => void;
    decline: () => void;
    callbackLater: () => void;
    hangup: () => void;
    toggleMute: () => void;
    /** Starts an outbound WhatsApp call. `ok` is true when the call card took
     *  over (it then shows every outcome itself); false only when it could not
     *  start at all (already on a call). */
    initiateCall: (to: string, name?: string | null, conversationId?: string | null) =>
        Promise<{ ok: boolean; error?: string }>;
    requestPermission: () => void;
    redial: () => void;
    dismiss: () => void;
    minimise: () => void;
    expand: () => void;
    /** Go to the customer's WhatsApp chat — minimising a live call, closing a wrap-up. */
    openChat: () => void;
    /** The dashboard registers how to open a customer's conversation (by wa_id). */
    setChatOpener: (fn: ((waId: string) => void) | null) => void;
    selectInput: (deviceId: string) => void;
    selectOutput: (deviceId: string) => void;
    refreshDevices: () => void;
    declineWaiting: () => void;
    callbackWaiting: () => void;
    endAndAnswerWaiting: () => void;
    callGranted: () => void;
    dismissGranted: () => void;
    requestNotifications: () => void;
    /** Ask for notifications once ever, on a calm gesture (a wrap-up's Done). */
    offerNotifications: () => void;
}

const Ctx = createContext<CallCtx | null>(null);
export const useCall = () => useContext(Ctx);

/** The name the card shows: their name, else their number. */
export const callerLabel = (c: { name?: string | null; from?: string } | null | undefined): string =>
    (c?.name || "").trim() || (c?.from ? `+${c.from}` : "Unknown caller");

export const firstName = (c: { name?: string | null; from?: string } | null | undefined): string =>
    (c?.name || "").trim().split(/\s+/)[0] || (c?.from ? `+${c.from}` : "they");

const LIVE: CallPhase[] = ["placing", "ringing_out", "connecting", "active", "reconnecting"];
export const isLivePhase = (p: CallPhase) => LIVE.includes(p);

const NO_NET = "No connection — can't answer yet";
const RECONNECT_GRACE_MS = 10_000;
const CONNECT_GUARD_MS = 20_000;
/** Answered on the agent's own phone (same agent id, another device). */
export const YOU_ELSEWHERE = "you on another device";

const MIC: MediaTrackConstraints = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };

interface Snap {
    phase: CallPhase;
    call: CallState | null;
    outcome: CallOutcome | null;
    reason: string | null;
    byAgent: string | null;
    duration: number | null;
    answeredAt: number | null;
    notice: string | null;
    minimised: boolean;
}
const IDLE: Snap = {
    phase: "idle", call: null, outcome: null, reason: null, byAgent: null,
    duration: null, answeredAt: null, notice: null, minimised: false,
};

// The live events on ws:channel:calls (services/call_log.py).
interface CallEvent {
    type?: string;
    call_id?: string;
    from?: string;
    name?: string | null;
    person_id?: string | null;
    conversation_id?: string | null;
    agent_id?: string | null;
    agent_name?: string | null;
    direction?: string | null;
    outcome?: string | null;
    duration?: number | null;
    sdp?: string;
    call?: ApiCall;
    wa_id?: string;
    status?: string;
}

type AudioContextCtor = typeof AudioContext;
const audioContextCtor = (): AudioContextCtor | null => {
    if (typeof window === "undefined") return null;
    return window.AudioContext
        || (window as unknown as { webkitAudioContext?: AudioContextCtor }).webkitAudioContext
        || null;
};

// A friendlier version of Meta's reasons ("call failed: …" → "…").
const friendly = (detail: string | null): string | null =>
    detail ? detail.replace(/^(call|accept|terminate) failed:\s*/i, "").trim() || null : null;

export function CallProvider({ children }: { children: ReactNode }) {
    const ws = useWs();
    const { data: session } = useSession();
    const myIdRef = useRef<string | null>(null);
    myIdRef.current = ((session as { user?: { id?: string } } | null)?.user?.id) ?? null;

    // The call itself lives in ONE snapshot (state for rendering + a ref for the
    // async paths), so the phase, the outcome and the words can never disagree.
    const [snap, setSnap] = useState<Snap>(IDLE);
    const snapRef = useRef<Snap>(IDLE);
    const put = useCallback((patch: Partial<Snap>) => {
        const next = { ...snapRef.current, ...patch };
        snapRef.current = next;
        setSnap(next);
    }, []);

    const [muted, setMuted] = useState(false);
    const mutedRef = useRef(false);
    const [recording, setRecording] = useState(false);
    const [recNote, setRecNote] = useState<{ callId: string; text: string } | null>(null);
    const [waiting, setWaitingState] = useState<WaitingCall | null>(null);
    const waitingRef = useRef<WaitingCall | null>(null);
    const setWaiting = useCallback((w: WaitingCall | null) => { waitingRef.current = w; setWaitingState(w); }, []);
    const [granted, setGranted] = useState<{ waId: string; name?: string | null } | null>(null);
    const [permissionBusy, setPermissionBusy] = useState(false);
    const [notifyPermission, setNotifyPermission] = useState<NotificationPermission | "unsupported">("unsupported");

    const pcRef = useRef<RTCPeerConnection | null>(null);
    const localStreamRef = useRef<MediaStream | null>(null);
    const remoteStreamRef = useRef<MediaStream | null>(null);
    const remoteAudioRef = useRef<HTMLAudioElement | null>(null);

    const attemptRef = useRef(0);                              // bumps on every new call / abort
    const cancelRef = useRef(false);                           // hung up while placing
    const answeredHereRef = useRef<string | null>(null);       // our answer POST succeeded
    const endedAtRef = useRef<Record<string, number>>({});     // callId → when it left this screen
    const pendingAnswerRef = useRef<Record<string, string>>({}); // outbound SDP that beat connect's reply
    const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const connectGuardRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const chatOpenerRef = useRef<((waId: string) => void) | null>(null);
    // Customers this agent asked for call permission (wa_id → name).
    const requestedRef = useRef<Map<string, string | null>>(new Map());

    // ── ICE config: fetched ahead of time so Answer is one request, not two ───
    const cfgRef = useRef<{ at: number; cfg: CallIceConfig } | null>(null);
    const iceConfig = useCallback(async (): Promise<CallIceConfig> => {
        const hit = cfgRef.current;
        if (hit && Date.now() - hit.at < 4 * 60_000) return hit.cfg;
        const cfg = await callsApi.iceConfig();
        cfgRef.current = { at: Date.now(), cfg };
        return cfg;
    }, []);

    // ── Ringtone ─────────────────────────────────────────────────────────────
    // Generated (no asset file → no 404): a soft two-tone double ring like a
    // desk phone for an incoming call, a single long ringback while we ring the
    // customer. Autoplay policy may hold the AudioContext suspended until the
    // agent touches the page — then it starts on that first touch; the card,
    // the notification and the tab title are the alert either way.
    const toneRef = useRef<{ ctx: AudioContext; timer: ReturnType<typeof setInterval>; unlock: () => void } | null>(null);
    const stopTone = useCallback(() => {
        const t = toneRef.current;
        if (!t) return;
        toneRef.current = null;
        clearInterval(t.timer);
        window.removeEventListener("pointerdown", t.unlock);
        window.removeEventListener("keydown", t.unlock);
        t.ctx.close().catch(() => {});
    }, []);
    const startTone = useCallback((kind: "ring" | "ringback") => {
        stopTone();
        const AC = audioContextCtor();
        if (!AC) return;
        try {
            const ctx = new AC();
            const master = ctx.createGain();
            master.gain.value = kind === "ring" ? 0.14 : 0.06;
            master.connect(ctx.destination);
            const burst = (at: number, len: number, freqs: number[]) => {
                const g = ctx.createGain();
                g.connect(master);
                g.gain.setValueAtTime(0.0001, at);
                g.gain.exponentialRampToValueAtTime(1, at + 0.03);
                g.gain.setValueAtTime(1, at + len - 0.06);
                g.gain.exponentialRampToValueAtTime(0.0001, at + len);
                for (const f of freqs) {
                    const o = ctx.createOscillator();
                    o.type = "sine"; o.frequency.value = f;
                    o.connect(g); o.start(at); o.stop(at + len + 0.02);
                }
            };
            const cycle = () => {
                if (toneRef.current?.ctx !== ctx || ctx.state !== "running") return;
                const t = ctx.currentTime + 0.02;
                if (kind === "ring") { burst(t, 0.4, [400, 450]); burst(t + 0.6, 0.4, [400, 450]); }
                else burst(t, 1.0, [425]);
            };
            const unlock = () => { ctx.resume().then(cycle).catch(() => {}); };
            toneRef.current = { ctx, timer: setInterval(cycle, kind === "ring" ? 3000 : 4000), unlock };
            if (ctx.state === "suspended") {
                ctx.resume().then(cycle).catch(() => {});
                window.addEventListener("pointerdown", unlock, { once: true });
                window.addEventListener("keydown", unlock, { once: true });
            } else cycle();
        } catch { /* no audio output — the card is the alert */ }
    }, [stopTone]);

    // ── Recording ────────────────────────────────────────────────────────────
    // Mix the agent mic + the customer's audio into one stream (Web Audio) and
    // capture it with MediaRecorder — free, the audio already flows through this
    // browser. Uploaded on hang-up so the server can transcribe + summarise.
    const recorderRef = useRef<MediaRecorder | null>(null);
    const recChunksRef = useRef<Blob[]>([]);
    const recCtxRef = useRef<AudioContext | null>(null);
    const recDestRef = useRef<MediaStreamAudioDestinationNode | null>(null);
    const recCallIdRef = useRef<string | null>(null);

    const startRecording = useCallback(() => {
        const cfg = cfgRef.current?.cfg;
        if (recorderRef.current || cfg?.record === false) return;
        if (typeof MediaRecorder === "undefined") return;
        const local = localStreamRef.current;
        const callId = snapRef.current.call?.callId;
        const AC = audioContextCtor();
        if (!local || !callId || callId === "pending" || !AC) return;
        try {
            const ctx = new AC();
            const dest = ctx.createMediaStreamDestination();
            ctx.createMediaStreamSource(local).connect(dest);
            const remote = remoteStreamRef.current;
            if (remote && remote.getAudioTracks().length) {
                try { ctx.createMediaStreamSource(remote).connect(dest); } catch { /* not audio */ }
            }
            recCtxRef.current = ctx;
            recDestRef.current = dest;
            const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus"
                : MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
            const rec = mime ? new MediaRecorder(dest.stream, { mimeType: mime }) : new MediaRecorder(dest.stream);
            recChunksRef.current = [];
            rec.ondataavailable = (e) => { if (e.data && e.data.size) recChunksRef.current.push(e.data); };
            rec.onerror = () => setRecording(false);
            rec.start(1000);   // 1s chunks so nothing is lost if the call ends abruptly
            recorderRef.current = rec;
            recCallIdRef.current = callId;
            setRecording(true);
        } catch (e) { console.warn("[call] recording unavailable:", e); }
    }, []);

    // Stop + upload. Called first in teardown() so it flushes on EVERY end path
    // (hang-up, remote hang-up, dropped connection) before the mic tracks stop.
    const stopRecording = useCallback(() => {
        const rec = recorderRef.current;
        const callId = recCallIdRef.current;
        recorderRef.current = null;
        recCallIdRef.current = null;
        setRecording(false);
        const closeCtx = () => { recCtxRef.current?.close().catch(() => {}); recCtxRef.current = null; recDestRef.current = null; };
        if (!rec) { closeCtx(); return; }
        try {
            rec.onstop = () => {
                closeCtx();
                const chunks = recChunksRef.current; recChunksRef.current = [];
                if (!callId || !chunks.length) return;
                const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
                if (blob.size < 2000) return;   // skip near-silent / empty recordings
                const cfg = cfgRef.current?.cfg;
                const saved = cfg?.auto_transcribe ? "Recording saved — summary in a minute"
                    : cfg?.transcribe ? "Recording saved — Transcribe from Calls"
                    : "Recording saved";
                const upload = (tries: number): Promise<unknown> =>
                    callsApi.uploadRecording(callId, blob).catch((e) =>
                        tries > 1 ? new Promise((r) => setTimeout(r, 2000)).then(() => upload(tries - 1)) : Promise.reject(e));
                upload(2)
                    .then(() => setRecNote({ callId, text: saved }))
                    .catch((e) => {
                        console.warn("[call] recording upload failed:", e);
                        setRecNote({ callId, text: "The recording couldn't be saved" });
                    });
            };
            rec.stop();
        } catch (e) { console.warn("[call] recording stop failed:", e); }
    }, []);

    const clearTimers = useCallback(() => {
        if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
        if (connectGuardRef.current) { clearTimeout(connectGuardRef.current); connectGuardRef.current = null; }
    }, []);

    // Everything media: recorder, peer connection, mic, ringtone, timers.
    const teardown = useCallback(() => {
        stopRecording();
        clearTimers();
        const pc = pcRef.current;
        pcRef.current = null;
        if (pc) { pc.onconnectionstatechange = null; pc.oniceconnectionstatechange = null; pc.close(); }
        localStreamRef.current?.getTracks().forEach((t) => t.stop());
        localStreamRef.current = null;
        remoteStreamRef.current = null;
        if (remoteAudioRef.current) remoteAudioRef.current.srcObject = null;
        stopTone();
    }, [stopRecording, clearTimers, stopTone]);

    // Hang-up is instant here; the request retries behind it (network blips,
    // a 5xx) so the customer is never left on a line nobody holds.
    const terminateInBackground = useCallback((callId: string | undefined, run?: () => Promise<unknown>) => {
        if (!callId || callId === "pending") return;
        const go = run ?? (() => callsApi.terminate(callId));
        const attempt = (left: number, wait: number) => {
            go().catch((e) => {
                const st = apiErrorStatus(e);
                if (left > 1 && (st === null || st >= 500)) setTimeout(() => attempt(left - 1, wait * 3), wait);
            });
        };
        attempt(3, 1000);
    }, []);

    const resetExtras = useCallback(() => {
        setMuted(false); mutedRef.current = false;
        setRecNote(null);
        answeredHereRef.current = null;
    }, []);

    // Ring this device for a call (the WS event, the poll fallback, a promoted
    // waiting call). While a call is live, a new one waits in a banner instead.
    const startRinging = useCallback((callId: string, from: string, name?: string | null,
                                      extra?: { conversationId?: string | null; personId?: string | null }) => {
        const s = snapRef.current;
        if (s.call?.callId === callId && s.phase !== "idle") return;         // already on screen
        const endedAt = endedAtRef.current[callId];
        if (endedAt && Date.now() - endedAt < 12_000) return;              // just left this screen
        if (s.phase === "idle" || s.phase === "ended") {
            teardown();
            resetExtras();
            attemptRef.current += 1;
            put({
                ...IDLE, phase: "incoming",
                call: { callId, from: (from || "").replace(/^\+/, ""), name: name ?? null, direction: "inbound",
                        conversationId: extra?.conversationId ?? null, personId: extra?.personId ?? null },
            });
            startTone("ring");
        } else if (waitingRef.current?.callId !== callId) {
            setWaiting({ callId, from: (from || "").replace(/^\+/, ""), name: name ?? null });
        }
    }, [put, teardown, resetExtras, startTone, setWaiting]);

    // Land on the wrap-up card. A call still waiting in the banner takes the
    // screen instead — a ringing call always beats a wrap-up.
    const endWith = useCallback((outcome: CallOutcome, extra: { reason?: string | null; byAgent?: string | null; duration?: number | null } = {}) => {
        const s = snapRef.current;
        teardown();
        attemptRef.current += 1;
        if (s.call) endedAtRef.current[s.call.callId] = Date.now();
        const duration = extra.duration !== undefined ? extra.duration
            : s.answeredAt ? Math.max(0, Math.round((Date.now() - s.answeredAt) / 1000)) : null;
        setMuted(false); mutedRef.current = false;
        const w = waitingRef.current;
        if (w) {
            setWaiting(null);
            put({ ...IDLE, phase: "ended", call: s.call, outcome, duration });
            startRinging(w.callId, w.from, w.name);
            return;
        }
        put({ phase: "ended", outcome, reason: extra.reason ?? null, byAgent: extra.byAgent ?? null,
              duration, notice: null });
    }, [put, teardown, setWaiting, startRinging]);

    // Answered, but the audio must arrive: never sit on "Connecting…" forever
    // (a lost SDP answer, a path ICE can't open).
    const armConnectGuard = useCallback((id: string) => {
        if (connectGuardRef.current) clearTimeout(connectGuardRef.current);
        connectGuardRef.current = setTimeout(() => {
            connectGuardRef.current = null;
            if (snapRef.current.phase === "connecting" && snapRef.current.call?.callId === id) {
                endWith("failed", { reason: "The call audio couldn't connect" });
                terminateInBackground(id);
            }
        }, CONNECT_GUARD_MS);
    }, [endWith, terminateInBackground]);

    // Our outbound call: the customer picked up — media follows the SDP answer.
    const customerAnswered = useCallback(() => {
        const s = snapRef.current;
        if (s.phase !== "ringing_out" || !s.call) return;
        stopTone();
        put({ phase: "connecting" });
        armConnectGuard(s.call.callId);
    }, [stopTone, put, armConnectGuard]);

    // A terminal status from the server (call_ended's outcome, or a re-read row)
    // → the wrap-up this device should show.
    const endFromStatus = useCallback((status: string, info: { agent_id?: string | null; agent_name?: string | null; duration?: number | null }) => {
        const s = snapRef.current;
        const c = s.call;
        if (!c) return;
        const other = !!info.agent_id && info.agent_id !== myIdRef.current;
        const answeringHere = answeredHereRef.current === c.callId;
        switch (status) {
            case "completed":
            case "ended":
                if (s.phase === "incoming" || (s.phase === "connecting" && c.direction === "inbound" && !answeringHere)) {
                    return endWith("answered_elsewhere", { byAgent: other ? info.agent_name ?? null : YOU_ELSEWHERE });
                }
                return endWith("completed", s.answeredAt ? {} : { duration: info.duration ?? null });
            case "missed": return endWith("missed");
            case "declined": return endWith("declined", { byAgent: other ? info.agent_name ?? "a colleague" : null });
            case "callback": return endWith("callback", { byAgent: other ? info.agent_name ?? "a colleague" : null });
            case "no_answer": return endWith("no_answer");
            case "cancelled": return endWith("cancelled");
            case "failed": return endWith("failed", { reason: "The call couldn't be connected" });
            default: return;   // ringing / answered — still live
        }
    }, [endWith]);

    // Fill in who the caller is from a row (name, chat, person) without
    // touching the phase.
    const enrich = useCallback((row: ApiCall) => {
        const c = snapRef.current.call;
        if (!c || c.callId !== row.call_id) return;
        const next: CallState = {
            ...c,
            name: c.name || row.name || null,
            from: c.from || (row.wa_id || "").replace(/^\+/, ""),
            conversationId: c.conversationId || row.conversation_id || null,
            personId: c.personId || row.person_id || null,
        };
        if (next.name !== c.name || next.from !== c.from || next.conversationId !== c.conversationId || next.personId !== c.personId) {
            put({ call: next });
        }
    }, [put]);

    // Correct this screen from the server's row (after a reconnect, on return
    // to the tab, from the poll fallback, or a call_update).
    const applyRow = useCallback((row: ApiCall) => {
        const s = snapRef.current;
        const c = s.call;
        if (!c || row.call_id !== c.callId) return;
        enrich(row);
        const st = row.status;
        const other = !!row.agent_id && row.agent_id !== myIdRef.current;
        if (st === "ringing") return;
        if (s.phase === "incoming") {
            if (st === "answered") return endWith("answered_elsewhere", { byAgent: other ? row.agent_name : YOU_ELSEWHERE });
            return endFromStatus(st, row);
        }
        if (s.phase === "ringing_out") {
            if (st === "answered") { customerAnswered(); return; }
            return endFromStatus(st, row);
        }
        if (s.phase === "connecting" || s.phase === "active" || s.phase === "reconnecting") {
            if (st === "answered") {
                if (s.phase === "connecting" && c.direction === "inbound" && other && answeredHereRef.current !== c.callId) {
                    endWith("answered_elsewhere", { byAgent: row.agent_name });
                }
                return;
            }
            return endFromStatus(st, row);
        }
    }, [enrich, endWith, endFromStatus, customerAnswered]);

    // ── Media state → phase ──────────────────────────────────────────────────
    const loseConnection = useCallback(() => {
        const s = snapRef.current;
        const id = s.call?.callId;
        if (!s.answeredAt) endWith("failed", { reason: "The call audio couldn't connect" });
        else endWith("connection_lost");
        terminateInBackground(id);
    }, [endWith, terminateInBackground]);

    const onMedia = useCallback((pc: RTCPeerConnection, st: string) => {
        if (pc !== pcRef.current) return;
        const s = snapRef.current;
        if (st === "connected") {
            if (reconnectTimerRef.current) { clearTimeout(reconnectTimerRef.current); reconnectTimerRef.current = null; }
            if (connectGuardRef.current) { clearTimeout(connectGuardRef.current); connectGuardRef.current = null; }
            if (s.phase === "connecting" || s.phase === "ringing_out" || s.phase === "reconnecting") {
                stopTone();
                put({ phase: "active", answeredAt: s.answeredAt ?? Date.now(), notice: null });
            }
        } else if (st === "disconnected") {
            if (s.phase !== "active") return;
            put({ phase: "reconnecting" });
            if (!reconnectTimerRef.current) {
                reconnectTimerRef.current = setTimeout(() => {
                    reconnectTimerRef.current = null;
                    if (snapRef.current.phase === "reconnecting" && pcRef.current === pc) loseConnection();
                }, RECONNECT_GRACE_MS);
            }
        } else if (st === "failed") {
            if (["connecting", "active", "reconnecting"].includes(s.phase)) loseConnection();
        }
    }, [put, stopTone, loseConnection]);

    const buildPc = useCallback((iceServers: RTCIceServer[]) => {
        const pc = new RTCPeerConnection({ iceServers });
        pc.ontrack = (e) => {
            const stream = e.streams[0] ?? new MediaStream([e.track]);
            remoteStreamRef.current = stream;
            if (remoteAudioRef.current) remoteAudioRef.current.srcObject = stream;
            // A recorder that started before the customer's audio arrived mixes it in now.
            if (recCtxRef.current && recDestRef.current) {
                try { recCtxRef.current.createMediaStreamSource(stream).connect(recDestRef.current); } catch { /* ignore */ }
            }
        };
        pc.onconnectionstatechange = () => onMedia(pc, pc.connectionState);
        pc.oniceconnectionstatechange = () => {
            const st = pc.iceConnectionState;
            // Only the states connectionState may lag on; "failed" / "disconnected"
            // come through connectionState where the browser has it.
            if (st === "connected" || st === "completed") onMedia(pc, "connected");
            else if (!("connectionState" in pc) && (st === "disconnected" || st === "failed")) onMedia(pc, st);
        };
        pc.onicecandidateerror = (e) => console.debug("[call] ICE candidate error:", (e as RTCPeerConnectionIceErrorEvent)?.errorText);
        return pc;
    }, [onMedia]);

    const gatherIce = useCallback((pc: RTCPeerConnection) => new Promise<void>((resolve) => {
        if (pc.iceGatheringState === "complete") return resolve();
        const check = () => { if (pc.iceGatheringState === "complete") { pc.removeEventListener("icegatheringstatechange", check); resolve(); } };
        pc.addEventListener("icegatheringstatechange", check);
        setTimeout(resolve, 2500);
    }), []);

    // ── Audio devices ────────────────────────────────────────────────────────
    const [inputs, setInputs] = useState<AudioDevice[]>([]);
    const [outputs, setOutputs] = useState<AudioDevice[]>([]);
    const [inputId, setInputId] = useState("");
    const [outputId, setOutputId] = useState("");
    const inputIdRef = useRef("");
    const outputIdRef = useRef("");
    const knownInputsRef = useRef<Set<string>>(new Set());
    const [deviceNotice, setDeviceNoticeState] = useState<string | null>(null);
    const deviceNoticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const setDeviceNotice = useCallback((text: string) => {
        setDeviceNoticeState(text);
        if (deviceNoticeTimer.current) clearTimeout(deviceNoticeTimer.current);
        deviceNoticeTimer.current = setTimeout(() => setDeviceNoticeState(null), 5000);
    }, []);
    const [canPickOutput, setCanPickOutput] = useState(false);
    useEffect(() => {
        setCanPickOutput(typeof HTMLMediaElement !== "undefined" && "setSinkId" in HTMLMediaElement.prototype);
        setNotifyPermission(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
    }, []);

    const getMic = useCallback((deviceId?: string) => {
        const id = deviceId ?? inputIdRef.current;
        return navigator.mediaDevices.getUserMedia({ audio: id ? { ...MIC, deviceId: { exact: id } } : MIC });
    }, []);

    const readDevices = useCallback(async () => {
        if (typeof navigator === "undefined" || !navigator.mediaDevices?.enumerateDevices) return null;
        try {
            const list = await navigator.mediaDevices.enumerateDevices();
            const pick = (kind: MediaDeviceKind, fallback: string) => list
                .filter((d) => d.kind === kind && d.deviceId && d.deviceId !== "default" && d.deviceId !== "communications")
                .map((d, i) => ({ deviceId: d.deviceId, label: d.label || `${fallback} ${i + 1}` }));
            const ins = pick("audioinput", "Microphone");
            const outs = pick("audiooutput", "Speaker");
            setInputs(ins); setOutputs(outs);
            return { ins, outs };
        } catch { return null; }
    }, []);

    // A mic unplugged mid-call ends its track: fall back to the default one.
    // (A ref, so selectInput and this watcher can call each other.)
    const watchTrackRef = useRef<(track: MediaStreamTrack) => void>(() => {});

    // Swap the microphone mid-call: a new track replaces the one being sent
    // (no renegotiation), and joins the recording mix.
    const selectInput = useCallback(async (deviceId: string) => {
        inputIdRef.current = deviceId; setInputId(deviceId);
        const pc = pcRef.current;
        if (!pc || !localStreamRef.current) return;
        try {
            const stream = await getMic(deviceId);
            const track = stream.getAudioTracks()[0];
            track.enabled = !mutedRef.current;
            const sender = pc.getSenders().find((x) => x.track?.kind === "audio" || x.track === null);
            if (sender) await sender.replaceTrack(track);
            if (recCtxRef.current && recDestRef.current) {
                try { recCtxRef.current.createMediaStreamSource(stream).connect(recDestRef.current); } catch { /* ignore */ }
            }
            const old = localStreamRef.current;
            localStreamRef.current = stream;
            old?.getTracks().forEach((t) => t.stop());
            watchTrackRef.current(track);
        } catch {
            setDeviceNotice("Couldn't switch the microphone — still using the previous one");
        }
    }, [getMic, setDeviceNotice]);

    watchTrackRef.current = (track: MediaStreamTrack) => {
        track.onended = () => {
            if (localStreamRef.current?.getAudioTracks()[0] !== track || !pcRef.current) return;
            setDeviceNotice("Microphone disconnected — switched to the default");
            selectInput("");
        };
    };

    const selectOutput = useCallback(async (deviceId: string) => {
        const el = remoteAudioRef.current as (HTMLAudioElement & { setSinkId?: (id: string) => Promise<void> }) | null;
        if (!el?.setSinkId) return;
        try {
            await el.setSinkId(deviceId);
            outputIdRef.current = deviceId; setOutputId(deviceId);
        } catch { setDeviceNotice("Couldn't switch the speaker"); }
    }, [setDeviceNotice]);

    const refreshDevices = useCallback(() => { readDevices(); }, [readDevices]);

    useEffect(() => {
        const md = typeof navigator !== "undefined" ? navigator.mediaDevices : undefined;
        if (!md?.addEventListener) return;
        const onChange = async () => {
            const r = await readDevices();
            if (!r) return;
            const live = !!pcRef.current;
            if (inputIdRef.current && !r.ins.some((d) => d.deviceId === inputIdRef.current)) {
                if (live) { setDeviceNotice("Microphone disconnected — switched to the default"); selectInput(""); }
                else { inputIdRef.current = ""; setInputId(""); }
            } else if (live) {
                const fresh = r.ins.find((d) => !knownInputsRef.current.has(d.deviceId));
                if (fresh && knownInputsRef.current.size) setDeviceNotice(`${fresh.label} connected — choose it under Audio`);
            }
            if (outputIdRef.current && !r.outs.some((d) => d.deviceId === outputIdRef.current)) {
                if (live) setDeviceNotice("Speaker disconnected — switched to the default");
                selectOutput("");
            }
            knownInputsRef.current = new Set(r.ins.map((d) => d.deviceId));
        };
        md.addEventListener("devicechange", onChange);
        return () => md.removeEventListener("devicechange", onChange);
    }, [readDevices, selectInput, selectOutput, setDeviceNotice]);

    // Labels only exist once the mic is granted — read the list when a call connects.
    useEffect(() => {
        if (snap.phase === "connecting" || snap.phase === "active") {
            readDevices().then((r) => { if (r) knownInputsRef.current = new Set(r.ins.map((d) => d.deviceId)); });
        }
    }, [snap.phase, readDevices]);

    const attachMic = useCallback((pc: RTCPeerConnection, mic: MediaStream) => {
        localStreamRef.current = mic;
        mic.getTracks().forEach((t) => { t.enabled = !mutedRef.current; pc.addTrack(t, mic); });
        const t = mic.getAudioTracks()[0];
        if (t) watchTrackRef.current(t);
    }, []);

    // ── Background tab: notification permission ──────────────────────────────
    const requestNotifications = useCallback(() => {
        if (typeof Notification === "undefined" || Notification.permission !== "default") return;
        try { localStorage.setItem("neema:call-notify-asked", "1"); } catch { /* private mode */ }
        Notification.requestPermission().then(setNotifyPermission).catch(() => {});
    }, []);
    // Asked once, on a gesture that is about calls (the first Answer / Call).
    const askNotifyOnce = useCallback(() => {
        try { if (localStorage.getItem("neema:call-notify-asked")) return; } catch { return; }
        requestNotifications();
    }, [requestNotifications]);

    // ── Actions ──────────────────────────────────────────────────────────────
    const answer = useCallback(async () => {
        const s = snapRef.current;
        const c = s.call;
        if (s.phase !== "incoming" || !c) return;
        if (typeof navigator !== "undefined" && navigator.onLine === false) { put({ notice: NO_NET }); return; }
        const id = c.callId;
        const token = ++attemptRef.current;
        const mine = () => attemptRef.current === token && snapRef.current.call?.callId === id
            && ["connecting", "active", "reconnecting"].includes(snapRef.current.phase);
        // Network gone mid-answer: back to the ringing card with a retryable Answer.
        const backToRinging = () => {
            const pc = pcRef.current; pcRef.current = null; pc?.close();
            localStreamRef.current?.getTracks().forEach((t) => t.stop()); localStreamRef.current = null;
            attemptRef.current += 1;
            put({ phase: "incoming", notice: NO_NET });
            startTone("ring");
        };
        stopTone();
        put({ phase: "connecting", notice: null, minimised: false });

        let cfg: CallIceConfig, offer: { sdp: string };
        try {
            [cfg, offer] = await Promise.all([iceConfig(), callsApi.offer(id)]);
        } catch (e) {
            if (!mine()) return;
            if (isNetworkError(e)) return backToRinging();
            if (apiErrorStatus(e) === 404) return endWith("missed", { reason: "This call has already ended" });
            return endWith("failed", { reason: friendly(apiErrorDetail(e)) || "Couldn't connect the call" });
        }
        if (!mine()) return;
        let mic: MediaStream;
        try { mic = await getMic(); }
        catch (e) {
            if (!mine()) return;
            const name = (e as DOMException)?.name;
            if (name === "NotFoundError" || name === "OverconstrainedError") {
                inputIdRef.current = ""; setInputId("");
                return endWith("failed", { reason: "No microphone found — plug one in and call them back" });
            }
            return endWith("mic_blocked");
        }
        if (!mine()) { mic.getTracks().forEach((t) => t.stop()); return; }
        const pc = buildPc(cfg.ice_servers);
        pcRef.current = pc;
        attachMic(pc, mic);
        try {
            await pc.setRemoteDescription({ type: "offer", sdp: offer.sdp });
            await pc.setLocalDescription(await pc.createAnswer());
            await gatherIce(pc);
        } catch {
            if (!mine()) return;
            return endWith("failed", { reason: "Couldn't set up the call audio" });
        }
        if (!mine()) return;
        try {
            await callsApi.answer(id, pc.localDescription!.sdp);
        } catch (e) {
            if (!mine()) return;
            const st = apiErrorStatus(e);
            if (st === 409) {
                const who = (apiErrorDetail(e) || "").match(/answered by (.+)$/i)?.[1] ?? null;
                return endWith("answered_elsewhere", { byAgent: who });
            }
            if (st === 410) return endWith("missed", { reason: "This call has already ended" });
            if (isNetworkError(e)) return backToRinging();
            return endWith("failed", { reason: friendly(apiErrorDetail(e)) || "Couldn't connect the call" });
        }
        answeredHereRef.current = id;
        if (snapRef.current.phase === "connecting") armConnectGuard(id);
    }, [put, stopTone, startTone, iceConfig, getMic, buildPc, attachMic, gatherIce, endWith, armConnectGuard]);

    // Declining / "call back later" end the call for the whole team (WhatsApp has
    // no per-agent decline). Shown at once; the request runs behind it — after
    // checking the call is still ringing, so a colleague who answered a moment
    // ago is never cut off by our tap.
    const verifyThenRun = useCallback((callId: string, kind: "decline" | "callback", run: () => Promise<unknown>) => {
        callsApi.get(callId)
            .then((row) => {
                // /callback also turns a call the caller already gave up on into a follow-up.
                if (row.status === "ringing" || (kind === "callback" && row.status === "missed")) {
                    terminateInBackground(callId, run);
                    return;
                }
                // Too late: correct the wrap-up to what really happened.
                const s = snapRef.current;
                if (s.phase !== "ended" || s.call?.callId !== callId) return;
                if ((row.status === "answered" || row.status === "completed") && row.agent_id !== myIdRef.current) {
                    put({ outcome: "answered_elsewhere", byAgent: row.agent_name, reason: null });
                } else if (row.status === "missed" && kind === "decline") {
                    put({ outcome: "missed", reason: null, byAgent: null });
                }
            })
            .catch(() => terminateInBackground(callId, run));
    }, [terminateInBackground, put]);

    const decline = useCallback(() => {
        const s = snapRef.current;
        if (s.phase !== "incoming" || !s.call) return;
        const id = s.call.callId;
        endWith("declined");
        verifyThenRun(id, "decline", () => callsApi.terminate(id));
    }, [endWith, verifyThenRun]);

    const callbackLater = useCallback(() => {
        const s = snapRef.current;
        if (s.phase !== "incoming" || !s.call) return;
        const id = s.call.callId;
        endWith("callback");
        // /callback also turns an already-missed call into a follow-up, so it
        // runs even when the caller gave up a moment before the tap.
        verifyThenRun(id, "callback", () => callsApi.callback(id));
    }, [endWith, verifyThenRun]);

    const hangup = useCallback(() => {
        const s = snapRef.current;
        const c = s.call;
        if (!c) return;
        switch (s.phase) {
            case "incoming": return decline();
            case "placing":
                cancelRef.current = true;
                return endWith("cancelled");
            case "ringing_out":
                endWith("cancelled");
                return terminateInBackground(c.callId);
            case "connecting":
            case "active":
            case "reconnecting": {
                const duration = s.answeredAt ? Math.max(0, Math.round((Date.now() - s.answeredAt) / 1000)) : null;
                teardown();
                attemptRef.current += 1;
                endedAtRef.current[c.callId] = Date.now();
                put({ phase: "ending" });
                terminateInBackground(c.callId);
                setTimeout(() => {
                    const now = snapRef.current;
                    if (now.phase === "ending" && now.call?.callId === c.callId) endWith("completed", { duration });
                }, 300);
                return;
            }
            default: return;
        }
    }, [decline, endWith, teardown, put, terminateInBackground]);

    const toggleMute = useCallback(() => {
        const next = !mutedRef.current;
        localStreamRef.current?.getAudioTracks().forEach((t) => (t.enabled = !next));
        mutedRef.current = next;
        setMuted(next);
    }, []);

    const applyOutboundAnswer = useCallback((callId: string, sdp: string) => {
        const pc = pcRef.current;
        if (!pc || snapRef.current.call?.callId !== callId) return;
        pc.setRemoteDescription({ type: "answer", sdp }).catch((e) => console.warn("[call] outbound answer rejected:", e));
        customerAnswered();
    }, [customerAnswered]);

    // Business-initiated call: WE call the customer. Build an offer, ask Meta to
    // place the call; the customer's SDP answer arrives as an outbound_answer
    // event. WhatsApp needs the customer's call permission (409 otherwise) — the
    // card then offers "Send call request"; we never send it on our own, it
    // messages the customer.
    const initiateCall = useCallback(async (to: string, name?: string | null, conversationId?: string | null) => {
        const s = snapRef.current;
        if (isLivePhase(s.phase) || s.phase === "incoming" || s.phase === "ending") {
            return { ok: false, error: "You're already on a call — end it first." };
        }
        const digits = (to || "").replace(/\D/g, "");
        if (digits.length < 7) return { ok: false, error: "No valid WhatsApp number for this customer." };
        teardown();
        resetExtras();
        const token = ++attemptRef.current;
        cancelRef.current = false;
        const base: CallState = { callId: "pending", from: digits, name: name ?? null, direction: "outbound",
                                  conversationId: conversationId ?? null, personId: null };
        put({ ...IDLE, phase: "placing", call: base });
        const placing = () => attemptRef.current === token && snapRef.current.phase === "placing";
        const permission = callsApi.permission(digits).catch(() => null);

        let mic: MediaStream;
        try { mic = await getMic(); }
        catch (e) {
            if (!placing()) return { ok: true };
            const n = (e as DOMException)?.name;
            if (n === "NotFoundError" || n === "OverconstrainedError") {
                inputIdRef.current = ""; setInputId("");
                endWith("failed", { reason: "No microphone found — plug one in and try again" });
            } else endWith("mic_blocked");
            return { ok: true };
        }
        if (!placing()) { mic.getTracks().forEach((t) => t.stop()); return { ok: true }; }
        let cfg: CallIceConfig;
        try { cfg = await iceConfig(); }
        catch (e) {
            mic.getTracks().forEach((t) => t.stop());
            if (placing()) endWith("failed", { reason: isNetworkError(e) ? "No connection — the call wasn't placed" : "Calling isn't available right now" });
            return { ok: true };
        }
        if (!placing()) { mic.getTracks().forEach((t) => t.stop()); return { ok: true }; }
        const pc = buildPc(cfg.ice_servers);
        pcRef.current = pc;
        attachMic(pc, mic);
        try {
            await pc.setLocalDescription(await pc.createOffer());
            await gatherIce(pc);
        } catch {
            if (placing()) endWith("failed", { reason: "Couldn't set up the call audio" });
            return { ok: true };
        }
        if (!placing()) return { ok: true };
        try {
            const { call_id } = await callsApi.connect(digits, pc.localDescription!.sdp, name || undefined);
            // Hung up (or started another call) while Meta was placing this one.
            if (!placing() || cancelRef.current) { terminateInBackground(call_id); return { ok: true }; }
            put({ phase: "ringing_out", call: { ...base, callId: call_id } });
            startTone("ringback");
            const early = pendingAnswerRef.current[call_id];
            if (early) { delete pendingAnswerRef.current[call_id]; applyOutboundAnswer(call_id, early); }
        } catch (e) {
            if (!placing()) return { ok: true };
            const st = apiErrorStatus(e);
            if (st === 409) {
                const perm = await permission;
                if (!placing()) return { ok: true };
                if (perm?.status === "requested") { requestedRef.current.set(digits, name ?? null); endWith("permission_requested"); }
                else endWith("permission_needed");
            } else if (isNetworkError(e)) {
                endWith("failed", { reason: "No connection — the call wasn't placed" });
            } else {
                endWith("failed", { reason: friendly(apiErrorDetail(e)) || "Couldn't place the call" });
            }
        }
        return { ok: true };
    }, [teardown, resetExtras, put, getMic, endWith, iceConfig, buildPc, attachMic, gatherIce,
        terminateInBackground, startTone, applyOutboundAnswer]);

    const requestPermission = useCallback(async () => {
        const s = snapRef.current;
        const c = s.call;
        if (!c || s.phase !== "ended") return;
        setPermissionBusy(true);
        try {
            await callsApi.requestPermission(c.from);
            requestedRef.current.set(c.from, c.name ?? null);
            if (snapRef.current.call?.callId === c.callId && snapRef.current.phase === "ended") {
                put({ outcome: "permission_requested", reason: null });
            }
        } catch (e) {
            put({ reason: isNetworkError(e) ? "No connection — the request wasn't sent. Try again."
                : friendly(apiErrorDetail(e)) || "Couldn't send the call request. Try again." });
        } finally { setPermissionBusy(false); }
    }, [put]);

    const dismiss = useCallback(() => {
        teardown();
        attemptRef.current += 1;
        const c = snapRef.current.call;
        if (c) endedAtRef.current[c.callId] = Date.now();
        resetExtras();
        put(IDLE);
    }, [teardown, resetExtras, put]);

    const redial = useCallback(() => {
        const c = snapRef.current.call;
        if (!c) return;
        initiateCall(c.from, c.name, c.conversationId);
    }, [initiateCall]);

    const minimise = useCallback(() => { if (snapRef.current.phase !== "idle") put({ minimised: true }); }, [put]);
    const expand = useCallback(() => put({ minimised: false }), [put]);
    const setChatOpener = useCallback((fn: ((waId: string) => void) | null) => { chatOpenerRef.current = fn; }, []);

    const openChat = useCallback(() => {
        const s = snapRef.current;
        const c = s.call;
        if (!c) return;
        if (isLivePhase(s.phase)) put({ minimised: true });
        else if (s.phase === "ended") dismiss();
        chatOpenerRef.current?.(c.from);
    }, [put, dismiss]);

    // The second call's banner.
    const declineWaiting = useCallback(() => {
        const w = waitingRef.current;
        if (!w) return;
        setWaiting(null);
        endedAtRef.current[w.callId] = Date.now();
        verifyThenRun(w.callId, "decline", () => callsApi.terminate(w.callId));
    }, [setWaiting, verifyThenRun]);
    const callbackWaiting = useCallback(() => {
        const w = waitingRef.current;
        if (!w) return;
        setWaiting(null);
        endedAtRef.current[w.callId] = Date.now();
        verifyThenRun(w.callId, "callback", () => callsApi.callback(w.callId));
    }, [setWaiting, verifyThenRun]);
    // No hold in the API: answering the second call means ending this one.
    const endAndAnswerWaiting = useCallback(() => {
        const w = waitingRef.current;
        const c = snapRef.current.call;
        if (!w) return;
        setWaiting(null);
        teardown();
        attemptRef.current += 1;
        // A call only ringing here keeps ringing for the team — ending it would
        // decline it for everyone; a live one is hung up.
        const wasLive = isLivePhase(snapRef.current.phase);
        if (c) { endedAtRef.current[c.callId] = Date.now(); if (wasLive) terminateInBackground(c.callId); }
        resetExtras();
        put({ ...IDLE, phase: "incoming", call: { callId: w.callId, from: w.from, name: w.name ?? null, direction: "inbound" } });
        answer();
    }, [setWaiting, teardown, terminateInBackground, resetExtras, put, answer]);

    const dismissGranted = useCallback(() => setGranted(null), []);
    const callGranted = useCallback(() => {
        const g = granted;
        setGranted(null);
        if (g) initiateCall(g.waId, g.name ?? null);
    }, [granted, initiateCall]);

    // ── Live events ──────────────────────────────────────────────────────────
    useEffect(() => {
        if (!ws) return;
        const onEvent = (evt: CallEvent) => {
            const type = evt?.type;
            if (!type) return;
            const cur = snapRef.current;
            const mineNow = !!evt.call_id && cur.call?.callId === evt.call_id;
            const w = waitingRef.current;
            if (type === "incoming_call" && evt.call_id) {
                startRinging(evt.call_id, evt.from || "", evt.name,
                    { conversationId: evt.conversation_id, personId: evt.person_id });
            } else if (type === "call_answered" && evt.call_id) {
                if (w?.callId === evt.call_id) setWaiting(null);
                if (!mineNow) return;
                if (cur.phase === "incoming") {
                    const me = evt.agent_id && evt.agent_id === myIdRef.current;
                    endWith("answered_elsewhere", { byAgent: me ? YOU_ELSEWHERE : evt.agent_name ?? null });
                } else if (cur.phase === "connecting" && cur.call?.direction === "inbound"
                           && evt.agent_id && evt.agent_id !== myIdRef.current) {
                    endWith("answered_elsewhere", { byAgent: evt.agent_name ?? null });
                } else if (cur.phase === "ringing_out") {
                    customerAnswered();
                }
            } else if (type === "outbound_answer" && evt.call_id && evt.sdp) {
                if (mineNow) applyOutboundAnswer(evt.call_id, evt.sdp);
                else if (cur.phase === "placing") pendingAnswerRef.current[evt.call_id] = evt.sdp;
            } else if (type === "call_ended" && evt.call_id) {
                if (w?.callId === evt.call_id) setWaiting(null);
                if (!mineNow || cur.phase === "ended" || cur.phase === "ending" || cur.phase === "idle") return;
                endFromStatus(evt.outcome || "completed", evt);
            } else if (type === "call_update" && evt.call) {
                const row = evt.call;
                if (w?.callId === row.call_id && row.status !== "ringing") setWaiting(null);
                if (row.call_id === cur.call?.callId) {
                    if (cur.phase === "ended" || cur.phase === "ending") enrich(row);
                    else applyRow(row);
                }
            } else if (type === "call_permission" && evt.wa_id) {
                const wa = String(evt.wa_id).replace(/^\+/, "");
                const onCard = cur.phase === "ended" && cur.call?.from === wa
                    && (cur.outcome === "permission_needed" || cur.outcome === "permission_requested");
                if (evt.status === "granted") {
                    if (requestedRef.current.has(wa) || onCard) {
                        setGranted({ waId: wa, name: requestedRef.current.get(wa) ?? cur.call?.name ?? null });
                        requestedRef.current.delete(wa);
                        if (onCard) dismiss();
                    }
                } else if (evt.status === "requested" && onCard && cur.outcome === "permission_needed") {
                    // A colleague sent it — don't offer to send it twice.
                    put({ outcome: "permission_requested", reason: null });
                }
            }
        };
        ws.on("event", onEvent);
        return () => ws.off("event", onEvent);
    }, [ws, startRinging, setWaiting, endWith, customerAnswered, put, applyOutboundAnswer, endFromStatus, enrich, applyRow, dismiss]);

    // ── Re-sync: after the socket reconnects or the tab comes back, re-read the
    // call on screen — a call that ended while we were away shows its real
    // outcome instead of ringing (or "connected") forever.
    const pollIdle = useCallback(async () => {
        if (typeof window !== "undefined" && !(window as unknown as { __neema_token?: string }).__neema_token) return;
        try {
            const calls = await callsApi.list({ limit: 5 });
            const now = Date.now();
            const ringing = calls.find((c) => c.status === "ringing" && c.direction !== "outbound"
                && c.started_at && now - new Date(c.started_at).getTime() < 90_000);
            if (ringing) startRinging(ringing.call_id, ringing.wa_id || "", ringing.name,
                { conversationId: ringing.conversation_id, personId: ringing.person_id });
        } catch { /* the socket is the primary path */ }
    }, [startRinging]);

    const resync = useCallback(() => {
        const s = snapRef.current;
        const w = waitingRef.current;
        if (w) callsApi.get(w.callId).then((r) => { if (r.status !== "ringing" && waitingRef.current?.callId === w.callId) setWaiting(null); }).catch(() => {});
        if (s.phase === "idle" || s.phase === "ended") { pollIdle(); return; }
        const id = s.call?.callId;
        if (!id || id === "pending" || s.phase === "ending") return;
        callsApi.get(id).then(applyRow).catch(() => {});
    }, [pollIdle, applyRow, setWaiting]);

    useEffect(() => {
        if (!ws) return;
        const onConnect = () => resync();
        ws.on("connect", onConnect);
        return () => ws.off("connect", onConnect);
    }, [ws, resync]);
    useEffect(() => {
        const onVis = () => { if (document.visibilityState === "visible") resync(); };
        const onOnline = () => {
            if (snapRef.current.notice === NO_NET) put({ notice: null });
            resync();
        };
        document.addEventListener("visibilitychange", onVis);
        window.addEventListener("online", onOnline);
        return () => { document.removeEventListener("visibilitychange", onVis); window.removeEventListener("online", onOnline); };
    }, [resync, put]);

    // ── Poll fallback (the socket is primary). Cheap: one row every 3 s while a
    // call rings or is reconnecting (catches a colleague answering, the caller
    // giving up), one row every 20 s on a live call, the last 5 calls every
    // 15 s when idle (a ring whose event was missed). Idle polling pauses in a
    // hidden tab; a ringing card keeps checking so it never rings a dead call.
    useEffect(() => {
        let stopped = false;
        let timer: ReturnType<typeof setTimeout> | null = null;
        const cadence = () => {
            const p = snapRef.current.phase;
            if (p === "incoming" || p === "ringing_out" || p === "reconnecting") return 3000;
            if (p === "connecting") return 5000;
            if (waitingRef.current) return 5000;
            return p === "active" ? 20_000 : 15_000;
        };
        const schedule = () => { if (!stopped) timer = setTimeout(run, cadence()); };
        const run = async () => {
            if (stopped) return;
            const s = snapRef.current;
            const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
            const hasToken = typeof window !== "undefined" && !!(window as unknown as { __neema_token?: string }).__neema_token;
            if (!hasToken) return schedule();
            const id = s.call?.callId;
            if (id && id !== "pending" && ["incoming", "ringing_out", "connecting", "active", "reconnecting"].includes(s.phase)) {
                if (!hidden || s.phase === "incoming" || s.phase === "reconnecting") {
                    try { applyRow(await callsApi.get(id)); } catch { /* next tick */ }
                }
            }
            const w = waitingRef.current;
            if (w) {
                try { const r = await callsApi.get(w.callId); if (r.status !== "ringing" && waitingRef.current?.callId === w.callId) setWaiting(null); }
                catch { /* next tick */ }
            }
            if ((s.phase === "idle" || s.phase === "ended") && !hidden) await pollIdle();
            schedule();
        };
        schedule();
        return () => { stopped = true; if (timer) clearTimeout(timer); };
    }, [applyRow, pollIdle, setWaiting]);

    // Warm the ICE config once signed in, so the first Answer skips a round trip.
    useEffect(() => {
        const t = setTimeout(() => {
            if ((window as unknown as { __neema_token?: string }).__neema_token) iceConfig().catch(() => {});
        }, 4000);
        return () => clearTimeout(t);
    }, [iceConfig, session]);

    // Recording starts once media flows (guarded: once per call).
    useEffect(() => {
        if (snap.phase === "active") startRecording();
    }, [snap.phase, startRecording]);

    // ── Ringing in a background tab: a notification (click → back to the card,
    // Answer focused) and a flashing tab title; both stop the moment it stops.
    const ringingId = snap.phase === "incoming" ? snap.call?.callId : undefined;
    const ringingWho = snap.phase === "incoming" ? callerLabel(snap.call) : "";
    const ringingWhoRef = useRef("");
    ringingWhoRef.current = ringingWho;
    useEffect(() => {
        if (!ringingId || typeof document === "undefined") return;
        const original = document.title;
        let note: Notification | null = null;
        let flip = false;
        const notify = () => {
            if (note || !document.hidden || typeof Notification === "undefined" || Notification.permission !== "granted") return;
            try {
                note = new Notification(`${ringingWhoRef.current} is calling`, {
                    body: "WhatsApp voice call — click to answer", tag: `neema-call-${ringingId}`, requireInteraction: true,
                });
                note.onclick = () => { window.focus(); note?.close(); };
            } catch { /* some browsers only allow notifications from a service worker */ }
        };
        const flash = () => {
            if (document.hidden) { flip = !flip; document.title = flip ? `📞 ${ringingWhoRef.current} is calling` : original; }
            else if (document.title !== original) document.title = original;
        };
        const onVis = () => { if (document.hidden) notify(); else document.title = original; };
        notify();
        const t = setInterval(flash, 1000);
        document.addEventListener("visibilitychange", onVis);
        return () => {
            clearInterval(t);
            document.removeEventListener("visibilitychange", onVis);
            document.title = original;
            note?.close();
        };
    }, [ringingId]);

    // The granted banner fades on its own after a minute.
    useEffect(() => {
        if (!granted) return;
        const t = setTimeout(() => setGranted(null), 60_000);
        return () => clearTimeout(t);
    }, [granted]);

    const recordingNote = recNote && snap.call && recNote.callId === snap.call.callId ? recNote.text : null;

    // Stable context identity: an inline object here re-rendered every
    // useCall() consumer (incl. the customer sidebar) on ANY provider render.
    const ctxValue = useMemo<CallCtx>(() => ({
        ...snap,
        outbound: snap.call?.direction === "outbound",
        muted, recording, recordingNote, waiting, granted, permissionBusy,
        inputs, outputs, inputId, outputId, canPickOutput, deviceNotice, notifyPermission,
        answer, decline, callbackLater, hangup, toggleMute, initiateCall, requestPermission, redial,
        dismiss, minimise, expand, openChat, setChatOpener,
        selectInput, selectOutput, refreshDevices,
        declineWaiting, callbackWaiting, endAndAnswerWaiting, callGranted, dismissGranted, requestNotifications,
        offerNotifications: askNotifyOnce,
    }), [snap, muted, recording, recordingNote, waiting, granted, permissionBusy,
        inputs, outputs, inputId, outputId, canPickOutput, deviceNotice, notifyPermission,
        answer, decline, callbackLater, hangup, toggleMute, initiateCall, requestPermission, redial,
        dismiss, minimise, expand, openChat, setChatOpener,
        selectInput, selectOutput, refreshDevices,
        declineWaiting, callbackWaiting, endAndAnswerWaiting, callGranted, dismissGranted, requestNotifications, askNotifyOnce]);
    return (
        <Ctx.Provider value={ctxValue}>
            {children}
            <audio ref={remoteAudioRef} autoPlay className="hidden" />
        </Ctx.Provider>
    );
}

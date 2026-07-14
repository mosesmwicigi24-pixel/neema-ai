"use client";

// Shared WhatsApp-call state + WebRTC, lifted to context so the call UI can
// render INSIDE the dashboard content area (sidebar stays visible) instead of a
// full-screen blackout — matching the Figma spec. CallProvider owns the socket
// listener, the peer connection, and the audio elements; useCall() exposes the
// state + actions to whatever renders the card.
import React, {
    createContext, useCallback, useContext, useEffect, useRef, useState, ReactNode,
} from "react";
import { useWs } from "@/lib/websocket";
import { callsApi } from "@/lib/api";

export type CallPhase = "idle" | "ringing" | "connecting" | "in_call" | "ended";
export interface CallState { callId: string; from: string; name?: string | null; }

interface CallCtx {
    phase: CallPhase;
    call: CallState | null;
    muted: boolean;
    seconds: number;
    error: string | null;
    note: string | null;
    answer: () => void;
    hangup: () => void;
    callback: () => void;
    toggleMute: () => void;
    initiateCall: (to: string, name?: string | null) => Promise<{ ok: boolean; error?: string }>;
    outbound: boolean;   // true while we placed the call (ringing THEM)
}

const Ctx = createContext<CallCtx | null>(null);
export const useCall = () => useContext(Ctx);

export function CallProvider({ children }: { children: ReactNode }) {
    const ws = useWs();
    const [phase, setPhase] = useState<CallPhase>("idle");
    const [call, setCall] = useState<CallState | null>(null);
    const [muted, setMuted] = useState(false);
    const [seconds, setSeconds] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [note, setNote] = useState<string | null>(null);
    const [outbound, setOutbound] = useState(false);

    const pcRef = useRef<RTCPeerConnection | null>(null);
    const localStreamRef = useRef<MediaStream | null>(null);
    const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
    const ringRef = useRef<{ ctx: AudioContext; timer: ReturnType<typeof setInterval> } | null>(null);

    // Generated ringtone (no asset file → no 404). Best-effort; browser autoplay
    // policy may mute it until a gesture, which is fine — the card is the alert.
    const startRing = useCallback(() => {
        try {
            const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
            const beep = () => {
                const o = ctx.createOscillator(), g = ctx.createGain();
                o.frequency.value = 480; o.type = "sine";
                o.connect(g); g.connect(ctx.destination);
                const t = ctx.currentTime;
                g.gain.setValueAtTime(0.0001, t);
                g.gain.exponentialRampToValueAtTime(0.18, t + 0.05);
                g.gain.exponentialRampToValueAtTime(0.0001, t + 0.7);
                o.start(t); o.stop(t + 0.75);
            };
            beep();
            ringRef.current = { ctx, timer: setInterval(beep, 2200) };
        } catch { /* ignore */ }
    }, []);
    const stopRing = useCallback(() => {
        if (ringRef.current) {
            clearInterval(ringRef.current.timer);
            ringRef.current.ctx.close().catch(() => {});
            ringRef.current = null;
        }
    }, []);
    const phaseRef = useRef<CallPhase>("idle");
    const activeIdRef = useRef<string | null>(null);          // the call currently on screen
    const endedAtRef = useRef<Record<string, number>>({});    // callId → when we last dismissed it
    useEffect(() => { phaseRef.current = phase; }, [phase]);

    // Start ringing for a given call (shared by the WS event + the poll fallback).
    // Rings whenever we're idle and this isn't a call we just dismissed (a short
    // cooldown stops a still-"ringing" record from instantly re-ringing after a
    // decline / failed answer, while still allowing a genuine retry after ~12s).
    const startRinging = useCallback((callId: string, from: string, name?: string | null) => {
        if (phaseRef.current !== "idle") return;
        const endedAt = endedAtRef.current[callId];
        if (endedAt && Date.now() - endedAt < 12000) return;
        activeIdRef.current = callId;
        setCall({ callId, from, name });
        startRing();
        setPhase("ringing");
    }, [startRing]);

    const cleanup = useCallback(() => {
        pcRef.current?.close(); pcRef.current = null;
        localStreamRef.current?.getTracks().forEach((t) => t.stop());
        localStreamRef.current = null;
        stopRing();
    }, [stopRing]);

    const finish = useCallback((noteText?: string) => {
        cleanup();
        if (activeIdRef.current) endedAtRef.current[activeIdRef.current] = Date.now();
        activeIdRef.current = null;
        if (noteText) setNote(noteText);
        setPhase("ended");
        setTimeout(() => {
            setPhase("idle"); setCall(null); setSeconds(0);
            setMuted(false); setError(null); setNote(null); setOutbound(false);
        }, noteText ? 1600 : 1000);
    }, [cleanup]);

    const hangup = useCallback(async () => {
        const id = call?.callId; cleanup();
        if (id) { try { await callsApi.terminate(id); } catch { /* gone */ } }
        finish();
    }, [call, cleanup, finish]);

    const callback = useCallback(async () => {
        const id = call?.callId; cleanup();
        if (id) { try { await callsApi.callback(id); } catch { /* recorded UI-side */ } }
        finish("Callback saved — find them under Calls");
    }, [call, cleanup, finish]);

    const answer = useCallback(async () => {
        if (!call) return;
        setError(null); setPhase("connecting"); stopRing();
        try {
            const [{ ice_servers }, offer] = await Promise.all([callsApi.iceConfig(), callsApi.offer(call.callId)]);
            console.debug("[call] ICE servers:", ice_servers);
            const pc = new RTCPeerConnection({ iceServers: ice_servers });
            pcRef.current = pc;
            pc.ontrack = (e) => { if (remoteAudioRef.current) remoteAudioRef.current.srcObject = e.streams[0]; };
            pc.onconnectionstatechange = () => {
                console.debug("[call] connectionState:", pc.connectionState);
                if (pc.connectionState === "connected") setPhase("in_call");
                if (["failed", "disconnected", "closed"].includes(pc.connectionState)) finish();
            };
            pc.oniceconnectionstatechange = () => {
                console.debug("[call] iceConnectionState:", pc.iceConnectionState);
                if (pc.iceConnectionState === "connected" || pc.iceConnectionState === "completed") setPhase("in_call");
            };
            pc.onicecandidate = (e) => {
                if (e.candidate && e.candidate.candidate.includes("typ relay")) console.debug("[call] got TURN relay candidate ✓");
            };
            pc.onicecandidateerror = (e: any) => console.warn("[call] ICE candidate error:", e?.errorText || e?.url);
            // Studio-ish mic: echo cancellation + noise suppression + auto gain.
            const mic = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
            });
            localStreamRef.current = mic;
            mic.getTracks().forEach((t) => pc.addTrack(t, mic));
            await pc.setRemoteDescription({ type: "offer", sdp: offer.sdp });
            await pc.setLocalDescription(await pc.createAnswer());
            await new Promise<void>((resolve) => {
                if (pc.iceGatheringState === "complete") return resolve();
                const check = () => { if (pc.iceGatheringState === "complete") { pc.removeEventListener("icegatheringstatechange", check); resolve(); } };
                pc.addEventListener("icegatheringstatechange", check);
                setTimeout(resolve, 2500);
            });
            await callsApi.answer(call.callId, pc.localDescription!.sdp);
        } catch (e: any) {
            setError(String(e?.message || "").includes("Permission")
                ? "Microphone blocked — allow it and try again" : "Couldn't connect the call");
            setTimeout(() => hangup(), 1800);
        }
    }, [call, finish, hangup]);

    const toggleMute = useCallback(() => {
        const s = localStreamRef.current; if (!s) return;
        const next = !muted;
        s.getAudioTracks().forEach((t) => (t.enabled = !next));
        setMuted(next);
    }, [muted]);

    const buildPc = useCallback((iceServers: RTCIceServer[]) => {
        const pc = new RTCPeerConnection({ iceServers });
        pc.ontrack = (e) => { if (remoteAudioRef.current) remoteAudioRef.current.srcObject = e.streams[0]; };
        pc.onconnectionstatechange = () => {
            console.debug("[call] connectionState:", pc.connectionState);
            if (pc.connectionState === "connected") setPhase("in_call");
            if (["failed", "disconnected", "closed"].includes(pc.connectionState)) finish();
        };
        pc.oniceconnectionstatechange = () => {
            console.debug("[call] iceConnectionState:", pc.iceConnectionState);
            if (pc.iceConnectionState === "connected" || pc.iceConnectionState === "completed") setPhase("in_call");
        };
        pc.onicecandidate = (e) => {
            if (e.candidate?.candidate.includes("typ relay")) console.debug("[call] got TURN relay candidate ✓");
        };
        pc.onicecandidateerror = (e: any) => console.warn("[call] ICE candidate error:", e?.errorText || e?.url);
        return pc;
    }, [finish]);

    const gatherThenReady = useCallback((pc: RTCPeerConnection) => new Promise<void>((resolve) => {
        if (pc.iceGatheringState === "complete") return resolve();
        const check = () => { if (pc.iceGatheringState === "complete") { pc.removeEventListener("icegatheringstatechange", check); resolve(); } };
        pc.addEventListener("icegatheringstatechange", check);
        setTimeout(resolve, 2500);
    }), []);

    // Business-initiated call: WE call the customer. Build an offer, ask Meta to
    // place the call; the customer's SDP answer arrives as an outbound_answer WS
    // event (handled below). Needs the customer's call permission (409 otherwise).
    const initiateCall = useCallback(async (to: string, name?: string | null): Promise<{ ok: boolean; error?: string }> => {
        if (phaseRef.current !== "idle") return { ok: false, error: "Already in a call" };
        setError(null); setOutbound(true);
        setCall({ callId: "pending", from: to.replace(/^\+/, ""), name: name ?? null });
        setPhase("connecting");
        try {
            const { ice_servers } = await callsApi.iceConfig();
            const pc = buildPc(ice_servers);
            pcRef.current = pc;
            const mic = await navigator.mediaDevices.getUserMedia({
                audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
            });
            localStreamRef.current = mic;
            mic.getTracks().forEach((t) => pc.addTrack(t, mic));
            await pc.setLocalDescription(await pc.createOffer());
            await gatherThenReady(pc);
            const { call_id } = await callsApi.connect(to, pc.localDescription!.sdp, name || undefined);
            activeIdRef.current = call_id;
            setCall((c) => (c ? { ...c, callId: call_id } : c));
            return { ok: true };
        } catch (e: any) {
            const msg = String(e?.message || "");
            const friendly = msg.includes("Permission") ? "Microphone blocked — allow it and try again"
                : msg.includes("409") ? "Customer hasn't granted call permission. Send the WhatsApp template first."
                : "Couldn't place the call";
            setError(friendly);
            setTimeout(() => { cleanup(); setOutbound(false); setPhase("idle"); setCall(null); }, 2200);
            return { ok: false, error: friendly };
        }
    }, [buildPc, gatherThenReady, cleanup]);

    // Primary path: the live WebSocket event (instant).
    useEffect(() => {
        if (!ws) { console.debug("[call] waiting for WebSocket…"); return; }
        console.debug("[call] listening for incoming calls");
        const onEvent = (evt: any) => {
            if (evt?.type === "incoming_call" || evt?.type === "call_ended") {
                console.debug("[call] WS event:", evt);
            }
            if (evt?.type === "incoming_call") {
                startRinging(evt.call_id, evt.from, evt.name);
            } else if (evt?.type === "outbound_answer" && evt.call_id === activeIdRef.current) {
                // The customer accepted OUR call — apply their SDP answer to connect.
                console.debug("[call] outbound answered");
                pcRef.current?.setRemoteDescription({ type: "answer", sdp: evt.sdp }).catch(() => {});
            } else if (evt?.type === "call_ended") {
                setCall((c) => { if (c && c.callId === evt.call_id) { cleanup(); setPhase("ended"); } return c; });
            }
        };
        ws.on("event", onEvent);
        return () => ws.off("event", onEvent);
    }, [ws, cleanup, startRinging]);

    // Fallback path: poll the call log for a fresh "ringing" call, so the card
    // appears even if the WS event was missed. The backend writes the ringing row
    // the instant a call connects; we ring on it within ~2.5s regardless of WS.
    useEffect(() => {
        const poll = async () => {
            try {
                const calls = await callsApi.list();
                const now = Date.now();
                // While we're RINGING, if the caller hung up (row no longer
                // "ringing") tear the card down — in case the WS end event was missed.
                if (phaseRef.current === "ringing") {
                    const cur = calls.find((c) => c.call_id === activeIdRef.current);
                    if (cur && cur.status !== "ringing") { cleanup(); activeIdRef.current = null; setPhase("idle"); setCall(null); }
                    return;
                }
                if (phaseRef.current !== "idle") return;
                const ringing = calls.find((c) =>
                    c.status === "ringing" &&
                    c.started_at && (now - new Date(c.started_at).getTime()) < 90000);
                if (ringing) {
                    console.debug("[call] poll fallback caught ringing call:", ringing.call_id);
                    startRinging(ringing.call_id, ringing.wa_id || "", ringing.name);
                }
            } catch { /* ignore */ }
        };
        const t = setInterval(poll, 2500);
        return () => clearInterval(t);
    }, [startRinging]);

    useEffect(() => {
        if (phase !== "in_call") return;
        const t = setInterval(() => setSeconds((s) => s + 1), 1000);
        return () => clearInterval(t);
    }, [phase]);

    return (
        <Ctx.Provider value={{ phase, call, muted, seconds, error, note, answer, hangup, callback, toggleMute, initiateCall, outbound }}>
            {children}
            <audio ref={remoteAudioRef} autoPlay className="hidden" />
        </Ctx.Provider>
    );
}

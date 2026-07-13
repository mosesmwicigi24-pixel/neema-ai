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

    const pcRef = useRef<RTCPeerConnection | null>(null);
    const localStreamRef = useRef<MediaStream | null>(null);
    const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
    const ringtoneRef = useRef<HTMLAudioElement | null>(null);

    const cleanup = useCallback(() => {
        pcRef.current?.close(); pcRef.current = null;
        localStreamRef.current?.getTracks().forEach((t) => t.stop());
        localStreamRef.current = null;
        ringtoneRef.current?.pause();
    }, []);

    const finish = useCallback((noteText?: string) => {
        cleanup();
        if (noteText) setNote(noteText);
        setPhase("ended");
        setTimeout(() => {
            setPhase("idle"); setCall(null); setSeconds(0);
            setMuted(false); setError(null); setNote(null);
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
        setError(null); setPhase("connecting"); ringtoneRef.current?.pause();
        try {
            const [{ ice_servers }, offer] = await Promise.all([callsApi.iceConfig(), callsApi.offer(call.callId)]);
            const pc = new RTCPeerConnection({ iceServers: ice_servers });
            pcRef.current = pc;
            pc.ontrack = (e) => { if (remoteAudioRef.current) remoteAudioRef.current.srcObject = e.streams[0]; };
            pc.onconnectionstatechange = () => {
                if (pc.connectionState === "connected") setPhase("in_call");
                if (["failed", "disconnected", "closed"].includes(pc.connectionState)) finish();
            };
            const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
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

    useEffect(() => {
        if (!ws) { console.debug("[call] waiting for WebSocket…"); return; }
        console.debug("[call] listening for incoming calls");
        const onEvent = (evt: any) => {
            if (evt?.type === "incoming_call" || evt?.type === "call_ended") {
                console.debug("[call] event received:", evt);
            }
            if (evt?.type === "incoming_call") {
                setPhase((p) => {
                    if (p !== "idle") return p;
                    setCall({ callId: evt.call_id, from: evt.from, name: evt.name });
                    ringtoneRef.current?.play().catch(() => {});
                    return "ringing";
                });
            } else if (evt?.type === "call_ended") {
                setCall((c) => { if (c && c.callId === evt.call_id) { cleanup(); setPhase("ended"); } return c; });
            }
        };
        ws.on("event", onEvent);
        return () => ws.off("event", onEvent);
    }, [ws, cleanup]);

    useEffect(() => {
        if (phase !== "in_call") return;
        const t = setInterval(() => setSeconds((s) => s + 1), 1000);
        return () => clearInterval(t);
    }, [phase]);

    return (
        <Ctx.Provider value={{ phase, call, muted, seconds, error, note, answer, hangup, callback, toggleMute }}>
            {children}
            <audio ref={remoteAudioRef} autoPlay className="hidden" />
            <audio ref={ringtoneRef} loop src="/ringtone.mp3" className="hidden" />
        </Ctx.Provider>
    );
}

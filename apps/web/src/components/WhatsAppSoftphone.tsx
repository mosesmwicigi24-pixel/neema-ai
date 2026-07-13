"use client";

// The dashboard softphone — answer inbound WhatsApp voice calls in the browser.
//
// Signalling: an inbound call publishes `incoming_call` over the existing
// WebSocket (type from routers/whatsapp_webhook.py). The agent clicks Answer;
// the browser fetches the caller's SDP offer + our ICE servers, builds a
// WebRTC answer with mic audio, and POSTs it — the API relays pre_accept →
// accept to Meta and audio flows browser↔customer directly. Hang up terminates.
//
// WhatsApp uses non-trickle SDP (the full answer, with ICE candidates, goes in
// one accept call), so we wait for ICE gathering to finish before sending.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useWs } from "@/lib/websocket";
import { callsApi } from "@/lib/api";

type Phase = "idle" | "ringing" | "connecting" | "in_call" | "ended";

interface CallState {
    callId: string;
    from: string;
    name?: string | null;
}

function fmtDur(s: number): string {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${m}:${sec.toString().padStart(2, "0")}`;
}

export function WhatsAppSoftphone(): React.ReactElement | null {
    const ws = useWs();
    const [phase, setPhase] = useState<Phase>("idle");
    const [call, setCall] = useState<CallState | null>(null);
    const [muted, setMuted] = useState(false);
    const [seconds, setSeconds] = useState(0);
    const [error, setError] = useState<string | null>(null);

    const pcRef = useRef<RTCPeerConnection | null>(null);
    const localStreamRef = useRef<MediaStream | null>(null);
    const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
    const ringtoneRef = useRef<HTMLAudioElement | null>(null);

    // ── Teardown ──────────────────────────────────────────────────────────────
    const cleanup = useCallback(() => {
        pcRef.current?.close();
        pcRef.current = null;
        localStreamRef.current?.getTracks().forEach((t) => t.stop());
        localStreamRef.current = null;
        ringtoneRef.current?.pause();
    }, []);

    const endCall = useCallback(
        async (notifyMeta: boolean) => {
            const id = call?.callId;
            cleanup();
            if (notifyMeta && id) {
                try { await callsApi.terminate(id); } catch { /* already gone */ }
            }
            setPhase("ended");
            setTimeout(() => { setPhase("idle"); setCall(null); setSeconds(0); setMuted(false); }, 1200);
        },
        [call, cleanup],
    );

    // ── Answer: WebRTC offer→answer, relayed to Meta ──────────────────────────
    const answer = useCallback(async () => {
        if (!call) return;
        setError(null);
        setPhase("connecting");
        ringtoneRef.current?.pause();
        try {
            const [{ ice_servers }, offer] = await Promise.all([
                callsApi.iceConfig(),
                callsApi.offer(call.callId),
            ]);
            const pc = new RTCPeerConnection({ iceServers: ice_servers });
            pcRef.current = pc;

            pc.ontrack = (e) => {
                if (remoteAudioRef.current) remoteAudioRef.current.srcObject = e.streams[0];
            };
            pc.onconnectionstatechange = () => {
                if (pc.connectionState === "connected") setPhase("in_call");
                if (["failed", "disconnected", "closed"].includes(pc.connectionState)) {
                    endCall(false);
                }
            };

            const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
            localStreamRef.current = mic;
            mic.getTracks().forEach((t) => pc.addTrack(t, mic));

            await pc.setRemoteDescription({ type: "offer", sdp: offer.sdp });
            const ans = await pc.createAnswer();
            await pc.setLocalDescription(ans);

            // Non-trickle: wait for ICE gathering to complete so the SDP we send
            // carries all candidates.
            await new Promise<void>((resolve) => {
                if (pc.iceGatheringState === "complete") return resolve();
                const check = () => {
                    if (pc.iceGatheringState === "complete") {
                        pc.removeEventListener("icegatheringstatechange", check);
                        resolve();
                    }
                };
                pc.addEventListener("icegatheringstatechange", check);
                setTimeout(resolve, 2500); // safety: don't hang forever
            });

            await callsApi.answer(call.callId, pc.localDescription!.sdp);
            // in_call is set by onconnectionstatechange when media connects.
        } catch (e: any) {
            setError(e?.message?.includes("Permission") ? "Microphone blocked" : "Couldn't connect the call");
            endCall(true);
        }
    }, [call, endCall]);

    const decline = useCallback(async () => {
        ringtoneRef.current?.pause();
        await endCall(true);
    }, [endCall]);

    const toggleMute = useCallback(() => {
        const s = localStreamRef.current;
        if (!s) return;
        const next = !muted;
        s.getAudioTracks().forEach((t) => (t.enabled = !next));
        setMuted(next);
    }, [muted]);

    // ── WS: incoming call / remote hangup ─────────────────────────────────────
    useEffect(() => {
        if (!ws) return;
        const onEvent = (evt: any) => {
            if (evt?.type === "incoming_call") {
                // Ignore a second ring while already on a call.
                setPhase((p) => {
                    if (p !== "idle") return p;
                    setCall({ callId: evt.call_id, from: evt.from, name: evt.name });
                    ringtoneRef.current?.play().catch(() => {});
                    return "ringing";
                });
            } else if (evt?.type === "call_ended") {
                setCall((c) => (c && c.callId === evt.call_id ? (cleanup(), setPhase("ended"), c) : c));
            }
        };
        ws.on("event", onEvent);
        return () => ws.off("event", onEvent);
    }, [ws, cleanup]);

    // ── In-call timer ─────────────────────────────────────────────────────────
    useEffect(() => {
        if (phase !== "in_call") return;
        const t = setInterval(() => setSeconds((s) => s + 1), 1000);
        return () => clearInterval(t);
    }, [phase]);

    if (phase === "idle") return <audio ref={remoteAudioRef} autoPlay className="hidden" />;

    const who = call?.name || (call?.from ? `+${call.from}` : "Unknown");

    return (
        <>
            <audio ref={remoteAudioRef} autoPlay className="hidden" />
            {/* Subtle ringtone via WebAudio-free loop; silent if the file 404s. */}
            <audio ref={ringtoneRef} loop src="/ringtone.mp3" className="hidden" />

            <div className="fixed bottom-6 right-6 z-[100] w-72 rounded-2xl shadow-2xl overflow-hidden"
                style={{ backgroundColor: "#0b141a", color: "#e9edef" }}>
                <div className="px-5 pt-5 pb-4 flex flex-col items-center gap-1">
                    <div className="w-14 h-14 rounded-full flex items-center justify-center text-xl font-bold"
                        style={{ backgroundColor: "#25D366", color: "#04220f" }}>
                        {(who[0] || "?").toUpperCase()}
                    </div>
                    <div className="text-sm font-semibold mt-1 text-center truncate max-w-full">{who}</div>
                    <div className="text-[11px]" style={{ color: "#8696a0" }}>
                        {phase === "ringing" && "Incoming WhatsApp call…"}
                        {phase === "connecting" && "Connecting…"}
                        {phase === "in_call" && fmtDur(seconds)}
                        {phase === "ended" && "Call ended"}
                    </div>
                    {error && <div className="text-[11px] text-red-400">{error}</div>}
                </div>

                <div className="flex items-center justify-center gap-4 pb-5">
                    {phase === "ringing" && (
                        <>
                            <button onClick={decline} title="Decline"
                                className="w-12 h-12 rounded-full flex items-center justify-center text-white text-xl"
                                style={{ backgroundColor: "#ef4444" }}>✕</button>
                            <button onClick={answer} title="Answer"
                                className="w-12 h-12 rounded-full flex items-center justify-center text-white text-xl"
                                style={{ backgroundColor: "#25D366" }}>📞</button>
                        </>
                    )}
                    {(phase === "connecting" || phase === "in_call") && (
                        <>
                            <button onClick={toggleMute} title={muted ? "Unmute" : "Mute"}
                                className="w-11 h-11 rounded-full flex items-center justify-center text-lg"
                                style={{ backgroundColor: muted ? "#8696a0" : "#202c33", color: "#fff" }}>
                                {muted ? "🔇" : "🎙"}
                            </button>
                            <button onClick={() => endCall(true)} title="Hang up"
                                className="w-12 h-12 rounded-full flex items-center justify-center text-white text-xl"
                                style={{ backgroundColor: "#ef4444" }}>📵</button>
                        </>
                    )}
                </div>
            </div>
        </>
    );
}

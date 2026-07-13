"use client";

// The dashboard softphone — answer inbound WhatsApp voice calls in the browser.
//
// A prominent, centred call modal (not a tucked-away card): when a call rings it
// takes over with a dimmed backdrop, a pulsing avatar, and three clear actions —
// Answer, Decline, Callback. On Answer it runs the WebRTC flow (fetch the caller's
// SDP offer + ICE servers, mic, build the answer, POST it → API relays
// pre_accept+accept to Meta → audio flows browser↔customer). In-call it shows a
// live timer, mute, and hang-up. WhatsApp is non-trickle, so we wait for ICE
// gathering before sending the answer.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useWs } from "@/lib/websocket";
import { callsApi } from "@/lib/api";

type Phase = "idle" | "ringing" | "connecting" | "in_call" | "ended";

interface CallState { callId: string; from: string; name?: string | null; }

function fmtDur(s: number): string {
    return `${Math.floor(s / 60)}:${(s % 60).toString().padStart(2, "0")}`;
}

export function WhatsAppSoftphone(): React.ReactElement | null {
    const ws = useWs();
    const [phase, setPhase] = useState<Phase>("idle");
    const [call, setCall] = useState<CallState | null>(null);
    const [muted, setMuted] = useState(false);
    const [seconds, setSeconds] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [note, setNote] = useState<string | null>(null);   // e.g. "Callback saved"

    const pcRef = useRef<RTCPeerConnection | null>(null);
    const localStreamRef = useRef<MediaStream | null>(null);
    const remoteAudioRef = useRef<HTMLAudioElement | null>(null);
    const ringtoneRef = useRef<HTMLAudioElement | null>(null);

    const cleanup = useCallback(() => {
        pcRef.current?.close();
        pcRef.current = null;
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
        const id = call?.callId;
        cleanup();
        if (id) { try { await callsApi.terminate(id); } catch { /* gone */ } }
        finish();
    }, [call, cleanup, finish]);

    const callback = useCallback(async () => {
        const id = call?.callId;
        cleanup();
        if (id) { try { await callsApi.callback(id); } catch { /* still recorded UI-side */ } }
        finish("Callback saved — find them under Calls");
    }, [call, cleanup, finish]);

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
                if (["failed", "disconnected", "closed"].includes(pc.connectionState)) finish();
            };
            const mic = await navigator.mediaDevices.getUserMedia({ audio: true });
            localStreamRef.current = mic;
            mic.getTracks().forEach((t) => pc.addTrack(t, mic));
            await pc.setRemoteDescription({ type: "offer", sdp: offer.sdp });
            await pc.setLocalDescription(await pc.createAnswer());
            await new Promise<void>((resolve) => {
                if (pc.iceGatheringState === "complete") return resolve();
                const check = () => {
                    if (pc.iceGatheringState === "complete") {
                        pc.removeEventListener("icegatheringstatechange", check); resolve();
                    }
                };
                pc.addEventListener("icegatheringstatechange", check);
                setTimeout(resolve, 2500);
            });
            await callsApi.answer(call.callId, pc.localDescription!.sdp);
        } catch (e: any) {
            setError(String(e?.message || "").includes("Permission")
                ? "Microphone blocked — allow it and try again"
                : "Couldn't connect the call");
            setTimeout(() => hangup(), 1800);
        }
    }, [call, finish, hangup]);

    const toggleMute = useCallback(() => {
        const s = localStreamRef.current;
        if (!s) return;
        const next = !muted;
        s.getAudioTracks().forEach((t) => (t.enabled = !next));
        setMuted(next);
    }, [muted]);

    // WS: incoming call / remote hangup.
    useEffect(() => {
        if (!ws) return;
        const onEvent = (evt: any) => {
            if (evt?.type === "incoming_call") {
                setPhase((p) => {
                    if (p !== "idle") return p;
                    setCall({ callId: evt.call_id, from: evt.from, name: evt.name });
                    ringtoneRef.current?.play().catch(() => {});
                    return "ringing";
                });
            } else if (evt?.type === "call_ended") {
                setCall((c) => {
                    if (c && c.callId === evt.call_id) { cleanup(); setPhase("ended"); }
                    return c;
                });
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

    if (phase === "idle") return <audio ref={remoteAudioRef} autoPlay className="hidden" />;

    const who = call?.name || (call?.from ? `+${call.from}` : "Unknown");
    const initial = (who.replace("+", "")[0] || "?").toUpperCase();
    const isRinging = phase === "ringing";
    const status =
        isRinging ? "Incoming WhatsApp call"
        : phase === "connecting" ? "Connecting…"
        : phase === "in_call" ? fmtDur(seconds)
        : note || "Call ended";

    return (
        <>
            <audio ref={remoteAudioRef} autoPlay className="hidden" />
            <audio ref={ringtoneRef} loop src="/ringtone.mp3" className="hidden" />

            {/* Backdrop — dims the app so the call can't be missed */}
            <div className="fixed inset-0 z-[200] flex items-center justify-center p-4"
                style={{ backgroundColor: "rgba(6, 20, 12, 0.55)", backdropFilter: "blur(3px)" }}>
                <div className="w-full max-w-sm rounded-3xl overflow-hidden shadow-2xl"
                    style={{ backgroundColor: "#0b141a", color: "#e9edef" }}>

                    <div className="px-8 pt-10 pb-6 flex flex-col items-center gap-3"
                        style={{ background: "linear-gradient(180deg,#0e5c3a 0%,#0b141a 78%)" }}>
                        {/* Pulsing avatar while ringing */}
                        <div className="relative">
                            {isRinging && (
                                <>
                                    <span className="absolute inset-0 rounded-full animate-ping"
                                        style={{ backgroundColor: "#25D366", opacity: 0.35 }} />
                                    <span className="absolute -inset-2 rounded-full animate-pulse"
                                        style={{ border: "2px solid #25D366", opacity: 0.4 }} />
                                </>
                            )}
                            <div className="relative w-24 h-24 rounded-full flex items-center justify-center text-3xl font-bold"
                                style={{ backgroundColor: "#25D366", color: "#04220f" }}>
                                {initial}
                            </div>
                        </div>
                        <div className="text-xl font-semibold mt-2 text-center px-2 truncate max-w-full">{who}</div>
                        <div className="text-[13px] flex items-center gap-1.5" style={{ color: "#a8c7b6" }}>
                            <span>🟢</span><span>WhatsApp voice</span>
                        </div>
                        <div className={`text-sm mt-1 ${error ? "text-red-300" : ""}`}
                            style={{ color: error ? undefined : "#cfe9d9" }}>
                            {error || status}
                        </div>
                    </div>

                    {/* Actions */}
                    <div className="px-6 py-7">
                        {isRinging && (
                            <div className="flex items-end justify-between">
                                <CallBtn color="#ef4444" label="Decline" icon="✕" onClick={hangup} />
                                <CallBtn color="#f59e0b" label="Callback" icon="↩" small onClick={callback} />
                                <CallBtn color="#25D366" label="Answer" icon="📞" big onClick={answer} />
                            </div>
                        )}
                        {(phase === "connecting" || phase === "in_call") && (
                            <div className="flex items-center justify-center gap-8">
                                <CallBtn color={muted ? "#8696a0" : "#202c33"}
                                    label={muted ? "Unmute" : "Mute"} icon={muted ? "🔇" : "🎙"} onClick={toggleMute} />
                                <CallBtn color="#ef4444" label="Hang up" icon="📵" big onClick={hangup} />
                            </div>
                        )}
                        {phase === "ended" && (
                            <div className="text-center text-sm" style={{ color: "#a8c7b6" }}>{note || "Call ended"}</div>
                        )}
                    </div>
                </div>
            </div>
        </>
    );
}

function CallBtn({ color, label, icon, onClick, big, small }: {
    color: string; label: string; icon: string; onClick: () => void; big?: boolean; small?: boolean;
}) {
    const size = big ? "w-16 h-16 text-2xl" : small ? "w-12 h-12 text-lg" : "w-14 h-14 text-xl";
    return (
        <button onClick={onClick} className="flex flex-col items-center gap-2 group">
            <span className={`${size} rounded-full flex items-center justify-center text-white shadow-lg transition-transform group-hover:scale-105 group-active:scale-95`}
                style={{ backgroundColor: color }}>{icon}</span>
            <span className="text-[11px]" style={{ color: "#8696a0" }}>{label}</span>
        </button>
    );
}

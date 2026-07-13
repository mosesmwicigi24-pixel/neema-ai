"use client";

// The dashboard softphone — answer inbound WhatsApp voice calls in the browser.
// Visual spec: the Figma "WhatsApp Softphone" board — a dimmed takeover with a
// pulsing-ring avatar (incoming), an online-dot avatar + big timer + animated
// waveform + "Connected" badge (live), and Answer / Decline / Callback actions.
// Logic: WebRTC answer (offer→answer, non-trickle) relayed to Meta via
// pre_accept+accept; audio flows browser↔customer.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useWs } from "@/lib/websocket";
import { callsApi } from "@/lib/api";

type Phase = "idle" | "ringing" | "connecting" | "in_call" | "ended";
interface CallState { callId: string; from: string; name?: string | null; }

// Inline SVG icons (the app has no icon webfont). 24×24, currentColor.
const ICONS: Record<string, React.ReactElement> = {
    phone: <path d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />,
    "phone-off": <><path d="M16 8l4-4m0 4l-4-4" /><path d="M18.5 16.5c.5.5.5 1.2.4 1.8A2 2 0 0117 20C9.7 20 4 14.3 4 7a2 2 0 011.7-2 1.9 1.9 0 011.8.4" /></>,
    callback: <path d="M9 14l-4-4 4-4M5 10h11a4 4 0 014 4v3" />,
    mic: <><path d="M12 2a3 3 0 00-3 3v6a3 3 0 006 0V5a3 3 0 00-3-3z" /><path d="M5 10v1a7 7 0 0014 0v-1M12 18v3" /></>,
    "mic-off": <><path d="M3 3l18 18" /><path d="M9 5a3 3 0 016 0v5m-1.3 2.7A3 3 0 019 11V9" /><path d="M5 10v1a7 7 0 0010.7 5.9M19 10v1a6.9 6.9 0 01-.3 2M12 18v3" /></>,
};

const fmt = (s: number) => `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;

function Waveform({ live }: { live: boolean }) {
    // 13 bars; when live they animate with staggered delays, otherwise flat.
    return (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 3, height: 26 }}>
            {Array.from({ length: 13 }).map((_, i) => (
                <span key={i} style={{
                    width: 3, borderRadius: 2, background: "#25D366",
                    height: 4,
                    animation: live ? `wf 0.9s ease-in-out ${(i % 7) * 0.09}s infinite` : "none",
                }} />
            ))}
        </div>
    );
}

export function WhatsAppSoftphone(): React.ReactElement | null {
    const ws = useWs();
    const [phase, setPhase] = useState<Phase>("idle");
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

    if (phase === "idle") return <audio ref={remoteAudioRef} autoPlay className="hidden" />;

    const who = call?.name || (call?.from ? `+${call.from}` : "Unknown");
    const initial = (who.replace("+", "")[0] || "?").toUpperCase();
    const isRinging = phase === "ringing";
    const live = phase === "in_call";

    return (
        <>
            <style>{`@keyframes wf{0%,100%{height:4px}50%{height:22px}}
                @keyframes ring1{0%{transform:scale(1);opacity:.5}100%{transform:scale(1.9);opacity:0}}
                @keyframes ring2{0%{transform:scale(1);opacity:.35}100%{transform:scale(2.4);opacity:0}}`}</style>
            <audio ref={remoteAudioRef} autoPlay className="hidden" />
            <audio ref={ringtoneRef} loop src="/ringtone.mp3" className="hidden" />

            <div className="fixed inset-0 z-[200] flex items-center justify-center p-4"
                style={{ backgroundColor: "rgba(4,14,9,0.62)", backdropFilter: "blur(4px)" }}>
                <div className="w-full max-w-sm rounded-[28px] overflow-hidden"
                    style={{ backgroundColor: "#0b141a", color: "#e9edef", boxShadow: "0 24px 60px rgba(0,0,0,0.5)", border: "1px solid #1c2b22" }}>

                    <div className="px-8 pt-11 pb-7 flex flex-col items-center"
                        style={{ background: "radial-gradient(120% 90% at 50% 0%, #0e5c3a 0%, #0b141a 70%)" }}>
                        {/* Avatar with pulse rings (ringing) or online dot (live) */}
                        <div className="relative mb-4" style={{ width: 104, height: 104 }}>
                            {isRinging && (
                                <>
                                    <span className="absolute inset-0 rounded-full" style={{ background: "#25D366", animation: "ring1 1.6s ease-out infinite" }} />
                                    <span className="absolute inset-0 rounded-full" style={{ background: "#25D366", animation: "ring2 1.6s ease-out infinite" }} />
                                </>
                            )}
                            <div className="relative w-[104px] h-[104px] rounded-full flex items-center justify-center text-4xl font-semibold"
                                style={{ backgroundColor: "#25D366", color: "#04220f" }}>
                                {initial}
                            </div>
                            {live && (
                                <span className="absolute bottom-1.5 right-1.5 w-5 h-5 rounded-full border-4"
                                    style={{ backgroundColor: "#25D366", borderColor: "#0b141a" }} />
                            )}
                        </div>

                        <div className="text-[22px] font-semibold text-center px-2 truncate max-w-full leading-tight">{who}</div>
                        {call?.from && <div className="text-[13px] mt-1 tracking-wide" style={{ color: "#8aa89a" }}>+{call.from}</div>}

                        {isRinging && (
                            <div className="mt-3 px-3 py-1 rounded-full text-[12px] flex items-center gap-1.5"
                                style={{ backgroundColor: "rgba(37,211,102,0.14)", color: "#a8e6c4" }}>
                                <span className="w-1.5 h-1.5 rounded-full" style={{ background: "#25D366" }} /> Incoming WhatsApp
                            </div>
                        )}
                        {phase === "connecting" && <div className="mt-4 text-sm" style={{ color: "#cfe9d9" }}>Connecting…</div>}
                        {live && (
                            <>
                                <div className="mt-4 text-[30px] font-light tracking-[0.15em] tabular-nums">{fmt(seconds)}</div>
                                <div className="mt-3"><Waveform live /></div>
                                <div className="mt-3 px-3 py-1 rounded-full text-[12px] flex items-center gap-1.5"
                                    style={{ backgroundColor: "rgba(37,211,102,0.14)", color: "#a8e6c4" }}>
                                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: "#25D366" }} /> Connected
                                </div>
                            </>
                        )}
                        {error && <div className="mt-3 text-sm text-red-300">{error}</div>}
                    </div>

                    <div className="px-7 py-8">
                        {isRinging && (
                            <div className="flex items-end justify-between">
                                <Btn color="#E24B4A" label="Decline" icon="phone-off" onClick={hangup} />
                                <Btn color="#EF9F27" label="Callback" icon="callback" small onClick={callback} />
                                <Btn color="#25D366" label="Answer" icon="phone" big onClick={answer} />
                            </div>
                        )}
                        {(phase === "connecting" || live) && (
                            <div className="flex items-center justify-center gap-10">
                                <Btn color={muted ? "#8696a0" : "#202c33"} label={muted ? "Unmute" : "Mute"}
                                    icon={muted ? "mic-off" : "mic"} onClick={toggleMute} />
                                <Btn color="#E24B4A" label="Hang up" icon="phone-off" big onClick={hangup} />
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

function Btn({ color, label, icon, onClick, big, small }: {
    color: string; label: string; icon: string; onClick: () => void; big?: boolean; small?: boolean;
}) {
    const d = big ? 64 : small ? 48 : 56;
    const s = big ? 26 : 22;
    return (
        <button onClick={onClick} className="flex flex-col items-center gap-2 group" aria-label={label}>
            <span className="rounded-full flex items-center justify-center text-white transition-transform group-hover:scale-105 group-active:scale-95"
                style={{ width: d, height: d, backgroundColor: color, boxShadow: "0 6px 16px rgba(0,0,0,0.35)" }}>
                <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    {ICONS[icon]}
                </svg>
            </span>
            <span className="text-[11px]" style={{ color: "#8696a0" }}>{label}</span>
        </button>
    );
}

"use client";

// The call card — rendered INSIDE the dashboard content area (absolute overlay),
// so the sidebar stays visible, exactly like the Figma "WhatsApp Softphone" board.
// Reads all state/actions from CallProvider; renders nothing when idle.
import React from "react";
import { useCall } from "@/lib/callContext";

const ICONS: Record<string, React.ReactElement> = {
    phone: <path d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />,
    "phone-off": <><path d="M16 8l4-4m0 4l-4-4" /><path d="M18.5 16.5c.5.5.5 1.2.4 1.8A2 2 0 0117 20C9.7 20 4 14.3 4 7a2 2 0 011.7-2 1.9 1.9 0 011.8.4" /></>,
    callback: <path d="M9 14l-4-4 4-4M5 10h11a4 4 0 014 4v3" />,
    mic: <><path d="M12 2a3 3 0 00-3 3v6a3 3 0 006 0V5a3 3 0 00-3-3z" /><path d="M5 10v1a7 7 0 0014 0v-1M12 18v3" /></>,
    "mic-off": <><path d="M3 3l18 18" /><path d="M9 5a3 3 0 016 0v5m-1.3 2.7A3 3 0 019 11V9" /><path d="M5 10v1a7 7 0 0010.7 5.9M19 10v1a6.9 6.9 0 01-.3 2M12 18v3" /></>,
};

const fmt = (s: number) => `${Math.floor(s / 60).toString().padStart(2, "0")}:${(s % 60).toString().padStart(2, "0")}`;

function Waveform() {
    return (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 4, height: 30 }}>
            {Array.from({ length: 15 }).map((_, i) => (
                <span key={i} style={{
                    width: 3, borderRadius: 2, background: "#25D366", height: 4,
                    animation: `cwf 0.9s ease-in-out ${(i % 8) * 0.08}s infinite`,
                }} />
            ))}
        </div>
    );
}

export function CallStage(): React.ReactElement | null {
    const c = useCall();
    if (!c || c.phase === "idle") return null;

    const { phase, call, muted, seconds, error, note, answer, hangup, callback, toggleMute } = c;
    const who = call?.name || (call?.from ? `+${call.from}` : "Unknown");
    const initial = (who.replace("+", "")[0] || "?").toUpperCase();
    const ringing = phase === "ringing";
    const live = phase === "in_call";

    return (
        <div className="absolute inset-0 z-50 flex items-center justify-center p-6"
            style={{ background: "radial-gradient(130% 100% at 50% 0%, #0e5c3a 0%, #06110b 60%)" }}>
            <style>{`@keyframes cwf{0%,100%{height:5px}50%{height:26px}}
                @keyframes cr1{0%{transform:scale(1);opacity:.45}100%{transform:scale(2);opacity:0}}
                @keyframes cr2{0%{transform:scale(1);opacity:.3}100%{transform:scale(2.6);opacity:0}}`}</style>

        <div className="w-full max-w-md rounded-[32px] overflow-hidden text-center"
            style={{ backgroundColor: "rgba(11,20,26,0.6)", border: "1px solid rgba(37,211,102,0.18)", boxShadow: "0 30px 80px rgba(0,0,0,0.55)" }}>
            <div className="px-10 pt-14 pb-10 flex flex-col items-center" style={{ color: "#e9edef" }}>
                {/* Avatar */}
                <div className="relative mb-6" style={{ width: 132, height: 132 }}>
                    {ringing && (
                        <>
                            <span className="absolute inset-0 rounded-full" style={{ background: "#25D366", animation: "cr1 1.7s ease-out infinite" }} />
                            <span className="absolute inset-0 rounded-full" style={{ background: "#25D366", animation: "cr2 1.7s ease-out infinite" }} />
                        </>
                    )}
                    <div className="relative rounded-full flex items-center justify-center font-semibold"
                        style={{ width: 132, height: 132, backgroundColor: "#25D366", color: "#04220f", fontSize: 46 }}>
                        {initial}
                    </div>
                    {live && <span className="absolute rounded-full" style={{ bottom: 8, right: 8, width: 26, height: 26, backgroundColor: "#25D366", border: "5px solid #06110b" }} />}
                </div>

                <div className="font-semibold leading-tight px-2 truncate max-w-full" style={{ fontSize: 26 }}>{who}</div>
                {call?.from && <div className="mt-1.5 tracking-widest" style={{ fontSize: 14, color: "#8aa89a" }}>+{call.from}</div>}

                {ringing && (
                    <div className="mt-5 px-4 py-1.5 rounded-full flex items-center gap-2" style={{ fontSize: 13, backgroundColor: "rgba(37,211,102,0.14)", color: "#a8e6c4" }}>
                        <span className="w-2 h-2 rounded-full" style={{ background: "#25D366" }} /> Incoming WhatsApp
                    </div>
                )}
                {phase === "connecting" && <div className="mt-6 text-sm" style={{ color: "#cfe9d9" }}>Connecting…</div>}
                {live && (
                    <>
                        <div className="mt-6 font-light tabular-nums" style={{ fontSize: 44, letterSpacing: "0.12em" }}>{fmt(seconds)}</div>
                        <div className="mt-4"><Waveform /></div>
                        <div className="mt-4 px-4 py-1.5 rounded-full flex items-center gap-2" style={{ fontSize: 13, backgroundColor: "rgba(37,211,102,0.14)", color: "#a8e6c4" }}>
                            <span className="w-2 h-2 rounded-full" style={{ background: "#25D366" }} /> Connected
                        </div>
                    </>
                )}
                {error && <div className="mt-4 text-sm text-red-300">{error}</div>}
                {phase === "ended" && <div className="mt-4 text-sm" style={{ color: "#a8c7b6" }}>{note || "Call ended"}</div>}

                {/* Actions */}
                <div className="mt-10 w-full">
                    {ringing && (
                        <div className="flex items-end justify-center gap-12">
                            <Btn color="#E24B4A" label="Decline" icon="phone-off" onClick={hangup} />
                            <Btn color="#EF9F27" label="Callback" icon="callback" small onClick={callback} />
                            <Btn color="#25D366" label="Answer" icon="phone" big onClick={answer} />
                        </div>
                    )}
                    {(phase === "connecting" || live) && (
                        <div className="flex items-center justify-center gap-14">
                            <Btn color={muted ? "#8696a0" : "#1f2c33"} label={muted ? "Unmute" : "Mute"} icon={muted ? "mic-off" : "mic"} onClick={toggleMute} />
                            <Btn color="#E24B4A" label="Hang up" icon="phone-off" big onClick={hangup} />
                        </div>
                    )}
                </div>
            </div>
        </div>
        </div>
    );
}

function Btn({ color, label, icon, onClick, big, small }: {
    color: string; label: string; icon: string; onClick: () => void; big?: boolean; small?: boolean;
}) {
    const d = big ? 72 : small ? 54 : 62;
    const s = big ? 28 : 24;
    return (
        <button onClick={onClick} className="flex flex-col items-center gap-2.5 group" aria-label={label}>
            <span className="rounded-full flex items-center justify-center text-white transition-transform group-hover:scale-105 group-active:scale-95"
                style={{ width: d, height: d, backgroundColor: color, boxShadow: "0 8px 20px rgba(0,0,0,0.4)" }}>
                <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    {ICONS[icon]}
                </svg>
            </span>
            <span style={{ fontSize: 12, color: "#8696a0" }}>{label}</span>
        </button>
    );
}

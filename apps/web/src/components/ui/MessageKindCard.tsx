// A non-plain message drawn as what it IS — a location with a map link, a
// shared contact, "Reacted ❤️ to …", a cart, or, for the residual WhatsApp
// won't show businesses, a calm card that names it (calls & audio programme,
// cycle 2). The words come from lib/messageKinds.ts; this file only draws.
import React from "react";
import type { KindView } from "@/lib/messageKinds";

const TONE: Record<KindView["tone"], { ink: string; soft: string; border: string }> = {
    neutral: { ink: "#1c2917", soft: "#f5f7f2", border: "#e2e8e0" },
    info: { ink: "#1c2917", soft: "#f2f7ee", border: "#d7ecd9" },
    good: { ink: "#128C4B", soft: "#E7F6EC", border: "#b7e4c7" },
    warn: { ink: "#A15C00", soft: "#FFF6E5", border: "#f3d9a4" },
    muted: { ink: "#57534e", soft: "#f5f5f4", border: "#e7e5e4" },
};

/** Inside the customer's bubble: icon + title, lines, an optional link. */
export function MessageKindCard({ view, isInbound }: { view: KindView; isInbound: boolean }) {
    const t = TONE[view.tone];
    return (
        <div className="flex flex-col gap-1 min-w-[180px] max-w-[320px]" data-message-kind={view.title}>
            <div className="flex items-start gap-2">
                <span className="text-base leading-5 flex-shrink-0 select-none" aria-hidden="true">{view.icon}</span>
                <p className="text-[13px] font-semibold leading-5" style={{ color: isInbound ? t.ink : "inherit" }}>
                    {view.title}
                </p>
            </div>
            {view.lines.length > 0 && (
                <ul className="pl-7 space-y-0.5">
                    {view.lines.map((l, i) => (
                        <li key={i} className="text-xs leading-relaxed whitespace-pre-wrap break-words"
                            style={{ color: isInbound ? "#57534e" : "inherit", opacity: isInbound ? 1 : 0.85 }}>
                            {l}
                        </li>
                    ))}
                </ul>
            )}
            {view.link && (
                <a href={view.link.href} target="_blank" rel="noopener noreferrer"
                    className="ml-7 inline-flex items-center gap-1 w-fit h-8 px-3 rounded-full text-xs font-semibold border hover:brightness-95 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#128C4B]"
                    style={{ color: "#128C4B", backgroundColor: "#fff", borderColor: "#b7e4c7" }}>
                    {view.link.label}
                    <span aria-hidden="true">↗</span>
                </a>
            )}
            {view.details && (
                <p className="pl-7 text-[10px] leading-snug" style={{ color: "#78716c" }}
                    title="What WhatsApp told us — for the team">
                    {view.details}
                </p>
            )}
        </div>
    );
}

/** A centred event line (a number change, a call-permission tap, a first open):
 *  something that happened in the chat, not something the customer said. */
export function MessageKindPill({ view, at }: { view: KindView; at?: string | null }) {
    const t = TONE[view.tone];
    return (
        <div className="flex items-center gap-2 my-2" data-message-kind={view.title}>
            <div className="flex-1 h-px bg-stone-200" />
            <div className="flex flex-wrap items-center justify-center gap-x-1.5 gap-y-0.5 px-3 py-1 rounded-full border max-w-[88%]"
                style={{ backgroundColor: t.soft, borderColor: t.border }}>
                <span className="text-xs select-none" aria-hidden="true">{view.icon}</span>
                <span className="text-[11px] font-semibold" style={{ color: t.ink }}>{view.title}</span>
                {view.lines.map((l, i) => (
                    <span key={i} className="text-[10px]" style={{ color: "#57534e" }}>· {l}</span>
                ))}
                {at && <span className="text-[10px] tabular-nums" style={{ color: "#78716c" }}>
                    · {new Date(at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>}
            </div>
            <div className="flex-1 h-px bg-stone-200" />
        </div>
    );
}

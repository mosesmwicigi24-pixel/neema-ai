"use client";

// The composer's two small menus (owner, 2026-11-09): what can be attached on
// this channel, and Neema's tools. Both open on demand so the row itself stays
// four controls: attach · Neema · text · send.

import { useEffect, useRef, useState } from "react";

export type AttachKind = { id: "media" | "document" | "audio"; label: string; hint: string; accept: string };

const MEDIA = "image/jpeg,image/png,image/webp,image/gif,video/mp4,video/3gpp,video/quicktime,video/hevc,video/x-m4v,.mov,.hevc";
const DOCS = "application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
    + "application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const AUDIO = "audio/ogg,audio/aac,audio/mpeg";

/**
 * What each channel can carry, so the menu never offers a file the send would
 * refuse: SMS is receive-only; Instagram DMs take photos, videos and audio but
 * no documents; WhatsApp and Messenger take all three.
 */
export function attachKindsFor(channel: string): AttachKind[] {
    if (channel === "sms") return [];
    const all: AttachKind[] = [
        { id: "media", label: "Photos & videos", hint: "Photos 5 MB · videos 150 MB", accept: MEDIA },
        { id: "document", label: "Document", hint: "PDF, Word, Excel · up to 18 MB", accept: DOCS },
        { id: "audio", label: "Audio file", hint: "MP3, AAC, OGG · up to 16 MB", accept: AUDIO },
    ];
    return channel === "instagram" ? all.filter((k) => k.id !== "document") : all;
}

/** Text with `insert` placed at the selection, and where the caret goes after it. */
export function insertAtCursor(text: string, insert: string, start: number, end: number) {
    const s = Math.max(0, Math.min(start, text.length));
    const e = Math.max(s, Math.min(end, text.length));
    return { text: text.slice(0, s) + insert + text.slice(e), caret: s + insert.length };
}

const ENTER_KEY = "neema.composer.enterSends";

/** Enter sends (default) or Ctrl/⌘+Enter sends — the agent's choice, kept in this browser. */
export function useEnterSends(): [boolean, (v: boolean) => void] {
    const [v, setV] = useState<boolean>(() => {
        try { return typeof window === "undefined" ? true : localStorage.getItem(ENTER_KEY) !== "0"; }
        catch { return true; }
    });
    const set = (next: boolean) => {
        setV(next);
        try { localStorage.setItem(ENTER_KEY, next ? "1" : "0"); } catch { /* private window */ }
    };
    return [v, set];
}

function usePopover(open: boolean, onClose: () => void) {
    const ref = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (!open) return;
        const down = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
        const key = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
        document.addEventListener("mousedown", down);
        document.addEventListener("keydown", key);
        return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
    }, [open, onClose]);
    return ref;
}

const ROUND = "h-11 w-11 sm:h-10 sm:w-10 rounded-2xl flex items-center justify-center transition-all active:scale-95 flex-shrink-0";
const PANEL = "absolute bottom-full left-0 mb-2 z-30 w-72 max-w-[calc(100vw-32px)] rounded-2xl bg-white border border-[#e5e8e2] shadow-[0_8px_30px_rgba(28,41,23,0.12)] p-1.5 animate-in fade-in slide-in-from-bottom-1 duration-150";

const KIND_ICON: Record<AttachKind["id"], { bg: string; fg: string; path: string }> = {
    media: { bg: "#eef4ff", fg: "#2563eb", path: "M4 16l4.6-4.6a2 2 0 012.8 0L16 16m-2-2l1.6-1.6a2 2 0 012.8 0L20 14M14 8h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" },
    document: { bg: "#f3effd", fg: "#7c3aed", path: "M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.6a1 1 0 01.7.3l5.4 5.4a1 1 0 01.3.7V19a2 2 0 01-2 2z" },
    audio: { bg: "#fff4e6", fg: "#d97706", path: "M9 19V6l12-3v13M9 19a3 3 0 11-6 0 3 3 0 016 0zm12-3a3 3 0 11-6 0 3 3 0 016 0z" },
};

export function AttachMenu({ open, onToggle, onClose, onPick, channel }: {
    open: boolean; onToggle: () => void; onClose: () => void; onPick: (k: AttachKind) => void; channel: string;
}) {
    const ref = usePopover(open, onClose);
    const kinds = attachKindsFor(channel);
    if (!kinds.length) return null;            // SMS: nothing can be sent, so nothing to attach
    return (
        <div ref={ref} className="relative">
            <button type="button" onClick={onToggle} title="Attach" aria-label="Attach" aria-expanded={open}
                    className={`${ROUND} ${open ? "bg-[#1c2917] text-white" : "bg-[#f1f3f5] text-[#64748b] hover:bg-[#e5e8eb]"}`}>
                <svg className={`w-[18px] h-[18px] transition-transform duration-200 ${open ? "rotate-45" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
                    <path strokeLinecap="round" d="M12 5v14M5 12h14" />
                </svg>
            </button>
            {open && (
                <div role="menu" className={PANEL}>
                    {kinds.map((k) => {
                        const ic = KIND_ICON[k.id];
                        return (
                            <button key={k.id} type="button" role="menuitem" onClick={() => onPick(k)}
                                    className="w-full flex items-center gap-3 px-2.5 py-2 rounded-xl text-left hover:bg-[#f6f7f5]">
                                <span className="h-9 w-9 rounded-xl flex items-center justify-center flex-shrink-0" style={{ backgroundColor: ic.bg, color: ic.fg }}>
                                    <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
                                        <path strokeLinecap="round" strokeLinejoin="round" d={ic.path} />
                                    </svg>
                                </span>
                                <span className="min-w-0">
                                    <span className="block text-[13px] font-medium text-[#1c2917]">{k.label}</span>
                                    <span className="block text-[11px] text-stone-400 truncate">{k.hint}</span>
                                </span>
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

export function ToolsMenu({
    open, onToggle, onClose, canDraft, drafting, onDraft, enterSends, onEnterSends,
}: {
    open: boolean; onToggle: () => void; onClose: () => void;
    canDraft: boolean; drafting: boolean; onDraft: () => void;
    enterSends: boolean; onEnterSends: (v: boolean) => void;
}) {
    const ref = usePopover(open, onClose);
    return (
        <div ref={ref} className="relative">
            <button type="button" onClick={onToggle} title="Neema tools" aria-label="Neema tools" aria-expanded={open}
                    className={`${ROUND} ${open ? "bg-[#fef3c7] text-[#b45309]" : "bg-[#f1f3f5] text-[#64748b] hover:bg-[#e5e8eb]"}`}>
                {drafting ? (
                    <span className="w-4 h-4 border-2 border-[#d97706] border-t-transparent rounded-full animate-spin" />
                ) : (
                    <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.8}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M9.8 3.5l1.3 3.6a2 2 0 001.2 1.2l3.6 1.3-3.6 1.3a2 2 0 00-1.2 1.2l-1.3 3.6-1.3-3.6a2 2 0 00-1.2-1.2L3.7 9.6l3.6-1.3a2 2 0 001.2-1.2L9.8 3.5zM17.5 14l.7 1.8a1 1 0 00.6.6l1.8.7-1.8.7a1 1 0 00-.6.6l-.7 1.8-.7-1.8a1 1 0 00-.6-.6l-1.8-.7 1.8-.7a1 1 0 00.6-.6l.7-1.8z" />
                    </svg>
                )}
            </button>
            {open && (
                <div role="menu" className={PANEL}>
                    <button type="button" role="menuitem" onClick={onDraft} disabled={!canDraft || drafting}
                            title={canDraft ? undefined : "Pick up the chat (human mode) to ask Neema for a draft"}
                            className="w-full flex items-center gap-3 px-2.5 py-2 rounded-xl text-left hover:bg-[#f6f7f5] disabled:opacity-45 disabled:hover:bg-transparent">
                        <span className="h-9 w-9 rounded-xl flex items-center justify-center bg-[#eef4ff] text-base">🤖</span>
                        <span className="min-w-0">
                            <span className="block text-[13px] font-medium text-[#1c2917]">{drafting ? "Drafting…" : "Ask Neema for a draft"}</span>
                            <span className="block text-[11px] text-stone-400">A reply you can send, edit or dismiss</span>
                        </span>
                    </button>
                    <div className="my-1 border-t border-[#eef1ea]" />
                    <button type="button" role="menuitemcheckbox" aria-checked={enterSends} onClick={() => onEnterSends(!enterSends)}
                            className="w-full flex items-center gap-3 px-2.5 py-2 rounded-xl text-left hover:bg-[#f6f7f5]">
                        <span className="h-9 w-9 rounded-xl flex items-center justify-center bg-[#f3f5f0] text-[13px] font-semibold text-[#64748b]">↵</span>
                        <span className="min-w-0 flex-1">
                            <span className="block text-[13px] font-medium text-[#1c2917]">Enter sends</span>
                            <span className="block text-[11px] text-stone-400">{enterSends ? "Shift + Enter for a new line" : "Ctrl/⌘ + Enter sends"}</span>
                        </span>
                        <Switch on={enterSends} />
                    </button>
                </div>
            )}
        </div>
    );
}

function Switch({ on }: { on: boolean }) {
    return (
        <span aria-hidden="true" className={`relative inline-flex h-5 w-9 flex-shrink-0 rounded-full transition-colors ${on ? "bg-[#589b31]" : "bg-stone-300"}`}>
            <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${on ? "translate-x-4" : "translate-x-0.5"}`} />
        </span>
    );
}

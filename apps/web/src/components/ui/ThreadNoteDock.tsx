"use client";

// The thread note (owner, 2026-11-15: "a note which is always floating at the
// foot … can be updated rather than internal notes that are in bits … collapsed
// like a chat box and opened again … highly summarized without missing key
// information").
//
// Folded: one slim line above the reply box — the team note, else Neema's
// status — with a count of what is new since you last looked.
// Open: a panel that rises over the chat like a chat window:
//   📌 Team note      one per thread, edited in place, who/when shown
//   🤝 Neema's brief  the newest handoff briefing as Status / Next / Avoid / Say
//   History           every other note as one line; tap for the full text
// Internal only: nothing here is sent to the customer or to the model.

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, CornerDownLeft, History, Pencil } from "lucide-react";
import { conversationsApi, apiErrorInfo, type TeamNote } from "@/lib/api";
import { useConversationEvents } from "@/lib/websocket";
import { timeAgo } from "@/lib/utils";
import {
    KIND_ICON, barSummary, noteKind, oneLine, parseBrief, splitNotes, unseenCount, type NoteLike,
} from "@/lib/threadNote";

const MAX = 1000;
const OPEN_KEY = "neema.threadNote.open";
const seenKey = (id: string) => `neema.threadNote.seen.${id}`;
const draftKey = (id: string) => `neema.threadNote.draft.${id}`;

// Storage can throw (private mode, quota): the panel must work without it.
const store = {
    get(k: string, s: Storage | undefined) { try { return s?.getItem(k) ?? null; } catch { return null; } },
    set(k: string, v: string, s: Storage | undefined) { try { s?.setItem(k, v); } catch { /* ignore */ } },
    del(k: string, s: Storage | undefined) { try { s?.removeItem(k); } catch { /* ignore */ } },
};
const local = () => (typeof window !== "undefined" ? window.localStorage : undefined);
const session = () => (typeof window !== "undefined" ? window.sessionStorage : undefined);

const LABEL_LOOK: Record<string, string> = {
    Status: "bg-slate-100 text-slate-700",
    Next:   "bg-emerald-50 text-emerald-700",
    Avoid:  "bg-rose-50 text-rose-700",
    Say:    "bg-sky-50 text-sky-700",
};

export function ThreadNoteDock({
    convId, notes, editSignal, onUseLine,
}: {
    convId: string;
    /** The thread's internal-note rows (isNote), any order. */
    notes: NoteLike[];
    /** Bumped by the header's Note button: open straight into editing. */
    editSignal: number;
    /** Put a line (the brief's "Say") into the reply box; absent when there is no reply box. */
    onUseLine?: (text: string) => void;
}) {
    const [open, setOpen] = useState<boolean>(() => store.get(OPEN_KEY, local()) === "1");
    const [team, setTeam] = useState<TeamNote | null>(null);
    const [loadFailed, setLoadFailed] = useState(false);
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState("");
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [conflict, setConflict] = useState<TeamNote | null>(null);
    const [historyOpen, setHistoryOpen] = useState(false);
    const [expanded, setExpanded] = useState<string | null>(null);
    const [seen, setSeen] = useState<string | null>(null);
    const [shown, setShown] = useState(false);           // drives the rise-in transition
    const area = useRef<HTMLTextAreaElement>(null);
    const panel = useRef<HTMLDivElement>(null);
    const bar = useRef<HTMLButtonElement>(null);
    const baseAt = useRef<string | null>(null);         // the `at` an edit started from

    const { brief, history } = useMemo(() => splitNotes(notes), [notes]);
    const rows = useMemo(() => parseBrief(brief?.text), [brief]);
    const summary = barSummary(team?.text, brief);
    const unseen = unseenCount(notes, seen);
    const empty = !team?.text && !brief && history.length === 0;

    // ── A new thread: load its note, restore an unsaved draft, read the mark ──
    useEffect(() => {
        let alive = true;
        setTeam(null); setLoadFailed(false); setConflict(null); setSaveError(null);
        setHistoryOpen(false); setExpanded(null);
        const kept = store.get(draftKey(convId), session());
        setEditing(kept !== null);
        setDraft(kept ?? "");
        const mark = store.get(seenKey(convId), local());
        setSeen(mark);
        conversationsApi.teamNote(convId)
            .then((n) => { if (alive) { setTeam(n); if (kept === null) baseAt.current = n.at; } })
            .catch(() => { if (alive) setLoadFailed(true); });
        return () => { alive = false; };
    }, [convId]);

    // First visit: everything already here counts as seen (no lit-up threads).
    useEffect(() => {
        if (seen !== null || notes.length === 0) return;
        const newest = notes.reduce((m, n) => (n.created_at && n.created_at > m ? n.created_at : m), "");
        if (newest) { store.set(seenKey(convId), newest, local()); setSeen(newest); }
    }, [convId, notes, seen]);

    const markSeen = useCallback(() => {
        const now = new Date().toISOString();
        store.set(seenKey(convId), now, local());
        setSeen(now);
    }, [convId]);

    // Open/close: remembered across threads, animated, focus kept sensible.
    const setOpenTo = useCallback((v: boolean) => {
        setOpen(v);
        store.set(OPEN_KEY, v ? "1" : "0", local());
        if (v) markSeen();
        else requestAnimationFrame(() => bar.current?.focus({ preventScroll: true }));
    }, [markSeen]);

    useEffect(() => {
        if (!open) { setShown(false); return; }
        const r = requestAnimationFrame(() => setShown(true));
        return () => cancelAnimationFrame(r);
    }, [open]);

    // While open, new notes are being read as they arrive.
    useEffect(() => { if (open) markSeen(); }, [open, notes.length, markSeen]);

    const startEdit = useCallback(() => {
        setOpenTo(true);
        setEditing(true);
        setSaveError(null);
        setConflict(null);
        setDraft((d) => (store.get(draftKey(convId), session()) !== null ? d : team?.text ?? ""));
        baseAt.current = team?.at ?? null;
        requestAnimationFrame(() => {
            const el = area.current;
            if (el) { el.focus({ preventScroll: true }); el.setSelectionRange(el.value.length, el.value.length); }
        });
    }, [convId, team, setOpenTo]);

    // The header's Note button.
    const lastSignal = useRef(editSignal);
    useEffect(() => {
        if (editSignal === lastSignal.current) return;
        lastSignal.current = editSignal;
        startEdit();
    }, [editSignal, startEdit]);

    // A colleague saved: show theirs live (unless we are mid-edit — then the
    // save will meet their version as a conflict, never silently overwrite).
    const onEvent = useCallback((e: { type?: string; conversationId?: string; note?: TeamNote }) => {
        if (e?.type !== "team_note" || e.conversationId !== convId || !e.note) return;
        const note = e.note;
        setTeam(note);
        if (!editing) baseAt.current = note.at;
    }, [convId, editing]);
    useConversationEvents(convId, onEvent);

    const cancelEdit = useCallback(() => {
        setEditing(false); setDraft(""); setSaveError(null); setConflict(null);
        store.del(draftKey(convId), session());
    }, [convId]);

    const save = useCallback(async (text: string, expectedAt: string | null) => {
        if (saving) return;
        setSaving(true); setSaveError(null);
        try {
            const out = await conversationsApi.saveTeamNote(convId, text, expectedAt);
            setTeam(out); baseAt.current = out.at;
            setEditing(false); setDraft(""); setConflict(null);
            store.del(draftKey(convId), session());
        } catch (e) {
            const info = apiErrorInfo(e);
            const cur = (info.data as { detail?: { current?: TeamNote } })?.detail?.current;
            if (info.status === 409 && cur) { setConflict(cur); setTeam(cur); }
            else setSaveError(info.status === 422 && info.detail ? info.detail
                : "Couldn't save — check the connection and try again. Your text is kept.");
        } finally {
            setSaving(false);
        }
    }, [convId, saving]);

    const changed = (draft.trim() !== (team?.text ?? "").trim());
    const over = draft.length > MAX;

    const onDraft = (v: string) => {
        setDraft(v);
        store.set(draftKey(convId), v, session());
    };

    // Grow the box with its text, up to a limit.
    useEffect(() => {
        const el = area.current;
        if (!el) return;
        el.style.height = "auto";
        el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
    }, [draft, editing]);

    // Escape folds the panel (or leaves editing first); a click outside folds it.
    useEffect(() => {
        if (!open) return;
        const key = (e: KeyboardEvent) => {
            if (e.key !== "Escape") return;
            if (editing) { if (!changed) cancelEdit(); return; }
            setOpenTo(false);
        };
        const away = (e: PointerEvent) => {
            if (editing) return;                       // never lose a half-written note
            if (panel.current && !panel.current.contains(e.target as Node)) setOpenTo(false);
        };
        document.addEventListener("keydown", key);
        document.addEventListener("pointerdown", away);
        return () => { document.removeEventListener("keydown", key); document.removeEventListener("pointerdown", away); };
    }, [open, editing, changed, cancelEdit, setOpenTo]);

    // ── Folded: the slim line ────────────────────────────────────────────────
    const Bar = (
        <button
            ref={bar}
            type="button"
            onClick={() => (empty && !team?.text ? startEdit() : setOpenTo(true))}
            aria-expanded={false}
            aria-label={summary ? `Thread note: ${summary.text}` : "Add a thread note"}
            className="group w-full flex items-center gap-2 h-9 pl-2.5 pr-2 rounded-xl text-left transition-colors
                       bg-[#fffbeb]/95 hover:bg-[#fef3c7] border border-amber-200/80 shadow-[0_2px_8px_rgba(120,80,0,0.08)]
                       focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
        >
            <span aria-hidden className="text-[13px] leading-none">{summary?.icon ?? "📌"}</span>
            <span className={`flex-1 min-w-0 truncate text-[12px] ${summary ? "text-amber-950" : "text-amber-700/70 italic"}`}>
                {summary?.text ?? "Add a note for the team…"}
            </span>
            {unseen > 0 && (
                <span className="flex-shrink-0 inline-flex items-center gap-1 rounded-full bg-amber-500 px-1.5 py-px text-[10px] font-semibold text-white"
                      title={`${unseen} new since you last looked`}>
                    {unseen} new
                </span>
            )}
            {unseen === 0 && history.length > 0 && (
                <span className="flex-shrink-0 inline-flex items-center gap-0.5 text-[10px] text-amber-700/70 tabular-nums" title="Earlier notes in the history">
                    <History aria-hidden className="w-3 h-3" />{history.length}
                </span>
            )}
            <ChevronUp aria-hidden className="w-4 h-4 flex-shrink-0 text-amber-600 transition-transform group-hover:-translate-y-px" />
        </button>
    );

    // ── Open: the panel ──────────────────────────────────────────────────────
    const Panel = (
        <div
            ref={panel}
            role="region"
            aria-label="Thread note"
            className={`absolute inset-x-0 bottom-0 z-20 flex flex-col rounded-2xl border border-amber-200 bg-white
                        shadow-[0_-6px_28px_rgba(28,41,23,0.16)] max-h-[min(55vh,460px)]
                        origin-bottom transition-[opacity,transform] duration-150 ease-out motion-reduce:transition-none
                        ${shown ? "opacity-100 translate-y-0" : "opacity-0 translate-y-2"}`}
        >
            {/* Header — also the way back down */}
            <button
                type="button"
                onClick={() => setOpenTo(false)}
                aria-expanded
                className="flex items-center gap-2 px-3.5 h-10 flex-shrink-0 rounded-t-2xl bg-[#fffbeb] border-b border-amber-100
                           text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-400"
            >
                <span aria-hidden className="text-[13px]">📌</span>
                <span className="text-[12px] font-semibold text-amber-950">Thread note</span>
                <span className="text-[10px] text-amber-700/70 truncate">· internal, never sent</span>
                <span className="flex-1" />
                <ChevronDown aria-hidden className="w-4 h-4 text-amber-600" />
                <span className="sr-only">Fold</span>
            </button>

            <div className="overflow-y-auto overscroll-contain px-3.5 py-3 space-y-3.5">
                {/* 📌 Team note */}
                <section>
                    <div className="flex items-center gap-2 mb-1.5">
                        <h3 className="text-[10px] font-bold uppercase tracking-wider text-[#6b7e64]">Team note</h3>
                        {team?.text && team.at && !editing && (
                            <span className="text-[10px] text-[#8a9e80] truncate">
                                {team.by_name ?? "Someone"} · {timeAgo(team.at)}
                            </span>
                        )}
                        <span className="flex-1" />
                        {!editing && team?.text && (
                            <button type="button" onClick={startEdit}
                                    className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium text-[#427425] hover:bg-[#f0f9e8]">
                                <Pencil aria-hidden className="w-3 h-3" /> Edit
                            </button>
                        )}
                    </div>

                    {!editing && (team?.text ? (
                        <p className="text-[13px] leading-relaxed text-[#1c2917] whitespace-pre-wrap break-words">{team.text}</p>
                    ) : (
                        <button type="button" onClick={startEdit}
                                className="w-full rounded-xl border border-dashed border-[#d6e0cd] px-3 py-2.5 text-left text-[12px] text-[#8a9e80] hover:border-[#427425]/40 hover:text-[#427425]">
                            {loadFailed ? "Couldn't load the note — tap to write one" : "What should the next person know? Tap to write…"}
                        </button>
                    ))}

                    {editing && (
                        <div>
                            {conflict && (
                                <div className="mb-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
                                    <p className="font-semibold">{conflict.by_name ?? "A colleague"} changed this note while you were writing:</p>
                                    <p className="mt-1 whitespace-pre-wrap text-amber-900/90">{conflict.text || "(cleared it)"}</p>
                                    <div className="mt-2 flex gap-2">
                                        <button type="button" onClick={cancelEdit}
                                                className="rounded-lg bg-white px-2.5 py-1 text-[11px] font-medium text-amber-900 border border-amber-200 hover:bg-amber-100">
                                            Keep theirs
                                        </button>
                                        <button type="button" onClick={() => save(draft, conflict.at)} disabled={saving || over}
                                                className="rounded-lg bg-amber-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-amber-700 disabled:opacity-50">
                                            Replace with mine
                                        </button>
                                    </div>
                                </div>
                            )}
                            <textarea
                                ref={area}
                                value={draft}
                                onChange={(e) => onDraft(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                                        e.preventDefault();
                                        if (changed && !over && !conflict) save(draft, baseAt.current);
                                    }
                                }}
                                rows={3}
                                maxLength={MAX + 200}
                                placeholder={"Short and factual, e.g.\nPays in rand · DHL to Durban · call after 5pm"}
                                aria-label="Team note"
                                className="w-full resize-none rounded-xl border border-[#d6e0cd] bg-[#fbfcfa] px-3 py-2 text-[16px] sm:text-[13px] leading-relaxed text-[#1c2917]
                                           placeholder:text-[#a8b8a0] focus:outline-none focus:border-[#427425]/50 focus:ring-2 focus:ring-[#427425]/15"
                            />
                            <div className="mt-1.5 flex items-center gap-2">
                                <span className={`text-[10px] tabular-nums ${over ? "text-rose-600 font-semibold" : draft.length > MAX * 0.9 ? "text-amber-600" : "text-[#a8b8a0]"}`}>
                                    {draft.length}/{MAX}
                                </span>
                                <span className="hidden sm:inline text-[10px] text-[#a8b8a0]">⌘/Ctrl+Enter saves · Esc cancels</span>
                                <span className="flex-1" />
                                {team?.text && !conflict && (
                                    <button type="button" disabled={saving}
                                            onClick={() => { if (window.confirm("Clear the team note for everyone?")) save("", baseAt.current); }}
                                            className="rounded-lg px-2 py-1 text-[11px] text-rose-600 hover:bg-rose-50 disabled:opacity-50">
                                        Clear
                                    </button>
                                )}
                                <button type="button" onClick={cancelEdit} disabled={saving}
                                        className="rounded-lg px-2.5 py-1 text-[11px] font-medium text-[#6b7e64] hover:bg-[#f5f6f3] disabled:opacity-50">
                                    Cancel
                                </button>
                                {!conflict && (
                                    <button type="button" onClick={() => save(draft, baseAt.current)} disabled={saving || !changed || over}
                                            className="rounded-lg bg-[#427425] px-3 py-1 text-[11px] font-semibold text-white hover:bg-[#365f1e] disabled:opacity-40">
                                        {saving ? "Saving…" : "Save"}
                                    </button>
                                )}
                            </div>
                            {saveError && <p role="alert" className="mt-1.5 text-[11px] text-rose-600">{saveError}</p>}
                        </div>
                    )}
                </section>

                {/* 🤝 Neema's brief */}
                {brief && rows.length > 0 && (
                    <section>
                        <div className="flex items-center gap-2 mb-1.5">
                            <h3 className="text-[10px] font-bold uppercase tracking-wider text-[#6b7e64]">Neema&apos;s brief</h3>
                            {brief.created_at && <span className="text-[10px] text-[#8a9e80]">{timeAgo(brief.created_at)}</span>}
                        </div>
                        <ul className="space-y-1.5">
                            {rows.map((r, i) => (
                                <li key={i} className="flex items-start gap-2">
                                    {r.label ? (
                                        <span className={`mt-px flex-shrink-0 w-[3.75rem] text-center rounded-md px-1 py-0.5 text-[10px] font-semibold ${LABEL_LOOK[r.label] ?? "bg-[#f5f6f3] text-[#6b7e64]"}`}>
                                            {r.label.length > 9 ? r.label.slice(0, 8) + "…" : r.label}
                                        </span>
                                    ) : (
                                        <span aria-hidden className="mt-1.5 flex-shrink-0 w-[3.75rem] flex justify-center">
                                            <span className="h-1 w-1 rounded-full bg-[#c5d1bc]" />
                                        </span>
                                    )}
                                    <span className="flex-1 min-w-0 text-[12.5px] leading-snug text-[#1c2917] break-words">{r.text}</span>
                                    {r.label === "Say" && onUseLine && (
                                        <button type="button"
                                                onClick={() => { onUseLine(r.text.replace(/^["“]|["”]$/g, "")); setOpenTo(false); }}
                                                title="Put this line in the reply box"
                                                className="flex-shrink-0 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-sky-700 hover:bg-sky-50">
                                            <CornerDownLeft aria-hidden className="w-3 h-3" /> Use
                                        </button>
                                    )}
                                </li>
                            ))}
                        </ul>
                    </section>
                )}

                {/* History */}
                {history.length > 0 && (
                    <section>
                        <button type="button" onClick={() => setHistoryOpen((o) => !o)} aria-expanded={historyOpen}
                                className="flex w-full items-center gap-1.5 text-left">
                            <History aria-hidden className="w-3 h-3 text-[#8a9e80]" />
                            <h3 className="text-[10px] font-bold uppercase tracking-wider text-[#6b7e64]">History</h3>
                            <span className="text-[10px] text-[#8a9e80] tabular-nums">{history.length}</span>
                            <span className="flex-1" />
                            {historyOpen ? <ChevronUp aria-hidden className="w-3.5 h-3.5 text-[#8a9e80]" />
                                         : <ChevronDown aria-hidden className="w-3.5 h-3.5 text-[#8a9e80]" />}
                        </button>
                        {historyOpen && (
                            <ul className="mt-1.5 divide-y divide-[#f0f2ec]">
                                {history.map((n, i) => {
                                    const id = n.id ?? `h-${i}`;
                                    const isOpen = expanded === id;
                                    const kind = noteKind(n);
                                    return (
                                        <li key={id}>
                                            <button type="button" onClick={() => setExpanded(isOpen ? null : id)} aria-expanded={isOpen}
                                                    className="flex w-full items-start gap-2 py-1.5 text-left hover:bg-[#fafbf8] rounded-md">
                                                <span aria-hidden className="w-4 flex-shrink-0 text-center text-[11px] leading-5">{KIND_ICON[kind]}</span>
                                                <span className={`flex-1 min-w-0 text-[12px] leading-5 text-[#3d4d36] ${isOpen ? "" : "truncate"}`}>
                                                    {kind === "staff" && n.agent_name && <span className="font-semibold text-[#1c2917]">{n.agent_name}: </span>}
                                                    {isOpen ? (n.text ?? "").trim() : oneLine(n)}
                                                </span>
                                                <span className="flex-shrink-0 text-[10px] leading-5 text-[#a8b8a0] tabular-nums">
                                                    {n.created_at ? timeAgo(n.created_at) : ""}
                                                </span>
                                            </button>
                                        </li>
                                    );
                                })}
                            </ul>
                        )}
                    </section>
                )}
            </div>
        </div>
    );

    // The bar keeps its place in the layout; the panel rises over the chat
    // from it, so opening never shoves the conversation around.
    return (
        <div className="relative px-3 sm:px-4 pt-1.5 pb-1.5 bg-transparent">
            {Bar}
            {open && <div className="absolute inset-x-3 sm:inset-x-4 bottom-1.5">{Panel}</div>}
        </div>
    );
}

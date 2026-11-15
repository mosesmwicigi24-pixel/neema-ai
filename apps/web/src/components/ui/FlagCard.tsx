"use client";

// A flag in the chat, where it happened (owner, 2026-11-09): the red
// "Flagged: Needs Attention" label with what the flag is about under it.
// Compact (owner, 2026-11-15: notes "too many and too long"): one line saying
// what happened; the reasons and the full note are a tap away. It stays in the
// chat — unlike other notes — because it explains why Neema went quiet there.

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { summarizeFlag, heldLine } from "@/lib/flagSummary";

export function FlagCard({ note, when }: { note: string | null | undefined; when: string }) {
    const [open, setOpen] = useState(false);
    const [full, setFull] = useState(false);
    const sum = summarizeFlag(note);
    const held = !!sum?.tag && /held back/i.test(sum.tag);
    return (
        <div className="flex justify-center my-1.5">
            <div className="w-full max-w-[88%] rounded-xl border border-red-100 bg-[#fff7f7] text-[#7f1d1d]">
                <button
                    type="button"
                    onClick={() => sum && setOpen((o) => !o)}
                    aria-expanded={open}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left"
                >
                    <span aria-hidden className="text-[12px]">{held ? "⛔" : "🚩"}</span>
                    <span className="flex-1 min-w-0 truncate text-[11.5px]">
                        <span className="font-semibold text-red-700">{held ? "Reply held" : "Flagged"}</span>
                        {sum?.headline && <span className="text-[#7f1d1d]/85"> · {held ? heldLine(sum) : sum.headline}</span>}
                    </span>
                    {when && <span className="flex-shrink-0 text-[10px] text-red-400 tabular-nums">{when}</span>}
                    {sum && (open
                        ? <ChevronUp aria-hidden className="w-3.5 h-3.5 flex-shrink-0 text-red-400" />
                        : <ChevronDown aria-hidden className="w-3.5 h-3.5 flex-shrink-0 text-red-400" />)}
                </button>
                {open && sum && (
                    <div className="px-3 pb-2.5 -mt-0.5 text-[12px] leading-snug">
                        {sum.tag && !held && (
                            <span className="inline-block mb-1 text-[9px] font-bold tracking-wider uppercase text-red-700 bg-red-100 rounded px-1.5 py-0.5">
                                {sum.tag}
                            </span>
                        )}
                        <p className="font-medium text-[#991b1b]">{sum.headline}</p>
                        {!full && sum.points.length > 0 && (
                            <ul className="mt-1 space-y-0.5">
                                {sum.points.map((p, i) => (
                                    <li key={i} className="flex gap-1.5">
                                        <span className="text-red-300 flex-shrink-0">•</span>
                                        <span className="min-w-0">
                                            {p.label && <span className="font-medium text-[#991b1b]">{p.label}: </span>}
                                            <span className="text-[#7f1d1d]/90">{p.text}</span>
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        )}
                        {full && <p className="mt-1 whitespace-pre-wrap text-[#7f1d1d]/90">{note}</p>}
                        <button type="button" onClick={() => setFull((f) => !f)}
                                className="mt-1 text-[11px] font-medium text-red-600 hover:underline">
                            {full ? "Show summary" : "Show full note"}
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}

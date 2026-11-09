"use client";

// A flag in the chat, where it happened (owner, 2026-11-09): the red
// "Flagged: Needs Attention" label with what the flag is about right under
// it — like an internal note — as a short summary. The full note stays one
// tap away; the activity log no longer repeats it.

import { useState } from "react";
import { summarizeFlag } from "@/lib/flagSummary";

export function FlagCard({ note, when }: { note: string | null | undefined; when: string }) {
    const [open, setOpen] = useState(false);
    const sum = summarizeFlag(note);
    return (
        <div className="flex flex-col items-center gap-1.5 my-2">
            <div className="flex items-center gap-2 w-full">
                <div className="flex-1 h-px bg-red-100" />
                <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-red-100 text-red-700">
                    <span className="text-[10px] font-semibold whitespace-nowrap">🚩 Flagged: Needs Attention</span>
                    {when && <span className="text-[9px] opacity-60 whitespace-nowrap">· {when}</span>}
                </div>
                <div className="flex-1 h-px bg-red-100" />
            </div>
            {sum && (
                <div className="w-full max-w-[88%] rounded-xl border border-red-100 bg-[#fff7f7] px-3 py-2.5 text-[12px] leading-snug text-[#7f1d1d]">
                    {sum.tag && (
                        <span className="inline-block mb-1 text-[9px] font-bold tracking-wider uppercase text-red-700 bg-red-100 rounded px-1.5 py-0.5">
                            {sum.tag}
                        </span>
                    )}
                    <p className="font-semibold text-[#991b1b]">{sum.headline}</p>
                    {!open && sum.points.length > 0 && (
                        <ul className="mt-1.5 space-y-1">
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
                    {open && <p className="mt-1.5 whitespace-pre-wrap text-[#7f1d1d]/90">{note}</p>}
                    <button type="button" onClick={() => setOpen((o) => !o)}
                            className="mt-1.5 text-[11px] font-medium text-red-600 hover:underline">
                        {open ? "Show summary" : "Show full note"}
                    </button>
                </div>
            )}
        </div>
    );
}

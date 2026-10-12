"use client";
import React from "react";
import Link from "next/link";

/** The dark sign-in frame shared by the public account pages (forgot / reset
 * password): the same colours as /login so they read as one place. */
export function AuthShell({ title, lead, children }: { title: string; lead: string; children: React.ReactNode }) {
    return (
        <div className="min-h-screen flex items-center justify-center p-6" style={{ backgroundColor: "#070d1c" }}>
            <div className="w-full max-w-sm">
                <div className="flex items-center gap-2.5 mb-8">
                    <div className="w-9 h-9 rounded-xl flex items-center justify-center shadow-lg" style={{ backgroundColor: "#589b31" }}>
                        <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2}
                                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                        </svg>
                    </div>
                    <div>
                        <div className="text-white font-bold text-base">Neema</div>
                        <div className="text-[10px] uppercase tracking-widest mt-0.5" style={{ color: "#699a32" }}>Bethany House · Admin</div>
                    </div>
                </div>
                <div className="mb-6">
                    <h1 className="text-2xl font-bold tracking-tight mb-1" style={{ color: "#f3f9ec" }}>{title}</h1>
                    <p className="text-sm leading-relaxed" style={{ color: "#699a32" }}>{lead}</p>
                </div>
                {children}
                <div className="mt-8 pt-6 border-t text-center text-xs" style={{ borderColor: "#152451", color: "#427425" }}>
                    <Link href="/login" className="underline" style={{ color: "#9ccd65" }}>Back to sign in</Link>
                </div>
            </div>
        </div>
    );
}

export const authInput: React.CSSProperties = {
    backgroundColor: "#0a1229", border: "1px solid #152451", color: "#f3f9ec", fontSize: 14,
};

export function AuthNotice({ tone, children }: { tone: "ok" | "error"; children: React.ReactNode }) {
    return (
        <div role={tone === "error" ? "alert" : "status"} className="p-3 rounded-lg border text-xs leading-relaxed"
            style={tone === "error"
                ? { backgroundColor: "rgba(192,57,43,0.15)", borderColor: "rgba(192,57,43,0.6)", color: "#fca5a5" }
                : { backgroundColor: "rgba(88,155,49,0.15)", borderColor: "rgba(88,155,49,0.6)", color: "#b5da8b" }}>
            {children}
        </div>
    );
}

export function AuthButton({ busy, label, busyLabel }: { busy: boolean; label: string; busyLabel: string }) {
    return (
        <button type="submit" disabled={busy}
            className="w-full h-11 rounded-xl text-sm font-semibold text-white transition-all mt-2 flex items-center justify-center gap-2 disabled:opacity-60"
            style={{ backgroundColor: "#589b31", boxShadow: "0 4px 20px rgba(88,155,49,0.3)" }}>
            {busy ? (<><div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />{busyLabel}</>) : label}
        </button>
    );
}

/** The server's sentence for a refused request, else a plain fallback. */
export function detailOf(e: unknown, fallback: string): string {
    const body = (e as { body?: { detail?: unknown } } | null)?.body;
    const d = body && typeof body.detail === "string" ? body.detail : "";
    return d || fallback;
}

"use client";
import React, { useState } from "react";
import { signIn, signOut, getSession } from "next-auth/react";

interface AgentProfile {
    name: string;
    email: string;
    role: string;
    is_superuser: boolean;
}

interface Props {
    email: string;
    /**
     * Called after successful re-auth with both the fresh token AND the
     * agent's full profile so the parent can restore name/role in the UI
     * without waiting for a page reload.
     */
    onSuccess: (freshToken: string, profile: AgentProfile) => void | Promise<void>;
    /** The stale/expired token — used to detect when a genuinely NEW token has arrived. */
    expiredToken?: string;
}

export function SessionExpiredModal({ email, onSuccess, expiredToken }: Props) {
    const [password, setPassword] = useState("");
    const [loading, setLoading]   = useState(false);
    const [error, setError]       = useState("");

    /**
     * Poll getSession() until we see a token that is:
     *   1. Present
     *   2. Different from the expired one (so we're not just reading the stale cache)
     *   3. Has no error flag
     */
    async function pollForFreshToken(maxWaitMs = 10_000): Promise<string | null> {
        const interval = 300;
        const deadline = Date.now() + maxWaitMs;
        while (Date.now() < deadline) {
            await new Promise<void>((r) => setTimeout(r, interval));
            const session  = await getSession();
            const token    = (session as any)?.accessToken as string | undefined;
            const hasError = !!(session as any)?.error;
            if (token && !hasError && token !== expiredToken) {
                return token;
            }
        }
        return null;
    }

    /**
     * Fetch the agent's full profile with the fresh token so the parent
     * can immediately restore the name/role without a page reload.
     * Falls back gracefully if the request fails.
     */
    async function fetchProfile(freshToken: string): Promise<AgentProfile> {
        try {
            const resp = await fetch("/api/admin/me", {
                headers: { Authorization: `Bearer ${freshToken}` },
            });
            if (resp.ok) {
                const data = await resp.json();
                return {
                    name:         data.name         ?? "",
                    email:        data.email        ?? email,
                    role:         data.role         ?? "agent",
                    is_superuser: data.is_superuser ?? false,
                };
            }
        } catch {
            // network error — fall through to minimal profile
        }
        return { name: "", email, role: "agent", is_superuser: false };
    }

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        if (!password) return;

        setLoading(true);
        setError("");

        try {
            const result = await signIn("credentials", {
                redirect: false,
                email,
                password,
            });

            if (result?.error) {
                setError("Incorrect password. Please try again.");
                setLoading(false);
                return;
            }

            const freshToken = await pollForFreshToken();

            if (!freshToken) {
                setError("Session didn't update in time. Please try again.");
                setLoading(false);
                return;
            }

            // Fetch fresh profile so the parent can restore the agent name immediately
            const profile = await fetchProfile(freshToken);
            await onSuccess(freshToken, profile);

        } catch {
            setError("Something went wrong. Please try again.");
            setLoading(false);
        }
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
            <div className="relative w-full max-w-sm mx-4 bg-white rounded-2xl shadow-2xl overflow-hidden">
                <div className="h-1 w-full bg-gradient-to-r from-green-600 to-emerald-400" />
                <div className="px-8 py-8">
                    <div className="flex justify-center mb-5">
                        <div className="w-14 h-14 rounded-full bg-amber-50 border border-amber-200 flex items-center justify-center">
                            <svg className="w-7 h-7 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
                                    d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                            </svg>
                        </div>
                    </div>

                    <h2 className="text-center text-xl font-semibold text-stone-900 mb-1">
                        Session expired
                    </h2>
                    <p className="text-center text-sm text-stone-500 mb-6">
                        Please enter your password to continue where you left off.
                    </p>

                    <form onSubmit={handleSubmit} className="space-y-4">
                        <div>
                            <label className="block text-xs font-medium text-stone-500 mb-1.5">
                                Signed in as
                            </label>
                            <div className="w-full px-3.5 py-2.5 rounded-xl bg-stone-100 border border-stone-200 text-sm text-stone-600 select-none">
                                {email}
                            </div>
                        </div>

                        <div>
                            <label
                                className="block text-xs font-medium text-stone-500 mb-1.5"
                                htmlFor="session-password"
                            >
                                Password
                            </label>
                            <input
                                id="session-password"
                                type="password"
                                autoFocus
                                autoComplete="current-password"
                                value={password}
                                onChange={(e) => setPassword(e.target.value)}
                                placeholder="••••••••"
                                className="w-full px-3.5 py-2.5 rounded-xl border border-stone-200 bg-white text-sm text-stone-900 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-green-500/40 focus:border-green-500 transition"
                            />
                        </div>

                        {error && (
                            <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3.5 py-2.5">
                                {error}
                            </p>
                        )}

                        <button
                            type="submit"
                            disabled={loading || !password}
                            className="w-full py-2.5 rounded-xl bg-stone-900 hover:bg-stone-800 text-white text-sm font-semibold transition disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                        >
                            {loading ? (
                                <>
                                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                                    </svg>
                                    Signing in…
                                </>
                            ) : (
                                "Continue"
                            )}
                        </button>

                        <button
                            type="button"
                            onClick={() => signOut({ callbackUrl: "/login" })}
                            className="w-full py-2 rounded-xl text-stone-400 hover:text-stone-700 text-sm transition text-center"
                        >
                            Sign out
                        </button>
                    </form>
                </div>
            </div>
        </div>
    );
}
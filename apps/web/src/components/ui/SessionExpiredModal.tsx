"use client";
import React, { useState } from "react";
import { signIn } from "next-auth/react";

interface Props {
    /** The email of the currently logged-in user — pre-filled in the form. */
    email: string;
    /** Called after a successful silent re-auth so the parent can resume. */
    onSuccess: () => void;
}

/**
 * SessionExpiredModal
 *
 * Shows a password-only prompt when the session token has expired.
 * - Pre-fills the known email so the user just types their password.
 * - Calls NextAuth's signIn() with redirect:false so we stay on the page.
 * - On success calls onSuccess() so the parent clears the expired state and
 *   the next API poll will use the fresh token.
 */
export function SessionExpiredModal({ email, onSuccess }: Props) {
    const [password, setPassword] = useState("");
    const [loading, setLoading]   = useState(false);
    const [error, setError]       = useState("");

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
            } else {
                // NextAuth jwt() callback will refresh the token.
                // Give it a tick to propagate then tell the parent we're good.
                setTimeout(onSuccess, 300);
            }
        } catch {
            setError("Something went wrong. Please try again.");
        } finally {
            setLoading(false);
        }
    }

    return (
        /* Backdrop */
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
            {/* Card */}
            <div className="relative w-full max-w-sm mx-4 bg-white rounded-2xl shadow-2xl overflow-hidden">

                {/* Top accent bar */}
                <div className="h-1 w-full bg-gradient-to-r from-green-600 to-emerald-400" />

                <div className="px-8 py-8">
                    {/* Icon */}
                    <div className="flex justify-center mb-5">
                        <div className="w-14 h-14 rounded-full bg-amber-50 border border-amber-200 flex items-center justify-center">
                            <svg className="w-7 h-7 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
                                    d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
                            </svg>
                        </div>
                    </div>

                    {/* Heading */}
                    <h2 className="text-center text-xl font-semibold text-stone-900 mb-1">
                        Session expired
                    </h2>
                    <p className="text-center text-sm text-stone-500 mb-6">
                        Please enter your password to continue where you left off.
                    </p>

                    {/* Form */}
                    <form onSubmit={handleSubmit} className="space-y-4">
                        {/* Email — read-only, just for context */}
                        <div>
                            <label className="block text-xs font-medium text-stone-500 mb-1.5">
                                Signed in as
                            </label>
                            <div className="w-full px-3.5 py-2.5 rounded-xl bg-stone-100 border border-stone-200 text-sm text-stone-600 select-none">
                                {email}
                            </div>
                        </div>

                        {/* Password */}
                        <div>
                            <label className="block text-xs font-medium text-stone-500 mb-1.5" htmlFor="session-password">
                                Password
                            </label>
                            <input
                                id="session-password"
                                type="password"
                                autoFocus
                                autoComplete="current-password"
                                value={password}
                                onChange={e => setPassword(e.target.value)}
                                placeholder="••••••••"
                                className="w-full px-3.5 py-2.5 rounded-xl border border-stone-200 bg-white text-sm text-stone-900 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-green-500/40 focus:border-green-500 transition"
                            />
                        </div>

                        {/* Error */}
                        {error && (
                            <p className="text-sm text-red-600 bg-red-50 border border-red-100 rounded-lg px-3.5 py-2.5">
                                {error}
                            </p>
                        )}

                        {/* Submit */}
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
                    </form>
                </div>
            </div>
        </div>
    );
}
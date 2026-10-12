"use client";
import React, { useEffect, useState } from "react";
import { authApi } from "@/lib/api";
import { AuthButton, AuthNotice, AuthShell, authInput, detailOf } from "@/components/AuthShell";

// Forgot password: the reset link is mailed to the Bethany House recovery
// inbox, not to the person — the office hands it over (owner, 2026-10-12).
export default function ForgotPasswordPage(): React.ReactElement {
    const [email, setEmail] = useState("");
    const [busy, setBusy] = useState(false);
    const [done, setDone] = useState<string | null>(null);
    const [error, setError] = useState("");
    useEffect(() => { document.title = "Forgot password | Neema"; }, []);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!email.trim()) { setError("Enter the email address of your Neema account."); return; }
        setBusy(true); setError("");
        try {
            const r = await authApi.forgotPassword(email.trim());
            setDone(r.message);
        } catch (err) {
            setError(detailOf(err, "Couldn't send the request — check your connection and try again."));
        } finally { setBusy(false); }
    };

    return (
        <AuthShell title="Forgot your password?"
            lead="Enter your account email. A single-use reset link is sent to the Bethany House recovery inbox, and the office hands it to you.">
            {done ? (
                <AuthNotice tone="ok">{done}</AuthNotice>
            ) : (
                <form onSubmit={submit} className="space-y-4">
                    <div>
                        <label htmlFor="fp-email" className="block text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "#699a32" }}>Email address</label>
                        <input id="fp-email" type="email" value={email} autoComplete="email" required
                            onChange={(e) => { setEmail(e.target.value); setError(""); }}
                            placeholder="you@bethanyhouse.co.ke"
                            className="w-full h-11 px-4 rounded-xl text-sm placeholder-[#427425] focus:outline-none" style={authInput} />
                    </div>
                    {error && <AuthNotice tone="error">{error}</AuthNotice>}
                    <AuthButton busy={busy} label="Send reset link" busyLabel="Sending…" />
                </form>
            )}
            <p className="mt-5 text-xs leading-relaxed" style={{ color: "#427425" }}>
                Not sure which email your account uses? The office can see every account under Settings → Team, and an admin can set a new password there directly.
            </p>
        </AuthShell>
    );
}

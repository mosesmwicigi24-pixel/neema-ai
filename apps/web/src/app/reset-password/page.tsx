"use client";
import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { authApi } from "@/lib/api";
import { AuthButton, AuthNotice, AuthShell, authInput, detailOf } from "@/components/AuthShell";

function ResetForm(): React.ReactElement {
    const params = useSearchParams();
    const token = params.get("token") ?? "";
    const [password, setPassword] = useState("");
    const [confirm, setConfirm] = useState("");
    const [busy, setBusy] = useState(false);
    const [doneFor, setDoneFor] = useState<string | null>(null);
    const [error, setError] = useState("");

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (password.length < 8) { setError("Password must be at least 8 characters."); return; }
        if (password !== confirm) { setError("The two passwords don't match."); return; }
        setBusy(true); setError("");
        try {
            const r = await authApi.resetPassword(token, password);
            setDoneFor(r.email);
        } catch (err) {
            setError(detailOf(err, "Couldn't reset the password — try again."));
        } finally { setBusy(false); }
    };

    if (!token) {
        return <AuthNotice tone="error">This page needs the link from the recovery mail. Open the link exactly as it was sent, or ask for a new one.</AuthNotice>;
    }
    if (doneFor) {
        return (
            <AuthNotice tone="ok">
                Password changed for {doneFor}. <Link href="/login" className="underline font-semibold">Sign in</Link> with the new one.
            </AuthNotice>
        );
    }
    return (
        <form onSubmit={submit} className="space-y-4">
            <div>
                <label htmlFor="rp-new" className="block text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "#699a32" }}>New password</label>
                <input id="rp-new" type="password" value={password} autoComplete="new-password" required minLength={8}
                    onChange={(e) => { setPassword(e.target.value); setError(""); }}
                    className="w-full h-11 px-4 rounded-xl text-sm focus:outline-none" style={authInput} />
            </div>
            <div>
                <label htmlFor="rp-confirm" className="block text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "#699a32" }}>Confirm password</label>
                <input id="rp-confirm" type="password" value={confirm} autoComplete="new-password" required minLength={8}
                    onChange={(e) => { setConfirm(e.target.value); setError(""); }}
                    className="w-full h-11 px-4 rounded-xl text-sm focus:outline-none" style={authInput} />
            </div>
            {error && <AuthNotice tone="error">{error}</AuthNotice>}
            <AuthButton busy={busy} label="Set new password" busyLabel="Saving…" />
        </form>
    );
}

export default function ResetPasswordPage(): React.ReactElement {
    useEffect(() => { document.title = "Reset password | Neema"; }, []);
    return (
        <AuthShell title="Choose a new password" lead="The link works once and expires an hour after it was sent.">
            <Suspense fallback={<p className="text-sm" style={{ color: "#699a32" }}>Loading…</p>}>
                <ResetForm />
            </Suspense>
        </AuthShell>
    );
}

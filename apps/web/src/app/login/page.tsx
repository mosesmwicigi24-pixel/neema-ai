"use client";
import React, { useState, useEffect } from "react";
import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";

export default function LoginPage(): React.ReactElement {
    const { status } = useSession();
    const router = useRouter();

    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);
    const [showPass, setShowPass] = useState(false);

    useEffect(() => {
        if (status === "authenticated") router.replace("/dashboard");
    }, [status, router]);

    // Update browser tab title
    useEffect(() => {
        document.title = "Sign in | Neema";
    }, []);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!email || !password) {
            setError("Please enter your email and password.");
            return;
        }
        setLoading(true);
        setError("");
        try {
            const result = await signIn("credentials", {
                email,
                password,
                redirect: false,
            });
            if (result?.error)
                setError("Invalid email or password. Please try again.");
            else router.push("/dashboard");
        } catch {
            setError("Something went wrong. Please try again.");
        } finally {
            setLoading(false);
        }
    };

    if (status === "loading" || status === "authenticated") {
        return (
            <div
                className="flex h-screen items-center justify-center"
                style={{ backgroundColor: "#070d1c" }}
            >
                <div
                    className="w-6 h-6 border-2 border-t-transparent rounded-full animate-spin"
                    style={{
                        borderColor: "#589b31",
                        borderTopColor: "transparent",
                    }}
                />
            </div>
        );
    }

    return (
        <div
            className="min-h-screen flex"
            style={{ backgroundColor: "#070d1c" }}
        >
            {/* Left branding panel */}
            <div
                className="hidden lg:flex lg:w-[420px] xl:w-[480px] flex-col justify-between p-10 border-r relative overflow-hidden flex-shrink-0"
                style={{ backgroundColor: "#0a1229", borderColor: "#152451" }}
            >
                {/* Radial glow */}
                <div
                    className="absolute inset-0 pointer-events-none"
                    style={{
                        background:
                            "radial-gradient(ellipse at top left, rgba(88,155,49,0.15) 0%, transparent 60%)",
                    }}
                />

                {/* Logo */}
                <div className="relative flex items-center gap-3">
                    <div
                        className="w-10 h-10 rounded-xl flex items-center justify-center shadow-lg flex-shrink-0"
                        style={{
                            backgroundColor: "#589b31",
                            boxShadow: "0 4px 20px rgba(88,155,49,0.4)",
                        }}
                    >
                        <svg
                            className="w-6 h-6 text-white"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2.2}
                                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                            />
                        </svg>
                    </div>
                    <div>
                        <div className="text-white font-bold text-lg leading-none tracking-tight">
                            Neema
                        </div>
                        <div
                            className="text-[10px] uppercase tracking-widest font-medium mt-0.5"
                            style={{ color: "#699a32" }}
                        >
                            Bethany House · Admin
                        </div>
                    </div>
                </div>

                {/* Feature list */}
                <div className="relative space-y-6">
                    <div>
                        <h2
                            className="text-2xl font-bold leading-snug mb-2"
                            style={{ color: "#f3f9ec" }}
                        >
                            Manage conversations,
                            <br />
                            <span style={{ color: "#9ccd65" }}>
                                grow your business.
                            </span>
                        </h2>
                        <p
                            className="text-sm leading-relaxed"
                            style={{ color: "#699a32" }}
                        >
                            AI-powered WhatsApp assistant for Bethany House —
                            handling orders, queries, and sales around the
                            clock.
                        </p>
                    </div>
                    <div className="space-y-3">
                        {[
                            {
                                icon: "💬",
                                label: "Live conversation monitoring",
                            },
                            {
                                icon: "🤖",
                                label: "AI-assisted replies & drafts",
                            },
                            { icon: "📦", label: "Order & catalog management" },
                            { icon: "📊", label: "Customer insights & CRM" },
                        ].map(({ icon, label }) => (
                            <div
                                key={label}
                                className="flex items-center gap-3"
                            >
                                <div
                                    className="w-8 h-8 rounded-lg flex items-center justify-center text-sm flex-shrink-0 border"
                                    style={{
                                        backgroundColor: "#2c4e18",
                                        borderColor: "#427425",
                                    }}
                                >
                                    {icon}
                                </div>
                                <span
                                    className="text-sm"
                                    style={{ color: "#b5da8b" }}
                                >
                                    {label}
                                </span>
                            </div>
                        ))}
                    </div>
                </div>

                <div className="relative text-xs" style={{ color: "#427425" }}>
                    © {new Date().getFullYear()} Bethany House · Nairobi, Kenya
                </div>
            </div>

            {/* Right form panel */}
            <div className="flex-1 flex items-center justify-center p-6">
                <div className="w-full max-w-sm">
                    {/* Mobile logo */}
                    <div className="lg:hidden flex items-center gap-2.5 mb-8">
                        <div
                            className="w-9 h-9 rounded-xl flex items-center justify-center shadow-lg"
                            style={{ backgroundColor: "#589b31" }}
                        >
                            <svg
                                className="w-5 h-5 text-white"
                                fill="none"
                                stroke="currentColor"
                                viewBox="0 0 24 24"
                            >
                                <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2.2}
                                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                                />
                            </svg>
                        </div>
                        <div>
                            <div className="text-white font-bold text-base">
                                Neema
                            </div>
                            <div
                                className="text-[10px] uppercase tracking-widest mt-0.5"
                                style={{ color: "#699a32" }}
                            >
                                Admin
                            </div>
                        </div>
                    </div>

                    <div className="mb-8">
                        <h1
                            className="text-2xl font-bold tracking-tight mb-1"
                            style={{ color: "#f3f9ec" }}
                        >
                            Sign in
                        </h1>
                        <p className="text-sm" style={{ color: "#699a32" }}>
                            Enter your credentials to access the dashboard
                        </p>
                    </div>

                    <form onSubmit={handleSubmit} className="space-y-4">
                        <div>
                            <label
                                className="block text-xs font-semibold uppercase tracking-wider mb-2"
                                style={{ color: "#699a32" }}
                            >
                                Email address
                            </label>
                            <input
                                type="email"
                                value={email}
                                autoComplete="email"
                                required
                                onChange={(e) => {
                                    setEmail(e.target.value);
                                    setError("");
                                }}
                                placeholder="admin@bethanyhouse.com"
                                className="w-full h-11 px-4 rounded-xl text-sm placeholder-[#427425] focus:outline-none focus:ring-2 transition-all"
                                style={{
                                    backgroundColor: "#0a1229",
                                    border: "1px solid #152451",
                                    color: "#f3f9ec",
                                    fontSize: 14,
                                    boxShadow: "none",
                                }}
                                onFocus={(e) => {
                                    e.target.style.borderColor = "#589b31";
                                    e.target.style.boxShadow =
                                        "0 0 0 3px rgba(88,155,49,0.2)";
                                }}
                                onBlur={(e) => {
                                    e.target.style.borderColor = "#152451";
                                    e.target.style.boxShadow = "none";
                                }}
                            />
                        </div>

                        <div>
                            <label
                                className="block text-xs font-semibold uppercase tracking-wider mb-2"
                                style={{ color: "#699a32" }}
                            >
                                Password
                            </label>
                            <div className="relative">
                                <input
                                    type={showPass ? "text" : "password"}
                                    value={password}
                                    autoComplete="current-password"
                                    required
                                    onChange={(e) => {
                                        setPassword(e.target.value);
                                        setError("");
                                    }}
                                    placeholder="••••••••"
                                    className="w-full h-11 px-4 pr-11 rounded-xl text-sm focus:outline-none transition-all"
                                    style={{
                                        backgroundColor: "#0a1229",
                                        border: "1px solid #152451",
                                        color: "#f3f9ec",
                                        fontSize: 14,
                                    }}
                                    onFocus={(e) => {
                                        e.target.style.borderColor = "#589b31";
                                        e.target.style.boxShadow =
                                            "0 0 0 3px rgba(88,155,49,0.2)";
                                    }}
                                    onBlur={(e) => {
                                        e.target.style.borderColor = "#152451";
                                        e.target.style.boxShadow = "none";
                                    }}
                                />
                                <button
                                    type="button"
                                    tabIndex={-1}
                                    onClick={() => setShowPass((s) => !s)}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 transition-colors"
                                    style={{ color: "#699a32" }}
                                >
                                    {showPass ? (
                                        <svg
                                            className="w-4 h-4"
                                            fill="none"
                                            stroke="currentColor"
                                            viewBox="0 0 24 24"
                                        >
                                            <path
                                                strokeLinecap="round"
                                                strokeLinejoin="round"
                                                strokeWidth={2}
                                                d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                                            />
                                        </svg>
                                    ) : (
                                        <svg
                                            className="w-4 h-4"
                                            fill="none"
                                            stroke="currentColor"
                                            viewBox="0 0 24 24"
                                        >
                                            <path
                                                strokeLinecap="round"
                                                strokeLinejoin="round"
                                                strokeWidth={2}
                                                d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                                            />
                                            <path
                                                strokeLinecap="round"
                                                strokeLinejoin="round"
                                                strokeWidth={2}
                                                d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                                            />
                                        </svg>
                                    )}
                                </button>
                            </div>
                        </div>

                        {error && (
                            <div
                                className="flex items-start gap-2.5 p-3 rounded-lg border border-red-800/60"
                                style={{
                                    backgroundColor: "rgba(192,57,43,0.15)",
                                }}
                            >
                                <svg
                                    className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5"
                                    fill="none"
                                    stroke="currentColor"
                                    viewBox="0 0 24 24"
                                >
                                    <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        strokeWidth={2}
                                        d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                                    />
                                </svg>
                                <p className="text-xs text-red-300">{error}</p>
                            </div>
                        )}

                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full h-11 rounded-xl text-sm font-semibold text-white transition-all mt-2 flex items-center justify-center gap-2 disabled:opacity-60"
                            style={{
                                backgroundColor: "#589b31",
                                boxShadow: "0 4px 20px rgba(88,155,49,0.3)",
                            }}
                            onMouseEnter={(e) => {
                                (
                                    e.currentTarget as HTMLElement
                                ).style.backgroundColor = "#427425";
                            }}
                            onMouseLeave={(e) => {
                                (
                                    e.currentTarget as HTMLElement
                                ).style.backgroundColor = "#589b31";
                            }}
                        >
                            {loading ? (
                                <>
                                    <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
                                    Signing in…
                                </>
                            ) : (
                                "Sign in"
                            )}
                        </button>
                    </form>

                    <div
                        className="mt-8 pt-6 border-t"
                        style={{ borderColor: "#152451" }}
                    >
                        <p
                            className="text-center text-xs"
                            style={{ color: "#427425" }}
                        >
                            Access restricted to Bethany House staff.
                            <br />
                            Contact your administrator if you need access.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
}
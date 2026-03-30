"use client";
import React, { useState, useEffect } from "react";
import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";

export default function LoginPage(): React.ReactElement {
    const { data: session, status } = useSession();
    const router = useRouter();

    const [email,    setEmail]    = useState("");
    const [password, setPassword] = useState("");
    const [error,    setError]    = useState("");
    const [loading,  setLoading]  = useState(false);
    const [showPass, setShowPass] = useState(false);

    // Redirect if already authenticated
    useEffect(() => {
        if (status === "authenticated") {
            router.replace("/dashboard");
        }
    }, [status, router]);

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
            if (result?.error) {
                setError("Invalid email or password. Please try again.");
            } else {
                router.push("/dashboard");
            }
        } catch {
            setError("Something went wrong. Please try again.");
        } finally {
            setLoading(false);
        }
    };

    if (status === "loading" || status === "authenticated") {
        return (
            <div className="flex h-screen items-center justify-center bg-gray-950">
                <div className="w-6 h-6 border-2 border-green-600 border-t-transparent rounded-full animate-spin" />
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gray-950 flex">

            {/* Left panel — branding */}
            <div className="hidden lg:flex lg:w-[420px] xl:w-[480px] flex-col justify-between p-10 bg-gray-900 border-r border-gray-800/60 relative overflow-hidden flex-shrink-0">
                {/* Background texture */}
                <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,_var(--tw-gradient-stops))] from-green-900/20 via-transparent to-transparent pointer-events-none" />
                <div className="absolute bottom-0 right-0 w-64 h-64 bg-green-800/5 rounded-full translate-x-1/2 translate-y-1/2 pointer-events-none" />

                {/* Logo */}
                <div className="relative flex items-center gap-3">
                    <div className="w-9 h-9 rounded-xl bg-green-700 flex items-center justify-center shadow-lg shadow-green-900/50 flex-shrink-0">
                        <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2}
                                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                        </svg>
                    </div>
                    <div>
                        <div className="text-white font-bold text-lg leading-none tracking-tight">Neema</div>
                        <div className="text-[10px] text-green-500/70 uppercase tracking-widest font-medium mt-0.5">
                            Admin Dashboard
                        </div>
                    </div>
                </div>

                {/* Feature list */}
                <div className="relative space-y-6">
                    <div>
                        <h2 className="text-2xl font-bold text-white leading-snug mb-2">
                            Manage conversations,<br />
                            <span className="text-green-400">grow your business.</span>
                        </h2>
                        <p className="text-sm text-gray-400 leading-relaxed">
                            Your AI-powered WhatsApp assistant for Bethany House — handling orders, customer queries, and sales around the clock.
                        </p>
                    </div>
                    <div className="space-y-3">
                        {[
                            { icon: "💬", label: "Live conversation monitoring" },
                            { icon: "🤖", label: "AI-assisted replies & drafts"  },
                            { icon: "📦", label: "Order & catalog management"    },
                            { icon: "📊", label: "Customer insights & CRM"       },
                        ].map(({ icon, label }) => (
                            <div key={label} className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded-lg bg-gray-800 border border-gray-700/60 flex items-center justify-center text-base flex-shrink-0">
                                    {icon}
                                </div>
                                <span className="text-sm text-gray-300">{label}</span>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Footer */}
                <div className="relative text-[11px] text-gray-600">
                    © {new Date().getFullYear()} Bethany House · Nairobi, Kenya
                </div>
            </div>

            {/* Right panel — form */}
            <div className="flex-1 flex items-center justify-center p-6">
                <div className="w-full max-w-sm">

                    {/* Mobile logo */}
                    <div className="lg:hidden flex items-center gap-2.5 mb-8">
                        <div className="w-8 h-8 rounded-lg bg-green-700 flex items-center justify-center shadow-lg shadow-green-900/50">
                            <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2}
                                    d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                            </svg>
                        </div>
                        <div>
                            <div className="text-white font-bold text-base leading-none">Neema</div>
                            <div className="text-[10px] text-green-500/70 uppercase tracking-widest mt-0.5">Admin</div>
                        </div>
                    </div>

                    {/* Heading */}
                    <div className="mb-8">
                        <h1 className="text-2xl font-bold text-white tracking-tight mb-1">
                            Sign in
                        </h1>
                        <p className="text-sm text-gray-500">
                            Enter your credentials to access the dashboard
                        </p>
                    </div>

                    {/* Form */}
                    <form onSubmit={handleSubmit} className="space-y-4">

                        {/* Email */}
                        <div>
                            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                                Email address
                            </label>
                            <input
                                type="email"
                                value={email}
                                onChange={(e) => { setEmail(e.target.value); setError(""); }}
                                placeholder="admin@bethanyhouse.com"
                                autoComplete="email"
                                required
                                className="w-full h-11 px-4 bg-gray-900 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent transition-all"
                                style={{ fontSize: 16 }}
                            />
                        </div>

                        {/* Password */}
                        <div>
                            <label className="block text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                                Password
                            </label>
                            <div className="relative">
                                <input
                                    type={showPass ? "text" : "password"}
                                    value={password}
                                    onChange={(e) => { setPassword(e.target.value); setError(""); }}
                                    placeholder="••••••••"
                                    autoComplete="current-password"
                                    required
                                    className="w-full h-11 px-4 pr-11 bg-gray-900 border border-gray-700 rounded-xl text-white text-sm placeholder-gray-600 focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent transition-all"
                                    style={{ fontSize: 16 }}
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowPass((s) => !s)}
                                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 transition-colors"
                                    tabIndex={-1}
                                >
                                    {showPass ? (
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                                        </svg>
                                    ) : (
                                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                        </svg>
                                    )}
                                </button>
                            </div>
                        </div>

                        {/* Error */}
                        {error && (
                            <div className="flex items-start gap-2.5 p-3 bg-red-950/60 border border-red-800/60 rounded-lg">
                                <svg className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                        d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                                </svg>
                                <p className="text-xs text-red-300">{error}</p>
                            </div>
                        )}

                        {/* Submit */}
                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full h-11 rounded-xl bg-green-700 hover:bg-green-600 disabled:opacity-60 disabled:cursor-not-allowed text-white text-sm font-semibold transition-colors shadow-lg shadow-green-900/30 flex items-center justify-center gap-2 mt-2"
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

                    {/* Divider */}
                    <div className="mt-8 pt-6 border-t border-gray-800/60">
                        <p className="text-center text-xs text-gray-600">
                            Access restricted to Bethany House staff.
                            <br />Contact your administrator if you need access.
                        </p>
                    </div>
                </div>
            </div>
        </div>
    );
}
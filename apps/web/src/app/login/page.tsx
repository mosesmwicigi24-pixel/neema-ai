"use client";
import { useState, useEffect } from "react";
import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);
    const [showPass, setShowPass] = useState(false);
    const [mounted, setMounted] = useState(false);
    const router = useRouter();

    useEffect(() => {
        setMounted(true);
    }, []);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        setLoading(true);
        setError("");
        const res = await signIn("credentials", {
            email,
            password,
            redirect: false,
        });
        setLoading(false);
        if (res?.ok) router.push("/dashboard");
        else setError("Invalid email or password. Please try again.");
    }

    return (
        <>
            <link
                href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&family=JetBrains+Mono:wght@400;500&display=swap"
                rel="stylesheet"
            />

            <style>{`
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'DM Sans', sans-serif; background: #09080a; }

        @keyframes slide-up {
          from { opacity: 0; transform: translateY(22px); }
          to   { opacity: 1; transform: translateY(0);    }
        }
        @keyframes fade-in {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @keyframes float {
          0%,100% { transform: translateY(0px) rotate(0deg); }
          40%      { transform: translateY(-12px) rotate(1.2deg); }
          70%      { transform: translateY(-6px) rotate(-0.8deg); }
        }
        @keyframes orbit-cw  { to { transform: rotate(360deg); } }
        @keyframes orbit-ccw { to { transform: rotate(-360deg); } }
        @keyframes shimmer-gold {
          0%   { background-position: 0% center; }
          100% { background-position: 200% center; }
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse-dot {
          0%,100% { opacity: 1; transform: scale(1); }
          50%      { opacity: 0.5; transform: scale(0.8); }
        }

        .su  { animation: slide-up 0.55s cubic-bezier(0.16,1,0.3,1) both; }
        .fi  { animation: fade-in  0.45s ease both; }
        .d1  { animation-delay: 0.08s; }
        .d2  { animation-delay: 0.16s; }
        .d3  { animation-delay: 0.24s; }
        .d4  { animation-delay: 0.32s; }
        .d5  { animation-delay: 0.40s; }
        .d6  { animation-delay: 0.50s; }

        .panel-grid {
          background-image:
            linear-gradient(rgba(201,151,58,0.055) 1px, transparent 1px),
            linear-gradient(90deg, rgba(201,151,58,0.055) 1px, transparent 1px);
          background-size: 52px 52px;
        }

        .ring-cw  { animation: orbit-cw  28s linear infinite; }
        .ring-ccw { animation: orbit-ccw 18s linear infinite; }
        .icon-float { animation: float 7s ease-in-out infinite; }

        .gold-text {
          background: linear-gradient(90deg,#c9973a 0%,#f5d06e 35%,#e8b84b 50%,#f5d06e 65%,#c9973a 100%);
          background-size: 200% auto;
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
          background-clip: text;
          animation: shimmer-gold 3.8s linear infinite;
        }

        /* Input */
        .field {
          width: 100%;
          background: rgba(255,255,255,0.025);
          border: 1px solid rgba(201,151,58,0.16);
          border-radius: 12px;
          color: #f0ece6;
          font-family: 'DM Sans', sans-serif;
          font-size: 14px;
          outline: none;
          transition: border-color 0.2s, box-shadow 0.2s;
        }
        .field::placeholder { color: #342e2a; }
        .field:focus {
          border-color: rgba(201,151,58,0.58);
          box-shadow: 0 0 0 3px rgba(201,151,58,0.11), 0 0 28px rgba(201,151,58,0.06);
        }

        /* Button */
        .btn-gold {
          width: 100%; border: none; border-radius: 12px; cursor: pointer;
          font-family: 'DM Sans', sans-serif; font-size: 14px; font-weight: 600;
          letter-spacing: 0.02em; color: #0d0b08; position: relative; overflow: hidden;
          background: linear-gradient(135deg, #c9973a 0%, #e8b84b 50%, #c9973a 100%);
          background-size: 200% auto;
          transition: background-position 0.4s ease, box-shadow 0.25s ease, transform 0.12s ease;
        }
        .btn-gold::after {
          content: '';
          position: absolute; inset: 0;
          background: linear-gradient(180deg, rgba(255,255,255,0.13) 0%, transparent 55%);
          border-radius: 12px; pointer-events: none;
        }
        .btn-gold:hover:not(:disabled) {
          background-position: right center;
          box-shadow: 0 0 0 3px rgba(201,151,58,0.2), 0 10px 30px rgba(201,151,58,0.3);
          transform: translateY(-1px);
        }
        .btn-gold:active:not(:disabled) { transform: translateY(0); }
        .btn-gold:disabled { opacity: 0.42; cursor: not-allowed; }

        .spinner { animation: spin 0.72s linear infinite; }
        .status-dot { animation: pulse-dot 2.5s ease-in-out infinite; }

        ::-webkit-scrollbar { display: none; }
        * { scrollbar-width: none; }
      `}</style>

            {/* ─── ROOT ──────────────────────────────────────────── */}
            <div
                style={{
                    minHeight: "100dvh",
                    display: "flex",
                    background: "#09080a",
                    overflow: "hidden",
                }}
            >
                {/* ══════════════════════════════════════════════════
            LEFT PANEL  (hidden < lg)
        ══════════════════════════════════════════════════ */}
                <div
                    className="panel-grid"
                    style={{
                        display: "flex",
                        flexDirection: "column",
                        justifyContent: "space-between",
                        padding: "48px 52px",
                        overflow: "hidden",
                        position: "relative",
                        flexShrink: 0,
                    }}
                    /* Tailwind breakpoint handled below via className trick */
                >
                    {/* We use a Tailwind-compatible wrapper to handle lg show/hide */}
                    <div className="hidden lg:contents">
                        {/* Ambient */}
                        <div
                            style={{
                                position: "absolute",
                                inset: 0,
                                pointerEvents: "none",
                                background:
                                    "radial-gradient(ellipse 55% 45% at 20% 20%, rgba(201,151,58,0.12) 0%, transparent 70%)",
                            }}
                        />
                        <div
                            style={{
                                position: "absolute",
                                bottom: -80,
                                right: -80,
                                width: 400,
                                height: 400,
                                borderRadius: "50%",
                                pointerEvents: "none",
                                background:
                                    "radial-gradient(circle, rgba(201,151,58,0.07) 0%, transparent 70%)",
                            }}
                        />

                        {/* Orbital decoration */}
                        <div
                            style={{
                                position: "absolute",
                                top: "47%",
                                left: "48%",
                                transform: "translate(-50%, -50%)",
                                pointerEvents: "none",
                            }}
                        >
                            <div
                                className="ring-cw"
                                style={{
                                    width: 440,
                                    height: 440,
                                    borderRadius: "50%",
                                    border: "1px solid rgba(201,151,58,0.09)",
                                }}
                            />
                            <div
                                className="ring-ccw"
                                style={{
                                    position: "absolute",
                                    inset: 58,
                                    borderRadius: "50%",
                                    border: "1px dashed rgba(201,151,58,0.07)",
                                }}
                            />
                            <div
                                style={{
                                    position: "absolute",
                                    inset: 116,
                                    borderRadius: "50%",
                                    border: "1px solid rgba(201,151,58,0.04)",
                                }}
                            />
                        </div>

                        {/* Wordmark */}
                        <div
                            className={mounted ? "su fi" : "opacity-0"}
                            style={{ position: "relative", zIndex: 2 }}
                        >
                            <div
                                style={{
                                    display: "flex",
                                    alignItems: "center",
                                    gap: 10,
                                    marginBottom: 8,
                                }}
                            >
                                <div
                                    style={{
                                        width: 36,
                                        height: 36,
                                        borderRadius: 10,
                                        flexShrink: 0,
                                        display: "flex",
                                        alignItems: "center",
                                        justifyContent: "center",
                                        background:
                                            "linear-gradient(135deg, #c9973a, #e8b84b)",
                                        boxShadow:
                                            "0 4px 18px rgba(201,151,58,0.38)",
                                    }}
                                >
                                    <svg
                                        width="18"
                                        height="18"
                                        fill="none"
                                        stroke="#09080a"
                                        viewBox="0 0 24 24"
                                    >
                                        <path
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                            strokeWidth={2.5}
                                            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                                        />
                                    </svg>
                                </div>
                                <span
                                    style={{
                                        fontFamily: "'DM Serif Display', serif",
                                        fontSize: 22,
                                        color: "#f0ece6",
                                    }}
                                >
                                    Neema
                                </span>
                            </div>
                            <p
                                style={{
                                    fontFamily: "'JetBrains Mono', monospace",
                                    fontSize: 10,
                                    color: "#4a4038",
                                    letterSpacing: "0.18em",
                                    textTransform: "uppercase",
                                }}
                            >
                                Bethany House · Agent Console
                            </p>
                        </div>

                        {/* Hero copy */}
                        <div style={{ position: "relative", zIndex: 2 }}>
                            <div
                                className={`icon-float ${mounted ? "su d1" : "opacity-0"}`}
                                style={{
                                    width: 80,
                                    height: 80,
                                    borderRadius: 22,
                                    marginBottom: 36,
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    background:
                                        "linear-gradient(135deg, rgba(201,151,58,0.13) 0%, rgba(201,151,58,0.04) 100%)",
                                    border: "1px solid rgba(201,151,58,0.2)",
                                    boxShadow: "0 0 52px rgba(201,151,58,0.09)",
                                }}
                            >
                                <svg
                                    width="36"
                                    height="36"
                                    fill="none"
                                    stroke="#c9973a"
                                    viewBox="0 0 24 24"
                                >
                                    <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        strokeWidth={1.5}
                                        d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
                                    />
                                </svg>
                            </div>

                            <h2
                                className={mounted ? "su d2" : "opacity-0"}
                                style={{
                                    fontFamily: "'DM Serif Display', serif",
                                    fontSize: "clamp(30px, 3vw, 46px)",
                                    lineHeight: 1.12,
                                    color: "#f0ece6",
                                    marginBottom: 18,
                                }}
                            >
                                Unified inbox for
                                <br />
                                <span className="gold-text">
                                    every conversation.
                                </span>
                            </h2>

                            <p
                                className={mounted ? "su d3" : "opacity-0"}
                                style={{
                                    color: "#534740",
                                    fontSize: 15,
                                    lineHeight: 1.72,
                                    maxWidth: 380,
                                    marginBottom: 36,
                                }}
                            >
                                WhatsApp, Messenger, Instagram, Email and SMS —
                                with AI that routes, drafts, and hands off
                                seamlessly to your team.
                            </p>

                            <div
                                style={{
                                    display: "flex",
                                    flexDirection: "column",
                                    gap: 12,
                                }}
                            >
                                {[
                                    {
                                        icon: "⚡",
                                        text: "AI-powered conversation routing",
                                    },
                                    {
                                        icon: "🔗",
                                        text: "5 channels · one unified inbox",
                                    },
                                    {
                                        icon: "📦",
                                        text: "Orders & catalog built right in",
                                    },
                                ].map((f, i) => (
                                    <div
                                        key={f.text}
                                        className={
                                            mounted
                                                ? `su d${i + 3}`
                                                : "opacity-0"
                                        }
                                        style={{
                                            display: "flex",
                                            alignItems: "center",
                                            gap: 12,
                                        }}
                                    >
                                        <div
                                            style={{
                                                width: 32,
                                                height: 32,
                                                borderRadius: 8,
                                                flexShrink: 0,
                                                display: "flex",
                                                alignItems: "center",
                                                justifyContent: "center",
                                                fontSize: 14,
                                                background:
                                                    "rgba(201,151,58,0.08)",
                                                border: "1px solid rgba(201,151,58,0.14)",
                                            }}
                                        >
                                            {f.icon}
                                        </div>
                                        <span
                                            style={{
                                                color: "#6a5e55",
                                                fontSize: 13,
                                            }}
                                        >
                                            {f.text}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Status */}
                        <div
                            className={mounted ? "fi d5" : "opacity-0"}
                            style={{
                                position: "relative",
                                zIndex: 2,
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                            }}
                        >
                            <div
                                className="status-dot"
                                style={{
                                    width: 7,
                                    height: 7,
                                    borderRadius: "50%",
                                    background: "#10b981",
                                    boxShadow: "0 0 8px rgba(16,185,129,0.75)",
                                }}
                            />
                            <span
                                style={{
                                    fontFamily: "'JetBrains Mono', monospace",
                                    fontSize: 10,
                                    color: "#342e2a",
                                    letterSpacing: "0.14em",
                                    textTransform: "uppercase",
                                }}
                            >
                                All systems operational
                            </span>
                        </div>
                    </div>
                </div>

                {/* Vertical rule */}
                <div
                    className="hidden lg:block"
                    style={{
                        width: 1,
                        flexShrink: 0,
                        background:
                            "linear-gradient(to bottom, transparent, rgba(201,151,58,0.16) 20%, rgba(201,151,58,0.16) 80%, transparent)",
                    }}
                />

                {/* ══════════════════════════════════════════════════
            RIGHT PANEL  —  form
        ══════════════════════════════════════════════════ */}
                <div
                    style={{
                        flex: 1,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        padding: "32px 20px",
                        position: "relative",
                    }}
                >
                    {/* Ambient */}
                    <div
                        style={{
                            position: "absolute",
                            inset: 0,
                            pointerEvents: "none",
                            background:
                                "radial-gradient(ellipse 65% 55% at 50% 50%, rgba(201,151,58,0.045) 0%, transparent 70%)",
                        }}
                    />

                    {/* Card */}
                    <div
                        className={mounted ? "su" : "opacity-0"}
                        style={{
                            position: "relative",
                            width: "100%",
                            maxWidth: 406,
                            background: "rgba(17,14,11,0.96)",
                            border: "1px solid rgba(201,151,58,0.15)",
                            borderRadius: 22,
                            padding: "40px 38px 36px",
                            backdropFilter: "blur(28px)",
                            boxShadow:
                                "0 0 0 1px rgba(201,151,58,0.04), 0 32px 80px rgba(0,0,0,0.6), 0 0 100px rgba(201,151,58,0.045)",
                        }}
                    >
                        {/* Corner glows */}
                        <div
                            style={{
                                position: "absolute",
                                top: 0,
                                right: 0,
                                width: 150,
                                height: 150,
                                pointerEvents: "none",
                                background:
                                    "radial-gradient(circle at top right, rgba(201,151,58,0.09) 0%, transparent 65%)",
                                borderRadius: "0 22px 0 0",
                            }}
                        />
                        <div
                            style={{
                                position: "absolute",
                                bottom: 0,
                                left: 0,
                                width: 100,
                                height: 100,
                                pointerEvents: "none",
                                background:
                                    "radial-gradient(circle at bottom left, rgba(201,151,58,0.05) 0%, transparent 65%)",
                                borderRadius: "0 0 0 22px",
                            }}
                        />

                        {/* Mobile logo */}
                        <div
                            className="lg:hidden"
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 10,
                                marginBottom: 32,
                            }}
                        >
                            <div
                                style={{
                                    width: 32,
                                    height: 32,
                                    borderRadius: 8,
                                    flexShrink: 0,
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    background:
                                        "linear-gradient(135deg, #c9973a, #e8b84b)",
                                    boxShadow:
                                        "0 4px 14px rgba(201,151,58,0.32)",
                                }}
                            >
                                <svg
                                    width="16"
                                    height="16"
                                    fill="none"
                                    stroke="#09080a"
                                    viewBox="0 0 24 24"
                                >
                                    <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        strokeWidth={2.5}
                                        d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                                    />
                                </svg>
                            </div>
                            <span
                                style={{
                                    fontFamily: "'DM Serif Display', serif",
                                    fontSize: 19,
                                    color: "#f0ece6",
                                }}
                            >
                                Neema
                            </span>
                        </div>

                        {/* Heading */}
                        <div
                            className={mounted ? "su d1" : "opacity-0"}
                            style={{ marginBottom: 30 }}
                        >
                            <h1
                                style={{
                                    fontFamily: "'DM Serif Display', serif",
                                    fontSize: 27,
                                    color: "#f0ece6",
                                    lineHeight: 1.15,
                                    marginBottom: 7,
                                }}
                            >
                                Welcome back
                            </h1>
                            <p
                                style={{
                                    color: "#534740",
                                    fontSize: 13.5,
                                    lineHeight: 1.55,
                                }}
                            >
                                Sign in to your Bethany House workspace
                            </p>
                        </div>

                        <form
                            onSubmit={handleSubmit}
                            style={{
                                display: "flex",
                                flexDirection: "column",
                                gap: 20,
                            }}
                        >
                            {/* Email */}
                            <div className={mounted ? "su d2" : "opacity-0"}>
                                <label
                                    style={{
                                        display: "block",
                                        fontFamily:
                                            "'JetBrains Mono', monospace",
                                        fontSize: 10,
                                        color: "#534740",
                                        letterSpacing: "0.14em",
                                        textTransform: "uppercase",
                                        marginBottom: 8,
                                    }}
                                >
                                    Email address
                                </label>
                                <div style={{ position: "relative" }}>
                                    <div
                                        style={{
                                            position: "absolute",
                                            left: 14,
                                            top: "50%",
                                            transform: "translateY(-50%)",
                                            pointerEvents: "none",
                                        }}
                                    >
                                        <svg
                                            width="15"
                                            height="15"
                                            fill="none"
                                            stroke="#342e2a"
                                            viewBox="0 0 24 24"
                                        >
                                            <path
                                                strokeLinecap="round"
                                                strokeLinejoin="round"
                                                strokeWidth={1.8}
                                                d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                                            />
                                        </svg>
                                    </div>
                                    <input
                                        type="email"
                                        value={email}
                                        onChange={(e) =>
                                            setEmail(e.target.value)
                                        }
                                        required
                                        autoComplete="email"
                                        placeholder="you@bethanyhouse.co"
                                        className="field"
                                        style={{
                                            paddingLeft: 42,
                                            paddingRight: 14,
                                            paddingTop: 13,
                                            paddingBottom: 13,
                                        }}
                                    />
                                </div>
                            </div>

                            {/* Password */}
                            <div className={mounted ? "su d3" : "opacity-0"}>
                                <div
                                    style={{
                                        display: "flex",
                                        justifyContent: "space-between",
                                        alignItems: "center",
                                        marginBottom: 8,
                                    }}
                                >
                                    <label
                                        style={{
                                            fontFamily:
                                                "'JetBrains Mono', monospace",
                                            fontSize: 10,
                                            color: "#534740",
                                            letterSpacing: "0.14em",
                                            textTransform: "uppercase",
                                        }}
                                    >
                                        Password
                                    </label>
                                    <button
                                        type="button"
                                        style={{
                                            fontFamily:
                                                "'JetBrains Mono', monospace",
                                            fontSize: 10,
                                            color: "#c9973a",
                                            letterSpacing: "0.1em",
                                            textTransform: "uppercase",
                                            background: "none",
                                            border: "none",
                                            cursor: "pointer",
                                            transition: "color 0.15s",
                                        }}
                                        onMouseEnter={(e) =>
                                            (e.currentTarget.style.color =
                                                "#e8b84b")
                                        }
                                        onMouseLeave={(e) =>
                                            (e.currentTarget.style.color =
                                                "#c9973a")
                                        }
                                    >
                                        Forgot?
                                    </button>
                                </div>
                                <div style={{ position: "relative" }}>
                                    <div
                                        style={{
                                            position: "absolute",
                                            left: 14,
                                            top: "50%",
                                            transform: "translateY(-50%)",
                                            pointerEvents: "none",
                                        }}
                                    >
                                        <svg
                                            width="15"
                                            height="15"
                                            fill="none"
                                            stroke="#342e2a"
                                            viewBox="0 0 24 24"
                                        >
                                            <path
                                                strokeLinecap="round"
                                                strokeLinejoin="round"
                                                strokeWidth={1.8}
                                                d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
                                            />
                                        </svg>
                                    </div>
                                    <input
                                        type={showPass ? "text" : "password"}
                                        value={password}
                                        onChange={(e) =>
                                            setPassword(e.target.value)
                                        }
                                        required
                                        autoComplete="current-password"
                                        placeholder="••••••••••••"
                                        className="field"
                                        style={{
                                            paddingLeft: 42,
                                            paddingRight: 46,
                                            paddingTop: 13,
                                            paddingBottom: 13,
                                        }}
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowPass((s) => !s)}
                                        style={{
                                            position: "absolute",
                                            right: 13,
                                            top: "50%",
                                            transform: "translateY(-50%)",
                                            background: "none",
                                            border: "none",
                                            cursor: "pointer",
                                            color: "#342e2a",
                                            transition: "color 0.15s",
                                            display: "flex",
                                            alignItems: "center",
                                        }}
                                        onMouseEnter={(e) =>
                                            (e.currentTarget.style.color =
                                                "#c9973a")
                                        }
                                        onMouseLeave={(e) =>
                                            (e.currentTarget.style.color =
                                                "#342e2a")
                                        }
                                    >
                                        {showPass ? (
                                            <svg
                                                width="15"
                                                height="15"
                                                fill="none"
                                                stroke="currentColor"
                                                viewBox="0 0 24 24"
                                            >
                                                <path
                                                    strokeLinecap="round"
                                                    strokeLinejoin="round"
                                                    strokeWidth={1.8}
                                                    d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                                                />
                                            </svg>
                                        ) : (
                                            <svg
                                                width="15"
                                                height="15"
                                                fill="none"
                                                stroke="currentColor"
                                                viewBox="0 0 24 24"
                                            >
                                                <path
                                                    strokeLinecap="round"
                                                    strokeLinejoin="round"
                                                    strokeWidth={1.8}
                                                    d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                                                />
                                                <path
                                                    strokeLinecap="round"
                                                    strokeLinejoin="round"
                                                    strokeWidth={1.8}
                                                    d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                                                />
                                            </svg>
                                        )}
                                    </button>
                                </div>
                            </div>

                            {/* Error */}
                            {error && (
                                <div
                                    className="su"
                                    style={{
                                        display: "flex",
                                        alignItems: "center",
                                        gap: 10,
                                        padding: "11px 14px",
                                        borderRadius: 12,
                                        background: "rgba(220,38,38,0.07)",
                                        border: "1px solid rgba(220,38,38,0.2)",
                                    }}
                                >
                                    <svg
                                        width="14"
                                        height="14"
                                        fill="none"
                                        stroke="#f87171"
                                        viewBox="0 0 24 24"
                                        style={{ flexShrink: 0 }}
                                    >
                                        <path
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                            strokeWidth={2}
                                            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                                        />
                                    </svg>
                                    <span
                                        style={{
                                            color: "#f87171",
                                            fontSize: 12.5,
                                        }}
                                    >
                                        {error}
                                    </span>
                                </div>
                            )}

                            {/* Submit */}
                            <div className={mounted ? "su d4" : "opacity-0"}>
                                <button
                                    type="submit"
                                    disabled={loading}
                                    className="btn-gold"
                                    style={{ padding: "15px 0" }}
                                >
                                    {loading ? (
                                        <span
                                            style={{
                                                display: "flex",
                                                alignItems: "center",
                                                justifyContent: "center",
                                                gap: 10,
                                            }}
                                        >
                                            <svg
                                                className="spinner"
                                                width="16"
                                                height="16"
                                                fill="none"
                                                viewBox="0 0 24 24"
                                            >
                                                <circle
                                                    style={{ opacity: 0.25 }}
                                                    cx="12"
                                                    cy="12"
                                                    r="10"
                                                    stroke="#0d0b08"
                                                    strokeWidth="3"
                                                />
                                                <path
                                                    style={{ opacity: 0.75 }}
                                                    fill="#0d0b08"
                                                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                                                />
                                            </svg>
                                            Authenticating…
                                        </span>
                                    ) : (
                                        <span
                                            style={{
                                                display: "flex",
                                                alignItems: "center",
                                                justifyContent: "center",
                                                gap: 8,
                                            }}
                                        >
                                            Sign in to console
                                            <svg
                                                width="16"
                                                height="16"
                                                fill="none"
                                                stroke="currentColor"
                                                viewBox="0 0 24 24"
                                            >
                                                <path
                                                    strokeLinecap="round"
                                                    strokeLinejoin="round"
                                                    strokeWidth={2}
                                                    d="M13 7l5 5m0 0l-5 5m5-5H6"
                                                />
                                            </svg>
                                        </span>
                                    )}
                                </button>
                            </div>
                        </form>

                        {/* Divider */}
                        <div
                            className={mounted ? "su d5" : "opacity-0"}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 14,
                                margin: "28px 0 22px",
                            }}
                        >
                            <div
                                style={{
                                    flex: 1,
                                    height: 1,
                                    background: "rgba(201,151,58,0.09)",
                                }}
                            />
                            <span
                                style={{
                                    fontFamily: "'JetBrains Mono', monospace",
                                    fontSize: 9,
                                    color: "#2a2520",
                                    letterSpacing: "0.14em",
                                    textTransform: "uppercase",
                                }}
                            >
                                secured access
                            </span>
                            <div
                                style={{
                                    flex: 1,
                                    height: 1,
                                    background: "rgba(201,151,58,0.09)",
                                }}
                            />
                        </div>

                        {/* Trust badges */}
                        <div
                            className={mounted ? "su d6" : "opacity-0"}
                            style={{
                                display: "flex",
                                justifyContent: "center",
                                alignItems: "center",
                                gap: 24,
                            }}
                        >
                            {[
                                { icon: "🔒", label: "256-bit TLS" },
                                { icon: "🛡", label: "SOC 2" },
                                { icon: "🔑", label: "2FA Support" },
                            ].map((b) => (
                                <div
                                    key={b.label}
                                    style={{
                                        display: "flex",
                                        alignItems: "center",
                                        gap: 5,
                                    }}
                                >
                                    <span style={{ fontSize: 11 }}>
                                        {b.icon}
                                    </span>
                                    <span
                                        style={{
                                            fontFamily:
                                                "'JetBrains Mono', monospace",
                                            fontSize: 9,
                                            color: "#2a2520",
                                            letterSpacing: "0.1em",
                                            textTransform: "uppercase",
                                        }}
                                    >
                                        {b.label}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </div>
        </>
    );
}
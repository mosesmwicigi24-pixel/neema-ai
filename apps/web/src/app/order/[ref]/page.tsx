"use client";

// Public order tracking. The enquiry UUID in the URL is the unguessable token —
// no login, no enumeration. Shows a coarse production timeline only (sanitized
// endpoint returns no phone, price, or internal ids).

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";
const MOSS = "#589b31";
const MOSS_DK = "#427425";
const INK = "#16270c";

interface Track {
    product_name: string | null;
    created_at: string | null;
    order_number: string | null;
    stage: "received" | "in_production" | "ready" | "delivered" | "closed";
    stages: string[];
}

const STEPS: { key: Track["stage"]; label: string; blurb: string }[] = [
    { key: "received", label: "Request received", blurb: "We have your measurements." },
    { key: "in_production", label: "In production", blurb: "Our tailors are making your item." },
    { key: "ready", label: "Ready", blurb: "Your order is ready." },
    { key: "delivered", label: "Delivered", blurb: "Enjoy — thank you!" },
];

export default function OrderTrackPage(): React.ReactElement {
    const params = useParams();
    const ref = Array.isArray(params.ref) ? params.ref[0] : params.ref;
    const [t, setT] = useState<Track | null>(null);
    const [state, setState] = useState<"loading" | "ok" | "missing">("loading");

    useEffect(() => {
        if (!ref) return;
        document.title = "Track your order | Bethany House";
        (async () => {
            try {
                const res = await fetch(`${BASE}/public/order/track/${ref}`);
                if (!res.ok) throw new Error();
                setT(await res.json());
                setState("ok");
            } catch {
                setState("missing");
            }
        })();
    }, [ref]);

    if (state === "loading") {
        return <Centered>Loading…</Centered>;
    }
    if (state === "missing" || !t) {
        return (
            <Centered>
                <p style={{ marginBottom: 16 }}>We couldn&apos;t find that order.</p>
                <Link href="/catalog" style={{ color: MOSS_DK, fontWeight: 700 }}>
                    ← Back to catalog
                </Link>
            </Centered>
        );
    }

    const closed = t.stage === "closed";
    const currentIdx = closed ? -1 : STEPS.findIndex((s) => s.key === t.stage);

    return (
        <div style={{ minHeight: "100vh", background: "#f7faf4", color: INK }}>
            <header
                style={{
                    background: `linear-gradient(135deg, ${MOSS_DK}, ${MOSS})`,
                    color: "white",
                    padding: "26px 20px 22px",
                }}
            >
                <div style={{ maxWidth: 560, margin: "0 auto" }}>
                    <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 22 }}>
                        Your order
                    </div>
                    <div style={{ opacity: 0.92, fontSize: 15, marginTop: 4 }}>
                        {t.product_name || "Made-to-order item"}
                        {t.order_number ? ` · ${t.order_number}` : ""}
                    </div>
                </div>
            </header>

            <main style={{ maxWidth: 560, margin: "0 auto", padding: "24px 20px 40px" }}>
                {closed ? (
                    <div
                        style={{
                            background: "white",
                            border: "1px solid #e8f0e0",
                            borderRadius: 14,
                            padding: 20,
                            color: "#64748b",
                            fontSize: 15,
                        }}
                    >
                        This request has been closed. If that&apos;s unexpected, please message us and
                        we&apos;ll help.
                    </div>
                ) : (
                    <div style={{ display: "grid", gap: 0 }}>
                        {STEPS.map((s, i) => {
                            const doneStep = i < currentIdx;
                            const active = i === currentIdx;
                            const dotColor = doneStep || active ? MOSS : "#d3e0c6";
                            return (
                                <div key={s.key} style={{ display: "flex", gap: 14 }}>
                                    {/* rail */}
                                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                                        <div
                                            style={{
                                                width: 26,
                                                height: 26,
                                                borderRadius: "50%",
                                                background: doneStep || active ? MOSS : "white",
                                                border: `2px solid ${dotColor}`,
                                                color: "white",
                                                display: "flex",
                                                alignItems: "center",
                                                justifyContent: "center",
                                                fontSize: 13,
                                                fontWeight: 800,
                                                flexShrink: 0,
                                            }}
                                        >
                                            {doneStep ? "✓" : ""}
                                        </div>
                                        {i < STEPS.length - 1 && (
                                            <div
                                                style={{
                                                    width: 2,
                                                    flex: 1,
                                                    minHeight: 34,
                                                    background: i < currentIdx ? MOSS : "#e0e9d6",
                                                }}
                                            />
                                        )}
                                    </div>
                                    {/* label */}
                                    <div style={{ paddingBottom: 22, paddingTop: 1 }}>
                                        <div
                                            style={{
                                                fontWeight: 700,
                                                fontSize: 15,
                                                color: active ? MOSS_DK : doneStep ? INK : "#94a3b8",
                                            }}
                                        >
                                            {s.label}
                                        </div>
                                        <div style={{ fontSize: 13, color: "#6a7d59", marginTop: 2 }}>
                                            {s.blurb}
                                        </div>
                                        {active && (
                                            <span
                                                style={{
                                                    display: "inline-block",
                                                    marginTop: 6,
                                                    background: "#eef6e6",
                                                    color: MOSS_DK,
                                                    fontSize: 11,
                                                    fontWeight: 700,
                                                    padding: "3px 9px",
                                                    borderRadius: 999,
                                                }}
                                            >
                                                Current status
                                            </span>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                )}

                <p style={{ fontSize: 12.5, color: "#8aa07a", marginTop: 18, lineHeight: 1.5 }}>
                    We&apos;ll keep this page up to date. Questions? Just reply on WhatsApp and our
                    team will help.
                </p>
                <div style={{ marginTop: 16 }}>
                    <Link href="/catalog" style={{ color: MOSS_DK, fontWeight: 700, fontSize: 14 }}>
                        ← Browse the catalog
                    </Link>
                </div>
            </main>
        </div>
    );
}

function Centered({ children }: { children: React.ReactNode }) {
    return (
        <div
            style={{
                minHeight: "100vh",
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                background: "#f7faf4",
                color: "#4a5c3b",
                padding: 20,
                textAlign: "center",
            }}
        >
            {children}
        </div>
    );
}

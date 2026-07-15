"use client";

// Public product detail — image gallery, price, description, and a one-tap
// WhatsApp order button. Fed by /api/public/catalog/{slug} (sanitized).

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

const MOSS = "#589b31";
const MOSS_DK = "#427425";
const INK = "#16270c";
const WA = "#25D366";

interface Image {
    url: string;
    thumb: string;
    alt: string;
}
interface Variant {
    label: string;
    price: number | null;
    currency: string;
}
interface Product {
    slug: string;
    name: string;
    category: string | null;
    description: string | null;
    price: number | null;
    currency: string;
    image_url: string | null;
    made_to_order: boolean;
    in_stock: boolean;
    order_url: string | null;
    images: Image[];
    variants?: Variant[];
    price_from?: number | null;
    price_to?: number | null;
}

// $ for USD, the ISO code otherwise (KES 12,000 · ZMW 1,260); cents below a unit.
function fmtMoney(v: number | null | undefined, currency: string): string {
    if (v == null) return "";
    const amt = v >= 1 ? Math.round(v).toLocaleString("en-US") : v.toFixed(2);
    return currency === "USD" ? "$" + amt : currency + " " + amt;
}

// A fitting liturgical glyph for a product with no photo (mirrors the grid).
function catGlyph(category: string | null, name: string): string {
    const s = ((category || "") + " " + (name || "")).toLowerCase();
    const rules: [RegExp, string][] = [
        [/wine|chalice|cup|communion|eucharist/, "🍷"],
        [/wafer|bread|host/, "🍞"],
        [/tray/, "🫙"],
        [/oil|anoint|candle|refill/, "🕯️"],
        [/cassock|vestment|gown|shirt|stole|cope|chasuble|alb|robe|shawl|tallit|apparel|cap/, "👘"],
        [/bell/, "🔔"],
        [/bible|book|missal/, "📖"],
        [/ring|cross|crozier|staff|rod|mitre|pectoral|accessor/, "✝️"],
    ];
    for (const [re, glyph] of rules) if (re.test(s)) return glyph;
    return "✝️";
}

export default function ProductPage(): React.ReactElement {
    const params = useParams();
    const slug = Array.isArray(params.slug) ? params.slug[0] : params.slug;
    const [p, setP] = useState<Product | null>(null);
    const [state, setState] = useState<"loading" | "ok" | "missing">("loading");
    const [active, setActive] = useState(0);

    useEffect(() => {
        if (!slug) return;
        (async () => {
            try {
                const params = new URLSearchParams(window.location.search);
                const qs = params.toString() ? `?${params.toString()}` : "";
                const res = await fetch(`${BASE}/public/catalog/${slug}${qs}`);
                if (!res.ok) throw new Error();
                const data: Product = await res.json();
                setP(data);
                setState("ok");
                document.title = `${data.name} | Bethany House`;
            } catch {
                setState("missing");
            }
        })();
    }, [slug]);

    if (state === "loading") {
        return (
            <div style={centered}>
                <p style={{ color: "#7a8a6c" }}>Loading…</p>
            </div>
        );
    }
    if (state === "missing" || !p) {
        return (
            <div style={centered}>
                <p style={{ color: "#7a8a6c", marginBottom: 16 }}>
                    We couldn&apos;t find that product.
                </p>
                <Link href="/catalog" style={{ color: MOSS_DK, fontWeight: 600 }}>
                    ← Back to catalog
                </Link>
            </div>
        );
    }

    const gallery = p.images && p.images.length ? p.images : p.image_url
        ? [{ url: p.image_url, thumb: p.image_url, alt: p.name }]
        : [];
    const hero = gallery[active]?.url;

    return (
        <div style={{ minHeight: "100vh", background: "#f7faf4", color: INK }}>
            <div
                style={{
                    maxWidth: 860,
                    margin: "0 auto",
                    padding: "14px 16px 0",
                }}
            >
                <Link
                    href="/catalog"
                    style={{ color: MOSS_DK, fontWeight: 600, fontSize: 14, textDecoration: "none" }}
                >
                    ← Catalog
                </Link>
            </div>

            <main
                style={{
                    maxWidth: 860,
                    margin: "0 auto",
                    padding: 16,
                    display: "grid",
                    gap: 20,
                }}
            >
                {/* Gallery */}
                <div>
                    <div
                        style={{
                            aspectRatio: "1 / 1",
                            background: "#eef4e8",
                            borderRadius: 18,
                            overflow: "hidden",
                            border: "1px solid #e8f0e0",
                        }}
                    >
                        {hero ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                                src={hero}
                                alt={p.name}
                                style={{ width: "100%", height: "100%", objectFit: "contain", padding: 16 }}
                            />
                        ) : (
                            <div
                                style={{
                                    width: "100%",
                                    height: "100%",
                                    display: "flex",
                                    alignItems: "center",
                                    justifyContent: "center",
                                    fontSize: 96,
                                    opacity: 0.85,
                                }}
                            >
                                {catGlyph(p.category, p.name)}
                            </div>
                        )}
                    </div>
                    {gallery.length > 1 && (
                        <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
                            {gallery.map((g, i) => (
                                <button
                                    key={i}
                                    onClick={() => setActive(i)}
                                    style={{
                                        width: 60,
                                        height: 60,
                                        borderRadius: 10,
                                        overflow: "hidden",
                                        border: `2px solid ${i === active ? MOSS : "transparent"}`,
                                        padding: 0,
                                        cursor: "pointer",
                                        background: "#eef4e8",
                                    }}
                                >
                                    {/* eslint-disable-next-line @next/next/no-img-element */}
                                    <img
                                        src={g.thumb || g.url}
                                        alt=""
                                        style={{ width: "100%", height: "100%", objectFit: "contain", padding: 4 }}
                                    />
                                </button>
                            ))}
                        </div>
                    )}
                </div>

                {/* Details */}
                <div>
                    {p.category && (
                        <div
                            style={{
                                textTransform: "uppercase",
                                letterSpacing: "0.06em",
                                fontSize: 11,
                                fontWeight: 700,
                                color: MOSS,
                            }}
                        >
                            {p.category}
                        </div>
                    )}
                    <h1
                        style={{
                            fontFamily: "'DM Serif Display', Georgia, serif",
                            fontSize: 27,
                            lineHeight: 1.15,
                            margin: "6px 0 10px",
                        }}
                    >
                        {p.name}
                    </h1>

                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 22, fontWeight: 800, color: MOSS_DK }}>
                            {p.price_from != null && p.price_to != null
                                ? `${fmtMoney(p.price_from, p.currency)} – ${fmtMoney(p.price_to, p.currency)}`
                                : fmtMoney(p.price, p.currency) || "Price on enquiry"}
                        </span>
                        {p.made_to_order ? (
                            <span
                                style={{
                                    background: "#eef6e6",
                                    color: MOSS_DK,
                                    fontSize: 12,
                                    fontWeight: 700,
                                    padding: "4px 10px",
                                    borderRadius: 999,
                                }}
                            >
                                Made to order
                            </span>
                        ) : null}
                    </div>

                    {/* Variant options with their own prices (size / colour). */}
                    {p.variants && p.variants.length > 0 && (
                        <div style={{ marginTop: 16 }}>
                            <div style={{ fontSize: 12, fontWeight: 700, color: MOSS,
                                          textTransform: "uppercase", letterSpacing: "0.05em",
                                          marginBottom: 8 }}>
                                Options
                            </div>
                            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                                {p.variants.map((v, i) => (
                                    <div key={i} style={{
                                        display: "flex", justifyContent: "space-between",
                                        alignItems: "center", gap: 10,
                                        padding: "9px 12px", borderRadius: 10,
                                        background: "#f4f8ef", border: "1px solid #e4eede",
                                    }}>
                                        <span style={{ fontSize: 14, fontWeight: 600, color: INK }}>
                                            {v.label}
                                        </span>
                                        <span style={{ fontSize: 14, fontWeight: 700, color: MOSS_DK,
                                                       whiteSpace: "nowrap" }}>
                                            {fmtMoney(v.price, v.currency)}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                    {p.description && (
                        <p
                            style={{
                                marginTop: 14,
                                fontSize: 15,
                                lineHeight: 1.6,
                                color: "#324025",
                                whiteSpace: "pre-wrap",
                            }}
                        >
                            {p.description}
                        </p>
                    )}

                    {p.made_to_order && (
                        <p style={{ marginTop: 12, fontSize: 13.5, color: "#6a7d59" }}>
                            This item is tailored to order. Message us to confirm your size and
                            measurements — we&apos;ll make it for you.
                        </p>
                    )}

                    {p.made_to_order && (
                        <Link
                            href={`/catalog/${p.slug}/measure`}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                gap: 8,
                                marginTop: 20,
                                background: MOSS,
                                color: "white",
                                fontWeight: 700,
                                fontSize: 16,
                                padding: "14px 18px",
                                borderRadius: 14,
                                textDecoration: "none",
                                boxShadow: "0 3px 10px rgba(88,155,49,0.28)",
                            }}
                        >
                            📏 Start your made-to-order
                        </Link>
                    )}

                    {p.order_url && (
                        <a
                            href={p.order_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                gap: 10,
                                marginTop: p.made_to_order ? 10 : 20,
                                background: p.made_to_order ? "transparent" : WA,
                                color: p.made_to_order ? MOSS_DK : "white",
                                border: p.made_to_order ? `1.5px solid ${WA}` : "none",
                                fontWeight: 700,
                                fontSize: 16,
                                padding: "13px 18px",
                                borderRadius: 14,
                                textDecoration: "none",
                                boxShadow: p.made_to_order ? "none" : "0 3px 10px rgba(37,211,102,0.3)",
                            }}
                        >
                            <svg viewBox="0 0 24 24" width="20" height="20" fill={p.made_to_order ? WA : "currentColor"}>
                                <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z" />
                            </svg>
                            {p.made_to_order ? "Ask on WhatsApp instead" : "Order on WhatsApp"}
                        </a>
                    )}
                </div>
            </main>

            <footer
                style={{
                    textAlign: "center",
                    padding: "28px 16px 40px",
                    color: "#8aa07a",
                    fontSize: 12,
                }}
            >
                Bethany House · Vestments &amp; liturgical supplies
            </footer>
        </div>
    );
}

const centered: React.CSSProperties = {
    minHeight: "100vh",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    background: "#f7faf4",
    padding: 20,
    textAlign: "center",
};

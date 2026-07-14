"use client";

// Public, unauthenticated storefront — the shareable Bethany House catalog.
// Reads the sanitized /api/public/catalog endpoint (no internal data), so this
// page is safe to share anywhere. Mobile-first; the agent sends /catalog links.

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";

const MOSS = "#589b31";
const MOSS_DK = "#427425";
const INK = "#16270c";

interface Variant {
    label: string;
    price_kes: number | null;
    price_usd: number | null;
}
interface Product {
    slug: string;
    name: string;
    category: string | null;
    description: string | null;
    price_kes: number | null;
    price_usd: number | null;
    image_url: string | null;
    thumbnail_url: string | null;
    made_to_order: boolean;
    in_stock: boolean;
    order_url: string | null;
    variants?: Variant[];
    price_from_kes?: number | null;
    price_to_kes?: number | null;
    price_from_usd?: number | null;
    price_to_usd?: number | null;
}

function fmtKes(v: number | null | undefined): string {
    if (v == null) return "";
    return "KES " + Math.round(v).toLocaleString("en-KE");
}

function fmtUsd(v: number | null | undefined): string {
    if (v == null) return "";
    return v >= 1 ? "$" + Math.round(v).toLocaleString("en-US") : "$" + v.toFixed(2);
}

// Card price line: a range ("from KES 9,000") for varied products, else a
// single price — with an approximate USD under it so international clients see
// their money too. Returns { kes, usd } strings ("" when unknown).
function priceLine(p: Product): { kes: string; usd: string } {
    if (p.price_from_kes != null && p.price_to_kes != null) {
        return {
            kes: "from " + fmtKes(p.price_from_kes),
            usd: p.price_from_usd != null ? "≈ from " + fmtUsd(p.price_from_usd) : "",
        };
    }
    return {
        kes: fmtKes(p.price_kes) || "Enquire",
        usd: p.price_usd != null ? "≈ " + fmtUsd(p.price_usd) : "",
    };
}

export default function CatalogPage(): React.ReactElement {
    const [products, setProducts] = useState<Product[] | null>(null);
    const [error, setError] = useState(false);
    const [query, setQuery] = useState("");
    const [cat, setCat] = useState<string>("All");

    useEffect(() => {
        document.title = "Catalog | Bethany House";
        (async () => {
            try {
                const res = await fetch(`${BASE}/public/catalog`);
                if (!res.ok) throw new Error();
                setProducts(await res.json());
            } catch {
                setError(true);
            }
        })();
    }, []);

    const categories = useMemo(() => {
        const set = new Set<string>();
        (products || []).forEach((p) => p.category && set.add(p.category));
        return ["All", ...Array.from(set).sort()];
    }, [products]);

    const shown = useMemo(() => {
        const q = query.trim().toLowerCase();
        return (products || []).filter((p) => {
            if (cat !== "All" && p.category !== cat) return false;
            if (!q) return true;
            return (
                p.name.toLowerCase().includes(q) ||
                (p.category || "").toLowerCase().includes(q) ||
                (p.description || "").toLowerCase().includes(q)
            );
        });
    }, [products, query, cat]);

    return (
        <div style={{ minHeight: "100vh", background: "#f7faf4", color: INK }}>
            {/* Header */}
            <header
                style={{
                    background: `linear-gradient(135deg, ${MOSS_DK}, ${MOSS})`,
                    color: "white",
                    padding: "28px 20px 22px",
                }}
            >
                <div style={{ maxWidth: 1100, margin: "0 auto" }}>
                    <div
                        style={{
                            fontFamily: "'DM Serif Display', Georgia, serif",
                            fontSize: 30,
                            lineHeight: 1.1,
                        }}
                    >
                        Bethany House
                    </div>
                    <div style={{ opacity: 0.9, fontSize: 14, marginTop: 4 }}>
                        Vestments, communion supplies &amp; liturgical items — made with care.
                    </div>
                </div>
            </header>

            {/* Controls */}
            <div style={{ maxWidth: 1100, margin: "0 auto", padding: "18px 16px 0" }}>
                <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search products…"
                    style={{
                        width: "100%",
                        padding: "11px 14px",
                        borderRadius: 12,
                        border: "1.5px solid #dbe7d0",
                        fontSize: 15,
                        outline: "none",
                        background: "white",
                    }}
                />
                <div
                    style={{
                        display: "flex",
                        gap: 8,
                        marginTop: 12,
                        overflowX: "auto",
                        paddingBottom: 4,
                    }}
                >
                    {categories.map((c) => (
                        <button
                            key={c}
                            onClick={() => setCat(c)}
                            style={{
                                whiteSpace: "nowrap",
                                padding: "6px 14px",
                                borderRadius: 999,
                                border: `1.5px solid ${cat === c ? MOSS : "#dbe7d0"}`,
                                background: cat === c ? MOSS : "white",
                                color: cat === c ? "white" : MOSS_DK,
                                fontSize: 13,
                                fontWeight: 600,
                                cursor: "pointer",
                            }}
                        >
                            {c}
                        </button>
                    ))}
                </div>
            </div>

            {/* Grid */}
            <main style={{ maxWidth: 1100, margin: "0 auto", padding: "16px" }}>
                {error && (
                    <p style={{ textAlign: "center", padding: 60, color: "#7a8a6c" }}>
                        The catalog is briefly unavailable. Please try again shortly.
                    </p>
                )}
                {!error && products == null && (
                    <p style={{ textAlign: "center", padding: 60, color: "#7a8a6c" }}>
                        Loading catalog…
                    </p>
                )}
                {!error && products != null && shown.length === 0 && (
                    <p style={{ textAlign: "center", padding: 60, color: "#7a8a6c" }}>
                        No products match your search.
                    </p>
                )}
                <div
                    style={{
                        display: "grid",
                        gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
                        gap: 14,
                        marginTop: 8,
                    }}
                >
                    {shown.map((p) => (
                        <Link
                            key={p.slug}
                            href={`/catalog/${p.slug}`}
                            style={{
                                textDecoration: "none",
                                color: INK,
                                background: "white",
                                borderRadius: 16,
                                overflow: "hidden",
                                border: "1px solid #e8f0e0",
                                boxShadow: "0 1px 3px rgba(22,39,12,0.05)",
                                display: "flex",
                                flexDirection: "column",
                            }}
                        >
                            <div
                                style={{
                                    aspectRatio: "1 / 1",
                                    background: "#eef4e8",
                                    position: "relative",
                                }}
                            >
                                {p.image_url ? (
                                    // eslint-disable-next-line @next/next/no-img-element
                                    <img
                                        src={p.thumbnail_url || p.image_url}
                                        alt={p.name}
                                        style={{
                                            width: "100%",
                                            height: "100%",
                                            objectFit: "cover",
                                        }}
                                    />
                                ) : (
                                    <div
                                        style={{
                                            width: "100%",
                                            height: "100%",
                                            display: "flex",
                                            alignItems: "center",
                                            justifyContent: "center",
                                            color: "#b6c9a6",
                                            fontSize: 34,
                                            fontFamily: "'DM Serif Display', serif",
                                        }}
                                    >
                                        {p.name.slice(0, 1)}
                                    </div>
                                )}
                                {p.made_to_order && (
                                    <span
                                        style={{
                                            position: "absolute",
                                            top: 8,
                                            left: 8,
                                            background: "rgba(66,116,37,0.92)",
                                            color: "white",
                                            fontSize: 10,
                                            fontWeight: 700,
                                            padding: "3px 8px",
                                            borderRadius: 999,
                                        }}
                                    >
                                        Made to order
                                    </span>
                                )}
                            </div>
                            <div style={{ padding: "10px 12px 12px" }}>
                                <div
                                    style={{
                                        fontSize: 13.5,
                                        fontWeight: 600,
                                        lineHeight: 1.3,
                                        display: "-webkit-box",
                                        WebkitLineClamp: 2,
                                        WebkitBoxOrient: "vertical",
                                        overflow: "hidden",
                                        minHeight: 36,
                                    }}
                                >
                                    {p.name}
                                </div>
                                <div
                                    style={{
                                        color: MOSS_DK,
                                        fontWeight: 700,
                                        fontSize: 14,
                                        marginTop: 4,
                                    }}
                                >
                                    {priceLine(p).kes}
                                </div>
                                {priceLine(p).usd && (
                                    <div style={{ color: "#8aa07a", fontSize: 11.5, marginTop: 1 }}>
                                        {priceLine(p).usd}
                                    </div>
                                )}
                            </div>
                        </Link>
                    ))}
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
                Bethany House · Tap any item to order on WhatsApp
            </footer>
        </div>
    );
}

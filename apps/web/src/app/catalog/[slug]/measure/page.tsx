"use client";

// Free-form made-to-order request: the customer's measurements + notes for a
// catalogue item. Submits to /api/public/order/measure, which lands it flagged
// in the staff inbox (an enquiry — a colleague confirms it into production).

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "/api";
const MOSS = "#589b31";
const MOSS_DK = "#427425";
const INK = "#16270c";

// Common garment measurements — all optional and free-form; the customer fills
// what they know, and "Other measurements / notes" catches anything else.
const FIELDS = [
    "Height",
    "Chest / Bust",
    "Waist",
    "Hip",
    "Shoulder width",
    "Sleeve length",
    "Neck",
    "Garment length",
];

export default function MeasurePage(): React.ReactElement {
    const params = useParams();
    const slug = Array.isArray(params.slug) ? params.slug[0] : params.slug;

    const [productName, setProductName] = useState<string>("");
    const [name, setName] = useState("");
    const [phone, setPhone] = useState("");
    const [location, setLocation] = useState("");
    const [notes, setNotes] = useState("");
    const [ms, setMs] = useState<Record<string, string>>({});
    const [submitting, setSubmitting] = useState(false);
    const [done, setDone] = useState(false);
    const [error, setError] = useState("");

    useEffect(() => {
        if (!slug) return;
        (async () => {
            try {
                const res = await fetch(`${BASE}/public/catalog/${slug}`);
                if (res.ok) {
                    const d = await res.json();
                    setProductName(d.name || "");
                    document.title = `Made to order · ${d.name} | Bethany House`;
                }
            } catch {
                /* non-fatal — the form still works without the product name */
            }
        })();
    }, [slug]);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError("");
        if (!name.trim() || phone.replace(/\D/g, "").length < 9) {
            setError("Please enter your name and a valid phone number.");
            return;
        }
        setSubmitting(true);
        try {
            const res = await fetch(`${BASE}/public/order/measure`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    slug,
                    product: productName,
                    name: name.trim(),
                    phone: phone.trim(),
                    location: location.trim(),
                    notes: notes.trim(),
                    measurements: Object.fromEntries(
                        Object.entries(ms).filter(([, v]) => v.trim()),
                    ),
                }),
            });
            if (!res.ok) throw new Error();
            setDone(true);
        } catch {
            setError("Something went wrong sending your request. Please try again.");
        } finally {
            setSubmitting(false);
        }
    };

    if (done) {
        return (
            <div style={wrap}>
                <div style={{ maxWidth: 520, margin: "0 auto", padding: "60px 20px", textAlign: "center" }}>
                    <div style={{ fontSize: 46 }}>🧵</div>
                    <h1 style={{ fontFamily: "'DM Serif Display', serif", fontSize: 26, margin: "12px 0 8px", color: INK }}>
                        Request received
                    </h1>
                    <p style={{ color: "#4a5c3b", fontSize: 15, lineHeight: 1.6 }}>
                        Thank you, {name.split(" ")[0]}! We&apos;ve got your measurements for{" "}
                        <strong>{productName || "your item"}</strong> and a member of our team will
                        confirm your made-to-order shortly.
                    </p>
                    <Link href="/catalog" style={{ display: "inline-block", marginTop: 22, color: MOSS_DK, fontWeight: 700 }}>
                        ← Back to catalog
                    </Link>
                </div>
            </div>
        );
    }

    return (
        <div style={wrap}>
            <div style={{ maxWidth: 560, margin: "0 auto", padding: "16px 16px 48px" }}>
                <Link href={`/catalog/${slug}`} style={{ color: MOSS_DK, fontWeight: 600, fontSize: 14, textDecoration: "none" }}>
                    ← Back
                </Link>

                <div style={{ marginTop: 14 }}>
                    <div style={{ textTransform: "uppercase", letterSpacing: "0.06em", fontSize: 11, fontWeight: 700, color: MOSS }}>
                        Made to order
                    </div>
                    <h1 style={{ fontFamily: "'DM Serif Display', serif", fontSize: 25, margin: "6px 0 6px", color: INK }}>
                        {productName || "Your measurements"}
                    </h1>
                    <p style={{ color: "#5c6e4d", fontSize: 14, lineHeight: 1.55 }}>
                        We tailor this to you. Share what you know — fill only the measurements
                        you have, and add anything else in the notes. We&apos;ll confirm the rest.
                    </p>
                </div>

                <form onSubmit={submit} style={{ marginTop: 18, display: "grid", gap: 14 }}>
                    <Field label="Your name *">
                        <input style={inp} value={name} onChange={(e) => setName(e.target.value)} placeholder="Full name" />
                    </Field>
                    <Field label="Phone (WhatsApp) *">
                        <input style={inp} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="e.g. 0712 345 678" inputMode="tel" />
                    </Field>

                    <div style={{ borderTop: "1px solid #e3ecda", paddingTop: 14 }}>
                        <div style={{ fontSize: 12.5, fontWeight: 700, color: MOSS_DK, marginBottom: 8 }}>
                            Measurements (optional — in cm or inches)
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                            {FIELDS.map((f) => (
                                <Field key={f} label={f} small>
                                    <input
                                        style={inp}
                                        value={ms[f] || ""}
                                        onChange={(e) => setMs((m) => ({ ...m, [f]: e.target.value }))}
                                        placeholder="—"
                                    />
                                </Field>
                            ))}
                        </div>
                    </div>

                    <Field label="Delivery location (optional)">
                        <input style={inp} value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Town / estate" />
                    </Field>
                    <Field label="Other measurements / notes">
                        <textarea
                            style={{ ...inp, minHeight: 80, resize: "vertical" }}
                            value={notes}
                            onChange={(e) => setNotes(e.target.value)}
                            placeholder="Colour, fabric, size reference, deadline, anything else…"
                        />
                    </Field>

                    {error && <div style={{ color: "#b91c1c", fontSize: 13 }}>{error}</div>}

                    <button
                        type="submit"
                        disabled={submitting}
                        style={{
                            marginTop: 4,
                            background: submitting ? "#9db98a" : MOSS,
                            color: "white",
                            fontWeight: 700,
                            fontSize: 16,
                            padding: "14px 18px",
                            borderRadius: 14,
                            border: "none",
                            cursor: submitting ? "default" : "pointer",
                        }}
                    >
                        {submitting ? "Sending…" : "Send my measurements"}
                    </button>
                    <p style={{ fontSize: 11.5, color: "#8aa07a", textAlign: "center", margin: 0 }}>
                        No payment now — we&apos;ll confirm your order and price first.
                    </p>
                </form>
            </div>
        </div>
    );
}

function Field({
    label,
    children,
    small,
}: {
    label: string;
    children: React.ReactNode;
    small?: boolean;
}) {
    return (
        <label style={{ display: "block" }}>
            <span style={{ display: "block", fontSize: small ? 11 : 12.5, fontWeight: 600, color: "#4a5c3b", marginBottom: 4 }}>
                {label}
            </span>
            {children}
        </label>
    );
}

const wrap: React.CSSProperties = { minHeight: "100vh", background: "#f7faf4" };
const inp: React.CSSProperties = {
    width: "100%",
    padding: "10px 12px",
    borderRadius: 10,
    border: "1.5px solid #d7e4c9",
    fontSize: 15,
    outline: "none",
    background: "white",
    color: INK,
    boxSizing: "border-box",
};

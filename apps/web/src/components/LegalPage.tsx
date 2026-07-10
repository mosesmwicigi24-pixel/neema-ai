// Shared shell for the public legal pages (/privacy, /terms, /data-deletion).
// Server-rendered, zero client JS — these exist for customers and for the Meta
// App Review "Privacy Policy / Terms / Data Deletion" URL requirements.
import React from "react";
import Link from "next/link";

const MOSS = "#589b31";
const INK = "#16270c";

export function LegalPage({
    title,
    updated,
    children,
}: {
    title: string;
    updated: string;
    children: React.ReactNode;
}): React.ReactElement {
    return (
        <main style={{ background: "#fafcf7", minHeight: "100vh" }}>
            <div className="max-w-3xl mx-auto px-5 py-10">
                <Link href="/catalog" className="text-sm font-semibold" style={{ color: MOSS }}>
                    ← Bethany House
                </Link>
                <h1 className="text-3xl font-bold mt-4 mb-1" style={{ color: INK }}>
                    {title}
                </h1>
                <p className="text-sm mb-8" style={{ color: "#64748b" }}>
                    Bethany House · Nairobi, Kenya · Last updated {updated}
                </p>
                <div
                    className="space-y-6 text-[15px] leading-relaxed"
                    style={{ color: "#273421" }}
                >
                    {children}
                </div>
                <div className="mt-12 pt-6 border-t text-sm" style={{ borderColor: "#e2e8f0", color: "#64748b" }}>
                    <Link href="/privacy" className="mr-4" style={{ color: MOSS }}>Privacy Policy</Link>
                    <Link href="/terms" className="mr-4" style={{ color: MOSS }}>Terms of Service</Link>
                    <Link href="/data-deletion" style={{ color: MOSS }}>Data Deletion</Link>
                </div>
            </div>
        </main>
    );
}

export function H({ children }: { children: React.ReactNode }) {
    return <h2 className="text-xl font-bold pt-2" style={{ color: INK }}>{children}</h2>;
}

// ── CatalogView.tsx ───────────────────────────────────────────────────────────
// Operator catalogue — a READ-ONLY view of the live Bethany House hub catalogue
// (the same source Neema's AI sells from). Products, prices and stock are
// maintained in the hub, shared across POS, the website and this WhatsApp agent,
// so what an operator sees here is exactly what the agent quotes. Nothing is
// edited from Neema; the hub is the single source of truth.
import React, { useState } from "react";
import { fmtCurrency } from "@/lib/utils";
import type { CatalogItem, SharedViewProps } from "@/types";

const catEmoji: Record<string, string> = {
    "Anointing Oil": "🕯️",
    "Communion Wafers": "🍞",
    "Communion Cups": "🥛",
    "Prefilled Cups": "🍷",
    "Communion Wine": "🍾",
    "Communion Trays": "🫙",
    "Communion Accessories": "🧴",
    "Clergy Apparel": "👕",
    "Clergy Vestments": "👘",
    anointing: "🕯️",
    communion: "🍷",
    vestments: "👘",
    trays: "🫙",
    wine: "🍾",
    apparel: "👕",
};

const catColors: Record<string, string> = {
    "Anointing Oil": "from-amber-50 to-yellow-50",
    "Communion Wafers": "from-orange-50 to-amber-50",
    "Communion Cups": "from-sky-50 to-blue-50",
    "Prefilled Cups": "from-red-50 to-rose-50",
    "Communion Wine": "from-red-50 to-pink-50",
    "Communion Trays": "from-stone-50 to-slate-50",
    "Communion Accessories": "from-teal-50 to-cyan-50",
    "Clergy Apparel": "from-blue-50 to-indigo-50",
    "Clergy Vestments": "from-purple-50 to-violet-50",
    anointing: "from-amber-50 to-yellow-50",
    communion: "from-red-50 to-rose-50",
    vestments: "from-purple-50 to-violet-50",
    trays: "from-stone-50 to-slate-50",
    wine: "from-red-50 to-pink-50",
    apparel: "from-blue-50 to-indigo-50",
};

interface CatalogViewProps extends SharedViewProps {
    catalog: CatalogItem[];
    // Kept for prop-compatibility with the dashboard; unused (read-only view).
    setCatalog?: React.Dispatch<React.SetStateAction<CatalogItem[]>>;
    refetchCatalog?: () => void;
}

// ── CatalogView (read-only operator view) ─────────────────────────────────────

export function CatalogView({
    catalog,
    isMobile,
}: CatalogViewProps): React.ReactElement {
    const [filter, setFilter] = useState("all");
    const [search, setSearch] = useState("");

    const categories = Array.from(
        new Set(catalog.map((c) => c.category).filter(Boolean)),
    );

    const filtered = catalog.filter(
        (c) =>
            (filter === "all" || c.category === filter) &&
            (!search ||
                c.name.toLowerCase().includes(search.toLowerCase()) ||
                (c.sku ?? "").toLowerCase().includes(search.toLowerCase()) ||
                (c.aliases ?? []).some((a) =>
                    a.toLowerCase().includes(search.toLowerCase()),
                )),
    );

    const inStockCount = catalog.filter((c) => c.in_stock).length;
    const outStockCount = catalog.filter((c) => !c.in_stock).length;

    return (
        <div
            className={`flex-1 overflow-y-auto bg-[#f3f9ec] ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            {/* Header */}
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h1 className="text-xl font-bold text-[#16270c] tracking-tight">
                        Catalog
                    </h1>
                    <p className="text-sm text-[#9ccd65] mt-0.5">
                        {catalog.length} items
                        <span className="mx-1.5 text-stone-200">·</span>
                        <span className="text-emerald-600">
                            {inStockCount} in stock
                        </span>
                        {outStockCount > 0 && (
                            <>
                                <span className="mx-1.5 text-stone-200">·</span>
                                <span className="text-red-500">
                                    {outStockCount} out of stock
                                </span>
                            </>
                        )}
                    </p>
                </div>
            </div>

            {/* Source banner — this is the hub's live catalogue, maintained there */}
            <div className="flex items-start gap-2.5 mb-5 px-3.5 py-2.5 rounded-xl bg-[#eaf5dd] border border-[#cee6b2]">
                <svg
                    className="w-4 h-4 text-[#427425] mt-0.5 flex-shrink-0"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                </svg>
                <p className="text-xs text-[#427425] leading-relaxed">
                    <span className="font-semibold">
                        Live from the Bethany House hub.
                    </span>{" "}
                    Prices and stock are maintained in the hub and shared with
                    the POS and website — this is exactly what Neema quotes to
                    customers. To change a product, edit it in the hub.
                </p>
            </div>

            {/* Search + category dropdown */}
            <div className="flex flex-col sm:flex-row gap-2 mb-5">
                <div className="relative flex-1">
                    <svg
                        className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#b5da8b]"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                    >
                        <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                        />
                    </svg>
                    <input
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder="Search name, SKU or alias…"
                        className="w-full h-10 pl-9 pr-3 text-sm bg-white border border-[#cee6b2] rounded-xl text-[#16270c] placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-[#589b31] focus:border-transparent transition-all"
                        style={{ fontSize: 16 }}
                    />
                </div>

                {/* Category dropdown */}
                <div className="relative">
                    <select
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                        className="h-10 pl-3 pr-8 text-sm bg-white border border-[#cee6b2] rounded-xl text-[#16270c] font-medium focus:outline-none focus:ring-2 focus:ring-[#589b31] focus:border-transparent appearance-none cursor-pointer min-w-[160px]"
                    >
                        <option value="all">All categories</option>
                        {categories.map((cat) => (
                            <option key={cat} value={cat}>
                                {catEmoji[cat] ?? "📦"} {cat}
                            </option>
                        ))}
                    </select>
                    <svg
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9ccd65] pointer-events-none"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                    >
                        <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 9l-7 7-7-7"
                        />
                    </svg>
                </div>
            </div>

            {/* Grid — read-only product cards */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                {filtered.map((item) => {
                    const gradient =
                        catColors[item.category ?? ""] ??
                        "from-stone-50 to-stone-100";
                    const qty = item.available_qty;
                    return (
                        <div
                            key={item.id}
                            className={`bg-white rounded-xl border border-[#e6f3d8] overflow-hidden shadow-sm transition-all duration-200 ${!item.in_stock ? "opacity-60" : ""}`}
                        >
                            <div
                                className={`h-20 bg-gradient-to-br ${gradient} flex items-center justify-center text-3xl`}
                            >
                                {catEmoji[item.category ?? ""] ?? "📦"}
                            </div>
                            <div className="p-3">
                                <div className="flex items-start justify-between gap-1 mb-1">
                                    <span className="text-xs font-semibold text-[#16270c] leading-tight">
                                        {item.name}
                                    </span>
                                    {item.in_stock ? (
                                        <span className="flex-shrink-0 text-[10px] bg-emerald-50 text-emerald-600 border border-emerald-200 px-1.5 py-0.5 rounded font-semibold">
                                            {typeof qty === "number"
                                                ? `${qty} left`
                                                : "IN"}
                                        </span>
                                    ) : (
                                        <span className="flex-shrink-0 text-[10px] bg-red-50 text-red-500 border border-red-200 px-1.5 py-0.5 rounded font-semibold">
                                            OUT
                                        </span>
                                    )}
                                </div>
                                {item.description && (
                                    <p className="text-xs text-[#9ccd65] mb-2 leading-snug line-clamp-2">
                                        {item.description}
                                    </p>
                                )}
                                <div className="text-sm font-bold text-[#2c4e18]">
                                    {fmtCurrency(item.price)}
                                </div>
                                {(item.aliases ?? []).length > 0 && (
                                    <div className="flex flex-wrap gap-1 mt-2">
                                        {(item.aliases ?? [])
                                            .slice(0, 3)
                                            .map((a) => (
                                                <span
                                                    key={a}
                                                    className="text-[10px] text-[#699a32] bg-[#f3f9ec] border border-[#e6f3d8] px-1.5 py-0.5 rounded"
                                                >
                                                    {a}
                                                </span>
                                            ))}
                                    </div>
                                )}
                                <div className="flex items-center justify-between mt-2">
                                    <span className="text-[10px] text-[#b5da8b] font-mono">
                                        {item.sku}
                                    </span>
                                    {item.hub_product_id != null && (
                                        <span className="text-[10px] text-[#b5da8b] font-mono">
                                            #{item.hub_product_id}
                                        </span>
                                    )}
                                </div>
                            </div>
                        </div>
                    );
                })}
                {filtered.length === 0 && (
                    <div className="col-span-full py-16 text-center">
                        <span className="text-3xl mb-3 block">📦</span>
                        <p className="text-sm text-[#9ccd65]">No items found</p>
                    </div>
                )}
            </div>
        </div>
    );
}

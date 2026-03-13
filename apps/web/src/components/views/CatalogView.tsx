import React, { useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { InputField } from "@/components/ui/FormFields";
import { fmtCurrency } from "@/lib/utils";
import type { CatalogItem, SharedViewProps } from "@/types";

const catEmoji: Record<string, string> = {
    Mains: "🍛",
    Sides: "🌽",
    Snacks: "🍩",
};
const catColors: Record<string, string> = {
    Mains: "from-orange-50 to-green-50",
    Sides: "from-green-50 to-emerald-50",
    Snacks: "from-pink-50 to-rose-50",
};

interface CatalogViewProps extends SharedViewProps {
    catalog: CatalogItem[];
    setCatalog: React.Dispatch<React.SetStateAction<CatalogItem[]>>;
}

const EMPTY = {
    sku: "",
    name: "",
    category: "",
    price: "",
    in_stock: true,
    description: "",
};

export function CatalogView({
    catalog,
    setCatalog,
    onToast,
    isMobile,
}: CatalogViewProps): React.ReactElement {
    const [modal, setModal] = useState(false);
    const [form, setForm] = useState({ ...EMPTY });
    const [filter, setFilter] = useState("all");
    const [search, setSearch] = useState("");

    const categories = [
        "all",
        ...Array.from(new Set(catalog.map((c) => c.category))),
    ];
    const filtered = catalog.filter(
        (c) =>
            (filter === "all" || c.category === filter) &&
            (!search || c.name.toLowerCase().includes(search.toLowerCase())),
    );

    const createItem = () => {
        setCatalog((cs) => [
            ...cs,
            {
                id: `cat${Date.now()}`,
                ...form,
                price: parseInt(form.price, 10) || 0,
            },
        ]);
        setModal(false);
        setForm({ ...EMPTY });
        onToast("Item added to catalog");
    };
    const toggleStock = (id: string) => {
        setCatalog((cs) =>
            cs.map((c) => (c.id === id ? { ...c, in_stock: !c.in_stock } : c)),
        );
        onToast("Stock status updated");
    };
    const deleteItem = (id: string) => {
        setCatalog((cs) => cs.filter((c) => c.id !== id));
        onToast("Item removed", "error");
    };

    const inStockCount = catalog.filter((c) => c.in_stock).length;
    const outStockCount = catalog.filter((c) => !c.in_stock).length;

    return (
        <div
            className={`flex-1 overflow-y-auto bg-stone-50 ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-xl font-bold text-stone-800 tracking-tight">
                        Catalog
                    </h1>
                    <p className="text-sm text-stone-400 mt-0.5">
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
                <button
                    onClick={() => setModal(true)}
                    className="flex items-center gap-2 h-9 px-4 rounded-lg bg-green-700 hover:bg-green-600 text-white text-sm font-semibold transition-colors shadow-sm"
                >
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
                            d="M12 4v16m8-8H4"
                        />
                    </svg>
                    Add Item
                </button>
            </div>

            {/* Search + category filters */}
            <div className="flex flex-col sm:flex-row gap-2 mb-5">
                <div className="relative flex-1">
                    <svg
                        className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-stone-300"
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
                        placeholder="Search items…"
                        className="w-full h-10 pl-9 pr-3 text-sm bg-white border border-stone-200 rounded-xl text-stone-800 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-green-600 focus:border-transparent transition-all"
                        style={{ fontSize: 16 }}
                    />
                </div>
                <div className="flex gap-1.5 flex-wrap">
                    {categories.map((cat) => (
                        <button
                            key={cat}
                            onClick={() => setFilter(cat)}
                            className={`px-3 h-10 rounded-xl border text-xs font-medium capitalize transition-all ${filter === cat ? "bg-stone-800 text-white border-stone-800" : "bg-white text-stone-500 border-stone-200 hover:border-stone-400"}`}
                        >
                            {cat === "all"
                                ? "All"
                                : `${catEmoji[cat] ?? "🍽"} ${cat}`}
                        </button>
                    ))}
                </div>
            </div>

            {/* Product grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                {filtered.map((item) => {
                    const gradient =
                        catColors[item.category] ??
                        "from-stone-50 to-stone-100";
                    return (
                        <div
                            key={item.id}
                            className={`group bg-white rounded-xl border border-stone-100 overflow-hidden shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 ${!item.in_stock ? "opacity-60" : ""}`}
                        >
                            {/* Thumbnail */}
                            <div
                                className={`h-20 bg-gradient-to-br ${gradient} flex items-center justify-center text-3xl`}
                            >
                                {catEmoji[item.category] ?? "🍽"}
                            </div>

                            <div className="p-3">
                                <div className="flex items-start justify-between gap-1 mb-1">
                                    <span className="text-sm font-semibold text-stone-800 leading-tight">
                                        {item.name}
                                    </span>
                                    {!item.in_stock && (
                                        <span className="flex-shrink-0 text-[10px] bg-red-50 text-red-500 border border-red-200 px-1.5 py-0.5 rounded font-semibold">
                                            OUT
                                        </span>
                                    )}
                                </div>
                                <p className="text-xs text-stone-400 mb-2.5 leading-snug line-clamp-2">
                                    {item.description}
                                </p>
                                <div className="text-sm font-bold text-green-800 mb-3">
                                    {fmtCurrency(item.price)}
                                </div>

                                <div className="flex items-center gap-1.5">
                                    <button
                                        onClick={() => toggleStock(item.id)}
                                        className={`flex-1 h-7 rounded-md text-xs font-medium transition-colors ${
                                            item.in_stock
                                                ? "bg-stone-100 text-stone-600 hover:bg-stone-200"
                                                : "bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100"
                                        }`}
                                    >
                                        {item.in_stock
                                            ? "Mark Out"
                                            : "In Stock"}
                                    </button>
                                    <button
                                        onClick={() => deleteItem(item.id)}
                                        className="w-7 h-7 rounded-md bg-red-50 text-red-500 hover:bg-red-100 transition-colors flex items-center justify-center border border-red-100"
                                    >
                                        <svg
                                            className="w-3.5 h-3.5"
                                            fill="none"
                                            stroke="currentColor"
                                            viewBox="0 0 24 24"
                                        >
                                            <path
                                                strokeLinecap="round"
                                                strokeLinejoin="round"
                                                strokeWidth={2}
                                                d="M6 18L18 6M6 6l12 12"
                                            />
                                        </svg>
                                    </button>
                                </div>

                                <div className="text-[10px] text-stone-300 font-mono mt-2">
                                    {item.sku}
                                </div>
                            </div>
                        </div>
                    );
                })}

                {filtered.length === 0 && (
                    <div className="col-span-full py-16 text-center">
                        <span className="text-3xl mb-3 block">🍽</span>
                        <p className="text-sm text-stone-400">No items found</p>
                    </div>
                )}
            </div>

            {/* Add item modal */}
            <Modal
                show={modal}
                onClose={() => setModal(false)}
                title="Add Catalog Item"
            >
                <InputField
                    label="SKU"
                    value={form.sku}
                    onChange={(v) => setForm((f) => ({ ...f, sku: v }))}
                    placeholder="JRC-001"
                />
                <InputField
                    label="Name"
                    value={form.name}
                    onChange={(v) => setForm((f) => ({ ...f, name: v }))}
                    placeholder="Jollof Rice Combo"
                    required
                />
                <InputField
                    label="Category"
                    value={form.category}
                    onChange={(v) => setForm((f) => ({ ...f, category: v }))}
                    placeholder="Mains"
                />
                <InputField
                    label="Price (KES)"
                    value={form.price}
                    onChange={(v) => setForm((f) => ({ ...f, price: v }))}
                    type="number"
                    placeholder="400"
                    required
                />
                <InputField
                    label="Description"
                    value={form.description}
                    onChange={(v) => setForm((f) => ({ ...f, description: v }))}
                    placeholder="Short product description"
                />
                <div className="flex gap-2">
                    <Btn onClick={createItem} variant="primary">
                        Add Item
                    </Btn>
                    <Btn onClick={() => setModal(false)} variant="outline">
                        Cancel
                    </Btn>
                </div>
            </Modal>
        </div>
    );
}
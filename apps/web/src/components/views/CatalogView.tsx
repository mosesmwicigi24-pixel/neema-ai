import React, { useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { SectionHeader } from "@/components/ui/Layout";
import { Modal } from "@/components/ui/Modal";
import { InputField } from "@/components/ui/FormFields";
import { fmtCurrency } from "@/lib/utils";
import type { CatalogItem, SharedViewProps } from "@/types";

const catEmoji: Record<string, string> = {
    Mains: "🍛",
    Sides: "🌽",
    Snacks: "🍩",
};

interface CatalogViewProps extends SharedViewProps {
    catalog: CatalogItem[];
    setCatalog: React.Dispatch<React.SetStateAction<CatalogItem[]>>;
}

const EMPTY: {
    sku: string;
    name: string;
    category: string;
    price: string;
    in_stock: boolean;
    description: string;
} = {
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

    return (
        <div
            className={`flex-1 overflow-y-auto ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            <SectionHeader
                title="Menu Catalog"
                subtitle={`${catalog.length} items · ${catalog.filter((c) => !c.in_stock).length} out of stock`}
                action={
                    <Btn
                        onClick={() => setModal(true)}
                        variant="primary"
                        size="sm"
                    >
                        + Add Item
                    </Btn>
                }
            />

            {/* Search + category filters */}
            <div className="flex flex-col sm:flex-row gap-2 mb-5">
                <div className="relative flex-1">
                    <svg
                        className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
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
                        className="w-full h-10 pl-9 pr-3 text-sm bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-xl text-gray-900 dark:text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-500"
                        style={{ fontSize: 16 }}
                    />
                </div>
                <div className="flex gap-1.5 flex-wrap">
                    {categories.map((cat) => (
                        <button
                            key={cat}
                            onClick={() => setFilter(cat)}
                            className={`px-3 h-10 rounded-xl border text-xs font-medium capitalize transition-all ${
                                filter === cat
                                    ? "bg-gray-900 dark:bg-white text-white dark:text-gray-900 border-transparent"
                                    : "bg-white dark:bg-gray-900 text-gray-500 dark:text-gray-400 border-gray-200 dark:border-gray-800 hover:border-gray-400"
                            }`}
                        >
                            {cat}
                        </button>
                    ))}
                </div>
            </div>

            {/* Product grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                {filtered.map((item) => (
                    <div
                        key={item.id}
                        className={`group bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden shadow-sm hover:shadow-md transition-shadow ${!item.in_stock ? "opacity-60" : ""}`}
                    >
                        {/* Header */}
                        <div className="h-20 bg-gradient-to-br from-amber-50 to-orange-50 dark:from-amber-950/20 dark:to-orange-950/20 flex items-center justify-center text-3xl">
                            {catEmoji[item.category] ?? "🍽"}
                        </div>
                        <div className="p-3">
                            <div className="flex items-start justify-between gap-1 mb-1">
                                <span className="text-sm font-semibold text-gray-900 dark:text-white leading-tight">
                                    {item.name}
                                </span>
                                {!item.in_stock && (
                                    <span className="flex-shrink-0 text-[10px] bg-red-50 dark:bg-red-950/40 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800 px-1.5 py-0.5 rounded font-medium">
                                        OUT
                                    </span>
                                )}
                            </div>
                            <p className="text-xs text-gray-400 dark:text-gray-500 mb-2 leading-snug line-clamp-2">
                                {item.description}
                            </p>
                            <div className="text-base font-bold text-amber-600 dark:text-amber-400 mb-3">
                                {fmtCurrency(item.price)}
                            </div>
                            <div className="flex items-center gap-1.5">
                                <Btn
                                    size="xs"
                                    onClick={() => toggleStock(item.id)}
                                    variant={
                                        item.in_stock ? "outline" : "success"
                                    }
                                    className="flex-1"
                                >
                                    {item.in_stock
                                        ? "Out of Stock"
                                        : "In Stock"}
                                </Btn>
                                <Btn
                                    size="xs"
                                    onClick={() => deleteItem(item.id)}
                                    variant="danger"
                                >
                                    <svg
                                        className="w-3 h-3"
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
                                </Btn>
                            </div>
                            <div className="text-[10px] text-gray-300 dark:text-gray-600 font-mono mt-2">
                                {item.sku}
                            </div>
                        </div>
                    </div>
                ))}
            </div>

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

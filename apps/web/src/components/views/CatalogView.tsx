// ── CatalogView.tsx ───────────────────────────────────────────────────────────
import React, { useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { InputField } from "@/components/ui/FormFields";
import { fmtCurrency } from "@/lib/utils";
import { catalogApi } from "@/lib/api";
import type { CatalogItem, SharedViewProps } from "@/types";

const catEmoji: Record<string, string> = {
    "Anointing Oil":       "🕯️",
    "Communion Wafers":    "🍞",
    "Communion Cups":      "🥛",
    "Prefilled Cups":      "🍷",
    "Communion Wine":      "🍾",
    "Communion Trays":     "🫙",
    "Communion Accessories": "🧴",
    "Clergy Apparel":      "👕",
    "Clergy Vestments":    "👘",
    anointing:  "🕯️",
    communion:  "🍷",
    vestments:  "👘",
    trays:      "🫙",
    wine:       "🍾",
    apparel:    "👕",
};

const catColors: Record<string, string> = {
    "Anointing Oil":       "from-amber-50 to-yellow-50",
    "Communion Wafers":    "from-orange-50 to-amber-50",
    "Communion Cups":      "from-sky-50 to-blue-50",
    "Prefilled Cups":      "from-red-50 to-rose-50",
    "Communion Wine":      "from-red-50 to-pink-50",
    "Communion Trays":     "from-stone-50 to-slate-50",
    "Communion Accessories": "from-teal-50 to-cyan-50",
    "Clergy Apparel":      "from-blue-50 to-indigo-50",
    "Clergy Vestments":    "from-purple-50 to-violet-50",
    anointing:  "from-amber-50 to-yellow-50",
    communion:  "from-red-50 to-rose-50",
    vestments:  "from-purple-50 to-violet-50",
    trays:      "from-stone-50 to-slate-50",
    wine:       "from-red-50 to-pink-50",
    apparel:    "from-blue-50 to-indigo-50",
};

interface CatalogViewProps extends SharedViewProps {
    catalog: CatalogItem[];
    setCatalog: React.Dispatch<React.SetStateAction<CatalogItem[]>>;
    refetchCatalog?: () => void;
}

const EMPTY_FORM = {
    sku: "", name: "", category: "", price: "",
    in_stock: true, description: "", aliases: "",
};

type FormState = typeof EMPTY_FORM;

// ── CatalogForm (moved outside CatalogView to preserve stable identity) ───────

interface CatalogFormProps {
    form: FormState;
    f: (key: keyof FormState, v: string | boolean) => void;
    categories: string[];
}

function CatalogForm({ form, f, categories }: CatalogFormProps) {
    return (
        <>
            <div className="grid grid-cols-2 gap-3 mb-1">
                <InputField
                    label="SKU"
                    value={form.sku}
                    onChange={(v) => f("sku", v)}
                    placeholder="WAFER-500"
                />
                <div>
                    <label className="block text-xs font-semibold text-[#427425] mb-1.5">
                        Category
                    </label>
                    <select
                        value={form.category}
                        onChange={(e) => f("category", e.target.value)}
                        className="w-full h-9 px-2.5 text-sm bg-white border border-[#cee6b2] rounded-lg text-[#16270c] focus:outline-none focus:ring-2 focus:ring-[#589b31] focus:border-transparent"
                    >
                        <option value="">— select —</option>
                        {categories.map((cat) => (
                            <option key={cat} value={cat}>{cat}</option>
                        ))}
                        <option value="__new__">+ New category…</option>
                    </select>
                    {form.category === "__new__" && (
                        <input
                            className="mt-1.5 w-full h-9 px-2.5 text-sm bg-white border border-[#cee6b2] rounded-lg text-[#16270c] focus:outline-none focus:ring-2 focus:ring-[#589b31]"
                            placeholder="New category name"
                            autoFocus
                            onChange={(e) => f("category", e.target.value)}
                        />
                    )}
                </div>
            </div>
            <InputField
                label="Name *"
                value={form.name}
                onChange={(v) => f("name", v)}
                placeholder="Holy Communion Wafers (500 pcs)"
                required
            />
            <div className="grid grid-cols-2 gap-3">
                <InputField
                    label="Price (KES) *"
                    value={form.price}
                    onChange={(v) => f("price", v)}
                    type="number"
                    placeholder="850"
                    required
                />
                <div className="flex flex-col justify-end pb-0.5">
                    <label className="flex items-center gap-2 cursor-pointer">
                        <div
                            onClick={() => f("in_stock", !form.in_stock)}
                            className={`w-9 h-5 rounded-full transition-colors flex-shrink-0 ${form.in_stock ? "bg-[#589b31]" : "bg-stone-300"}`}
                        >
                            <div className={`w-4 h-4 rounded-full bg-white shadow mt-0.5 transition-transform ${form.in_stock ? "translate-x-4.5 ml-4" : "ml-0.5"}`} />
                        </div>
                        <span className="text-xs text-[#427425] font-medium">In stock</span>
                    </label>
                </div>
            </div>
            <InputField
                label="Description"
                value={form.description}
                onChange={(v) => f("description", v)}
                placeholder="Short product description"
            />
            <InputField
                label="Aliases (comma-separated)"
                value={form.aliases}
                onChange={(v) => f("aliases", v)}
                placeholder="wafers, hosts, eucharist wafers"
            />
        </>
    );
}

// ── CatalogView ───────────────────────────────────────────────────────────────

export function CatalogView({
    catalog,
    setCatalog,
    onToast,
    isMobile,
    refetchCatalog,
}: CatalogViewProps): React.ReactElement {
    const [addModal,  setAddModal]  = useState(false);
    const [editModal, setEditModal] = useState(false);
    const [delModal,  setDelModal]  = useState(false);
    const [saving,    setSaving]    = useState(false);
    const [deleting,  setDeleting]  = useState(false);
    const [form,      setForm]      = useState<FormState>({ ...EMPTY_FORM });
    const [editItem,  setEditItem]  = useState<CatalogItem | null>(null);
    const [delItem,   setDelItem]   = useState<CatalogItem | null>(null);
    const [filter,    setFilter]    = useState("all");
    const [search,    setSearch]    = useState("");

    const categories = Array.from(new Set(catalog.map((c) => c.category).filter(Boolean)));

    const filtered = catalog.filter(
        (c) =>
            (filter === "all" || c.category === filter) &&
            (!search || c.name.toLowerCase().includes(search.toLowerCase())),
    );

    const f = (key: keyof FormState, v: string | boolean) =>
        setForm((prev) => ({ ...prev, [key]: v }));

    // ── Create ────────────────────────────────────────────────────────────────

    const createItem = async () => {
        if (!form.name || !form.price) {
            onToast("Name and price are required", "error");
            return;
        }
        setSaving(true);
        try {
            await catalogApi.create({
                sku:         form.sku,
                name:        form.name,
                category:    form.category,
                price:       parseFloat(form.price) || 0,
                description: form.description,
                in_stock:    form.in_stock,
                aliases:     form.aliases
                    ? form.aliases.split(",").map((a) => a.trim()).filter(Boolean)
                    : [],
            });
            refetchCatalog?.();
            setAddModal(false);
            setForm({ ...EMPTY_FORM });
            onToast("Item added to catalog");
        } catch (e: any) {
            onToast(e.message ?? "Failed to add item", "error");
        } finally {
            setSaving(false);
        }
    };

    // ── Edit ──────────────────────────────────────────────────────────────────

    const openEdit = (item: CatalogItem) => {
        setEditItem(item);
        setForm({
            sku:         item.sku,
            name:        item.name,
            category:    item.category ?? "",
            price:       String(item.price),
            in_stock:    item.in_stock,
            description: item.description ?? "",
            aliases:     (item.aliases ?? []).join(", "),
        });
        setEditModal(true);
    };

    const saveEdit = async () => {
        if (!editItem) return;
        if (!form.name || !form.price) {
            onToast("Name and price are required", "error");
            return;
        }
        setSaving(true);
        try {
            await catalogApi.update(editItem.id, {
                sku:         form.sku,
                name:        form.name,
                category:    form.category,
                price:       parseFloat(form.price) || 0,
                description: form.description,
                in_stock:    form.in_stock,
                aliases:     form.aliases
                    ? form.aliases.split(",").map((a) => a.trim()).filter(Boolean)
                    : [],
            });
            refetchCatalog?.();
            setEditModal(false);
            setEditItem(null);
            setForm({ ...EMPTY_FORM });
            onToast("Item updated");
        } catch (e: any) {
            onToast(e.message ?? "Failed to update item", "error");
        } finally {
            setSaving(false);
        }
    };

    // ── Stock toggle ──────────────────────────────────────────────────────────

    const toggleStock = async (id: string, current: boolean) => {
        try {
            await catalogApi.toggleStock(id, !current);
            refetchCatalog?.();
            onToast(current ? "Marked out of stock" : "Marked in stock");
        } catch {
            onToast("Failed to update stock", "error");
        }
    };

    // ── Delete ────────────────────────────────────────────────────────────────

    const openDelete = (item: CatalogItem) => {
        setDelItem(item);
        setDelModal(true);
    };

    const confirmDelete = async () => {
        if (!delItem) return;
        setDeleting(true);
        try {
            await catalogApi.delete(delItem.id);
            refetchCatalog?.();
            setDelModal(false);
            setDelItem(null);
            onToast("Item removed");
        } catch {
            onToast("Failed to remove item", "error");
        } finally {
            setDeleting(false);
        }
    };

    const inStockCount  = catalog.filter((c) => c.in_stock).length;
    const outStockCount = catalog.filter((c) => !c.in_stock).length;

    return (
        <div className={`flex-1 overflow-y-auto bg-[#f3f9ec] ${isMobile ? "p-4 pb-24" : "p-6"}`}>

            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-xl font-bold text-[#16270c] tracking-tight">Catalog</h1>
                    <p className="text-sm text-[#9ccd65] mt-0.5">
                        {catalog.length} items
                        <span className="mx-1.5 text-stone-200">·</span>
                        <span className="text-emerald-600">{inStockCount} in stock</span>
                        {outStockCount > 0 && (
                            <>
                                <span className="mx-1.5 text-stone-200">·</span>
                                <span className="text-red-500">{outStockCount} out of stock</span>
                            </>
                        )}
                    </p>
                </div>
                <button
                    onClick={() => { setForm({ ...EMPTY_FORM }); setAddModal(true); }}
                    className="flex items-center gap-2 h-9 px-4 rounded-lg bg-[#427425] hover:bg-[#589b31] text-white text-sm font-semibold transition-colors shadow-sm"
                >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                    </svg>
                    Add Item
                </button>
            </div>

            {/* Search + category dropdown */}
            <div className="flex flex-col sm:flex-row gap-2 mb-5">
                <div className="relative flex-1">
                    <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#b5da8b]"
                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                    <input
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder="Search items…"
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
                    <svg className="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9ccd65] pointer-events-none"
                        fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                </div>
            </div>

            {/* Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
                {filtered.map((item) => {
                    const gradient = catColors[item.category ?? ""] ?? "from-stone-50 to-stone-100";
                    return (
                        <div
                            key={item.id}
                            className={`group bg-white rounded-xl border border-[#e6f3d8] overflow-hidden shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 ${!item.in_stock ? "opacity-60" : ""}`}
                        >
                            <div className={`h-20 bg-gradient-to-br ${gradient} flex items-center justify-center text-3xl`}>
                                {catEmoji[item.category ?? ""] ?? "📦"}
                            </div>
                            <div className="p-3">
                                <div className="flex items-start justify-between gap-1 mb-1">
                                    <span className="text-xs font-semibold text-[#16270c] leading-tight">
                                        {item.name}
                                    </span>
                                    {!item.in_stock && (
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
                                <div className="text-sm font-bold text-[#2c4e18] mb-2.5">
                                    {fmtCurrency(item.price)}
                                </div>
                                {/* Actions */}
                                <div className="flex items-center gap-1">
                                    {/* Stock toggle */}
                                    <button
                                        onClick={() => toggleStock(item.id, item.in_stock)}
                                        className={`flex-1 h-7 rounded-md text-xs font-medium transition-colors ${
                                            item.in_stock
                                                ? "bg-[#e6f3d8] text-[#427425] hover:bg-[#cee6b2]"
                                                : "bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100"
                                        }`}
                                    >
                                        {item.in_stock ? "Out of stock" : "In Stock"}
                                    </button>
                                    {/* Edit */}
                                    <button
                                        onClick={() => openEdit(item)}
                                        title="Edit"
                                        className="w-7 h-7 rounded-md bg-[#f3f9ec] text-[#699a32] hover:bg-[#e6f3d8] hover:text-[#16270c] transition-colors flex items-center justify-center border border-[#cee6b2]"
                                    >
                                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                        </svg>
                                    </button>
                                    {/* Delete */}
                                    <button
                                        onClick={() => openDelete(item)}
                                        title="Delete"
                                        className="w-7 h-7 rounded-md bg-red-50 text-red-500 hover:bg-red-100 transition-colors flex items-center justify-center border border-red-100"
                                    >
                                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                        </svg>
                                    </button>
                                </div>
                                <div className="text-[10px] text-[#b5da8b] font-mono mt-2">{item.sku}</div>
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

            {/* ── Add modal ─────────────────────────────────────────────────── */}
            <Modal show={addModal} onClose={() => setAddModal(false)} title="Add Catalog Item">
                <CatalogForm form={form} f={f} categories={categories} />
                <div className="flex gap-2 mt-4">
                    <Btn onClick={createItem} variant="primary" disabled={saving} full>
                        {saving ? "Adding…" : "Add Item"}
                    </Btn>
                    <Btn onClick={() => setAddModal(false)} variant="outline">Cancel</Btn>
                </div>
            </Modal>

            {/* ── Edit modal ────────────────────────────────────────────────── */}
            <Modal show={editModal} onClose={() => setEditModal(false)}
                title={`Edit — ${editItem?.name ?? ""}`}>
                <CatalogForm form={form} f={f} categories={categories} />
                <div className="flex gap-2 mt-4">
                    <Btn onClick={saveEdit} variant="primary" disabled={saving} full>
                        {saving ? "Saving…" : "Save Changes"}
                    </Btn>
                    <Btn onClick={() => setEditModal(false)} variant="outline">Cancel</Btn>
                </div>
            </Modal>

            {/* ── Delete confirm modal ──────────────────────────────────────── */}
            <Modal show={delModal} onClose={() => setDelModal(false)} title="Remove Item">
                <p className="text-sm text-[#427425] mb-1">
                    Are you sure you want to remove{" "}
                    <span className="font-semibold text-[#16270c]">{delItem?.name}</span>?
                </p>
                <p className="text-xs text-[#9ccd65] mb-5">This action cannot be undone.</p>
                <div className="flex gap-2">
                    <Btn onClick={confirmDelete} variant="danger" disabled={deleting} full>
                        {deleting ? "Removing…" : "Remove"}
                    </Btn>
                    <Btn onClick={() => setDelModal(false)} variant="outline">Cancel</Btn>
                </div>
            </Modal>
        </div>
    );
}
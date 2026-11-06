// PerformanceView.tsx
// The executive performance dashboard: one call to GET /api/admin/performance.
// Every figure says whether it is measured, partial or not yet measured, and
// nothing here is estimated — a metric the API has not measured shows
// "NOT YET MEASURED" and what it needs, never a number.

import React, { useEffect, useState } from "react";
import { apiErrorDetail, getPerformance } from "@/lib/api";
import type { ApiEvalRun, ApiPerformance, ApiPerformanceMetric } from "@/lib/api";
import type { SharedViewProps } from "@/types";

type PerformanceViewProps = SharedViewProps;

type WindowDays = 7 | 30;

// Groups render in this order; a key the API adds later lands in "Other".
const GROUPS: { title: string; keys: string[] }[] = [
    {
        title: "Intelligence (from the case-set evaluation)",
        keys: [
            "intent_next_action", "critical_safety", "language_continuity", "figures_verified",
            "emotional_appropriateness", "consultative_judgment", "autonomous_task_completion",
            "onboarding_success",
        ],
    },
    {
        title: "Service",
        keys: [
            "first_response_neema", "first_response_human", "resolution", "customer_rating",
            "human_intervention", "avoidable_escalation", "first_draft_pass_today",
            "pricing_quote_payment_accuracy",
        ],
    },
    {
        title: "Commercial",
        keys: [
            "verified_paid_conversion", "paid_orders_per_active_conversation", "revenue_paid",
            "revenue_placed_unpaid", "sales_autonomous", "sales_assisted", "sales_human_only",
            "follow_up_reply_rate", "follow_up_convert_rate", "opt_outs",
        ],
    },
    {
        title: "Cost and availability",
        keys: ["model_cost", "turn_latency", "availability_now", "availability_history"],
    },
];

// ── Formatting ────────────────────────────────────────────────────────────────

function fmtNum(v: number, decimals?: number): string {
    const d = decimals ?? (Number.isInteger(v) ? 0 : v < 10 ? 2 : 1);
    return v.toLocaleString("en-KE", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/** A value in the metric's unit. Proportions are percentages with one decimal;
 *  seconds and minutes carry their unit word; anything else shows the unit as given. */
function fmtValue(v: number | null, unit: string): string {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    if (unit === "proportion") return `${(v * 100).toFixed(1)}%`;
    if (unit === "seconds") return `${fmtNum(v, 1)} s`;
    if (unit === "minutes") return `${fmtNum(v, 1)} min`;
    if (unit === "USD") return `$${fmtNum(v, 2)}`;
    return unit ? `${fmtNum(v)} ${unit}` : fmtNum(v);
}

function fmtCi(ci: [number, number] | null, unit: string): string | null {
    if (!ci || ci.length !== 2) return null;
    const [lo, hi] = ci;
    if (unit === "proportion") return `${(lo * 100).toFixed(1)}–${(hi * 100).toFixed(1)}%`;
    return `${fmtValue(lo, unit)} – ${fmtValue(hi, unit)}`;
}

function fmtP(m: { p: number | null; ci95: [number, number] | null } | undefined, withCi = false): string {
    if (!m || m.p === null || m.p === undefined) return "—";
    const p = `${(m.p * 100).toFixed(1)}%`;
    if (!withCi || !m.ci95) return p;
    return `${p} (${(m.ci95[0] * 100).toFixed(1)}–${(m.ci95[1] * 100).toFixed(1)})`;
}

function shortDate(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10) || "—";
    return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

const TREND_ARROW: Record<NonNullable<ApiPerformanceMetric["trend"]>, string> = {
    up: "↑", down: "↓", flat: "→",
};

// ── Pieces ────────────────────────────────────────────────────────────────────

function StatusChip({ status }: { status: ApiPerformanceMetric["status"] }) {
    if (status === "measured") {
        return (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-[#f0f9ec] text-[#427425] border border-[#b5da8b]">
                Measured
            </span>
        );
    }
    if (status === "partial") {
        return (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-amber-50 text-amber-700 border border-amber-200">
                Partial
            </span>
        );
    }
    return (
        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-stone-100 text-stone-500 border border-stone-200">
            Not measured
        </span>
    );
}

function MetricCard({ metric }: { metric: ApiPerformanceMetric }) {
    const { status, label, value, unit, n, ci95, basis, caveat, instrumentation, previous, trend } = metric;
    const notMeasured = status === "not_measured";
    const ci = fmtCi(ci95, unit);

    return (
        <div className={`bg-white rounded-xl border shadow-sm p-4 flex flex-col gap-2 min-w-0 ${
            notMeasured ? "border-stone-200 border-dashed" : status === "partial" ? "border-amber-200" : "border-[#cee6b2]"
        }`}>
            <div className="flex items-start justify-between gap-2">
                <div className="text-xs font-semibold text-[#16270c] leading-snug">{label}</div>
                <div className="flex-shrink-0"><StatusChip status={status} /></div>
            </div>

            {notMeasured ? (
                <>
                    <div className="text-base font-extrabold tracking-wide text-stone-500 uppercase">
                        Not yet measured
                    </div>
                    {instrumentation && (
                        <div className="text-[11px] text-[#78716c] leading-snug">
                            <span className="font-semibold text-stone-600">What it needs: </span>{instrumentation}
                        </div>
                    )}
                </>
            ) : (
                <>
                    <div className="flex items-baseline gap-2 flex-wrap">
                        <div className="text-2xl font-bold text-[#16270c] tabular-nums leading-none">
                            {fmtValue(value, unit)}
                        </div>
                        {previous !== null && previous !== undefined && (
                            <div className={`text-[11px] font-semibold tabular-nums ${
                                trend === "up" ? "text-[#427425]" : trend === "down" ? "text-red-600" : "text-[#78716c]"
                            }`} title="vs previous window">
                                {trend ? TREND_ARROW[trend] : ""} {fmtValue(previous, unit)}
                                <span className="font-normal text-[#9ccd65]"> vs previous window</span>
                            </div>
                        )}
                    </div>
                    {(n !== null && n !== undefined) || ci ? (
                        <div className="text-[11px] text-[#699a32] tabular-nums">
                            {n !== null && n !== undefined && <span>n = {fmtNum(n, 0)}</span>}
                            {n !== null && n !== undefined && ci && <span> · </span>}
                            {ci && <span>95% CI {ci}</span>}
                        </div>
                    ) : null}
                    {status === "partial" && caveat && (
                        <div className="text-[11px] text-amber-800 bg-amber-50 border border-amber-100 rounded-md px-2 py-1 leading-snug">
                            {caveat}
                        </div>
                    )}
                    {status === "measured" && caveat && (
                        <div className="text-[11px] text-[#78716c] leading-snug">{caveat}</div>
                    )}
                </>
            )}

            {basis && (
                <div className="text-[10px] text-[#9ccd65] leading-snug break-words mt-auto">
                    Basis: {basis}
                </div>
            )}
        </div>
    );
}

/** A tiny line of turns p across the runs, oldest to newest. */
function Sparkline({ values }: { values: number[] }) {
    const w = 96, h = 24, pad = 2;
    const min = Math.min(...values), max = Math.max(...values);
    const span = max - min || 1;
    const pts = values.map((v, i) => {
        const x = pad + (i / Math.max(values.length - 1, 1)) * (w - pad * 2);
        const y = h - pad - ((v - min) / span) * (h - pad * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    return (
        <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true" className="flex-shrink-0">
            <polyline points={pts.join(" ")} fill="none" stroke="#589b31" strokeWidth={1.5}
                strokeLinejoin="round" strokeLinecap="round" />
            <circle cx={pts[pts.length - 1].split(",")[0]} cy={pts[pts.length - 1].split(",")[1]} r={2} fill="#427425" />
        </svg>
    );
}

function EvalHistory({ history }: { history: ApiEvalRun[] }) {
    const turnsP = history.map((r) => r.turns?.p).filter((p): p is number => typeof p === "number");
    const first = turnsP[0], last = turnsP[turnsP.length - 1];
    const delta = turnsP.length >= 2 ? last - first : null;

    return (
        <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm overflow-hidden">
            <div className="px-4 py-3 border-b border-[#e6f3d8] flex flex-wrap items-center justify-between gap-2">
                <div>
                    <span className="text-xs font-bold text-[#699a32] uppercase tracking-wider">
                        Case-set runs · {history.length} {history.length === 1 ? "run" : "runs"}
                    </span>
                    <p className="text-[11px] text-[#78716c] mt-0.5">
                        Baseline is the first run, current is the last. Each proportion is passed ÷ cases with a 95% interval.
                    </p>
                </div>
                {delta !== null && (
                    <div className="flex items-center gap-2 text-[11px] font-semibold tabular-nums">
                        <Sparkline values={turnsP} />
                        <span className={delta > 0 ? "text-[#427425]" : delta < 0 ? "text-red-600" : "text-[#78716c]"}>
                            {delta > 0 ? "↑" : delta < 0 ? "↓" : "→"} turns {(first * 100).toFixed(1)}% → {(last * 100).toFixed(1)}%
                        </span>
                    </div>
                )}
            </div>
            {history.length === 0 ? (
                <div className="py-8 text-center text-xs text-[#9ccd65]">No case-set run recorded yet.</div>
            ) : (
                <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                        <thead>
                            <tr className="border-b border-[#e6f3d8]">
                                {["Date", "Git", "Cases", "Turns p (95% CI)", "Critical p", "Language p", "Figures p"].map((c) => (
                                    <th key={c} className="text-left py-2.5 px-3 text-[10px] font-bold text-[#9ccd65] uppercase tracking-wider whitespace-nowrap">
                                        {c}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {history.map((r, i) => (
                                <tr key={`${r.at}-${r.git}-${i}`} className="border-b border-[#f3f9ec] hover:bg-[#f3f9ec] transition-colors">
                                    <td className="py-2.5 px-3 text-[#16270c] whitespace-nowrap">{shortDate(r.at)}</td>
                                    <td className="py-2.5 px-3 text-[#16270c] whitespace-nowrap font-mono text-[11px]" title={r.git}>
                                        {(r.git || "—").slice(0, 7)}
                                    </td>
                                    <td className="py-2.5 px-3 text-[#16270c] whitespace-nowrap tabular-nums">{r.cases ?? "—"}</td>
                                    <td className="py-2.5 px-3 text-[#16270c] whitespace-nowrap tabular-nums">{fmtP(r.turns, true)}</td>
                                    <td className="py-2.5 px-3 text-[#16270c] whitespace-nowrap tabular-nums">{fmtP(r.critical)}</td>
                                    <td className="py-2.5 px-3 text-[#16270c] whitespace-nowrap tabular-nums">{fmtP(r.language)}</td>
                                    <td className="py-2.5 px-3 text-[#16270c] whitespace-nowrap tabular-nums">{fmtP(r.figures)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}

// ── View ──────────────────────────────────────────────────────────────────────

export function PerformanceView({ isMobile }: PerformanceViewProps) {
    const [days, setDays] = useState<WindowDays>(7);
    const [data, setData] = useState<ApiPerformance | null>(null);
    const [failed, setFailed] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [reloadKey, setReloadKey] = useState(0);

    // Loading/failed are reset by the handlers that trigger a refetch (window
    // toggle, retry), so the effect only fetches and settles state afterwards.
    useEffect(() => {
        let alive = true;
        getPerformance(days)
            .then((r) => { if (alive) { setData(r); setLoading(false); } })
            .catch((e) => {
                if (alive) {
                    setFailed(apiErrorDetail(e) || "Couldn't load the performance view");
                    setLoading(false);
                }
            });
        return () => { alive = false; };
    }, [days, reloadKey]);

    const changeDays = (d: WindowDays) => {
        if (d === days) return;
        setDays(d);
        setLoading(true);
        setFailed(null);
    };
    const retry = () => {
        setReloadKey((k) => k + 1);
        setLoading(true);
        setFailed(null);
    };

    const metrics = data?.metrics ?? {};
    const placed = new Set(GROUPS.flatMap((g) => g.keys));
    const otherKeys = Object.keys(metrics).filter((k) => !placed.has(k));
    const groups = [...GROUPS, ...(otherKeys.length ? [{ title: "Other", keys: otherKeys }] : [])];

    const counts = data?.counts;
    const gridCls = isMobile ? "grid-cols-1" : "grid-cols-2 lg:grid-cols-3 xl:grid-cols-4";

    return (
        <div className={`flex-1 overflow-y-auto bg-[#f3f9ec] ${isMobile ? "p-4 pb-24" : "p-6"}`}>

            {/* Header */}
            <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
                <div className="min-w-0">
                    <h1 className="text-xl font-bold text-[#16270c] tracking-tight">Performance</h1>
                    <p className="text-sm text-[#699a32] mt-0.5 tabular-nums">
                        Last {days} days
                        {counts && (
                            <> · measured {counts.measured} · partial {counts.partial} · not yet measured {counts.not_measured}</>
                        )}
                    </p>
                </div>
                <div className="flex items-center gap-1 bg-white border border-[#b5da8b] rounded-lg p-0.5" role="group" aria-label="Window">
                    {([7, 30] as WindowDays[]).map((d) => (
                        <button key={d} onClick={() => changeDays(d)} disabled={loading && days === d}
                            aria-pressed={days === d}
                            className={`h-8 px-3 rounded-md text-xs font-semibold transition-colors ${
                                days === d ? "bg-[#589b31] text-white" : "text-[#427425] hover:bg-[#f0f9ec]"
                            }`}>
                            {d} days
                        </button>
                    ))}
                </div>
            </div>

            <p className="text-xs text-[#78716c] bg-white border border-[#e6f3d8] rounded-lg px-3 py-2 mb-5 leading-snug">
                Every figure says whether it is measured, partial or not yet measured. Nothing here is estimated.
            </p>

            {failed && (
                <div className="bg-red-50 border border-red-200 text-red-700 text-xs rounded-lg px-3 py-2 mb-5 flex flex-wrap items-center justify-between gap-2">
                    <span>{failed}</span>
                    <button onClick={retry}
                        className="h-7 px-3 rounded-md text-xs font-semibold bg-white border border-red-200 hover:bg-red-100">
                        Try again
                    </button>
                </div>
            )}

            {/* Never show placeholders that look like figures while the data is loading. */}
            {loading && !data && !failed && (
                <p className="text-sm text-[#699a32] py-8 text-center">Loading the performance view…</p>
            )}

            {data && (
                <div className={`space-y-6 ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
                    {groups.map((g) => {
                        const present = g.keys.filter((k) => metrics[k]);
                        if (present.length === 0 && g.title !== GROUPS[0].title) return null;
                        return (
                            <section key={g.title}>
                                <h2 className="text-xs font-bold text-[#699a32] uppercase tracking-wider mb-3">{g.title}</h2>
                                {present.length > 0 ? (
                                    <div className={`grid gap-3 ${gridCls}`}>
                                        {present.map((k) => <MetricCard key={k} metric={metrics[k]} />)}
                                    </div>
                                ) : (
                                    <p className="text-xs text-[#9ccd65]">Nothing reported for this group.</p>
                                )}
                                {g.title === GROUPS[0].title && (
                                    <div className="mt-3">
                                        <EvalHistory history={data.eval_history ?? []} />
                                    </div>
                                )}
                            </section>
                        );
                    })}
                    <p className="text-[10px] text-[#9ccd65]">
                        Window {shortDate(data.since)} – {shortDate(data.until)} ({data.window_days} days).
                    </p>
                </div>
            )}
        </div>
    );
}

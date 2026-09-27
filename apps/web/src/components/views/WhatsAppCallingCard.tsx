"use client";

// Settings → WhatsApp calling (admins: manage_settings). The number's calling
// settings as Meta holds them (GET/POST /admin/calls/settings — docs/CALLING_UX.md
// §2.1): callback permission, the call button, voicemail, call hours and
// holidays; Meta's restrictions (read-only); the call-permission template that
// lets agents ask customers outside the 24 h window; and whether WhatsApp
// records / transcribes calls (a server switch — shown, not changed here).
// Saves only the fields that changed; the server's refusal is shown inline.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
    callsApi, apiErrorInfo, isNetworkError,
    type CallSettings, type CallSettingsPatch, type CallPermissionTemplate, type CallIceConfig,
} from "@/lib/api";
import { useWs } from "@/lib/websocket";
import { dayDate } from "@/lib/callStatus";
import type { SharedViewProps } from "@/types";

const DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"] as const;
type Day = (typeof DAYS)[number];
const DAY_LABEL: Record<Day, string> = {
    MONDAY: "Mon", TUESDAY: "Tue", WEDNESDAY: "Wed", THURSDAY: "Thu", FRIDAY: "Fri", SATURDAY: "Sat", SUNDAY: "Sun",
};

interface DayHours { open: boolean; from: string; to: string; }
interface Holiday { date: string; from: string; to: string; }
interface Draft {
    callback: boolean;
    icon: string;
    vmOn: boolean;
    vmTimeout: number;
    hoursOn: boolean;
    tz: string;
    week: Record<Day, DayHours>;
    holidays: Holiday[];
}

// Meta keeps times as "HHMM"; the time inputs want "HH:MM".
const toInput = (v?: string | null) => {
    const d = String(v ?? "").replace(/\D/g, "").padStart(4, "0").slice(0, 4);
    return `${d.slice(0, 2)}:${d.slice(2)}`;
};
const toMeta = (v: string) => v.replace(":", "").padStart(4, "0").slice(0, 4);

function draftOf(s: CallSettings): Draft {
    const hours = s.call_hours ?? {};
    const week = {} as Record<Day, DayHours>;
    for (const d of DAYS) {
        const slot = (hours.weekly_operating_hours ?? []).find((w) => String(w.day_of_week).toUpperCase() === d);
        week[d] = slot ? { open: true, from: toInput(slot.open_time), to: toInput(slot.close_time) }
            : { open: false, from: "08:00", to: "17:00" };
    }
    return {
        callback: String(s.callback_permission_status ?? "").toUpperCase() === "ENABLED",
        icon: String(s.call_icon_visibility ?? "DEFAULT").toUpperCase(),
        vmOn: String(s.voicemail?.status ?? "").toUpperCase() === "ENABLED",
        vmTimeout: Number(s.voicemail?.timeout_seconds ?? 20),
        hoursOn: String(hours.status ?? "").toUpperCase() === "ENABLED",
        tz: hours.timezone_id ?? "Africa/Nairobi",
        week,
        holidays: (hours.holiday_schedule ?? []).map((h) => ({ date: h.date, from: toInput(h.start_time), to: toInput(h.end_time) })),
    };
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Only what changed — the server merges call_hours / voicemail over the current ones. */
function patchOf(orig: Draft, d: Draft): CallSettingsPatch {
    const p: CallSettingsPatch = {};
    if (d.callback !== orig.callback) p.callback_permission_status = d.callback ? "ENABLED" : "DISABLED";
    if (d.icon !== orig.icon) p.call_icon_visibility = d.icon;
    const vm: NonNullable<CallSettingsPatch["voicemail"]> = {};
    if (d.vmOn !== orig.vmOn) vm.status = d.vmOn ? "ENABLED" : "DISABLED";
    if (d.vmTimeout !== orig.vmTimeout) vm.timeout_seconds = d.vmTimeout;
    if (Object.keys(vm).length) p.voicemail = vm;
    const hours: NonNullable<CallSettingsPatch["call_hours"]> = {};
    if (d.hoursOn !== orig.hoursOn) hours.status = d.hoursOn ? "ENABLED" : "DISABLED";
    if (d.tz !== orig.tz) hours.timezone_id = d.tz;
    if (!same(d.week, orig.week)) {
        hours.weekly_operating_hours = DAYS.filter((day) => d.week[day].open).map((day) => ({
            day_of_week: day, open_time: toMeta(d.week[day].from), close_time: toMeta(d.week[day].to),
        }));
    }
    if (!same(d.holidays, orig.holidays)) {
        hours.holiday_schedule = d.holidays.map((h) => ({ date: h.date, start_time: toMeta(h.from), end_time: toMeta(h.to) }));
    }
    if (Object.keys(hours).length) p.call_hours = hours;
    return p;
}

const ICON_CHOICES: [string, string][] = [
    ["DEFAULT", "Show the call button"],
    ["HIDE_IN_CHAT", "Hide it inside chats"],
    ["DISABLE_ALL", "Hide it everywhere"],
];

const RESTRICTION_WORDS: Record<string, string> = {
    RESTRICTED_BUSINESS_INITIATED_CALLING: "We can't call customers",
    RESTRICTED_USER_INITIATED_CALLING: "Customers can't call us",
};

const box = "rounded-xl border px-3 py-3";
const inputCls = "h-11 px-2.5 text-sm rounded-lg border border-stone-300 bg-white text-stone-800 focus:outline-none focus:ring-2 focus:ring-[#589b31]";

/** An accessible switch: role=switch, visible On/Off, a 44px target. */
function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
    return (
        <button type="button" role="switch" aria-checked={checked} aria-label={label} disabled={disabled}
            onClick={() => onChange(!checked)}
            className="flex-shrink-0 flex items-center gap-2 rounded-full px-1 disabled:opacity-50" style={{ minHeight: 44 }}>
            <span className={`relative w-11 h-6 rounded-full transition-colors ${checked ? "bg-[#128C4B]" : "bg-stone-300"}`}>
                <span className={`absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${checked ? "translate-x-5" : "translate-x-0.5"}`} />
            </span>
            <span className="text-xs font-semibold w-6 text-left" style={{ color: checked ? "#128C4B" : "#57534e" }}>{checked ? "On" : "Off"}</span>
        </button>
    );
}

function Row({ title, hint, children }: { title: string; hint?: React.ReactNode; children: React.ReactNode }) {
    return (
        <div className="flex items-start justify-between gap-3 py-2">
            <div className="min-w-0">
                <div className="text-sm font-medium text-[#16270c]">{title}</div>
                {hint && <div className="text-xs text-stone-500 mt-0.5 leading-relaxed">{hint}</div>}
            </div>
            {children}
        </div>
    );
}

function TemplateStatus({ onToast }: { onToast: SharedViewProps["onToast"] }) {
    const [tpl, setTpl] = useState<CallPermissionTemplate | null>(null);
    const [err, setErr] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const load = useCallback(() => {
        setErr(null);
        callsApi.permissionTemplate().then(setTpl)
            .catch((e) => setErr(isNetworkError(e) ? "No connection — couldn't check the template." : apiErrorInfo(e).detail || "Couldn't check the template."));
    }, []);
    useEffect(() => { load(); }, [load]);
    const create = async () => {
        setBusy(true); setErr(null);
        try {
            const r = await callsApi.createPermissionTemplate({});
            setTpl((t) => ({ ...(t ?? { configured: true, source: "app", waba_configured: true, exists: true, category: "UTILITY" }),
                configured: true, name: r.name, language: r.language, exists: true, status: r.status || "pending" } as CallPermissionTemplate));
            onToast("Call-request template sent to WhatsApp for review");
        } catch (e) {
            setErr(isNetworkError(e) ? "No connection — nothing was created. Try again." : apiErrorInfo(e).detail || "Couldn't create the template.");
        } finally { setBusy(false); }
    };
    let state: { word: string; color: string; note: string };
    const st = (tpl?.status || "").toLowerCase();
    if (!tpl) state = { word: err ? "Unknown" : "Checking…", color: "#57534e", note: "" };
    else if (!tpl.configured || tpl.exists === false) state = { word: "Not created", color: "#A15C00",
        note: "Agents can only ask customers who messaged in the last 24 hours." };
    else if (st === "approved") state = { word: "Approved", color: "#128C4B", note: "Call requests reach customers outside the 24-hour window." };
    else if (st === "rejected") state = { word: "Rejected", color: "#C62828", note: "WhatsApp rejected it — create it again with different wording." };
    else if (st === "pending" || st === "in_appeal" || st === "pending_deletion") state = { word: "Waiting for WhatsApp's review", color: "#A15C00", note: "Requests use it as soon as it's approved." };
    else if (tpl.exists === null) state = { word: "Couldn't reach WhatsApp", color: "#57534e", note: tpl.error?.reason || "" };
    else state = { word: st ? st[0].toUpperCase() + st.slice(1) : "Unknown", color: "#57534e", note: "" };
    const canCreate = !!tpl && tpl.waba_configured && (!tpl.configured || tpl.exists === false || st === "rejected");
    return (
        <div className={box} style={{ borderColor: "#e6f3d8" }}>
            <div className="flex items-start justify-between gap-3 flex-wrap">
                <div className="min-w-0">
                    <div className="text-sm font-medium text-[#16270c]">Call-request template</div>
                    <div className="text-xs mt-0.5 font-semibold" style={{ color: state.color }}>
                        {state.word}{tpl?.name ? <span className="font-normal text-stone-500"> · {tpl.name} ({tpl.language})</span> : null}
                    </div>
                    {state.note && <div className="text-xs text-stone-500 mt-0.5">{state.note}</div>}
                    {tpl && !tpl.waba_configured && (
                        <div className="text-xs text-stone-500 mt-0.5">Set WABA_BUSINESS_ACCOUNT_ID on the server to create templates.</div>
                    )}
                </div>
                {canCreate && (
                    <button type="button" onClick={create} disabled={busy}
                        className="rounded-lg px-4 text-sm font-semibold text-white disabled:opacity-60" style={{ minHeight: 44, backgroundColor: "#128C4B" }}>
                        {busy ? "Creating…" : "Create template"}
                    </button>
                )}
            </div>
            {err && <p role="alert" className="text-xs mt-2" style={{ color: "#C62828" }}>{err}</p>}
        </div>
    );
}

export function WhatsAppCallingCard({ onToast }: { onToast: SharedViewProps["onToast"] }): React.ReactElement {
    const ws = useWs();
    const [settings, setSettings] = useState<CallSettings | null>(null);
    const [orig, setOrig] = useState<Draft | null>(null);
    const [draft, setDraft] = useState<Draft | null>(null);
    const [loadErr, setLoadErr] = useState<string | null>(null);
    const [saveErr, setSaveErr] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [saved, setSaved] = useState(false);
    const [changedRemote, setChangedRemote] = useState(false);
    const [ice, setIce] = useState<CallIceConfig | null>(null);

    const apply = useCallback((s: CallSettings) => {
        const d = draftOf(s);
        setSettings(s); setOrig(d); setDraft(d); setChangedRemote(false);
    }, []);
    const load = useCallback(() => {
        setLoadErr(null);
        callsApi.settings().then(apply)
            .catch((e) => setLoadErr(isNetworkError(e) ? "No connection — couldn't read the calling settings."
                : apiErrorInfo(e).detail || "Couldn't read the calling settings."));
    }, [apply]);
    useEffect(() => { load(); }, [load]);
    useEffect(() => { callsApi.iceConfig().then(setIce).catch(() => { /* shown as unknown */ }); }, []);

    const patch = useMemo(() => (orig && draft ? patchOf(orig, draft) : {}), [orig, draft]);
    const dirty = Object.keys(patch).length > 0;

    // Meta says the settings changed (maybe in WhatsApp Manager): reload, unless
    // that would throw away the admin's unsaved edits.
    useEffect(() => {
        if (!ws) return;
        const on = (e: { type?: string }) => {
            if (e?.type !== "call_settings") return;
            if (dirty) setChangedRemote(true); else load();
        };
        ws.on("event", on);
        return () => ws.off("event", on);
    }, [ws, dirty, load]);

    const set = (p: Partial<Draft>) => { setSaved(false); setSaveErr(null); setDraft((d) => (d ? { ...d, ...p } : d)); };
    const setDay = (day: Day, p: Partial<DayHours>) => draft && set({ week: { ...draft.week, [day]: { ...draft.week[day], ...p } } });
    const setHoliday = (i: number, p: Partial<Holiday>) => draft && set({ holidays: draft.holidays.map((h, j) => (j === i ? { ...h, ...p } : h)) });

    const save = async () => {
        if (!dirty || saving) return;
        setSaving(true); setSaveErr(null); setSaved(false);
        try {
            const r = await callsApi.saveSettings(patch);
            if (r?.settings) apply({ ...settings, ...r.settings });
            else if (draft) { setOrig(draft); }
            setSaved(true);
            onToast("WhatsApp calling settings saved");
        } catch (e) {
            setSaveErr(isNetworkError(e) ? "No connection — nothing was saved. Try again."
                : apiErrorInfo(e).detail || "Couldn't save the calling settings.");
        } finally { setSaving(false); }
    };

    const restrictions = settings?.restrictions ?? [];
    const timeValid = !draft || DAYS.every((d) => !draft.week[d].open || draft.week[d].from < draft.week[d].to)
        && draft.holidays.every((h) => /^\d{4}-\d{2}-\d{2}$/.test(h.date));

    return (
        <section id="whatsapp-calling" tabIndex={-1} aria-labelledby="wa-calling-title"
            className="bg-white rounded-xl border border-[#cee6b2] shadow-sm p-4 sm:p-5 mb-4 focus:outline-none">
            <div className="mb-3">
                <h4 id="wa-calling-title" className="text-sm font-semibold text-[#16270c]">WhatsApp calling</h4>
                <p className="text-xs text-[#699a32] mt-1 leading-relaxed">
                    How customers reach us by WhatsApp call, and how we reach them. Changes can take up to 7 days to reach customers&apos; phones.
                </p>
            </div>

            {restrictions.length > 0 && (
                <div role="alert" className="rounded-xl px-3 py-2 mb-3 text-sm flex items-start gap-2"
                    style={{ backgroundColor: "#fdecee", color: "#9b1c1c", border: "1px solid #f5c2c7" }}>
                    <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="flex-shrink-0 mt-0.5">
                        <path d="M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" />
                    </svg>
                    <div>
                        <div className="font-semibold">WhatsApp restricted calling on this number</div>
                        <ul className="mt-0.5 text-xs space-y-0.5">
                            {restrictions.map((r, i) => {
                                const exp = r.expiration != null ? (typeof r.expiration === "number" ? new Date(r.expiration * 1000).toISOString() : String(r.expiration)) : null;
                                return <li key={i}>{RESTRICTION_WORDS[String(r.type)] ?? String(r.type ?? "Restricted")}{exp ? ` — until ${dayDate(exp)}` : ""}</li>;
                            })}
                        </ul>
                    </div>
                </div>
            )}

            {!draft ? (
                loadErr ? (
                    <div role="alert" className="text-sm flex items-center gap-3 flex-wrap" style={{ color: "#C62828" }}>
                        {loadErr}
                        <button type="button" onClick={load} className="rounded-lg px-4 text-sm font-semibold border border-stone-300 text-stone-700" style={{ minHeight: 44 }}>Retry</button>
                    </div>
                ) : <p className="text-sm text-stone-500">Loading calling settings…</p>
            ) : (
                <div className="space-y-3">
                    {changedRemote && (
                        <div role="status" className="rounded-lg px-3 py-2 text-xs flex items-center gap-2 flex-wrap" style={{ backgroundColor: "#fff7e6", color: "#7a4a00" }}>
                            These settings changed in WhatsApp while you were editing.
                            <button type="button" onClick={load} className="font-semibold underline" style={{ minHeight: 44 }}>Reload</button>
                        </div>
                    )}
                    <div className={box} style={{ borderColor: "#e6f3d8" }}>
                        <Row title="Customers who call us can be called back for 7 days"
                            hint="When a customer calls this number, WhatsApp lets us call them back for 7 days — no call request needed.">
                            <Switch label="Customers who call us can be called back for 7 days" checked={draft.callback} onChange={(v) => set({ callback: v })} />
                        </Row>
                        <Row title="Call button for customers" hint="Hiding it doesn't stop customers calling from their call log or contacts.">
                            <select aria-label="Call button for customers" value={draft.icon} onChange={(e) => set({ icon: e.target.value })}
                                className={`${inputCls} max-w-[12rem]`}>
                                {ICON_CHOICES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                            </select>
                        </Row>
                        <Row title="Voicemail" hint="When nobody answers, the customer can leave a voice message — it lands in their chat.">
                            <Switch label="Voicemail" checked={draft.vmOn} onChange={(v) => set({ vmOn: v })} />
                        </Row>
                        {draft.vmOn && (
                            <label className="flex items-center gap-2 text-xs text-stone-600 flex-wrap">
                                Offer voicemail after
                                <input type="number" min={0} max={30} value={draft.vmTimeout} aria-label="Seconds before voicemail"
                                    onChange={(e) => set({ vmTimeout: Math.max(0, Math.min(30, Number(e.target.value) || 0)) })}
                                    className={`${inputCls} w-20`} />
                                seconds of ringing (0–30)
                            </label>
                        )}
                    </div>

                    <div className={box} style={{ borderColor: "#e6f3d8" }}>
                        <Row title="Call hours" hint="Outside these hours customers see that we're closed instead of ringing.">
                            <Switch label="Call hours" checked={draft.hoursOn} onChange={(v) => set({ hoursOn: v })} />
                        </Row>
                        {draft.hoursOn && (
                            <div className="space-y-2 mt-1">
                                <label className="flex items-center gap-2 text-xs text-stone-600 flex-wrap">
                                    Time zone
                                    <input value={draft.tz} onChange={(e) => set({ tz: e.target.value })} aria-label="Time zone"
                                        className={`${inputCls} flex-1 min-w-[10rem]`} placeholder="Africa/Nairobi" />
                                </label>
                                <ul className="space-y-1" aria-label="Weekly call hours">
                                    {DAYS.map((day) => {
                                        const h = draft.week[day];
                                        const bad = h.open && h.from >= h.to;
                                        return (
                                            <li key={day} className="flex items-center gap-2 flex-wrap">
                                                <span className="w-10 text-sm font-medium text-stone-700">{DAY_LABEL[day]}</span>
                                                <Switch label={`${DAY_LABEL[day]} open`} checked={h.open} onChange={(v) => setDay(day, { open: v })} />
                                                {h.open ? (
                                                    <span className="flex items-center gap-1.5">
                                                        <input type="time" value={h.from} aria-label={`${DAY_LABEL[day]} opens`} onChange={(e) => setDay(day, { from: e.target.value })} className={inputCls} />
                                                        <span className="text-stone-400" aria-hidden="true">–</span>
                                                        <input type="time" value={h.to} aria-label={`${DAY_LABEL[day]} closes`} onChange={(e) => setDay(day, { to: e.target.value })} className={inputCls} />
                                                    </span>
                                                ) : <span className="text-xs text-stone-500">Closed</span>}
                                                {bad && <span role="alert" className="text-xs" style={{ color: "#C62828" }}>Closes before it opens</span>}
                                            </li>
                                        );
                                    })}
                                </ul>
                                <div className="pt-2">
                                    <div className="text-sm font-medium text-[#16270c]">Holidays</div>
                                    <p className="text-xs text-stone-500">Days with different hours (up to 20).</p>
                                    <ul className="space-y-1 mt-1" aria-label="Holidays">
                                        {draft.holidays.map((h, i) => (
                                            <li key={i} className="flex items-center gap-1.5 flex-wrap">
                                                <input type="date" value={h.date} aria-label={`Holiday ${i + 1} date`} onChange={(e) => setHoliday(i, { date: e.target.value })} className={inputCls} />
                                                <input type="time" value={h.from} aria-label={`Holiday ${i + 1} opens`} onChange={(e) => setHoliday(i, { from: e.target.value })} className={inputCls} />
                                                <span className="text-stone-400" aria-hidden="true">–</span>
                                                <input type="time" value={h.to} aria-label={`Holiday ${i + 1} closes`} onChange={(e) => setHoliday(i, { to: e.target.value })} className={inputCls} />
                                                <button type="button" onClick={() => set({ holidays: draft.holidays.filter((_, j) => j !== i) })}
                                                    aria-label={`Remove holiday ${h.date || i + 1}`} className="rounded-lg px-3 text-xs font-semibold text-stone-600 border border-stone-300" style={{ minHeight: 44 }}>
                                                    Remove
                                                </button>
                                            </li>
                                        ))}
                                    </ul>
                                    {draft.holidays.length < 20 && (
                                        <button type="button" onClick={() => set({ holidays: [...draft.holidays, { date: new Date().toISOString().slice(0, 10), from: "00:00", to: "00:00" }] })}
                                            className="mt-1 rounded-lg px-3 text-xs font-semibold border border-[#b5da8b] text-[#3d5a30]" style={{ minHeight: 44 }}>
                                            + Add holiday
                                        </button>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>

                    <TemplateStatus onToast={onToast} />

                    <div className={box} style={{ borderColor: "#e6f3d8" }}>
                        <div className="text-sm font-medium text-[#16270c]">WhatsApp recording &amp; transcription</div>
                        <div className="text-xs mt-0.5 font-semibold" style={{ color: ice?.meta_transcription ? "#128C4B" : "#57534e" }}>
                            {ice == null ? "Unknown" : ice.meta_transcription ? "On — WhatsApp writes the call summary" : "Off"}
                        </div>
                        <p className="text-xs text-stone-500 mt-0.5 leading-relaxed">
                            Switched on the server (CALL_META_TRANSCRIPTION / CALL_META_RECORDING), not here. When on, WhatsApp tells the customer the call is being recorded.
                        </p>
                    </div>

                    <div className="flex items-center gap-3 flex-wrap pt-1">
                        <button type="button" onClick={save} disabled={!dirty || saving || !timeValid}
                            className="rounded-lg px-5 text-sm font-semibold text-white disabled:opacity-50" style={{ minHeight: 44, backgroundColor: "#589b31" }}>
                            {saving ? "Saving…" : "Save calling settings"}
                        </button>
                        {dirty && !saving && (
                            <button type="button" onClick={() => { setDraft(orig); setSaveErr(null); }}
                                className="rounded-lg px-4 text-sm font-semibold text-stone-600" style={{ minHeight: 44 }}>
                                Discard changes
                            </button>
                        )}
                        {saved && !dirty && <span role="status" className="text-xs" style={{ color: "#128C4B" }}>Saved — customers see it within 7 days.</span>}
                    </div>
                    {saveErr && <p role="alert" className="text-sm" style={{ color: "#C62828" }}>{saveErr}</p>}
                </div>
            )}
        </section>
    );
}

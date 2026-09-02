// SettingsView.tsx
import React, { useEffect, useState } from "react";
import { Toggle } from "@/components/ui/Layout";
import { InputField } from "@/components/ui/FormFields";
import { settingsApi, type ApiTranslationSetting,
         type ApiCampaign, type ApiOfferSetting } from "@/lib/api";
import type { SharedViewProps } from "@/types";

// ── Platform SVG icons ────────────────────────────────────────────────────────

const WhatsAppIcon = () => (
    <svg viewBox="0 0 32 32" className="w-5 h-5" fill="currentColor">
        <path d="M16 2C8.28 2 2 8.28 2 16c0 2.44.64 4.73 1.76 6.72L2 30l7.44-1.72A13.92 13.92 0 0016 30c7.72 0 14-6.28 14-14S23.72 2 16 2zm0 25.6a11.56 11.56 0 01-5.88-1.6l-.42-.26-4.42 1.02.98-4.3-.28-.44A11.6 11.6 0 014.4 16C4.4 9.6 9.6 4.4 16 4.4S27.6 9.6 27.6 16 22.4 27.6 16 27.6zm6.36-8.68c-.34-.18-2.02-.98-2.34-1.1-.32-.1-.54-.18-.78.18-.22.34-.88 1.1-1.08 1.32-.2.24-.4.26-.74.08-.34-.18-1.44-.52-2.74-1.66a10.3 10.3 0 01-1.9-2.32c-.2-.34-.02-.52.14-.7.16-.16.34-.42.52-.62.16-.22.22-.36.34-.6.1-.24.06-.44-.02-.62-.08-.18-.78-1.86-1.06-2.54-.28-.68-.56-.58-.78-.6-.2-.02-.42-.02-.66-.02s-.6.08-.92.44c-.32.34-1.2 1.16-1.2 2.84 0 1.66 1.22 3.28 1.4 3.5.16.22 2.42 3.7 5.86 5.18.82.36 1.46.56 1.96.72.82.26 1.56.22 2.16.14.66-.1 2.02-.82 2.3-1.62.28-.78.28-1.46.2-1.62-.1-.14-.32-.22-.66-.4z" />
    </svg>
);

const MessengerIcon = () => (
    <svg viewBox="0 0 32 32" className="w-5 h-5" fill="currentColor">
        <path d="M16 2C8.27 2 2 7.93 2 15.2c0 3.82 1.6 7.25 4.2 9.72V30l4.88-2.68A14.5 14.5 0 0016 28.4c7.73 0 14-5.93 14-13.2S23.73 2 16 2zm1.38 17.78l-3.56-3.8-6.96 3.8L13.2 12l3.66 3.8L23.72 12l-6.34 7.78z" />
    </svg>
);

const InstagramIcon = () => (
    <svg viewBox="0 0 32 32" className="w-5 h-5" fill="currentColor">
        <path d="M16 2.88c3.52 0 3.94.02 5.32.08 1.28.06 1.98.28 2.44.46.62.24 1.06.52 1.52.98.46.46.74.9.98 1.52.18.46.4 1.16.46 2.44.06 1.38.08 1.8.08 5.32s-.02 3.94-.08 5.32c-.06 1.28-.28 1.98-.46 2.44-.24.62-.52 1.06-.98 1.52-.46.46-.9.74-1.52.98-.46.18-1.16.4-2.44.46-1.38.06-1.8.08-5.32.08s-3.94-.02-5.32-.08c-1.28-.06-1.98-.28-2.44-.46-.62-.24-1.06-.52-1.52-.98-.46-.46-.74-.9-.98-1.52-.18-.46-.4-1.16-.46-2.44C2.9 19.94 2.88 19.52 2.88 16s.02-3.94.08-5.32c.06-1.28.28-1.98.46-2.44.24-.62.52-1.06.98-1.52.46-.46.9-.74 1.52-.98.46-.18 1.16-.4 2.44-.46C12.06 2.9 12.48 2.88 16 2.88M16 .5c-3.58 0-4.03.02-5.44.08-1.4.06-2.36.3-3.2.62C6.5 1.54 5.7 2 4.9 2.8c-.8.8-1.26 1.6-1.6 2.46-.32.84-.56 1.8-.62 3.2C2.52 9.87 2.5 10.32 2.5 16s.02 6.13.08 7.54c.06 1.4.3 2.36.62 3.2.34.86.8 1.66 1.6 2.46.8.8 1.6 1.26 2.46 1.6.84.32 1.8.56 3.2.62 1.41.06 1.86.08 7.54.08s6.13-.02 7.54-.08c1.4-.06 2.36-.3 3.2-.62.86-.34 1.66-.8 2.46-1.6.8-.8 1.26-1.6 1.6-2.46.32-.84.56-1.8.62-3.2.06-1.41.08-1.86.08-7.54s-.02-6.13-.08-7.54c-.06-1.4-.3-2.36-.62-3.2-.34-.86-.8-1.66-1.6-2.46-.8-.8-1.6-1.26-2.46-1.6-.84-.32-1.8-.56-3.2-.62C22.13.52 21.68.5 16 .5zm0 6.44a9.06 9.06 0 100 18.12A9.06 9.06 0 0016 6.94zm0 14.94a5.88 5.88 0 110-11.76 5.88 5.88 0 010 11.76zm9.42-15.3a2.12 2.12 0 100 4.24 2.12 2.12 0 000-4.24z" />
    </svg>
);

const MPesaIcon = () => (
    <svg viewBox="0 0 32 32" className="w-5 h-5" fill="none">
        <rect width="32" height="32" rx="6" fill="#00A651"/>
        <text x="4" y="22" fontSize="11" fontWeight="bold" fill="white" fontFamily="Arial">M-PESA</text>
    </svg>
);

const EmailIcon = () => (
    <svg viewBox="0 0 32 32" className="w-5 h-5" fill="none" stroke="currentColor">
        <rect x="2" y="6" width="28" height="20" rx="3" strokeWidth="2"/>
        <path d="M2 9l14 9 14-9" strokeWidth="2"/>
    </svg>
);

const SlackIcon = () => (
    <svg viewBox="0 0 32 32" className="w-5 h-5" fill="currentColor">
        <path d="M13.5 5a2.5 2.5 0 00-2.5 2.5V10H8.5a2.5 2.5 0 000 5H11v2H8.5a2.5 2.5 0 000 5H11v2.5a2.5 2.5 0 005 0V24h2.5v2.5a2.5 2.5 0 005 0V22h2.5a2.5 2.5 0 000-5H21v-2h2.5a2.5 2.5 0 000-5H21V7.5a2.5 2.5 0 00-5 0V10h-2.5V7.5A2.5 2.5 0 0013.5 5zm0 9.5H11v-2h2.5v2zm7 0H18v-2h2.5v2z" />
    </svg>
);

const SheetsIcon = () => (
    <svg viewBox="0 0 32 32" className="w-5 h-5" fill="none">
        <rect width="32" height="32" rx="4" fill="#0F9D58"/>
        <rect x="6" y="8" width="20" height="16" rx="1" fill="white" opacity="0.9"/>
        <line x1="6" y1="13" x2="26" y2="13" stroke="#0F9D58" strokeWidth="1.5"/>
        <line x1="6" y1="18" x2="26" y2="18" stroke="#0F9D58" strokeWidth="1.5"/>
        <line x1="14" y1="8" x2="14" y2="24" stroke="#0F9D58" strokeWidth="1.5"/>
    </svg>
);

type IconKey = "whatsapp" | "messenger" | "instagram" | "mpesa" | "email" | "slack" | "sheets";

const PLATFORM_ICONS: Record<IconKey, { component: React.FC; bg: string; color: string }> = {
    whatsapp:  { component: WhatsAppIcon,  bg: "#25D366", color: "white" },
    messenger: { component: MessengerIcon, bg: "#0099FF", color: "white" },
    instagram: { component: InstagramIcon, bg: "linear-gradient(45deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888)", color: "white" },
    mpesa:     { component: MPesaIcon,     bg: "#00A651", color: "white" },
    email:     { component: EmailIcon,     bg: "#4d66b3", color: "white" },
    slack:     { component: SlackIcon,     bg: "#4A154B", color: "white" },
    sheets:    { component: SheetsIcon,    bg: "#0F9D58", color: "white" },
};

// ── Types ─────────────────────────────────────────────────────────────────────

interface Integration {
    key:         IconKey;
    name:        string;
    status:      "connected" | "disconnected";
    description: string;
    configFields?: { label: string; key: string; type?: string; placeholder?: string }[];
}

interface AiSettings {
    auto_intercept_threshold: number;
    draft_approval: boolean;
    response_delay_ms: number;
    escalation_keywords: string;
}

interface BizSettings {
    business_name: string;
    currency: string;
    wa_number: string;
    open_hours: string;
    timezone: string;
}

// ── Static data ───────────────────────────────────────────────────────────────

const INTEGRATIONS: Integration[] = [
    {
        key: "whatsapp", name: "WhatsApp Business API", status: "connected",
        description: "Primary messaging channel",
        configFields: [
            { label: "Phone Number ID", key: "phone_id", placeholder: "752950797900067" },
            { label: "Access Token",    key: "token",    type: "password", placeholder: "EAAx…" },
            { label: "Webhook Secret",  key: "secret",   type: "password", placeholder: "your-secret" },
        ],
    },
    {
        key: "messenger", name: "Facebook Messenger", status: "connected",
        description: "Meta messaging platform",
        configFields: [
            { label: "Page ID",       key: "page_id",    placeholder: "123456789" },
            { label: "Access Token",  key: "page_token", type: "password", placeholder: "EAAx…" },
        ],
    },
    {
        key: "instagram", name: "Instagram DMs", status: "connected",
        description: "Instagram direct messages",
        configFields: [
            { label: "Business Account ID", key: "ig_id",    placeholder: "17841…" },
            { label: "Access Token",        key: "ig_token", type: "password", placeholder: "EAAx…" },
        ],
    },
    {
        key: "mpesa", name: "M-Pesa Daraja API", status: "connected",
        description: "Mobile payment processing",
        configFields: [
            { label: "Consumer Key",    key: "consumer_key",    type: "password" },
            { label: "Consumer Secret", key: "consumer_secret", type: "password" },
            { label: "Paybill Number",  key: "paybill",         placeholder: "542542" },
            { label: "Account Number",  key: "account",         placeholder: "50036" },
        ],
    },
    {
        key: "email", name: "Email (SMTP)", status: "connected",
        description: "Email channel integration",
        configFields: [
            { label: "SMTP Host",    key: "smtp_host",     placeholder: "smtp.gmail.com" },
            { label: "SMTP Port",    key: "smtp_port",     placeholder: "587" },
            { label: "Username",     key: "smtp_user",     placeholder: "hello@bethanyhouse.co.ke" },
            { label: "Password",     key: "smtp_pass",     type: "password" },
        ],
    },
    {
        key: "slack", name: "Slack Notifications", status: "disconnected",
        description: "Team alert channel",
        configFields: [
            { label: "Webhook URL",  key: "slack_url",     placeholder: "https://hooks.slack.com/…" },
            { label: "Channel",      key: "slack_channel", placeholder: "#neema-alerts" },
        ],
    },
    {
        key: "sheets", name: "Google Sheets", status: "disconnected",
        description: "Data export and reporting",
        configFields: [
            { label: "Sheet ID",    key: "sheet_id",    placeholder: "1BxiMVs0XRA5nFM…" },
            { label: "Service Account JSON", key: "gcp_json", type: "password", placeholder: "Paste service account JSON…" },
        ],
    },
];

// ── Sub-components ────────────────────────────────────────────────────────────

/** Standing orders — the FIRST live settings card: what you type here is read
 *  by Neema before every reply, within minutes, no deploy. */
function StandingOrdersCard({ onToast }: { onToast: SharedViewProps["onToast"] }) {
    const [text, setText] = useState("");
    const [maxChars, setMaxChars] = useState(600);
    const [loaded, setLoaded] = useState(false);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        let gone = false;
        settingsApi.getDirectives()
            .then((r) => { if (!gone) { setText(r.directives); setMaxChars(r.max_chars); setLoaded(true); } })
            .catch(() => { if (!gone) setLoaded(true); });
        return () => { gone = true; };
    }, []);

    const save = async () => {
        setSaving(true);
        try {
            const r = await settingsApi.putDirectives(text);
            setText(r.directives);
            onToast("Standing orders saved — Neema follows them within ~5 minutes");
        } catch {
            onToast("Couldn't save (admin only)", "error");
        } finally {
            setSaving(false);
        }
    };

    return (
        <SectionCard title="Standing Orders"
            description="Live steering — Neema reads this before every reply. Emphasis only; pricing & payment rules always win.">
            <textarea
                value={text}
                onChange={(e) => setText(e.target.value.slice(0, maxChars))}
                disabled={!loaded}
                rows={4}
                placeholder={'e.g. "Push copes this week — Easter is close. Quote 3-week lead times on made-to-order. Mention the new Ladies Princess Cassock to lady customers."'}
                className="w-full text-xs rounded-lg px-3 py-2 border border-stone-200 focus:outline-none focus:ring-2 focus:ring-[#589b31]/40 resize-y"
            />
            <div className="flex items-center justify-between mt-1">
                <span className="text-[10px] text-stone-400">{text.length}/{maxChars}</span>
                <button onClick={save} disabled={saving || !loaded}
                    className="h-8 px-4 rounded-lg text-xs font-semibold text-white transition-colors flex items-center gap-1.5 disabled:opacity-60"
                    style={{ backgroundColor: "#589b31" }}>
                    {saving && <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                    {saving ? "Saving…" : "Save standing orders"}
                </button>
            </div>
        </SectionCard>
    );
}

/** The team's reading glass. Off by a click when the bill matters, on again by
 *  another — no deploy, no env edit. The 30-day spend sits beside the switch
 *  because "should this stay on?" is a money question, and guessing at it is
 *  how a small feature becomes a scary one. */
function TranslationCard({ onToast }: { onToast: SharedViewProps["onToast"] }) {
    const [state, setState] = useState<ApiTranslationSetting | null>(null);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        let gone = false;
        settingsApi.getTranslation()
            .then((r) => { if (!gone) setState(r); })
            .catch(() => { /* leave the card in its loading state */ });
        return () => { gone = true; };
    }, []);

    const toggle = async () => {
        if (!state || saving) return;
        const next = !state.enabled;
        setState({ ...state, enabled: next });          // optimistic: the switch must feel instant
        setSaving(true);
        try {
            await settingsApi.putTranslation(next);
            onToast(next
                ? "Translation on — foreign messages get an English line from the next thread you open"
                : "Translation off — no new translations will be bought. Ones already saved stay visible.");
        } catch {
            setState({ ...state, enabled: !next });     // put it back; nothing was saved
            onToast("Couldn't change that (admin only)", "error");
        } finally {
            setSaving(false);
        }
    };

    const money = (v: number) =>
        v > 0 && v < 0.01 ? "under $0.01" : `$${v.toFixed(2)}`;

    return (
        <SectionCard title="Translation for the team"
            description="Shows an English line under any message that is not English or Swahili — in both directions, so you can follow a whole conversation. Customers never see it.">
            <div className="flex items-center justify-between gap-4">
                <div className="min-w-0">
                    <p className="text-xs font-semibold text-stone-700">
                        {state === null ? "Loading…" : state.enabled ? "On" : "Off"}
                    </p>
                    <p className="text-[10px] text-stone-400 mt-0.5 leading-relaxed">
                        {state === null
                            ? "\u00a0"
                            : state.calls_30d > 0
                                ? `${money(state.spend_30d_usd)} over the last 30 days · ${state.calls_30d} call${state.calls_30d === 1 ? "" : "s"}`
                                : "Nothing spent in the last 30 days"}
                    </p>
                </div>
                <Toggle checked={!!state?.enabled} onChange={toggle} />
            </div>
            {state !== null && !state.enabled && (
                <p className="text-[10px] text-stone-400 mt-3 leading-relaxed">
                    Translations already saved stay visible — turning this off only stops new ones being bought.
                </p>
            )}
        </SectionCard>
    );
}

/** The offer Neema states outright. Named, sized, scoped and dated — the four
 *  things a customer needs, and the four a vague "we have a discount" leaves
 *  out. Order lines still reach the hub at list price and a person applies the
 *  offer, so the card says so rather than letting anyone assume otherwise. */
function OfferCard({ onToast }: { onToast: SharedViewProps["onToast"] }) {
    const [state, setState] = useState<ApiOfferSetting | null>(null);
    const [draft, setDraft] = useState<ApiCampaign | null>(null);
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        let gone = false;
        settingsApi.getOffer()
            .then((r) => { if (!gone) { setState(r); setDraft(r.campaign); } })
            .catch(() => { /* leave it loading rather than show a wrong state */ });
        return () => { gone = true; };
    }, []);

    const blank = (): ApiCampaign => {
        const end = new Date();
        end.setMonth(end.getMonth() + 1);          // "for 1 month" is the common case
        return { name: "", percent: 10, scope: "all", categories: [], skus: [],
                 starts_on: null, ends_on: end.toISOString().slice(0, 10) };
    };

    const save = async (c: ApiCampaign | null) => {
        setSaving(true);
        try {
            const r = await settingsApi.putOffer(c);
            setState((s) => s ? { ...s, campaign: r.campaign, running: r.running, says: r.says } : s);
            setDraft(r.campaign);
            onToast(r.campaign
                ? `Offer live — Neema will say: ${r.says}`
                : "Offer ended — Neema stops mentioning it from her next reply");
        } catch {
            onToast("Couldn't save that offer (admin only, and it needs a name, a percentage and an end date)", "error");
        } finally {
            setSaving(false);
        }
    };

    const set = (patch: Partial<ApiCampaign>) =>
        setDraft((d) => ({ ...(d ?? blank()), ...patch }));

    const list = (v: string) => v.split(",").map((x) => x.trim()).filter(Boolean);

    return (
        <SectionCard title="Offer running now"
            description="A discount you have given. Neema states it outright — the offer's name, the old price, the new one, and when it ends — and stops the day it expires.">
            {state === null ? (
                <p className="text-xs text-stone-400">Loading…</p>
            ) : (
                <>
                    {state.says && (
                        <p className="text-xs text-[#16270c] bg-[#f3f9ec] border border-[#cee6b2] rounded-lg px-3 py-2 mb-3">
                            Neema says: <span className="font-semibold">{state.says}</span>
                        </p>
                    )}
                    {state.campaign && !state.running && (
                        <p className="text-[10px] text-amber-700 mb-3">
                            This offer has passed its end date — it is saved, but Neema is not mentioning it.
                        </p>
                    )}

                    <Field label="Offer name" hint="What the customer hears it called.">
                        <SmallInput value={draft?.name ?? ""} placeholder="Harvest Offer"
                            onChange={(v: string) => set({ name: v })} />
                    </Field>

                    <div className="grid grid-cols-2 gap-3">
                        <Field label="Discount %" hint={`1–${state.max_percent}`}>
                            <SmallInput type="number" value={String(draft?.percent ?? 10)}
                                onChange={(v: string) => set({ percent: Number(v) || 0 })} />
                        </Field>
                        <Field label="Last day" hint="Inclusive — it runs through this date.">
                            <SmallInput type="date" value={draft?.ends_on ?? ""}
                                onChange={(v: string) => set({ ends_on: v })} />
                        </Field>
                    </div>

                    <Field label="Applies to">
                        <select value={draft?.scope ?? "all"}
                            onChange={(e) => set({ scope: e.target.value as ApiCampaign["scope"] })}
                            className="w-full text-xs rounded-lg px-3 py-2 border border-stone-200 focus:outline-none focus:ring-2 focus:ring-[#589b31]/40">
                            <option value="all">Everything in the catalogue</option>
                            <option value="category">Certain categories</option>
                            <option value="products">Certain products</option>
                        </select>
                    </Field>

                    {draft?.scope === "category" && (
                        <Field label="Categories" hint="Comma-separated, as they appear in the hub. e.g. gowns, cassocks">
                            <SmallInput value={(draft?.categories ?? []).join(", ")}
                                onChange={(v: string) => set({ categories: list(v) })} />
                        </Field>
                    )}
                    {draft?.scope === "products" && (
                        <Field label="Product SKUs" hint="Comma-separated. Only these items get the offer.">
                            <SmallInput value={(draft?.skus ?? []).join(", ")}
                                onChange={(v: string) => set({ skus: list(v) })} />
                        </Field>
                    )}

                    <p className="text-[10px] text-stone-400 mb-3 leading-relaxed">
                        Orders still reach the hub at the list price with the offer noted on them —
                        a person applies it before payment.
                    </p>

                    <div className="flex items-center gap-2">
                        <button onClick={() => save(draft)} disabled={saving}
                            className="h-8 px-4 rounded-lg text-xs font-semibold text-white transition-colors flex items-center gap-1.5 disabled:opacity-60"
                            style={{ backgroundColor: "#589b31" }}>
                            {saving && <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                            {saving ? "Saving…" : state.campaign ? "Update offer" : "Start offer"}
                        </button>
                        {state.campaign && (
                            <button onClick={() => save(null)} disabled={saving}
                                className="h-8 px-4 rounded-lg text-xs font-semibold text-stone-600 border border-stone-200 disabled:opacity-60">
                                End it now
                            </button>
                        )}
                    </div>
                </>
            )}
        </SectionCard>
    );
}

function SectionCard({ title, description, children }: {
    title: string; description?: string; children: React.ReactNode;
}) {
    return (
        <div className="bg-white rounded-xl border border-[#cee6b2] shadow-sm p-5">
            <div className="mb-4">
                <h4 className="text-sm font-semibold text-[#16270c]">{title}</h4>
                {description && <p className="text-xs text-[#699a32] mt-1 leading-relaxed">{description}</p>}
            </div>
            {children}
        </div>
    );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
    return (
        <div className="mb-3">
            <label className="block text-xs font-semibold text-stone-600 mb-1.5">{label}</label>
            {children}
            {hint && <p className="text-[10px] text-stone-400 mt-1">{hint}</p>}
        </div>
    );
}

function SmallInput({ value, onChange, placeholder, type = "text" }: {
    value: string | number; onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
    return (
        <input
            type={type}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            className="w-full h-8 px-2.5 text-xs bg-[#f3f9ec] border border-[#b5da8b] rounded-lg text-stone-800 placeholder-stone-300 focus:outline-none focus:ring-2 focus:ring-[#589b31] focus:border-transparent"
            style={{ fontSize: 12 }}
        />
    );
}

// ── Main component ────────────────────────────────────────────────────────────

export function SettingsView({ onToast, isMobile }: SharedViewProps): React.ReactElement {
    const [savingBiz, setSavingBiz]   = useState(false);
    const [savingAi,  setSavingAi]    = useState(false);
    const [integrations, setIntegrations] = useState<Integration[]>(INTEGRATIONS);
    const [expandedInteg, setExpandedInteg] = useState<string | null>(null);
    const [integConfig, setIntegConfig]     = useState<Record<string, Record<string, string>>>({});

    const [ai, setAi] = useState<AiSettings>({
        auto_intercept_threshold: 3,
        draft_approval: true,
        response_delay_ms: 1500,
        escalation_keywords: "refund, complaint, manager, urgent",
    });

    const [biz, setBiz] = useState<BizSettings>({
        business_name: "Bethany House",
        currency: "KES",
        wa_number: "+254785490805",
        open_hours: "08:00–18:00",
        timezone: "Africa/Nairobi",
    });

    const saveBiz = async () => {
        setSavingBiz(true);
        await new Promise((r) => setTimeout(r, 600));
        setSavingBiz(false);
        onToast("Business settings saved");
    };

    const saveAi = async () => {
        setSavingAi(true);
        await new Promise((r) => setTimeout(r, 600));
        setSavingAi(false);
        onToast("AI settings saved");
    };

    const toggleIntegration = (key: string) => {
        setIntegrations((prev) => prev.map((i) =>
            i.key === key ? { ...i, status: i.status === "connected" ? "disconnected" : "connected" } : i
        ));
        const integ = integrations.find((i) => i.key === key);
        onToast(`${integ?.name} ${integ?.status === "connected" ? "disconnected" : "connected"}`);
    };

    const saveIntegConfig = (key: string) => {
        onToast(`${integrations.find((i) => i.key === key)?.name} settings saved`);
        setExpandedInteg(null);
    };

    return (
        <div className={`flex-1 overflow-y-auto bg-[#f3f9ec] ${isMobile ? "p-4 pb-24" : "p-6"}`}>
            <div className="mb-6">
                <h1 className="text-xl font-bold text-[#16270c] tracking-tight">Settings</h1>
                <p className="text-xs text-[#699a32] mt-0.5">Platform configuration and integrations</p>
            </div>

            <div className={`grid gap-4 ${isMobile ? "grid-cols-1" : "grid-cols-2"} mb-4`}>

                {/* Business */}
                <StandingOrdersCard onToast={onToast} />
                <TranslationCard onToast={onToast} />
                <OfferCard onToast={onToast} />

                <SectionCard title="Business" description="Core platform details">
                    <div className="grid grid-cols-2 gap-x-3">
                        <Field label="Business Name">
                            <SmallInput value={biz.business_name} onChange={(v) => setBiz((s) => ({ ...s, business_name: v }))} placeholder="Bethany House" />
                        </Field>
                        <Field label="Currency">
                            <SmallInput value={biz.currency} onChange={(v) => setBiz((s) => ({ ...s, currency: v }))} placeholder="KES" />
                        </Field>
                        <Field label="WhatsApp Number">
                            <SmallInput value={biz.wa_number} onChange={(v) => setBiz((s) => ({ ...s, wa_number: v }))} placeholder="+254..." />
                        </Field>
                        <Field label="Timezone">
                            <SmallInput value={biz.timezone} onChange={(v) => setBiz((s) => ({ ...s, timezone: v }))} placeholder="Africa/Nairobi" />
                        </Field>
                        <Field label="Open Hours" hint="Shown to customers">
                            <SmallInput value={biz.open_hours} onChange={(v) => setBiz((s) => ({ ...s, open_hours: v }))} placeholder="08:00–18:00" />
                        </Field>
                    </div>
                    <button onClick={saveBiz} disabled={savingBiz}
                        className="mt-1 h-8 px-4 rounded-lg text-xs font-semibold text-white transition-colors flex items-center gap-1.5 disabled:opacity-60"
                        style={{ backgroundColor: "#589b31" }}>
                        {savingBiz && <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                        {savingBiz ? "Saving…" : "Save"}
                    </button>
                </SectionCard>

                {/* AI */}
                <SectionCard title="AI Configuration" description="How the AI handles conversations">
                    <div className="grid grid-cols-2 gap-x-3">
                        <Field label="Escalation Threshold" hint="Messages before escalating">
                            <SmallInput value={ai.auto_intercept_threshold} type="number"
                                onChange={(v) => setAi((s) => ({ ...s, auto_intercept_threshold: Number(v) }))} />
                        </Field>
                        <Field label="Response Delay (ms)" hint="Typing simulation">
                            <SmallInput value={ai.response_delay_ms} type="number"
                                onChange={(v) => setAi((s) => ({ ...s, response_delay_ms: Number(v) }))} />
                        </Field>
                    </div>
                    <Field label="Escalation Keywords" hint="Comma-separated trigger words">
                        <SmallInput value={ai.escalation_keywords}
                            onChange={(v) => setAi((s) => ({ ...s, escalation_keywords: v }))}
                            placeholder="refund, complaint, manager" />
                    </Field>
                    <div className="flex items-center justify-between py-3 border-y border-[#e6f3d8] mb-3">
                        <div>
                            <div className="text-xs font-medium text-[#16270c]">Require draft approval</div>
                            <div className="text-[10px] text-stone-400 mt-0.5">AI drafts need agent approval before sending</div>
                        </div>
                        <Toggle checked={ai.draft_approval}
                            onChange={() => setAi((s) => ({ ...s, draft_approval: !s.draft_approval }))} />
                    </div>
                    <button onClick={saveAi} disabled={savingAi}
                        className="h-8 px-4 rounded-lg text-xs font-semibold text-white transition-colors flex items-center gap-1.5 disabled:opacity-60"
                        style={{ backgroundColor: "#589b31" }}>
                        {savingAi && <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                        {savingAi ? "Saving…" : "Save AI Settings"}
                    </button>
                </SectionCard>
            </div>

            {/* Integrations */}
            <SectionCard title="Integrations" description="Connected platforms and services">
                <div className="space-y-1">
                    {integrations.map((integ) => {
                        const isConnected = integ.status === "connected";
                        const isExpanded  = expandedInteg === integ.key;
                        const iconMeta    = PLATFORM_ICONS[integ.key];
                        const IconComp    = iconMeta.component;
                        const cfg         = integConfig[integ.key] ?? {};

                        return (
                            <div key={integ.key} className="border border-[#e6f3d8] rounded-xl overflow-hidden">
                                {/* Row */}
                                <div className="flex items-center gap-3 px-4 py-3">
                                    {/* Platform icon */}
                                    <div className="w-9 h-9 rounded-xl flex items-center justify-center text-white flex-shrink-0 shadow-sm"
                                        style={{ background: iconMeta.bg }}>
                                        <IconComp />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-xs font-semibold text-[#16270c]">{integ.name}</div>
                                        <div className="flex items-center gap-1.5 mt-0.5">
                                            <div className={`w-1.5 h-1.5 rounded-full ${isConnected ? "bg-[#589b31]" : "bg-stone-300"}`} />
                                            <span className={`text-[10px] font-medium ${isConnected ? "text-[#589b31]" : "text-stone-400"}`}>
                                                {isConnected ? "Connected" : "Not connected"}
                                            </span>
                                            <span className="text-stone-200">·</span>
                                            <span className="text-[10px] text-stone-400 truncate">{integ.description}</span>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-1.5 flex-shrink-0">
                                        {integ.configFields && (
                                            <button
                                                onClick={() => setExpandedInteg(isExpanded ? null : integ.key)}
                                                className="h-7 px-2.5 rounded-lg text-[10px] font-semibold border transition-colors"
                                                style={{
                                                    backgroundColor: isExpanded ? "#e6f3d8" : "white",
                                                    color: "#589b31",
                                                    borderColor: "#b5da8b",
                                                }}
                                            >
                                                {isExpanded ? "Close" : "Configure"}
                                            </button>
                                        )}
                                        <button
                                            onClick={() => toggleIntegration(integ.key)}
                                            className="h-7 px-2.5 rounded-lg text-[10px] font-semibold transition-colors"
                                            style={isConnected
                                                ? { backgroundColor: "#fff5f5", color: "#c0392b", border: "1px solid #fecaca" }
                                                : { backgroundColor: "#f0f9ec", color: "#589b31", border: "1px solid #b5da8b" }}
                                        >
                                            {isConnected ? "Disconnect" : "Connect"}
                                        </button>
                                    </div>
                                </div>

                                {/* Config panel */}
                                {isExpanded && integ.configFields && (
                                    <div className="border-t border-[#e6f3d8] bg-[#f3f9ec] px-4 py-4">
                                        <div className="grid grid-cols-2 gap-3 mb-3">
                                            {integ.configFields.map((field) => (
                                                <Field key={field.key} label={field.label}>
                                                    <SmallInput
                                                        type={field.type}
                                                        value={cfg[field.key] ?? ""}
                                                        onChange={(v) => setIntegConfig((prev) => ({
                                                            ...prev,
                                                            [integ.key]: { ...(prev[integ.key] ?? {}), [field.key]: v },
                                                        }))}
                                                        placeholder={field.placeholder}
                                                    />
                                                </Field>
                                            ))}
                                        </div>
                                        <button
                                            onClick={() => saveIntegConfig(integ.key)}
                                            className="h-7 px-4 rounded-lg text-[10px] font-semibold text-white"
                                            style={{ backgroundColor: "#589b31" }}
                                        >
                                            Save Configuration
                                        </button>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </SectionCard>

            {/* Danger zone */}
            <div className="mt-4">
                <SectionCard title="Danger Zone" description="Irreversible actions. Proceed with caution.">
                    <div className="space-y-2">
                        {[
                            { label: "Clear conversation history", sub: "Permanently delete messages older than 90 days", action: "Clear" },
                            { label: "Reset AI memory",            sub: "Clear all customer facts and session history",    action: "Reset" },
                        ].map((item) => (
                            <div key={item.label} className="flex items-center justify-between p-3 rounded-lg border border-red-100 bg-red-50">
                                <div>
                                    <div className="text-xs font-medium text-red-800">{item.label}</div>
                                    <div className="text-[10px] text-red-500 mt-0.5">{item.sub}</div>
                                </div>
                                <button
                                    onClick={() => onToast("Requires confirmation — coming soon", "warning")}
                                    className="flex-shrink-0 h-7 px-3 rounded-lg text-xs font-semibold bg-red-100 text-red-700 border border-red-200 hover:bg-red-200 transition-colors"
                                >
                                    {item.action}
                                </button>
                            </div>
                        ))}
                    </div>
                </SectionCard>
            </div>
        </div>
    );
}
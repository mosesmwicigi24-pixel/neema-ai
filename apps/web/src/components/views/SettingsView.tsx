// SettingsView.tsx
import React, { useState } from "react";
import { Toggle } from "@/components/ui/Layout";
import { InputField } from "@/components/ui/FormFields";
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

const N8NIcon = () => (
    <svg viewBox="0 0 32 32" className="w-5 h-5" fill="none">
        <rect width="32" height="32" rx="6" fill="#EA4B71"/>
        <text x="4" y="22" fontSize="12" fontWeight="bold" fill="white" fontFamily="Arial">n8n</text>
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

type IconKey = "whatsapp" | "messenger" | "instagram" | "mpesa" | "n8n" | "email" | "slack" | "sheets";

const PLATFORM_ICONS: Record<IconKey, { component: React.FC; bg: string; color: string }> = {
    whatsapp:  { component: WhatsAppIcon,  bg: "#25D366", color: "white" },
    messenger: { component: MessengerIcon, bg: "#0099FF", color: "white" },
    instagram: { component: InstagramIcon, bg: "linear-gradient(45deg,#f09433,#e6683c,#dc2743,#cc2366,#bc1888)", color: "white" },
    mpesa:     { component: MPesaIcon,     bg: "#00A651", color: "white" },
    n8n:       { component: N8NIcon,       bg: "#EA4B71", color: "white" },
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
        key: "n8n", name: "n8n Automation", status: "connected",
        description: "Workflow automation engine",
        configFields: [
            { label: "Webhook URL", key: "n8n_url",    placeholder: "https://n8n.yourhost.com/webhook/…" },
            { label: "API Secret",  key: "n8n_secret", type: "password", placeholder: "zXsH8…" },
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
import React, { useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { Toggle } from "@/components/ui/Layout";
import { InputField } from "@/components/ui/FormFields";
import type { SharedViewProps } from "@/types";

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
interface Integration {
    name: string;
    status: "connected" | "disconnected";
    icon: string;
    description: string;
}

const INTEGRATIONS: Integration[] = [
    {
        name: "WhatsApp Business API",
        status: "connected",
        icon: "📱",
        description: "Primary messaging channel",
    },
    {
        name: "Facebook Messenger",
        status: "connected",
        icon: "💙",
        description: "Meta messaging platform",
    },
    {
        name: "Instagram DMs",
        status: "connected",
        icon: "📸",
        description: "Instagram direct messages",
    },
    {
        name: "M-Pesa Daraja API",
        status: "connected",
        icon: "💳",
        description: "Mobile payment processing",
    },
    {
        name: "n8n Automation",
        status: "connected",
        icon: "⚙️",
        description: "Workflow automation",
    },
    {
        name: "Email (SMTP)",
        status: "connected",
        icon: "📧",
        description: "Email channel integration",
    },
    {
        name: "Slack Notifications",
        status: "disconnected",
        icon: "💬",
        description: "Team alert channel",
    },
    {
        name: "Google Sheets",
        status: "disconnected",
        icon: "📊",
        description: "Data export and reporting",
    },
];

function SectionCard({
    title,
    description,
    children,
}: {
    title: string;
    description?: string;
    children: React.ReactNode;
}) {
    return (
        <div className="bg-white rounded-xl border border-stone-100 shadow-sm p-5">
            <div className="mb-5">
                <h4 className="text-sm font-semibold text-stone-800">
                    {title}
                </h4>
                {description && (
                    <p className="text-xs text-stone-400 mt-1 leading-relaxed">
                        {description}
                    </p>
                )}
            </div>
            {children}
        </div>
    );
}

export function SettingsView({
    onToast,
    isMobile,
}: SharedViewProps): React.ReactElement {
    const [ai, setAi] = useState<AiSettings>({
        auto_intercept_threshold: 3,
        draft_approval: true,
        response_delay_ms: 1500,
        escalation_keywords: "refund, complaint, manager, urgent",
    });
    const [biz, setBiz] = useState<BizSettings>({
        business_name: "Neema",
        currency: "KES",
        wa_number: "+254712000000",
        open_hours: "08:00–22:00",
        timezone: "Africa/Nairobi",
    });

    return (
        <div
            className={`flex-1 overflow-y-auto bg-stone-50 ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            {/* Header */}
            <div className="mb-6">
                <h1 className="text-xl font-bold text-stone-800 tracking-tight">
                    Settings
                </h1>
                <p className="text-sm text-stone-400 mt-0.5">
                    Configure AI behavior, business info, and integrations
                </p>
            </div>

            <div className="space-y-4">
                {/* Business info */}
                <SectionCard title="Business Information">
                    <div
                        className={`grid gap-x-4 ${isMobile ? "grid-cols-1" : "grid-cols-2"}`}
                    >
                        <InputField
                            label="Business Name"
                            value={biz.business_name}
                            onChange={(v) =>
                                setBiz((s) => ({ ...s, business_name: v }))
                            }
                        />
                        <InputField
                            label="WhatsApp Number"
                            value={biz.wa_number}
                            onChange={(v) =>
                                setBiz((s) => ({ ...s, wa_number: v }))
                            }
                        />
                        <InputField
                            label="Currency"
                            value={biz.currency}
                            onChange={(v) =>
                                setBiz((s) => ({ ...s, currency: v }))
                            }
                        />
                        <InputField
                            label="Operating Hours"
                            value={biz.open_hours}
                            onChange={(v) =>
                                setBiz((s) => ({ ...s, open_hours: v }))
                            }
                        />
                        <InputField
                            label="Timezone"
                            value={biz.timezone}
                            onChange={(v) =>
                                setBiz((s) => ({ ...s, timezone: v }))
                            }
                            hint="IANA identifier e.g. Africa/Nairobi"
                        />
                    </div>
                    <button
                        onClick={() => onToast("Business settings saved")}
                        className="h-9 px-5 rounded-lg text-sm font-semibold text-white bg-green-700 hover:bg-green-600 transition-colors shadow-sm"
                    >
                        Save Changes
                    </button>
                </SectionCard>

                {/* AI config */}
                <SectionCard
                    title="AI Configuration"
                    description="Control how the AI handles conversations and when to escalate to agents."
                >
                    <div
                        className={`grid gap-x-4 ${isMobile ? "grid-cols-1" : "grid-cols-2"}`}
                    >
                        <InputField
                            label="Escalation Threshold"
                            value={ai.auto_intercept_threshold}
                            type="number"
                            onChange={(v) =>
                                setAi((s) => ({
                                    ...s,
                                    auto_intercept_threshold: Number(v),
                                }))
                            }
                            hint="Escalate after N unanswered messages"
                        />
                        <InputField
                            label="Response Delay (ms)"
                            value={ai.response_delay_ms}
                            type="number"
                            onChange={(v) =>
                                setAi((s) => ({
                                    ...s,
                                    response_delay_ms: Number(v),
                                }))
                            }
                            hint="Simulate human-like typing delay"
                        />
                    </div>
                    <InputField
                        label="Escalation Keywords"
                        value={ai.escalation_keywords}
                        onChange={(v) =>
                            setAi((s) => ({ ...s, escalation_keywords: v }))
                        }
                        hint="Comma-separated words that trigger human handover"
                    />

                    {/* Draft approval toggle */}
                    <div className="flex items-center justify-between py-4 border-y border-stone-100 mb-4">
                        <div>
                            <div className="text-sm font-medium text-stone-800">
                                Require draft approval
                            </div>
                            <div className="text-xs text-stone-400 mt-0.5">
                                AI drafts must be approved before sending
                            </div>
                        </div>
                        <Toggle
                            checked={ai.draft_approval}
                            onChange={() =>
                                setAi((s) => ({
                                    ...s,
                                    draft_approval: !s.draft_approval,
                                }))
                            }
                        />
                    </div>

                    <button
                        onClick={() => onToast("AI settings saved")}
                        className="h-9 px-5 rounded-lg text-sm font-semibold text-white bg-green-700 hover:bg-green-600 transition-colors shadow-sm"
                    >
                        Save AI Settings
                    </button>
                </SectionCard>

                {/* Integrations */}
                <SectionCard title="Integrations">
                    <div className="divide-y divide-stone-100">
                        {INTEGRATIONS.map((integ) => {
                            const isConnected = integ.status === "connected";
                            return (
                                <div
                                    key={integ.name}
                                    className="flex items-center justify-between py-3.5 gap-4 group"
                                >
                                    <div className="flex items-center gap-3 min-w-0">
                                        <div className="w-9 h-9 rounded-xl bg-stone-50 border border-stone-100 flex items-center justify-center text-lg flex-shrink-0">
                                            {integ.icon}
                                        </div>
                                        <div className="min-w-0">
                                            <div className="text-sm font-semibold text-stone-800 truncate">
                                                {integ.name}
                                            </div>
                                            <div className="flex items-center gap-1.5 mt-0.5">
                                                <div
                                                    className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${isConnected ? "bg-emerald-500" : "bg-stone-300"}`}
                                                />
                                                <span
                                                    className={`text-xs font-medium ${isConnected ? "text-emerald-600" : "text-stone-400"}`}
                                                >
                                                    {isConnected
                                                        ? "Connected"
                                                        : "Not connected"}
                                                </span>
                                                <span className="text-stone-200">
                                                    ·
                                                </span>
                                                <span className="text-xs text-stone-400 truncate">
                                                    {integ.description}
                                                </span>
                                            </div>
                                        </div>
                                    </div>
                                    <button
                                        onClick={() =>
                                            onToast(
                                                `${integ.name} ${isConnected ? "disconnected" : "connected"}`,
                                            )
                                        }
                                        className={`flex-shrink-0 h-8 px-3 rounded-lg text-xs font-semibold transition-colors ${
                                            isConnected
                                                ? "bg-red-50 text-red-600 border border-red-200 hover:bg-red-100"
                                                : "bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100"
                                        }`}
                                    >
                                        {isConnected ? "Disconnect" : "Connect"}
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                </SectionCard>
            </div>
        </div>
    );
}
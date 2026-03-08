import React, { useState } from "react";
import { Btn } from "@/components/ui/Btn";
import { Card, SectionHeader, Toggle } from "@/components/ui/Layout";
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
            className={`flex-1 overflow-y-auto ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            <SectionHeader
                title="System Settings"
                subtitle="Configure AI behavior, business info, and integrations"
            />

            <div className="space-y-5">
                {/* Business info */}
                <Card>
                    <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-5">
                        Business Information
                    </h4>
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
                    <Btn
                        onClick={() => onToast("Business settings saved")}
                        variant="primary"
                        size="sm"
                    >
                        Save Changes
                    </Btn>
                </Card>

                {/* AI Configuration */}
                <Card>
                    <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-1">
                        AI Configuration
                    </h4>
                    <p className="text-sm text-gray-500 dark:text-gray-400 mb-5">
                        Control how the AI handles conversations and when to
                        escalate to agents.
                    </p>
                    <div
                        className={`grid gap-x-4 ${isMobile ? "grid-cols-1" : "grid-cols-2"}`}
                    >
                        <InputField
                            label="Escalation Threshold"
                            value={ai.auto_intercept_threshold}
                            onChange={(v) =>
                                setAi((s) => ({
                                    ...s,
                                    auto_intercept_threshold: Number(v),
                                }))
                            }
                            type="number"
                            hint="Escalate after N unanswered messages"
                        />
                        <InputField
                            label="Response Delay (ms)"
                            value={ai.response_delay_ms}
                            onChange={(v) =>
                                setAi((s) => ({
                                    ...s,
                                    response_delay_ms: Number(v),
                                }))
                            }
                            type="number"
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
                    <div className="flex items-center justify-between py-4 border-y border-gray-100 dark:border-gray-800 mb-4">
                        <div>
                            <div className="text-sm font-medium text-gray-900 dark:text-white">
                                Require draft approval
                            </div>
                            <div className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
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
                    <Btn
                        onClick={() => onToast("AI settings saved")}
                        variant="primary"
                        size="sm"
                    >
                        Save AI Settings
                    </Btn>
                </Card>

                {/* Integrations */}
                <Card>
                    <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-5">
                        Integrations
                    </h4>
                    <div className="divide-y divide-gray-100 dark:divide-gray-800">
                        {INTEGRATIONS.map((integ) => (
                            <div
                                key={integ.name}
                                className="flex items-center justify-between py-3.5 gap-4"
                            >
                                <div className="flex items-center gap-3 min-w-0">
                                    <div className="w-9 h-9 rounded-xl bg-gray-50 dark:bg-gray-800 border border-gray-100 dark:border-gray-700 flex items-center justify-center text-lg flex-shrink-0">
                                        {integ.icon}
                                    </div>
                                    <div className="min-w-0">
                                        <div className="text-sm font-medium text-gray-900 dark:text-white truncate">
                                            {integ.name}
                                        </div>
                                        <div className="flex items-center gap-1.5 mt-0.5">
                                            <div
                                                className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${integ.status === "connected" ? "bg-emerald-500" : "bg-gray-400"}`}
                                            />
                                            <span
                                                className={`text-xs ${integ.status === "connected" ? "text-emerald-600 dark:text-emerald-400" : "text-gray-400"}`}
                                            >
                                                {integ.status === "connected"
                                                    ? "Connected"
                                                    : "Not connected"}
                                            </span>
                                            <span className="text-gray-300 dark:text-gray-600">
                                                ·
                                            </span>
                                            <span className="text-xs text-gray-400 truncate">
                                                {integ.description}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                                <Btn
                                    size="xs"
                                    onClick={() =>
                                        onToast(
                                            `${integ.name} ${integ.status === "connected" ? "disconnected" : "connected"}`,
                                        )
                                    }
                                    variant={
                                        integ.status === "connected"
                                            ? "danger"
                                            : "success"
                                    }
                                >
                                    {integ.status === "connected"
                                        ? "Disconnect"
                                        : "Connect"}
                                </Btn>
                            </div>
                        ))}
                    </div>
                </Card>
            </div>
        </div>
    );
}

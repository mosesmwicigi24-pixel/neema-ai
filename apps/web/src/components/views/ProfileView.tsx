import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { RoleBadge } from "@/components/ui/Badges";
import { Btn } from "@/components/ui/Btn";
import { Card, SectionHeader, Divider, Toggle } from "@/components/ui/Layout";
import { InputField } from "@/components/ui/FormFields";
import { fmtDate } from "@/lib/utils";
import { ALL_PERMISSIONS } from "@/lib/mockData";
import type { Agent, Session, ThemeMode, SharedViewProps } from "@/types";

interface ProfileViewProps extends SharedViewProps {
    session: Session;
    agents: Agent[];
    setAgents: React.Dispatch<React.SetStateAction<Agent[]>>;
    theme: ThemeMode;
    setTheme: React.Dispatch<React.SetStateAction<ThemeMode>>;
}

interface NotifSettings {
    new_conv: boolean;
    human_transfer: boolean;
    order_updates: boolean;
    daily_summary: boolean;
}

export function ProfileView({
    session,
    agents,
    setAgents,
    onToast,
    theme,
    setTheme,
    isMobile,
}: ProfileViewProps): React.ReactElement {
    const agent =
        agents.find((a) => a.email === session.user.email) ?? agents[2];
    const [editMode, setEditMode] = useState(false);
    const [form, setForm] = useState({
        name: agent.name,
        email: agent.email,
        department: agent.department ?? "",
    });
    const [notifs, setNotifs] = useState<NotifSettings>({
        new_conv: true,
        human_transfer: true,
        order_updates: false,
        daily_summary: true,
    });

    const save = () => {
        setAgents((as) =>
            as.map((a) => (a.id === agent.id ? { ...a, ...form } : a)),
        );
        setEditMode(false);
        onToast("Profile updated");
    };

    const permKeys = agent.permissions.includes("all")
        ? ALL_PERMISSIONS.map((p) => p.key)
        : agent.permissions;

    return (
        <div
            className={`flex-1 overflow-y-auto ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            <SectionHeader
                title="My Profile"
                subtitle="Manage account, preferences and security"
            />

            <div
                className={`grid gap-5 ${isMobile ? "grid-cols-1" : "grid-cols-[320px_1fr]"}`}
            >
                {/* Left column */}
                <div className="space-y-4">
                    {/* Profile card */}
                    <Card className="text-center">
                        <div className="flex justify-center mb-4">
                            <div className="relative">
                                <Avatar name={agent.name} size="xl" />
                                <div
                                    className={`absolute bottom-1 right-1 w-4 h-4 rounded-full ring-2 ring-white dark:ring-gray-900 ${agent.is_available ? "bg-emerald-500" : "bg-gray-400"}`}
                                />
                            </div>
                        </div>
                        <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-1">
                            {agent.name}
                        </h3>
                        <p className="text-sm text-gray-500 dark:text-gray-400 mb-3">
                            {agent.email}
                        </p>
                        <div className="flex justify-center gap-2 mb-4">
                            <RoleBadge role={agent.role} />
                            {agent.department && (
                                <span className="text-xs bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400 px-2 py-0.5 rounded-lg">
                                    {agent.department}
                                </span>
                            )}
                        </div>
                        <Divider />
                        <div className="grid grid-cols-2 gap-2">
                            {(
                                [
                                    ["Active", agent.active_convs],
                                    [
                                        "Since",
                                        agent.joined_at
                                            ? fmtDate(agent.joined_at)
                                            : "—",
                                    ],
                                ] as [string, string | number][]
                            ).map(([k, v]) => (
                                <div
                                    key={k}
                                    className="bg-gray-50 dark:bg-gray-800 rounded-xl p-3"
                                >
                                    <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">
                                        {k}
                                    </div>
                                    <div className="text-sm font-bold text-gray-900 dark:text-white">
                                        {v}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </Card>

                    {/* Permissions */}
                    <Card>
                        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                            Your Permissions
                        </h4>
                        <div className="space-y-1.5">
                            {permKeys.map((perm) => (
                                <div
                                    key={perm}
                                    className="flex items-center gap-2 py-1"
                                >
                                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 flex-shrink-0" />
                                    <span className="text-xs text-gray-600 dark:text-gray-400">
                                        {ALL_PERMISSIONS.find(
                                            (p) => p.key === perm,
                                        )?.label ?? perm}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </Card>
                </div>

                {/* Right column */}
                <div className="space-y-4">
                    {/* Account info */}
                    <Card>
                        <div className="flex justify-between items-center mb-4">
                            <h4 className="text-sm font-semibold text-gray-900 dark:text-white">
                                Account Information
                            </h4>
                            {!editMode && (
                                <Btn
                                    size="xs"
                                    onClick={() => setEditMode(true)}
                                    variant="outline"
                                >
                                    Edit
                                </Btn>
                            )}
                        </div>
                        {editMode ? (
                            <>
                                <InputField
                                    label="Full Name"
                                    value={form.name}
                                    onChange={(v) =>
                                        setForm((f) => ({ ...f, name: v }))
                                    }
                                />
                                <InputField
                                    label="Email"
                                    value={form.email}
                                    onChange={(v) =>
                                        setForm((f) => ({ ...f, email: v }))
                                    }
                                    type="email"
                                />
                                <InputField
                                    label="Department"
                                    value={form.department}
                                    onChange={(v) =>
                                        setForm((f) => ({
                                            ...f,
                                            department: v,
                                        }))
                                    }
                                    placeholder="e.g. Support"
                                />
                                <div className="flex gap-2">
                                    <Btn
                                        onClick={save}
                                        variant="primary"
                                        size="sm"
                                    >
                                        Save Changes
                                    </Btn>
                                    <Btn
                                        onClick={() => setEditMode(false)}
                                        variant="outline"
                                        size="sm"
                                    >
                                        Cancel
                                    </Btn>
                                </div>
                            </>
                        ) : (
                            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                                {(
                                    [
                                        ["Name", agent.name],
                                        ["Email", agent.email],
                                        ["Department", agent.department || "—"],
                                    ] as [string, string][]
                                ).map(([k, v]) => (
                                    <div
                                        key={k}
                                        className="bg-gray-50 dark:bg-gray-800 rounded-xl p-3"
                                    >
                                        <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">
                                            {k}
                                        </div>
                                        <div className="text-sm text-gray-900 dark:text-white font-medium truncate">
                                            {v}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </Card>

                    {/* Appearance */}
                    <Card>
                        <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">
                            Appearance
                        </h4>
                        <div className="grid grid-cols-2 gap-3">
                            {(["light", "dark"] as ThemeMode[]).map((t) => (
                                <button
                                    key={t}
                                    onClick={() => setTheme(t)}
                                    className={`p-4 rounded-xl border-2 transition-all ${theme === t ? "border-amber-500 bg-amber-50 dark:bg-amber-950/20" : "border-gray-200 dark:border-gray-700 hover:border-gray-300"}`}
                                >
                                    <div
                                        className={`w-full h-12 rounded-lg mb-3 flex items-start p-2 gap-1.5 ${t === "light" ? "bg-white border border-gray-200" : "bg-gray-900 border border-gray-700"}`}
                                    >
                                        <div
                                            className={`w-14 h-1.5 rounded-full ${t === "light" ? "bg-gray-200" : "bg-gray-700"}`}
                                        />
                                        <div
                                            className={`w-8 h-1.5 rounded-full ${t === "light" ? "bg-amber-300" : "bg-amber-500"}`}
                                        />
                                    </div>
                                    <div
                                        className={`text-sm font-semibold capitalize ${theme === t ? "text-amber-700 dark:text-amber-300" : "text-gray-600 dark:text-gray-400"}`}
                                    >
                                        {t} {theme === t ? "✓" : ""}
                                    </div>
                                </button>
                            ))}
                        </div>
                    </Card>

                    {/* Notifications */}
                    <Card>
                        <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">
                            Notifications
                        </h4>
                        <div className="divide-y divide-gray-100 dark:divide-gray-800">
                            {[
                                {
                                    key: "new_conv" as keyof NotifSettings,
                                    label: "New conversation assigned",
                                    desc: "When assigned to you",
                                },
                                {
                                    key: "human_transfer" as keyof NotifSettings,
                                    label: "Human takeover requests",
                                    desc: "When AI flags for you",
                                },
                                {
                                    key: "order_updates" as keyof NotifSettings,
                                    label: "Order status changes",
                                    desc: "Confirmations and deliveries",
                                },
                                {
                                    key: "daily_summary" as keyof NotifSettings,
                                    label: "Daily digest",
                                    desc: "End-of-day performance report",
                                },
                            ].map((item) => (
                                <div
                                    key={item.key}
                                    className="flex items-center justify-between py-3 gap-3"
                                >
                                    <div>
                                        <div className="text-sm font-medium text-gray-900 dark:text-white">
                                            {item.label}
                                        </div>
                                        <div className="text-xs text-gray-400 dark:text-gray-500">
                                            {item.desc}
                                        </div>
                                    </div>
                                    <Toggle
                                        checked={notifs[item.key]}
                                        onChange={() =>
                                            setNotifs((s) => ({
                                                ...s,
                                                [item.key]: !s[item.key],
                                            }))
                                        }
                                    />
                                </div>
                            ))}
                        </div>
                    </Card>

                    {/* Security */}
                    <Card>
                        <h4 className="text-sm font-semibold text-gray-900 dark:text-white mb-4">
                            Security
                        </h4>
                        <div className="flex gap-2 flex-wrap">
                            <Btn
                                onClick={() =>
                                    onToast("Password reset email sent")
                                }
                                variant="outline"
                                size="sm"
                            >
                                Change Password
                            </Btn>
                            <Btn
                                onClick={() => onToast("2FA setup initiated")}
                                variant="blue"
                                size="sm"
                            >
                                Enable 2FA
                            </Btn>
                        </div>
                    </Card>
                </div>
            </div>
        </div>
    );
}
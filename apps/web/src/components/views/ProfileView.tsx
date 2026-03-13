import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { RoleBadge } from "@/components/ui/Badges";
import { Btn } from "@/components/ui/Btn";
import { Toggle } from "@/components/ui/Layout";
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

    const notifItems = [
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
    ];

    return (
        <div
            className={`flex-1 overflow-y-auto bg-stone-50 ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            {/* Page header */}
            <div className="mb-6">
                <h1 className="text-xl font-bold text-stone-800 tracking-tight">
                    My Profile
                </h1>
                <p className="text-sm text-stone-400 mt-0.5">
                    Manage account, preferences and security
                </p>
            </div>

            <div
                className={`grid gap-5 ${isMobile ? "grid-cols-1" : "grid-cols-[300px_1fr]"}`}
            >
                {/* ── Left column ──────────────────────────────────────────── */}
                <div className="space-y-4">
                    {/* Profile card */}
                    <div className="bg-white rounded-xl border border-stone-100 shadow-sm p-5 text-center">
                        <div className="flex justify-center mb-4">
                            <div className="relative">
                                <Avatar name={agent.name} size="xl" />
                                <div
                                    className={`absolute bottom-1 right-1 w-3.5 h-3.5 rounded-full ring-2 ring-white ${agent.is_available ? "bg-emerald-500" : "bg-stone-300"}`}
                                />
                            </div>
                        </div>
                        <h3 className="text-base font-bold text-stone-800 mb-0.5">
                            {agent.name}
                        </h3>
                        <p className="text-sm text-stone-400 mb-3">
                            {agent.email}
                        </p>
                        <div className="flex justify-center gap-2 mb-4">
                            <RoleBadge role={agent.role} />
                            {agent.department && (
                                <span className="text-xs bg-stone-100 text-stone-500 px-2 py-0.5 rounded-md">
                                    {agent.department}
                                </span>
                            )}
                        </div>
                        <div className="border-t border-stone-100 pt-4 grid grid-cols-2 gap-2">
                            {(
                                [
                                    ["Active convs", agent.active_convs],
                                    [
                                        "Member since",
                                        agent.joined_at
                                            ? fmtDate(agent.joined_at)
                                            : "—",
                                    ],
                                ] as [string, string | number][]
                            ).map(([k, v]) => (
                                <div
                                    key={k}
                                    className="bg-stone-50 rounded-lg p-3"
                                >
                                    <div className="text-xs text-stone-400 mb-1">
                                        {k}
                                    </div>
                                    <div className="text-sm font-bold text-stone-800">
                                        {v}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Permissions */}
                    <div className="bg-white rounded-xl border border-stone-100 shadow-sm p-5">
                        <h4 className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-3">
                            Your Permissions
                        </h4>
                        <div className="space-y-1">
                            {permKeys.map((perm) => (
                                <div
                                    key={perm}
                                    className="flex items-center gap-2 py-1"
                                >
                                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
                                    <span className="text-xs text-stone-500">
                                        {ALL_PERMISSIONS.find(
                                            (p) => p.key === perm,
                                        )?.label ?? perm}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                {/* ── Right column ─────────────────────────────────────────── */}
                <div className="space-y-4">
                    {/* Account info */}
                    <div className="bg-white rounded-xl border border-stone-100 shadow-sm p-5">
                        <div className="flex items-center justify-between mb-4">
                            <h4 className="text-sm font-semibold text-stone-800">
                                Account Information
                            </h4>
                            {!editMode && (
                                <button
                                    onClick={() => setEditMode(true)}
                                    className="h-7 px-3 rounded-md text-xs font-medium text-stone-600 bg-stone-100 hover:bg-stone-200 transition-colors"
                                >
                                    Edit
                                </button>
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
                                        className="bg-stone-50 rounded-lg p-3"
                                    >
                                        <div className="text-xs text-stone-400 mb-1">
                                            {k}
                                        </div>
                                        <div className="text-sm text-stone-800 font-medium truncate">
                                            {v}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Appearance */}
                    <div className="bg-white rounded-xl border border-stone-100 shadow-sm p-5">
                        <h4 className="text-sm font-semibold text-stone-800 mb-4">
                            Appearance
                        </h4>
                        <div className="grid grid-cols-2 gap-3">
                            {(["light", "dark"] as ThemeMode[]).map((t) => (
                                <button
                                    key={t}
                                    onClick={() => setTheme(t)}
                                    className={`p-4 rounded-xl border-2 transition-all text-left ${theme === t ? "border-green-600 bg-green-50 shadow-sm" : "border-stone-200 hover:border-stone-300"}`}
                                >
                                    {/* Preview */}
                                    <div
                                        className={`w-full h-10 rounded-lg mb-3 flex items-start gap-1.5 p-2 overflow-hidden ${t === "light" ? "bg-white border border-stone-200" : "bg-stone-900 border border-stone-700"}`}
                                    >
                                        <div
                                            className={`w-12 h-1.5 rounded-full mt-0.5 ${t === "light" ? "bg-stone-200" : "bg-stone-700"}`}
                                        />
                                        <div
                                            className={`w-7 h-1.5 rounded-full mt-0.5 ${t === "light" ? "bg-green-500" : "bg-green-700"}`}
                                        />
                                    </div>
                                    <div
                                        className={`text-sm font-semibold capitalize ${theme === t ? "text-green-900" : "text-stone-500"}`}
                                    >
                                        {t}{" "}
                                        {theme === t && (
                                            <span className="text-green-700">
                                                ✓
                                            </span>
                                        )}
                                    </div>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Notifications */}
                    <div className="bg-white rounded-xl border border-stone-100 shadow-sm p-5">
                        <h4 className="text-sm font-semibold text-stone-800 mb-4">
                            Notifications
                        </h4>
                        <div className="divide-y divide-stone-100">
                            {notifItems.map((item) => (
                                <div
                                    key={item.key}
                                    className="flex items-center justify-between py-3 gap-3"
                                >
                                    <div>
                                        <div className="text-sm font-medium text-stone-700">
                                            {item.label}
                                        </div>
                                        <div className="text-xs text-stone-400 mt-0.5">
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
                    </div>

                    {/* Security */}
                    <div className="bg-white rounded-xl border border-stone-100 shadow-sm p-5">
                        <h4 className="text-sm font-semibold text-stone-800 mb-4">
                            Security
                        </h4>
                        <div className="flex gap-2 flex-wrap">
                            <button
                                onClick={() =>
                                    onToast("Password reset email sent")
                                }
                                className="h-9 px-4 rounded-lg text-sm font-medium text-stone-700 bg-stone-100 hover:bg-stone-200 transition-colors border border-stone-200"
                            >
                                Change Password
                            </button>
                            <button
                                onClick={() => onToast("2FA setup initiated")}
                                className="h-9 px-4 rounded-lg text-sm font-medium text-white bg-stone-800 hover:bg-stone-700 transition-colors shadow-sm"
                            >
                                Enable 2FA
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
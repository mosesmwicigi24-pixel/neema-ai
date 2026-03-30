import React, { useState, useEffect } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { RoleBadge } from "@/components/ui/Badges";
import { Btn } from "@/components/ui/Btn";
import { Toggle } from "@/components/ui/Layout";
import { InputField } from "@/components/ui/FormFields";
import { fmtDate } from "@/lib/utils";
import { ALL_PERMISSIONS } from "@/lib/mockData";
import { profileApi, agentsApi } from "@/lib/api";
import type { Agent, Session, ThemeMode, SharedViewProps } from "@/types";

interface ProfileViewProps extends SharedViewProps {
    session: Session;
    agents: Agent[];
    setAgents: React.Dispatch<React.SetStateAction<Agent[]>>;
    theme: ThemeMode;
    setTheme: React.Dispatch<React.SetStateAction<ThemeMode>>;
    refetchAgents?: () => void;
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
    refetchAgents,
}: ProfileViewProps): React.ReactElement {
    const agent =
        agents.find((a) => a.email === session.user.email) ?? agents[0];
    const [editMode, setEditMode] = useState(false);
    const [saving, setSaving] = useState(false);
    const [changingPassword, setChangingPassword] = useState(false);
    const [form, setForm] = useState({
        name: agent?.name ?? "",
        email: agent?.email ?? "",
        department: agent?.department ?? "",
    });
    const [passwordForm, setPasswordForm] = useState({
        current: "",
        new_: "",
        confirm: "",
    });
    const [notifs, setNotifs] = useState<NotifSettings>({
        new_conv: true,
        human_transfer: true,
        order_updates: false,
        daily_summary: true,
    });

    // Sync form when agent data loads
    useEffect(() => {
        if (agent) {
            setForm({
                name: agent.name,
                email: agent.email,
                department: agent.department ?? "",
            });
        }
    }, [agent?.id]);

    const save = async () => {
        if (!agent) return;
        setSaving(true);
        try {
            await profileApi.update({ name: form.name, email: form.email });
            refetchAgents?.();
            setEditMode(false);
            onToast("Profile updated");
        } catch (e: any) {
            onToast(e.message ?? "Failed to update profile", "error");
        } finally {
            setSaving(false);
        }
    };

    const changePassword = async () => {
        if (passwordForm.new_ !== passwordForm.confirm) {
            onToast("Passwords don't match", "error");
            return;
        }
        if (passwordForm.new_.length < 8) {
            onToast("Password must be at least 8 characters", "error");
            return;
        }
        setSaving(true);
        try {
            await profileApi.update({ password: passwordForm.new_ });
            setChangingPassword(false);
            setPasswordForm({ current: "", new_: "", confirm: "" });
            onToast("Password changed successfully");
        } catch (e: any) {
            onToast(e.message ?? "Failed to change password", "error");
        } finally {
            setSaving(false);
        }
    };

    const permKeys = agent
        ? (agent.permissions ?? []).includes("all")
            ? ALL_PERMISSIONS.map((p) => p.key)
            : (agent.permissions ?? [])
        : [];

    if (!agent) {
        return (
            <div className="flex-1 flex items-center justify-center">
                <p className="text-sm text-[#9ccd65]">Loading profile…</p>
            </div>
        );
    }

    return (
        <div
            className={`flex-1 overflow-y-auto bg-[#f3f9ec] ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            <div className="mb-6">
                <h1 className="text-xl font-bold text-[#16270c] tracking-tight">
                    Profile
                </h1>
                <p className="text-sm text-[#9ccd65] mt-0.5">
                    Manage your account and preferences
                </p>
            </div>

            <div className="space-y-4 max-w-2xl">
                {/* Profile card */}
                <div className="bg-white rounded-xl border border-[#e6f3d8] shadow-sm p-5">
                    <div className="flex items-start gap-4 mb-5">
                        <Avatar name={agent.name} size={56} />
                        <div className="flex-1">
                            <div className="flex items-center gap-2 mb-1">
                                <h2 className="text-base font-bold text-[#16270c]">
                                    {agent.name}
                                </h2>
                                <span
                                    className={`text-xs px-2 py-0.5 rounded-full font-semibold capitalize border ${
                                        agent.role === "admin"
                                            ? "bg-purple-100 text-purple-700 border-purple-200"
                                            : "bg-[#e6f3d8] text-[#427425] border-[#cee6b2]"
                                    }`}
                                >
                                    {agent.role}
                                </span>
                            </div>
                            <p className="text-sm text-[#9ccd65]">
                                {agent.email}
                            </p>
                            <p className="text-xs text-[#9ccd65] mt-1">
                                Joined{" "}
                                {agent.created_at
                                    ? fmtDate(agent.created_at)
                                    : "—"}
                                {agent.last_seen_at && (
                                    <>
                                        {" "}
                                        · Last active{" "}
                                        {fmtDate(agent.last_seen_at)}
                                    </>
                                )}
                            </p>
                        </div>
                        <Btn
                            onClick={() => setEditMode(!editMode)}
                            variant={editMode ? "outline" : "secondary"}
                            small
                        >
                            {editMode ? "Cancel" : "Edit"}
                        </Btn>
                    </div>

                    {editMode && (
                        <div className="border-t border-[#e6f3d8] pt-4 space-y-3">
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
                            />
                            <InputField
                                label="Department"
                                value={form.department}
                                onChange={(v) =>
                                    setForm((f) => ({ ...f, department: v }))
                                }
                                placeholder="Sales, Support…"
                            />
                            <div className="flex gap-2">
                                <Btn
                                    onClick={save}
                                    variant="primary"
                                    disabled={saving}
                                >
                                    {saving ? "Saving…" : "Save Changes"}
                                </Btn>
                                <Btn
                                    onClick={() => setEditMode(false)}
                                    variant="outline"
                                >
                                    Cancel
                                </Btn>
                            </div>
                        </div>
                    )}
                </div>

                {/* Change password */}
                <div className="bg-white rounded-xl border border-[#e6f3d8] shadow-sm p-5">
                    <div className="flex items-center justify-between mb-4">
                        <div>
                            <h3 className="text-sm font-semibold text-[#16270c]">
                                Password
                            </h3>
                            <p className="text-xs text-[#9ccd65] mt-0.5">
                                Change your login password
                            </p>
                        </div>
                        <Btn
                            onClick={() =>
                                setChangingPassword(!changingPassword)
                            }
                            variant="secondary"
                            small
                        >
                            {changingPassword ? "Cancel" : "Change"}
                        </Btn>
                    </div>
                    {changingPassword && (
                        <div className="space-y-3">
                            <InputField
                                label="New Password"
                                value={passwordForm.new_}
                                onChange={(v) =>
                                    setPasswordForm((f) => ({ ...f, new_: v }))
                                }
                                type="password"
                                placeholder="Minimum 8 characters"
                            />
                            <InputField
                                label="Confirm Password"
                                value={passwordForm.confirm}
                                onChange={(v) =>
                                    setPasswordForm((f) => ({
                                        ...f,
                                        confirm: v,
                                    }))
                                }
                                type="password"
                            />
                            <Btn
                                onClick={changePassword}
                                variant="primary"
                                disabled={saving}
                            >
                                {saving ? "Changing…" : "Change Password"}
                            </Btn>
                        </div>
                    )}
                </div>

                {/* Appearance */}
                <div className="bg-white rounded-xl border border-[#e6f3d8] shadow-sm p-5">
                    <h3 className="text-sm font-semibold text-[#16270c] mb-4">
                        Appearance
                    </h3>
                    <div className="flex items-center justify-between">
                        <div>
                            <div className="text-sm font-medium text-[#16270c]">
                                Dark Mode
                            </div>
                            <div className="text-xs text-[#9ccd65] mt-0.5">
                                Switch to dark theme
                            </div>
                        </div>
                        <Toggle
                            checked={theme === "dark"}
                            onChange={() =>
                                setTheme(theme === "dark" ? "light" : "dark")
                            }
                        />
                    </div>
                </div>

                {/* Notifications */}
                <div className="bg-white rounded-xl border border-[#e6f3d8] shadow-sm p-5">
                    <h3 className="text-sm font-semibold text-[#16270c] mb-4">
                        Notifications
                    </h3>
                    <div className="space-y-4">
                        {(
                            [
                                {
                                    key: "new_conv",
                                    label: "New conversations",
                                    desc: "Alert when a new chat arrives",
                                },
                                {
                                    key: "human_transfer",
                                    label: "Human transfers",
                                    desc: "Alert when a conversation is transferred to you",
                                },
                                {
                                    key: "order_updates",
                                    label: "Order updates",
                                    desc: "Notify on order status changes",
                                },
                                {
                                    key: "daily_summary",
                                    label: "Daily summary",
                                    desc: "Morning digest of activity",
                                },
                            ] as const
                        ).map((item) => (
                            <div
                                key={item.key}
                                className="flex items-center justify-between"
                            >
                                <div>
                                    <div className="text-sm font-medium text-[#16270c]">
                                        {item.label}
                                    </div>
                                    <div className="text-xs text-[#9ccd65] mt-0.5">
                                        {item.desc}
                                    </div>
                                </div>
                                <Toggle
                                    checked={notifs[item.key]}
                                    onChange={() =>
                                        setNotifs((n) => ({
                                            ...n,
                                            [item.key]: !n[item.key],
                                        }))
                                    }
                                />
                            </div>
                        ))}
                    </div>
                </div>

                {/* Permissions */}
                <div className="bg-white rounded-xl border border-[#e6f3d8] shadow-sm p-5">
                    <h3 className="text-sm font-semibold text-[#16270c] mb-4">
                        Your Permissions
                    </h3>
                    <div className="grid grid-cols-2 gap-2">
                        {ALL_PERMISSIONS.map((p) => {
                            const has = permKeys.includes(p.key);
                            return (
                                <div
                                    key={p.key}
                                    className={`flex items-center gap-2 p-2.5 rounded-lg border text-xs ${has ? "bg-[#f0f9ec] border-[#b5da8b] text-[#2c4e18]" : "bg-[#f3f9ec] border-[#cee6b2] text-[#9ccd65]"}`}
                                >
                                    <div
                                        className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${has ? "bg-[#f0f9ec]0" : "bg-stone-300"}`}
                                    />
                                    {p.label}
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>
        </div>
    );
}
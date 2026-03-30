import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { RoleBadge } from "@/components/ui/Badges";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { InputField, SelectField } from "@/components/ui/FormFields";
import { Toggle } from "@/components/ui/Layout";
import { fmtDate } from "@/lib/utils";
import { ROLE_DEFINITIONS, ALL_PERMISSIONS } from "@/lib/mockData";
import { agentsApi } from "@/lib/api";
import type { Agent, AgentRole, SharedViewProps } from "@/types";

interface AgentsViewProps extends SharedViewProps {
    agents: Agent[];
    setAgents: React.Dispatch<React.SetStateAction<Agent[]>>;
    refetchAgents?: () => void;
}

interface AgentForm {
    name: string;
    email: string;
    role: AgentRole;
    password: string;
    department: string;
}

const ROLE_COLORS: Record<string, string> = {
    admin: "bg-purple-100 text-purple-700 border-purple-200",
    supervisor: "bg-blue-100 text-blue-700 border-blue-200",
    agent: "bg-stone-100 text-stone-600 border-stone-200",
    viewer: "bg-gray-100 text-gray-500 border-gray-200",
};

export function AgentsView({
    agents,
    setAgents,
    onToast,
    isMobile,
    refetchAgents,
}: AgentsViewProps): React.ReactElement {
    const [modal, setModal] = useState<"create" | null>(null);
    const [permAgent, setPermAgent] = useState<Agent | null>(null);
    const [saving, setSaving] = useState(false);
    const [form, setForm] = useState<AgentForm>({
        name: "",
        email: "",
        role: "agent",
        password: "",
        department: "",
    });

    const createAgent = async () => {
        if (!form.name || !form.email || !form.password) {
            onToast("Name, email and password are required", "error");
            return;
        }
        setSaving(true);
        try {
            await agentsApi.create({
                name: form.name,
                email: form.email,
                password: form.password,
                role: form.role,
            });
            refetchAgents?.();
            setModal(null);
            setForm({
                name: "",
                email: "",
                role: "agent",
                password: "",
                department: "",
            });
            onToast("Agent created successfully");
        } catch (e: any) {
            onToast(e.message ?? "Failed to create agent", "error");
        } finally {
            setSaving(false);
        }
    };

    const deleteAgent = async (id: string) => {
        try {
            await agentsApi.delete(id);
            refetchAgents?.();
            onToast("Agent removed", "error");
        } catch {
            onToast("Failed to remove agent", "error");
        }
    };

    const toggleOnline = async (id: string, current: boolean) => {
        try {
            await agentsApi.toggleAvailable(id, !current);
            refetchAgents?.();
        } catch {
            onToast("Failed to update availability", "error");
        }
    };

    const onlineCount = agents.filter((a) => a.is_available).length;

    return (
        <div
            className={`flex-1 overflow-y-auto bg-stone-50 ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-xl font-bold text-stone-800 tracking-tight">
                        Team
                    </h1>
                    <p className="text-sm text-stone-400 mt-0.5">
                        {agents.length} agents
                        <span className="mx-1.5 text-stone-200">·</span>
                        <span className="text-emerald-600">
                            {onlineCount} online
                        </span>
                    </p>
                </div>
                <button
                    onClick={() => setModal("create")}
                    className="flex items-center gap-2 h-9 px-4 rounded-lg bg-green-700 hover:bg-green-600 text-white text-sm font-semibold transition-colors shadow-sm"
                >
                    <svg
                        className="w-4 h-4"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                    >
                        <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M12 4v16m8-8H4"
                        />
                    </svg>
                    Add Agent
                </button>
            </div>

            {/* Agent grid */}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {agents.map((agent) => (
                    <div
                        key={agent.id}
                        className="bg-white rounded-xl border border-stone-100 shadow-sm p-4 hover:shadow-md transition-all"
                    >
                        <div className="flex items-start gap-3 mb-3">
                            <div className="relative">
                                <Avatar name={agent.name} size={44} />
                                <div
                                    className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-white ${agent.is_available ? "bg-emerald-500" : "bg-stone-300"}`}
                                />
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2">
                                    <span className="text-sm font-semibold text-stone-800 truncate">
                                        {agent.name}
                                    </span>
                                    <span
                                        className={`text-[10px] px-1.5 py-0.5 rounded border font-semibold capitalize ${ROLE_COLORS[agent.role] ?? ROLE_COLORS.agent}`}
                                    >
                                        {agent.role}
                                    </span>
                                </div>
                                <p className="text-xs text-stone-400 truncate mt-0.5">
                                    {agent.email}
                                </p>
                                <p className="text-xs text-stone-400 mt-0.5">
                                    {agent.active_convs} active · Joined{" "}
                                    {agent.created_at
                                        ? fmtDate(agent.created_at)
                                        : "—"}
                                </p>
                            </div>
                        </div>

                        <div className="flex items-center justify-between border-t border-stone-50 pt-3">
                            <div className="flex items-center gap-2">
                                <span className="text-xs text-stone-400">
                                    Available
                                </span>
                                <Toggle
                                    checked={agent.is_available}
                                    onChange={() =>
                                        toggleOnline(
                                            agent.id,
                                            agent.is_available,
                                        )
                                    }
                                />
                            </div>
                            <div className="flex gap-1.5">
                                <button
                                    onClick={() => setPermAgent(agent)}
                                    className="h-7 px-2.5 rounded-lg text-xs font-medium bg-stone-100 text-stone-600 hover:bg-stone-200 transition-colors"
                                >
                                    Permissions
                                </button>
                                <button
                                    onClick={() => deleteAgent(agent.id)}
                                    className="w-7 h-7 rounded-lg bg-red-50 text-red-500 hover:bg-red-100 border border-red-100 flex items-center justify-center transition-colors"
                                >
                                    <svg
                                        className="w-3.5 h-3.5"
                                        fill="none"
                                        stroke="currentColor"
                                        viewBox="0 0 24 24"
                                    >
                                        <path
                                            strokeLinecap="round"
                                            strokeLinejoin="round"
                                            strokeWidth={2}
                                            d="M6 18L18 6M6 6l12 12"
                                        />
                                    </svg>
                                </button>
                            </div>
                        </div>
                    </div>
                ))}

                {agents.length === 0 && (
                    <div className="col-span-full py-16 text-center">
                        <p className="text-sm text-stone-400">
                            No agents yet. Add one to get started.
                        </p>
                    </div>
                )}
            </div>

            {/* Create agent modal */}
            <Modal
                show={modal === "create"}
                onClose={() => setModal(null)}
                title="Add Agent"
            >
                <InputField
                    label="Full Name"
                    value={form.name}
                    onChange={(v) => setForm((f) => ({ ...f, name: v }))}
                    placeholder="Jane Doe"
                    required
                />
                <InputField
                    label="Email"
                    value={form.email}
                    onChange={(v) => setForm((f) => ({ ...f, email: v }))}
                    placeholder="jane@bethanyhouse.co.ke"
                    required
                />
                <InputField
                    label="Password"
                    value={form.password}
                    onChange={(v) => setForm((f) => ({ ...f, password: v }))}
                    type="password"
                    placeholder="Minimum 8 characters"
                    required
                />
                <SelectField
                    label="Role"
                    value={form.role}
                    onChange={(v) =>
                        setForm((f) => ({ ...f, role: v as AgentRole }))
                    }
                    options={[
                        { value: "agent", label: "Agent" },
                        { value: "admin", label: "Admin" },
                        { value: "readonly", label: "Read Only" },
                    ]}
                />
                <InputField
                    label="Department"
                    value={form.department}
                    onChange={(v) => setForm((f) => ({ ...f, department: v }))}
                    placeholder="Sales, Support…"
                />
                <div className="flex gap-2">
                    <Btn
                        onClick={createAgent}
                        variant="primary"
                        disabled={saving}
                    >
                        {saving ? "Creating…" : "Create Agent"}
                    </Btn>
                    <Btn onClick={() => setModal(null)} variant="outline">
                        Cancel
                    </Btn>
                </div>
            </Modal>

            {/* Permissions modal */}
            <Modal
                show={!!permAgent}
                onClose={() => setPermAgent(null)}
                title={`Permissions — ${permAgent?.name}`}
            >
                <p className="text-xs text-stone-400 mb-3">
                    Role:{" "}
                    <span className="font-semibold capitalize text-stone-600">
                        {permAgent?.role}
                    </span>
                </p>
                <div className="grid grid-cols-2 gap-2">
                    {ALL_PERMISSIONS.map((p) => {
                        const perms: string[] =
                            permAgent?.permissions ?? [];
                        const hasAll = perms.includes("all");
                        const hasThis = hasAll || perms.includes(p.key);
                        return (
                            <div
                                key={p.key}
                                className={`flex items-center gap-2 p-2.5 rounded-lg border text-xs ${hasThis ? "bg-green-50 border-green-200 text-green-800" : "bg-stone-50 border-stone-200 text-stone-500"}`}
                            >
                                <div
                                    className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${hasThis ? "bg-green-500" : "bg-stone-300"}`}
                                />
                                {p.label}
                            </div>
                        );
                    })}
                </div>
                <div className="mt-4">
                    <Btn onClick={() => setPermAgent(null)} variant="outline">
                        Close
                    </Btn>
                </div>
            </Modal>
        </div>
    );
}
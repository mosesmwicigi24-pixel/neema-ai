import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { RoleBadge } from "@/components/ui/Badges";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { InputField, SelectField } from "@/components/ui/FormFields";
import { Toggle } from "@/components/ui/Layout";
import { fmtDate } from "@/lib/utils";
import { ROLE_DEFINITIONS, ALL_PERMISSIONS } from "@/lib/mockData";
import type { Agent, AgentRole, SharedViewProps } from "@/types";

interface AgentsViewProps extends SharedViewProps {
    agents: Agent[];
    setAgents: React.Dispatch<React.SetStateAction<Agent[]>>;
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
}: AgentsViewProps): React.ReactElement {
    const [modal, setModal] = useState<"create" | null>(null);
    const [permAgent, setPermAgent] = useState<Agent | null>(null);
    const [form, setForm] = useState<AgentForm>({
        name: "",
        email: "",
        role: "agent",
        password: "",
        department: "",
    });

    const createAgent = () => {
        setAgents((as) => [
            ...as,
            {
                id: `a${Date.now()}`,
                ...form,
                permissions: ROLE_DEFINITIONS[form.role]?.permissions ?? [],
                is_available: true,
                active_convs: 0,
                last_seen_at: null,
                joined_at: new Date().toISOString().split("T")[0],
                created_at: new Date().toISOString(),
            },
        ]);
        setModal(null);
        setForm({
            name: "",
            email: "",
            role: "agent",
            password: "",
            department: "",
        });
        onToast("Agent created successfully");
    };

    const deleteAgent = (id: string) => {
        setAgents((as) => as.filter((a) => a.id !== id));
        onToast("Agent removed", "error");
    };
    const toggleOnline = (id: string) => {
        setAgents((as) =>
            as.map((a) =>
                a.id === id ? { ...a, is_available: !a.is_available } : a,
            ),
        );
    };
    const updateRole = (id: string, role: AgentRole) => {
        setAgents((as) =>
            as.map((a) =>
                a.id === id
                    ? {
                          ...a,
                          role,
                          permissions:
                              ROLE_DEFINITIONS[role]?.permissions ?? [],
                      }
                    : a,
            ),
        );
        onToast("Role updated");
    };
    const togglePerm = (agentId: string, perm: string) => {
        setAgents((as) =>
            as.map((a) => {
                if (a.id !== agentId) return a;
                const perms = a.permissions.includes("all")
                    ? ALL_PERMISSIONS.map((p) => p.key)
                    : [...a.permissions];
                const idx = perms.indexOf(perm);
                if (idx >= 0) perms.splice(idx, 1);
                else perms.push(perm);
                return { ...a, permissions: perms };
            }),
        );
        setPermAgent((prev) =>
            prev && agents.find((a) => a.id === prev.id)
                ? { ...(agents.find((a) => a.id === prev.id) as Agent) }
                : prev,
        );
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
                        {agents.length} members · {onlineCount} online
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
                    Add Member
                </button>
            </div>

            {/* Role summary cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
                {(
                    Object.entries(ROLE_DEFINITIONS) as [
                        AgentRole,
                        (typeof ROLE_DEFINITIONS)[AgentRole],
                    ][]
                ).map(([key, role]) => (
                    <div
                        key={key}
                        className="bg-white rounded-xl border border-stone-100 p-4 shadow-sm"
                    >
                        <div className="text-2xl font-bold text-stone-800 mb-1">
                            {agents.filter((a) => a.role === key).length}
                        </div>
                        <div className="text-sm font-semibold text-stone-700">
                            {role.label}
                        </div>
                        <div className="text-xs text-stone-400 mt-0.5 leading-snug">
                            {role.description}
                        </div>
                    </div>
                ))}
            </div>

            {/* Mobile cards */}
            {isMobile ? (
                <div className="space-y-3">
                    {agents.map((agent) => (
                        <div
                            key={agent.id}
                            className="bg-white rounded-xl border border-stone-100 p-4 shadow-sm"
                        >
                            <div className="flex items-center gap-3 mb-3">
                                <div className="relative">
                                    <Avatar name={agent.name} size="md" />
                                    <div
                                        className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full ring-2 ring-white ${agent.is_available ? "bg-emerald-500" : "bg-stone-300"}`}
                                    />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm font-semibold text-stone-800">
                                        {agent.name}
                                    </div>
                                    <div className="text-xs text-stone-400 truncate">
                                        {agent.email}
                                    </div>
                                </div>
                                <span
                                    className={`text-xs font-medium px-2 py-0.5 rounded-md border ${ROLE_COLORS[agent.role] ?? "bg-stone-100 text-stone-500 border-stone-200"}`}
                                >
                                    {ROLE_DEFINITIONS[agent.role]?.label ??
                                        agent.role}
                                </span>
                            </div>
                            <div className="flex gap-2 flex-wrap">
                                <button
                                    onClick={() => setPermAgent(agent)}
                                    className="flex-1 h-8 text-xs font-medium text-stone-600 bg-stone-100 hover:bg-stone-200 rounded-lg transition-colors"
                                >
                                    Permissions
                                </button>
                                <button
                                    onClick={() => toggleOnline(agent.id)}
                                    className={`flex items-center gap-1.5 h-8 px-3 rounded-lg text-xs font-medium transition-colors ${agent.is_available ? "bg-emerald-50 text-emerald-700 border border-emerald-200" : "bg-stone-100 text-stone-500"}`}
                                >
                                    <div
                                        className={`w-1.5 h-1.5 rounded-full ${agent.is_available ? "bg-emerald-500" : "bg-stone-400"}`}
                                    />
                                    {agent.is_available ? "Online" : "Offline"}
                                </button>
                                {agent.id !== "a3" && (
                                    <button
                                        onClick={() => deleteAgent(agent.id)}
                                        className="h-8 px-3 rounded-lg text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 border border-red-200 transition-colors"
                                    >
                                        Remove
                                    </button>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                /* Desktop table */
                <div className="bg-white rounded-xl border border-stone-100 overflow-hidden shadow-sm">
                    <table className="w-full">
                        <thead>
                            <tr className="border-b border-stone-100">
                                {[
                                    "Member",
                                    "Department",
                                    "Role",
                                    "Status",
                                    "Active Convs",
                                    "Joined",
                                    "Actions",
                                ].map((h) => (
                                    <th
                                        key={h}
                                        className="px-5 py-3 text-left text-xs font-semibold text-stone-400 uppercase tracking-wider"
                                    >
                                        {h}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-stone-50">
                            {agents.map((agent) => (
                                <tr
                                    key={agent.id}
                                    className="hover:bg-stone-50 transition-colors group"
                                >
                                    <td className="px-5 py-3.5">
                                        <div className="flex items-center gap-3">
                                            <div className="relative">
                                                <Avatar
                                                    name={agent.name}
                                                    size="sm"
                                                />
                                                <div
                                                    className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full ring-2 ring-white ${agent.is_available ? "bg-emerald-500" : "bg-stone-300"}`}
                                                />
                                            </div>
                                            <div>
                                                <div className="text-sm font-semibold text-stone-800">
                                                    {agent.name}
                                                </div>
                                                <div className="text-xs text-stone-400">
                                                    {agent.email}
                                                </div>
                                            </div>
                                        </div>
                                    </td>
                                    <td className="px-5 py-3.5 text-sm text-stone-400">
                                        {agent.department || "—"}
                                    </td>
                                    <td className="px-5 py-3.5">
                                        <select
                                            value={agent.role}
                                            onChange={(e) =>
                                                updateRole(
                                                    agent.id,
                                                    e.target.value as AgentRole,
                                                )
                                            }
                                            className="text-xs bg-transparent border-0 font-semibold cursor-pointer focus:outline-none focus:ring-2 focus:ring-green-600 rounded-lg py-1 px-0 text-stone-700"
                                        >
                                            {(
                                                Object.keys(
                                                    ROLE_DEFINITIONS,
                                                ) as AgentRole[]
                                            ).map((r) => (
                                                <option key={r} value={r}>
                                                    {ROLE_DEFINITIONS[r].label}
                                                </option>
                                            ))}
                                        </select>
                                    </td>
                                    <td className="px-5 py-3.5">
                                        <button
                                            onClick={() =>
                                                toggleOnline(agent.id)
                                            }
                                            className="flex items-center gap-1.5 touch-manipulation"
                                        >
                                            <div
                                                className={`w-2 h-2 rounded-full ${agent.is_available ? "bg-emerald-500" : "bg-stone-300"}`}
                                            />
                                            <span
                                                className={`text-xs font-medium ${agent.is_available ? "text-emerald-600" : "text-stone-400"}`}
                                            >
                                                {agent.is_available
                                                    ? "Online"
                                                    : "Offline"}
                                            </span>
                                        </button>
                                    </td>
                                    <td className="px-5 py-3.5 text-sm font-semibold text-stone-800">
                                        {agent.active_convs}
                                    </td>
                                    <td className="px-5 py-3.5 text-xs text-stone-400">
                                        {fmtDate(agent.joined_at)}
                                    </td>
                                    <td className="px-5 py-3.5">
                                        <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                            <button
                                                onClick={() =>
                                                    setPermAgent(agent)
                                                }
                                                className="h-7 px-3 rounded-md text-xs font-medium text-stone-600 bg-stone-100 hover:bg-stone-200 transition-colors"
                                            >
                                                Permissions
                                            </button>
                                            {agent.id !== "a3" && (
                                                <button
                                                    onClick={() =>
                                                        deleteAgent(agent.id)
                                                    }
                                                    className="h-7 px-3 rounded-md text-xs font-medium text-red-600 bg-red-50 hover:bg-red-100 transition-colors"
                                                >
                                                    Remove
                                                </button>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Create agent modal */}
            <Modal
                show={modal === "create"}
                onClose={() => setModal(null)}
                title="Add Team Member"
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
                    placeholder="jane@neema.co"
                    type="email"
                    required
                />
                <InputField
                    label="Password"
                    value={form.password}
                    onChange={(v) => setForm((f) => ({ ...f, password: v }))}
                    type="password"
                    placeholder="••••••••"
                    required
                />
                <InputField
                    label="Department"
                    value={form.department}
                    onChange={(v) => setForm((f) => ({ ...f, department: v }))}
                    placeholder="Support"
                />
                <SelectField
                    label="Role"
                    value={form.role}
                    onChange={(v) =>
                        setForm((f) => ({ ...f, role: v as AgentRole }))
                    }
                >
                    {(
                        Object.entries(ROLE_DEFINITIONS) as [
                            AgentRole,
                            (typeof ROLE_DEFINITIONS)[AgentRole],
                        ][]
                    ).map(([k, r]) => (
                        <option key={k} value={k}>
                            {r.label} — {r.description}
                        </option>
                    ))}
                </SelectField>
                <div className="mb-4 p-3 bg-stone-50 rounded-xl border border-stone-100">
                    <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-2">
                        Permissions for {ROLE_DEFINITIONS[form.role]?.label}
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                        {(ROLE_DEFINITIONS[form.role]?.permissions ?? []).map(
                            (p) => (
                                <span
                                    key={p}
                                    className="text-xs bg-green-50 text-green-900 border border-green-200 px-2 py-0.5 rounded-md"
                                >
                                    {p}
                                </span>
                            ),
                        )}
                    </div>
                </div>
                <div className="flex gap-2">
                    <Btn onClick={createAgent} variant="primary">
                        Create Member
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
                title={`Permissions — ${permAgent?.name ?? ""}`}
                size="md"
            >
                {permAgent &&
                    (() => {
                        const liveAgent = agents.find(
                            (a) => a.id === permAgent.id,
                        );
                        const agentPerms = liveAgent?.permissions ?? [];
                        return (
                            <>
                                <div className="flex items-center gap-3 p-3 bg-stone-50 rounded-xl mb-5">
                                    <Avatar name={permAgent.name} size="sm" />
                                    <div className="flex-1 min-w-0">
                                        <div className="text-sm font-semibold text-stone-800">
                                            {permAgent.name}
                                        </div>
                                        <div className="text-xs text-stone-400 truncate">
                                            {permAgent.email}
                                        </div>
                                    </div>
                                    <RoleBadge role={permAgent.role} />
                                </div>
                                {[
                                    "Conversations",
                                    "Team",
                                    "Orders",
                                    "Catalog",
                                    "Analytics",
                                    "Settings",
                                ].map((group) => {
                                    const groupPerms = ALL_PERMISSIONS.filter(
                                        (p) => p.group === group,
                                    );
                                    if (!groupPerms.length) return null;
                                    return (
                                        <div key={group} className="mb-5">
                                            <div className="text-xs font-semibold text-stone-400 uppercase tracking-wider mb-2">
                                                {group}
                                            </div>
                                            <div className="space-y-1">
                                                {groupPerms.map((perm) => {
                                                    const has =
                                                        agentPerms.includes(
                                                            "all",
                                                        ) ||
                                                        agentPerms.includes(
                                                            perm.key,
                                                        );
                                                    return (
                                                        <div
                                                            key={perm.key}
                                                            className="flex items-center justify-between py-2.5 border-b border-stone-100"
                                                        >
                                                            <span className="text-sm text-stone-700">
                                                                {perm.label}
                                                            </span>
                                                            <Toggle
                                                                checked={has}
                                                                onChange={() =>
                                                                    togglePerm(
                                                                        permAgent.id,
                                                                        perm.key,
                                                                    )
                                                                }
                                                            />
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    );
                                })}
                                <Btn
                                    onClick={() => setPermAgent(null)}
                                    variant="primary"
                                    full
                                >
                                    Done
                                </Btn>
                            </>
                        );
                    })()}
            </Modal>
        </div>
    );
}
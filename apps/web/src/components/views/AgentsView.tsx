import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { RoleBadge } from "@/components/ui/Badges";
import { Btn } from "@/components/ui/Btn";
import { Card, SectionHeader, Toggle } from "@/components/ui/Layout";
import { Modal } from "@/components/ui/Modal";
import { InputField, SelectField } from "@/components/ui/FormFields";
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

    return (
        <div
            className={`flex-1 overflow-y-auto ${isMobile ? "p-4 pb-24" : "p-6"}`}
        >
            <SectionHeader
                title="Team Management"
                subtitle={`${agents.length} members · ${agents.filter((a) => a.is_available).length} online`}
                action={
                    <Btn
                        onClick={() => setModal("create")}
                        variant="primary"
                        size="sm"
                    >
                        + Add Member
                    </Btn>
                }
            />

            {/* Role overview */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
                {(
                    Object.entries(ROLE_DEFINITIONS) as [
                        AgentRole,
                        (typeof ROLE_DEFINITIONS)[AgentRole],
                    ][]
                ).map(([key, role]) => (
                    <div
                        key={key}
                        className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4"
                        style={{
                            borderLeftColor: role.color,
                            borderLeftWidth: 3,
                        }}
                    >
                        <div className="text-2xl font-bold text-gray-900 dark:text-white mb-1">
                            {agents.filter((a) => a.role === key).length}
                        </div>
                        <div className="text-sm font-semibold text-gray-700 dark:text-gray-300">
                            {role.label}
                        </div>
                        <div className="text-xs text-gray-400 mt-0.5">
                            {role.description}
                        </div>
                    </div>
                ))}
            </div>

            {isMobile ? (
                <div className="space-y-3">
                    {agents.map((agent) => (
                        <div
                            key={agent.id}
                            className="bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4"
                        >
                            <div className="flex items-center gap-3 mb-3">
                                <div className="relative">
                                    <Avatar name={agent.name} size="md" />
                                    <div
                                        className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full ring-2 ring-white dark:ring-gray-900 ${agent.is_available ? "bg-emerald-500" : "bg-gray-400"}`}
                                    />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <div className="text-sm font-semibold text-gray-900 dark:text-white">
                                        {agent.name}
                                    </div>
                                    <div className="text-xs text-gray-400 truncate">
                                        {agent.email}
                                    </div>
                                </div>
                                <RoleBadge role={agent.role} />
                            </div>
                            <div className="flex gap-2 flex-wrap">
                                <Btn
                                    size="xs"
                                    onClick={() => setPermAgent(agent)}
                                    variant="outline"
                                >
                                    Permissions
                                </Btn>
                                <Btn
                                    size="xs"
                                    onClick={() => toggleOnline(agent.id)}
                                    variant={
                                        agent.is_available
                                            ? "success"
                                            : "outline"
                                    }
                                >
                                    {agent.is_available
                                        ? "● Online"
                                        : "○ Offline"}
                                </Btn>
                                {agent.id !== "a3" && (
                                    <Btn
                                        size="xs"
                                        onClick={() => deleteAgent(agent.id)}
                                        variant="danger"
                                    >
                                        Remove
                                    </Btn>
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            ) : (
                <Card padding={false}>
                    <table className="w-full">
                        <thead>
                            <tr className="border-b border-gray-100 dark:border-gray-800">
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
                                        className="px-4 py-3 text-left text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider"
                                    >
                                        {h}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-50 dark:divide-gray-800">
                            {agents.map((agent) => (
                                <tr
                                    key={agent.id}
                                    className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors"
                                >
                                    <td className="px-4 py-3">
                                        <div className="flex items-center gap-3">
                                            <div className="relative">
                                                <Avatar
                                                    name={agent.name}
                                                    size="sm"
                                                />
                                                <div
                                                    className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full ring-2 ring-white dark:ring-gray-900 ${agent.is_available ? "bg-emerald-500" : "bg-gray-400"}`}
                                                />
                                            </div>
                                            <div>
                                                <div className="text-sm font-semibold text-gray-900 dark:text-white">
                                                    {agent.name}
                                                </div>
                                                <div className="text-xs text-gray-400">
                                                    {agent.email}
                                                </div>
                                            </div>
                                        </div>
                                    </td>
                                    <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
                                        {agent.department || "—"}
                                    </td>
                                    <td className="px-4 py-3">
                                        <select
                                            value={agent.role}
                                            onChange={(e) =>
                                                updateRole(
                                                    agent.id,
                                                    e.target.value as AgentRole,
                                                )
                                            }
                                            className="text-xs bg-transparent border-0 font-semibold cursor-pointer focus:outline-none focus:ring-2 focus:ring-amber-500 rounded-lg py-1 px-0 text-gray-700 dark:text-gray-200"
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
                                    <td className="px-4 py-3">
                                        <button
                                            onClick={() =>
                                                toggleOnline(agent.id)
                                            }
                                            className="flex items-center gap-1.5 touch-manipulation"
                                        >
                                            <div
                                                className={`w-2 h-2 rounded-full ${agent.is_available ? "bg-emerald-500" : "bg-gray-400"}`}
                                            />
                                            <span
                                                className={`text-xs font-medium ${agent.is_available ? "text-emerald-600 dark:text-emerald-400" : "text-gray-400"}`}
                                            >
                                                {agent.is_available
                                                    ? "Online"
                                                    : "Offline"}
                                            </span>
                                        </button>
                                    </td>
                                    <td className="px-4 py-3 text-sm text-gray-900 dark:text-white font-medium">
                                        {agent.active_convs}
                                    </td>
                                    <td className="px-4 py-3 text-xs text-gray-400">
                                        {fmtDate(agent.joined_at)}
                                    </td>
                                    <td className="px-4 py-3">
                                        <div className="flex gap-2">
                                            <Btn
                                                size="xs"
                                                onClick={() =>
                                                    setPermAgent(agent)
                                                }
                                                variant="outline"
                                            >
                                                Permissions
                                            </Btn>
                                            {agent.id !== "a3" && (
                                                <Btn
                                                    size="xs"
                                                    onClick={() =>
                                                        deleteAgent(agent.id)
                                                    }
                                                    variant="danger"
                                                >
                                                    Remove
                                                </Btn>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </Card>
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
                {/* Preview permissions */}
                <div className="mb-4 p-3 bg-gray-50 dark:bg-gray-800 rounded-xl">
                    <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                        Permissions for {ROLE_DEFINITIONS[form.role]?.label}
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                        {(ROLE_DEFINITIONS[form.role]?.permissions ?? []).map(
                            (p) => (
                                <span
                                    key={p}
                                    className="text-xs bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 px-2 py-0.5 rounded-lg"
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
                                <div className="flex items-center gap-3 p-3 bg-gray-50 dark:bg-gray-800 rounded-xl mb-5">
                                    <Avatar name={permAgent.name} size="sm" />
                                    <div className="flex-1 min-w-0">
                                        <div className="text-sm font-semibold text-gray-900 dark:text-white">
                                            {permAgent.name}
                                        </div>
                                        <div className="text-xs text-gray-400 truncate">
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
                                            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
                                                {group}
                                            </div>
                                            <div className="space-y-2">
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
                                                            className="flex items-center justify-between py-2 border-b border-gray-100 dark:border-gray-800"
                                                        >
                                                            <span className="text-sm text-gray-700 dark:text-gray-300">
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

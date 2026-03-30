import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { Btn } from "@/components/ui/Btn";
import { Modal } from "@/components/ui/Modal";
import { InputField, SelectField } from "@/components/ui/FormFields";
import { Toggle } from "@/components/ui/Layout";
import { fmtDate } from "@/lib/utils";
import { agentsApi } from "@/lib/api";
import type { Agent, AgentRole, SharedViewProps } from "@/types";

interface AgentsViewProps extends SharedViewProps {
    agents: Agent[];
    setAgents: React.Dispatch<React.SetStateAction<Agent[]>>;
    refetchAgents?: () => void;
}

interface CreateForm {
    name: string; email: string; role: AgentRole; password: string;
}
interface EditForm {
    name: string; email: string; role: AgentRole;
}
interface PasswordForm {
    password: string; confirm: string;
}

const ROLE_COLORS: Record<string, string> = {
    admin:    "bg-purple-100 text-purple-700 border-purple-200",
    agent:    "bg-stone-100 text-stone-600 border-stone-200",
    readonly: "bg-gray-100 text-gray-500 border-gray-200",
};

const EMPTY_CREATE: CreateForm   = { name: "", email: "", role: "agent", password: "" };
const EMPTY_EDIT: EditForm       = { name: "", email: "", role: "agent" };
const EMPTY_PW: PasswordForm     = { password: "", confirm: "" };

export function AgentsView({
    agents,
    setAgents,
    onToast,
    isMobile,
    refetchAgents,
}: AgentsViewProps): React.ReactElement {
    const [createModal, setCreateModal] = useState(false);
    const [editAgent,   setEditAgent]   = useState<Agent | null>(null);
    const [pwAgent,     setPwAgent]     = useState<Agent | null>(null);
    const [delAgent,    setDelAgent]    = useState<Agent | null>(null);
    const [saving,      setSaving]      = useState(false);

    const [createForm, setCreateForm] = useState<CreateForm>({ ...EMPTY_CREATE });
    const [editForm,   setEditForm]   = useState<EditForm>({ ...EMPTY_EDIT });
    const [pwForm,     setPwForm]     = useState<PasswordForm>({ ...EMPTY_PW });

    // ── Create ────────────────────────────────────────────────────────────────

    const createAgent = async () => {
        if (!createForm.name || !createForm.email || !createForm.password) {
            onToast("Name, email and password are required", "error");
            return;
        }
        if (createForm.password.length < 8) {
            onToast("Password must be at least 8 characters", "error");
            return;
        }
        setSaving(true);
        try {
            await agentsApi.create({
                name:     createForm.name,
                email:    createForm.email,
                password: createForm.password,
                role:     createForm.role,
            });
            refetchAgents?.();
            setCreateModal(false);
            setCreateForm({ ...EMPTY_CREATE });
            onToast("Agent created successfully");
        } catch (e: any) {
            onToast(e.message ?? "Failed to create agent", "error");
        } finally {
            setSaving(false);
        }
    };

    // ── Edit ──────────────────────────────────────────────────────────────────

    const openEdit = (agent: Agent) => {
        setEditAgent(agent);
        setEditForm({ name: agent.name, email: agent.email, role: agent.role });
    };

    const saveEdit = async () => {
        if (!editAgent) return;
        if (!editForm.name || !editForm.email) {
            onToast("Name and email are required", "error");
            return;
        }
        setSaving(true);
        try {
            await agentsApi.update(editAgent.id, {
                name:  editForm.name,
                email: editForm.email,
                role:  editForm.role,
            });
            refetchAgents?.();
            setEditAgent(null);
            onToast("Agent updated");
        } catch (e: any) {
            onToast(e.message ?? "Failed to update agent", "error");
        } finally {
            setSaving(false);
        }
    };

    // ── Password reset ────────────────────────────────────────────────────────

    const savePassword = async () => {
        if (!pwAgent) return;
        if (!pwForm.password || pwForm.password.length < 8) {
            onToast("Password must be at least 8 characters", "error");
            return;
        }
        if (pwForm.password !== pwForm.confirm) {
            onToast("Passwords do not match", "error");
            return;
        }
        setSaving(true);
        try {
            await agentsApi.update(pwAgent.id, { password: pwForm.password });
            setPwAgent(null);
            setPwForm({ ...EMPTY_PW });
            onToast("Password updated");
        } catch (e: any) {
            onToast(e.message ?? "Failed to update password", "error");
        } finally {
            setSaving(false);
        }
    };

    // ── Delete ────────────────────────────────────────────────────────────────

    const confirmDelete = async () => {
        if (!delAgent) return;
        setSaving(true);
        try {
            await agentsApi.delete(delAgent.id);
            refetchAgents?.();
            setDelAgent(null);
            onToast("Agent removed");
        } catch {
            onToast("Failed to remove agent", "error");
        } finally {
            setSaving(false);
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

    const ROLE_OPTIONS = [
        { value: "agent",    label: "Agent"     },
        { value: "admin",    label: "Admin"     },
        { value: "readonly", label: "Read Only" },
    ];

    return (
        <div className={`flex-1 overflow-y-auto bg-stone-50 ${isMobile ? "p-4 pb-24" : "p-6"}`}>

            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div>
                    <h1 className="text-xl font-bold text-stone-800 tracking-tight">Team</h1>
                    <p className="text-sm text-stone-400 mt-0.5">
                        {agents.length} agents
                        <span className="mx-1.5 text-stone-200">·</span>
                        <span className="text-emerald-600">{onlineCount} online</span>
                    </p>
                </div>
                <button
                    onClick={() => setCreateModal(true)}
                    className="flex items-center gap-2 h-9 px-4 rounded-lg bg-green-700 hover:bg-green-600 text-white text-sm font-semibold transition-colors shadow-sm"
                >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                    </svg>
                    Add Agent
                </button>
            </div>

            {/* Agent grid */}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {agents.map((agent) => (
                    <div key={agent.id}
                        className="bg-white rounded-xl border border-stone-100 shadow-sm p-4 hover:shadow-md transition-all">
                        <div className="flex items-start gap-3 mb-3">
                            <div className="relative flex-shrink-0">
                                <Avatar name={agent.name} size={44} />
                                <div className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-white ${agent.is_available ? "bg-emerald-500" : "bg-stone-300"}`} />
                            </div>
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-sm font-semibold text-stone-800 truncate">
                                        {agent.name}
                                    </span>
                                    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-semibold capitalize ${ROLE_COLORS[agent.role] ?? ROLE_COLORS.agent}`}>
                                        {agent.role}
                                    </span>
                                </div>
                                <p className="text-xs text-stone-400 truncate mt-0.5">{agent.email}</p>
                                <p className="text-xs text-stone-400 mt-0.5">
                                    {agent.active_convs} active · Joined {agent.created_at ? fmtDate(agent.created_at) : "—"}
                                </p>
                                {agent.last_seen_at && (
                                    <p className="text-[10px] text-stone-300 mt-0.5">
                                        Last seen {new Date(agent.last_seen_at).toLocaleDateString()}
                                    </p>
                                )}
                            </div>
                        </div>

                        {/* Availability toggle */}
                        <div className="flex items-center justify-between border-t border-stone-50 pt-3">
                            <div className="flex items-center gap-2">
                                <span className="text-xs text-stone-400">Available</span>
                                <Toggle
                                    checked={agent.is_available}
                                    onChange={() => toggleOnline(agent.id, agent.is_available)}
                                />
                            </div>

                            {/* Actions */}
                            <div className="flex items-center gap-1">
                                {/* Edit */}
                                <button
                                    onClick={() => openEdit(agent)}
                                    title="Edit agent"
                                    className="h-7 px-2.5 rounded-lg text-xs font-medium bg-stone-100 text-stone-600 hover:bg-stone-200 transition-colors"
                                >
                                    Edit
                                </button>
                                {/* Reset password */}
                                <button
                                    onClick={() => { setPwAgent(agent); setPwForm({ ...EMPTY_PW }); }}
                                    title="Reset password"
                                    className="h-7 px-2.5 rounded-lg text-xs font-medium bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100 transition-colors"
                                >
                                    🔑
                                </button>
                                {/* Delete */}
                                <button
                                    onClick={() => setDelAgent(agent)}
                                    title="Remove agent"
                                    className="w-7 h-7 rounded-lg bg-red-50 text-red-500 hover:bg-red-100 border border-red-100 flex items-center justify-center transition-colors"
                                >
                                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                    </svg>
                                </button>
                            </div>
                        </div>
                    </div>
                ))}

                {agents.length === 0 && (
                    <div className="col-span-full py-16 text-center">
                        <p className="text-sm text-stone-400">No agents yet. Add one to get started.</p>
                    </div>
                )}
            </div>

            {/* ── Create modal ─────────────────────────────────────────────── */}
            <Modal show={createModal} onClose={() => setCreateModal(false)} title="Add Agent">
                <InputField label="Full Name" value={createForm.name}
                    onChange={(v) => setCreateForm((f) => ({ ...f, name: v }))}
                    placeholder="Jane Doe" required />
                <InputField label="Email" value={createForm.email}
                    onChange={(v) => setCreateForm((f) => ({ ...f, email: v }))}
                    placeholder="jane@bethanyhouse.co.ke" required />
                <InputField label="Password" value={createForm.password}
                    onChange={(v) => setCreateForm((f) => ({ ...f, password: v }))}
                    type="password" placeholder="Minimum 8 characters" required />
                <SelectField label="Role" value={createForm.role}
                    onChange={(v) => setCreateForm((f) => ({ ...f, role: v as AgentRole }))}
                    options={ROLE_OPTIONS} />
                <div className="flex gap-2 mt-4">
                    <Btn onClick={createAgent} variant="primary" disabled={saving} full>
                        {saving ? "Creating…" : "Create Agent"}
                    </Btn>
                    <Btn onClick={() => setCreateModal(false)} variant="outline">Cancel</Btn>
                </div>
            </Modal>

            {/* ── Edit modal ────────────────────────────────────────────────── */}
            <Modal show={!!editAgent} onClose={() => setEditAgent(null)}
                title={`Edit — ${editAgent?.name ?? ""}`}>
                <InputField label="Full Name" value={editForm.name}
                    onChange={(v) => setEditForm((f) => ({ ...f, name: v }))}
                    placeholder="Jane Doe" required />
                <InputField label="Email" value={editForm.email}
                    onChange={(v) => setEditForm((f) => ({ ...f, email: v }))}
                    placeholder="jane@bethanyhouse.co.ke" required />
                <SelectField label="Role" value={editForm.role}
                    onChange={(v) => setEditForm((f) => ({ ...f, role: v as AgentRole }))}
                    options={ROLE_OPTIONS} />
                <div className="flex gap-2 mt-4">
                    <Btn onClick={saveEdit} variant="primary" disabled={saving} full>
                        {saving ? "Saving…" : "Save Changes"}
                    </Btn>
                    <Btn onClick={() => setEditAgent(null)} variant="outline">Cancel</Btn>
                </div>
            </Modal>

            {/* ── Reset password modal ──────────────────────────────────────── */}
            <Modal show={!!pwAgent} onClose={() => setPwAgent(null)}
                title={`Reset Password — ${pwAgent?.name ?? ""}`}>
                <p className="text-xs text-stone-400 mb-4">
                    Set a new password for <span className="font-semibold text-stone-600">{pwAgent?.email}</span>.
                    The agent will need to use this password on their next login.
                </p>
                <InputField label="New Password" value={pwForm.password}
                    onChange={(v) => setPwForm((f) => ({ ...f, password: v }))}
                    type="password" placeholder="Minimum 8 characters" required />
                <InputField label="Confirm Password" value={pwForm.confirm}
                    onChange={(v) => setPwForm((f) => ({ ...f, confirm: v }))}
                    type="password" placeholder="Repeat new password" required />
                {pwForm.confirm && pwForm.password !== pwForm.confirm && (
                    <p className="text-xs text-red-500 -mt-2 mb-1">Passwords do not match</p>
                )}
                <div className="flex gap-2 mt-4">
                    <Btn onClick={savePassword} variant="primary" disabled={saving || (!!pwForm.confirm && pwForm.password !== pwForm.confirm)} full>
                        {saving ? "Saving…" : "Update Password"}
                    </Btn>
                    <Btn onClick={() => setPwAgent(null)} variant="outline">Cancel</Btn>
                </div>
            </Modal>

            {/* ── Delete confirm ────────────────────────────────────────────── */}
            <Modal show={!!delAgent} onClose={() => setDelAgent(null)} title="Remove Agent">
                <p className="text-sm text-stone-600 mb-1">
                    Remove <span className="font-semibold text-stone-800">{delAgent?.name}</span>?
                </p>
                <p className="text-xs text-stone-400 mb-5">
                    This cannot be undone. All conversations assigned to this agent will be unassigned.
                </p>
                <div className="flex gap-2">
                    <Btn onClick={confirmDelete} variant="danger" disabled={saving} full>
                        {saving ? "Removing…" : "Remove Agent"}
                    </Btn>
                    <Btn onClick={() => setDelAgent(null)} variant="outline">Cancel</Btn>
                </div>
            </Modal>
        </div>
    );
}
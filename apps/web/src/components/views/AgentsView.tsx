// AgentsView.tsx
// Team management with fully custom roles.
// Super Admin is the only predefined role (protected, not editable/deletable).
// Other roles can be created with custom permission sets.

import React, { useState } from "react";
import { Avatar } from "@/components/ui/Avatar";
import { Modal } from "@/components/ui/Modal";
import { Toggle } from "@/components/ui/Layout";
import { fmtDate } from "@/lib/utils";
import { agentsApi } from "@/lib/api";
import type { Agent, SharedViewProps } from "@/types";

// ── Permission catalogue ──────────────────────────────────────────────────────

interface Permission {
    key:   string;
    label: string;
    group: string;
}

const ALL_PERMISSIONS: Permission[] = [
    // Conversations
    { key: "view_conversations",    label: "View conversations",     group: "Conversations" },
    { key: "reply_conversations",   label: "Send replies",           group: "Conversations" },
    { key: "intercept_release",     label: "Intercept / Release AI", group: "Conversations" },
    { key: "close_conversations",   label: "Close conversations",    group: "Conversations" },
    { key: "transfer_conversations",label: "Transfer conversations", group: "Conversations" },
    { key: "add_notes",             label: "Add internal notes",     group: "Conversations" },
    // Orders
    { key: "view_orders",    label: "View orders",    group: "Orders" },
    { key: "manage_orders",  label: "Update order status", group: "Orders" },
    // Catalog
    { key: "view_catalog",   label: "View catalog",   group: "Catalog" },
    { key: "manage_catalog", label: "Edit catalog",   group: "Catalog" },
    // CRM / Leads
    { key: "view_leads",     label: "View leads",     group: "CRM" },
    { key: "manage_leads",   label: "Manage leads",   group: "CRM" },
    { key: "view_crm",       label: "View CRM profile", group: "CRM" },
    { key: "edit_crm",       label: "Edit CRM profile", group: "CRM" },
    // Reports & Analytics
    { key: "view_analytics", label: "View analytics", group: "Reports" },
    { key: "view_reports",   label: "View reports",   group: "Reports" },
    { key: "export_reports", label: "Export reports", group: "Reports" },
    // Admin
    { key: "manage_agents",  label: "Manage agents",  group: "Admin" },
    { key: "manage_roles",   label: "Manage roles",   group: "Admin" },
    { key: "manage_settings",label: "Manage settings",group: "Admin" },
];

const PERMISSION_GROUPS = [...new Set(ALL_PERMISSIONS.map(p => p.group))];

// ── Custom role definition ────────────────────────────────────────────────────

interface CustomRole {
    id:          string;
    name:        string;
    description: string;
    color:       string;  // hex
    permissions: string[];
    protected:   boolean; // super admin is protected
}

const SUPER_ADMIN_ROLE: CustomRole = {
    id:          "super_admin",
    name:        "Super Admin",
    description: "Full platform access — cannot be modified",
    color:       "#7c3aed",
    permissions: ALL_PERMISSIONS.map(p => p.key),
    protected:   true,
};

const DEFAULT_ROLES: CustomRole[] = [
    SUPER_ADMIN_ROLE,
    {
        id: "agent", name: "Agent", description: "Handle conversations and orders",
        color: "#589b31",
        permissions: ["view_conversations","reply_conversations","intercept_release",
            "close_conversations","transfer_conversations","add_notes","view_orders",
            "manage_orders","view_catalog","view_crm","view_leads"],
        protected: false,
    },
    {
        id: "viewer", name: "Viewer", description: "Read-only access",
        color: "#699a32",
        permissions: ["view_conversations","view_orders","view_catalog","view_crm","view_leads","view_analytics"],
        protected: false,
    },
];

const ROLE_COLORS = [
    "#589b31","#427425","#699a32","#2a48a2","#1f367a","#3d528f",
    "#717425","#979a32","#7c3aed","#0891b2","#0f766e","#b45309",
];

// ── Shared small components ───────────────────────────────────────────────────

function SBtn({ children, onClick, variant = "default", small, disabled }: {
    children: React.ReactNode; onClick?: () => void;
    variant?: "primary"|"danger"|"ghost"|"default";
    small?: boolean; disabled?: boolean;
}) {
    const styles: Record<string,React.CSSProperties> = {
        primary: { backgroundColor:"#589b31", color:"white", border:"1px solid #427425" },
        danger:  { backgroundColor:"#fff5f5", color:"#c0392b", border:"1px solid #fecaca" },
        ghost:   { backgroundColor:"transparent", color:"#699a32", border:"1px solid #b5da8b" },
        default: { backgroundColor:"white", color:"#427425", border:"1px solid #b5da8b" },
    };
    return (
        <button onClick={onClick} disabled={disabled}
            className={`font-semibold rounded-lg transition-colors flex items-center justify-center gap-1.5 disabled:opacity-50 ${small ? "text-[10px] px-2 py-1" : "text-xs px-3 py-1.5"}`}
            style={styles[variant]}>
            {children}
        </button>
    );
}

function SmallInput({ value, onChange, placeholder, type="text", label }: {
    value: string; onChange:(v:string)=>void; placeholder?:string; type?:string; label?:string;
}) {
    return (
        <div className="mb-3">
            {label && <label className="block text-xs font-semibold mb-1.5" style={{color:"#699a32"}}>{label}</label>}
            <input type={type} value={value} onChange={e=>onChange(e.target.value)} placeholder={placeholder}
                className="w-full h-8 px-2.5 text-xs rounded-lg focus:outline-none focus:ring-2"
                style={{backgroundColor:"#f3f9ec",border:"1px solid #b5da8b",color:"#16270c",fontSize:12}} />
        </div>
    );
}

// ── Props ─────────────────────────────────────────────────────────────────────

interface AgentsViewProps extends SharedViewProps {
    agents: Agent[];
    setAgents: React.Dispatch<React.SetStateAction<Agent[]>>;
    refetchAgents?: () => void;
}

// ── Main component ────────────────────────────────────────────────────────────

export function AgentsView({ agents, setAgents, onToast, isMobile, refetchAgents }: AgentsViewProps) {
    const [activeTab, setActiveTab] = useState<"agents"|"roles">("agents");

    // Roles state (local only — persisted to backend when API exists)
    const [roles, setRoles] = useState<CustomRole[]>(DEFAULT_ROLES);

    // Agent modals
    const [createModal,  setCreateModal]  = useState(false);
    const [editAgent,    setEditAgent]    = useState<Agent|null>(null);
    const [pwAgent,      setPwAgent]      = useState<Agent|null>(null);
    const [delAgent,     setDelAgent]     = useState<Agent|null>(null);

    // Role modals
    const [roleModal,    setRoleModal]    = useState<"create"|CustomRole|null>(null);
    const [delRole,      setDelRole]      = useState<CustomRole|null>(null);

    // Forms
    const [saving, setSaving] = useState(false);
    const [createForm, setCreateForm] = useState({ name:"", email:"", password:"", roleId:"agent" });
    const [editForm,   setEditForm]   = useState({ name:"", email:"", roleId:"agent" });
    const [pwForm,     setPwForm]     = useState({ password:"", confirm:"" });
    const [roleForm,   setRoleForm]   = useState<Omit<CustomRole,"id"|"protected">>({
        name:"", description:"", color:ROLE_COLORS[0], permissions:[]
    });

    // ── Agent CRUD ─────────────────────────────────────────────────────────────

    const createAgent = async () => {
        if (!createForm.name || !createForm.email || !createForm.password) {
            return onToast("Name, email and password are required","error");
        }
        if (createForm.password.length < 8) return onToast("Password must be ≥8 characters","error");
        setSaving(true);
        try {
            await agentsApi.create({ name:createForm.name, email:createForm.email,
                password:createForm.password, role:createForm.roleId as any });
            refetchAgents?.();
            setCreateModal(false);
            setCreateForm({ name:"", email:"", password:"", roleId:"agent" });
            onToast("Agent created");
        } catch (e:any) { onToast(e.message??"Failed to create agent","error"); }
        finally { setSaving(false); }
    };

    const saveEdit = async () => {
        if (!editAgent || !editForm.name || !editForm.email) return onToast("Name and email required","error");
        setSaving(true);
        try {
            await agentsApi.update(editAgent.id, { name:editForm.name, email:editForm.email, role:editForm.roleId as any });
            refetchAgents?.(); setEditAgent(null); onToast("Agent updated");
        } catch (e:any) { onToast(e.message??"Failed","error"); }
        finally { setSaving(false); }
    };

    const savePassword = async () => {
        if (!pwAgent) return;
        if (pwForm.password.length < 8) return onToast("Password must be ≥8 characters","error");
        if (pwForm.password !== pwForm.confirm) return onToast("Passwords do not match","error");
        setSaving(true);
        try {
            await agentsApi.update(pwAgent.id, { password:pwForm.password });
            setPwAgent(null); setPwForm({password:"",confirm:""}); onToast("Password updated");
        } catch (e:any) { onToast(e.message??"Failed","error"); }
        finally { setSaving(false); }
    };

    const confirmDelete = async () => {
        if (!delAgent) return;
        setSaving(true);
        try {
            await agentsApi.delete(delAgent.id); refetchAgents?.(); setDelAgent(null); onToast("Agent removed");
        } catch { onToast("Failed to remove","error"); }
        finally { setSaving(false); }
    };

    const toggleOnline = async (id:string, current:boolean) => {
        try { await agentsApi.toggleAvailable(id, !current); refetchAgents?.(); }
        catch { onToast("Failed to update","error"); }
    };

    // ── Role CRUD ──────────────────────────────────────────────────────────────

    const openCreateRole = () => {
        setRoleForm({ name:"", description:"", color:ROLE_COLORS[0], permissions:[] });
        setRoleModal("create");
    };
    const openEditRole = (role: CustomRole) => {
        setRoleForm({ name:role.name, description:role.description, color:role.color, permissions:[...role.permissions] });
        setRoleModal(role);
    };
    const saveRole = () => {
        if (!roleForm.name.trim()) return onToast("Role name required","error");
        if (roleModal === "create") {
            const newRole: CustomRole = {
                id: `role_${Date.now()}`, ...roleForm, protected: false,
            };
            setRoles(r => [...r, newRole]);
            onToast("Role created");
        } else if (roleModal && roleModal !== "create") {
            setRoles(r => r.map(x => x.id === (roleModal as CustomRole).id ? { ...x, ...roleForm } : x));
            onToast("Role updated");
        }
        setRoleModal(null);
    };
    const deleteRole = () => {
        if (!delRole) return;
        setRoles(r => r.filter(x => x.id !== delRole.id));
        setDelRole(null); onToast("Role deleted");
    };
    const togglePermission = (key: string) => {
        setRoleForm(f => ({
            ...f,
            permissions: f.permissions.includes(key)
                ? f.permissions.filter(p => p !== key)
                : [...f.permissions, key],
        }));
    };

    const getRoleById = (id: string) => roles.find(r => r.id === id);
    const onlineCount = agents.filter(a => a.is_available).length;

    // ── Render ─────────────────────────────────────────────────────────────────

    return (
        <div className={`flex-1 overflow-y-auto ${isMobile?"p-4 pb-24":"p-6"}`} style={{backgroundColor:"#f3f9ec"}}>

            {/* Header */}
            <div className="flex items-center justify-between mb-5">
                <div>
                    <h1 className="text-xl font-bold tracking-tight" style={{color:"#16270c"}}>Team</h1>
                    <p className="text-sm mt-0.5" style={{color:"#699a32"}}>
                        {agents.length} agents · <span style={{color:"#589b31"}}>{onlineCount} online</span>
                    </p>
                </div>
                {activeTab === "agents" ? (
                    <SBtn variant="primary" onClick={() => setCreateModal(true)}>
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4"/>
                        </svg>
                        Add Agent
                    </SBtn>
                ) : (
                    <SBtn variant="primary" onClick={openCreateRole}>
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4"/>
                        </svg>
                        New Role
                    </SBtn>
                )}
            </div>

            {/* Tab switcher */}
            <div className="flex gap-1 mb-5" style={{borderBottom:"1px solid #cee6b2"}}>
                {(["agents","roles"] as const).map(t => (
                    <button key={t} onClick={() => setActiveTab(t)}
                        className={`px-4 py-2 text-xs font-semibold capitalize transition-colors border-b-2 -mb-px`}
                        style={ activeTab===t
                            ? {color:"#427425",borderColor:"#589b31"}
                            : {color:"#699a32",borderColor:"transparent"} }>
                        {t === "agents" ? `Agents (${agents.length})` : `Roles (${roles.length})`}
                    </button>
                ))}
            </div>

            {/* ── AGENTS TAB ─────────────────────────────────────────────────── */}
            {activeTab === "agents" && (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                    {agents.map(agent => {
                        const role = getRoleById(agent.role);
                        return (
                            <div key={agent.id} className="rounded-xl shadow-sm p-4 hover:shadow-md transition-all"
                                style={{backgroundColor:"white",border:"1px solid #cee6b2"}}>
                                <div className="flex items-start gap-3 mb-3">
                                    <div className="relative flex-shrink-0">
                                        <Avatar name={agent.name} size={44} />
                                        <div className={`absolute -bottom-0.5 -right-0.5 w-3 h-3 rounded-full border-2 border-white ${agent.is_available?"bg-emerald-500":"bg-stone-300"}`} />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="text-sm font-semibold truncate" style={{color:"#16270c"}}>{agent.name}</span>
                                            {role && (
                                                <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded-full text-white flex-shrink-0"
                                                    style={{backgroundColor:role.color}}>
                                                    {role.name}
                                                </span>
                                            )}
                                        </div>
                                        <p className="text-xs truncate mt-0.5" style={{color:"#699a32"}}>{agent.email}</p>
                                        <p className="text-xs mt-0.5" style={{color:"#9ccd65"}}>
                                            {agent.active_convs} active · Joined {agent.created_at ? fmtDate(agent.created_at) : "—"}
                                        </p>
                                    </div>
                                </div>
                                <div className="flex items-center justify-between pt-3" style={{borderTop:"1px solid #e6f3d8"}}>
                                    <div className="flex items-center gap-2">
                                        <span className="text-xs" style={{color:"#699a32"}}>Available</span>
                                        <Toggle checked={agent.is_available} onChange={() => toggleOnline(agent.id, agent.is_available)} />
                                    </div>
                                    <div className="flex items-center gap-1">
                                        <SBtn small onClick={() => { setEditAgent(agent); setEditForm({name:agent.name,email:agent.email,roleId:agent.role}); }}>
                                            Edit
                                        </SBtn>
                                        <SBtn small variant="ghost" onClick={() => { setPwAgent(agent); setPwForm({password:"",confirm:""}); }}>🔑</SBtn>
                                        <SBtn small variant="danger" onClick={() => setDelAgent(agent)}>
                                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                    d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                            </svg>
                                        </SBtn>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                    {agents.length === 0 && (
                        <div className="col-span-full py-16 text-center">
                            <p className="text-sm" style={{color:"#699a32"}}>No agents yet.</p>
                        </div>
                    )}
                </div>
            )}

            {/* ── ROLES TAB ──────────────────────────────────────────────────── */}
            {activeTab === "roles" && (
                <div className="space-y-3">
                    {roles.map(role => {
                        const agentCount = agents.filter(a => a.role === role.id).length;
                        return (
                            <div key={role.id} className="rounded-xl shadow-sm overflow-hidden"
                                style={{backgroundColor:"white",border:"1px solid #cee6b2"}}>
                                <div className="flex items-start gap-4 p-4">
                                    {/* Color swatch */}
                                    <div className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 text-white font-bold text-sm"
                                        style={{backgroundColor:role.color}}>
                                        {role.name[0].toUpperCase()}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap mb-1">
                                            <span className="text-sm font-bold" style={{color:"#16270c"}}>{role.name}</span>
                                            {role.protected && (
                                                <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-full"
                                                    style={{backgroundColor:"#e6f3d8",color:"#427425"}}>Protected</span>
                                            )}
                                            <span className="text-[10px]" style={{color:"#699a32"}}>{agentCount} agent{agentCount!==1?"s":""}</span>
                                        </div>
                                        <p className="text-xs mb-2" style={{color:"#699a32"}}>{role.description}</p>
                                        {/* Permission chips */}
                                        <div className="flex flex-wrap gap-1">
                                            {role.permissions.slice(0,8).map(p => {
                                                const perm = ALL_PERMISSIONS.find(x => x.key === p);
                                                return perm ? (
                                                    <span key={p} className="text-[9px] font-medium px-1.5 py-0.5 rounded"
                                                        style={{backgroundColor:"#f0f9ec",color:"#427425",border:"1px solid #b5da8b"}}>
                                                        {perm.label}
                                                    </span>
                                                ) : null;
                                            })}
                                            {role.permissions.length > 8 && (
                                                <span className="text-[9px] font-medium px-1.5 py-0.5 rounded"
                                                    style={{backgroundColor:"#e6f3d8",color:"#699a32"}}>
                                                    +{role.permissions.length-8} more
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                    {!role.protected && (
                                        <div className="flex items-center gap-1 flex-shrink-0">
                                            <SBtn small onClick={() => openEditRole(role)}>Edit</SBtn>
                                            <SBtn small variant="danger" onClick={() => setDelRole(role)}>
                                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                                        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                                                </svg>
                                            </SBtn>
                                        </div>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* ── MODALS ─────────────────────────────────────────────────────── */}

            {/* Create agent */}
            <Modal show={createModal} onClose={() => setCreateModal(false)} title="Add Agent">
                <SmallInput label="Full Name" value={createForm.name} onChange={v=>setCreateForm(f=>({...f,name:v}))} placeholder="Jane Doe" />
                <SmallInput label="Email" value={createForm.email} onChange={v=>setCreateForm(f=>({...f,email:v}))} placeholder="jane@bethanyhouse.co.ke" />
                <SmallInput label="Password" type="password" value={createForm.password} onChange={v=>setCreateForm(f=>({...f,password:v}))} placeholder="Min. 8 characters" />
                <div className="mb-4">
                    <label className="block text-xs font-semibold mb-1.5" style={{color:"#699a32"}}>Role</label>
                    <select value={createForm.roleId} onChange={e=>setCreateForm(f=>({...f,roleId:e.target.value}))}
                        className="w-full h-8 px-2.5 text-xs rounded-lg" style={{backgroundColor:"#f3f9ec",border:"1px solid #b5da8b",color:"#16270c",fontSize:12}}>
                        {roles.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                    </select>
                </div>
                <div className="flex gap-2 mt-4">
                    <SBtn variant="primary" onClick={createAgent} disabled={saving}>{saving?"Creating…":"Create Agent"}</SBtn>
                    <SBtn onClick={() => setCreateModal(false)}>Cancel</SBtn>
                </div>
            </Modal>

            {/* Edit agent */}
            <Modal show={!!editAgent} onClose={() => setEditAgent(null)} title={`Edit — ${editAgent?.name??""}`}>
                <SmallInput label="Full Name" value={editForm.name} onChange={v=>setEditForm(f=>({...f,name:v}))} placeholder="Jane Doe" />
                <SmallInput label="Email" value={editForm.email} onChange={v=>setEditForm(f=>({...f,email:v}))} placeholder="jane@bethanyhouse.co.ke" />
                <div className="mb-4">
                    <label className="block text-xs font-semibold mb-1.5" style={{color:"#699a32"}}>Role</label>
                    <select value={editForm.roleId} onChange={e=>setEditForm(f=>({...f,roleId:e.target.value}))}
                        className="w-full h-8 px-2.5 text-xs rounded-lg" style={{backgroundColor:"#f3f9ec",border:"1px solid #b5da8b",color:"#16270c",fontSize:12}}>
                        {roles.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}
                    </select>
                </div>
                <div className="flex gap-2 mt-4">
                    <SBtn variant="primary" onClick={saveEdit} disabled={saving}>{saving?"Saving…":"Save Changes"}</SBtn>
                    <SBtn onClick={() => setEditAgent(null)}>Cancel</SBtn>
                </div>
            </Modal>

            {/* Reset password */}
            <Modal show={!!pwAgent} onClose={() => setPwAgent(null)} title={`Reset Password — ${pwAgent?.name??""}`}>
                <p className="text-xs mb-4" style={{color:"#699a32"}}>
                    Set a new password for <span className="font-semibold" style={{color:"#16270c"}}>{pwAgent?.email}</span>.
                </p>
                <SmallInput label="New Password" type="password" value={pwForm.password} onChange={v=>setPwForm(f=>({...f,password:v}))} placeholder="Min. 8 characters" />
                <SmallInput label="Confirm Password" type="password" value={pwForm.confirm} onChange={v=>setPwForm(f=>({...f,confirm:v}))} placeholder="Repeat new password" />
                {pwForm.confirm && pwForm.password !== pwForm.confirm && (
                    <p className="text-[10px] text-red-500 -mt-2 mb-2">Passwords do not match</p>
                )}
                <div className="flex gap-2 mt-4">
                    <SBtn variant="primary" onClick={savePassword} disabled={saving || (!!pwForm.confirm && pwForm.password !== pwForm.confirm)}>
                        {saving ? "Saving…" : "Update Password"}
                    </SBtn>
                    <SBtn onClick={() => setPwAgent(null)}>Cancel</SBtn>
                </div>
            </Modal>

            {/* Delete agent */}
            <Modal show={!!delAgent} onClose={() => setDelAgent(null)} title="Remove Agent">
                <p className="text-sm mb-1" style={{color:"#16270c"}}>Remove <strong>{delAgent?.name}</strong>?</p>
                <p className="text-xs mb-5" style={{color:"#699a32"}}>This cannot be undone. Their conversations will be unassigned.</p>
                <div className="flex gap-2">
                    <SBtn variant="danger" onClick={confirmDelete} disabled={saving}>{saving?"Removing…":"Remove Agent"}</SBtn>
                    <SBtn onClick={() => setDelAgent(null)}>Cancel</SBtn>
                </div>
            </Modal>

            {/* Create / Edit Role */}
            <Modal
                show={!!roleModal}
                onClose={() => setRoleModal(null)}
                title={roleModal === "create" ? "New Role" : `Edit Role — ${(roleModal as CustomRole)?.name??""}`}
            >
                <SmallInput label="Role Name" value={roleForm.name} onChange={v=>setRoleForm(f=>({...f,name:v}))} placeholder="e.g. Sales Agent" />
                <SmallInput label="Description" value={roleForm.description} onChange={v=>setRoleForm(f=>({...f,description:v}))} placeholder="Brief description" />

                {/* Color picker */}
                <div className="mb-4">
                    <label className="block text-xs font-semibold mb-1.5" style={{color:"#699a32"}}>Colour</label>
                    <div className="flex flex-wrap gap-2">
                        {ROLE_COLORS.map(c => (
                            <button key={c} onClick={() => setRoleForm(f=>({...f,color:c}))}
                                className="w-6 h-6 rounded-full transition-transform"
                                style={{ backgroundColor:c, outline: roleForm.color===c ? `2px solid ${c}` : "none", outlineOffset:2, transform: roleForm.color===c?"scale(1.25)":"scale(1)" }} />
                        ))}
                    </div>
                </div>

                {/* Permissions by group */}
                <div className="mb-4">
                    <label className="block text-xs font-semibold mb-2" style={{color:"#699a32"}}>Permissions</label>
                    <div className="space-y-3 max-h-60 overflow-y-auto pr-1">
                        {PERMISSION_GROUPS.map(group => (
                            <div key={group}>
                                <div className="flex items-center justify-between mb-1.5">
                                    <span className="text-[10px] font-bold uppercase tracking-wider" style={{color:"#427425"}}>{group}</span>
                                    <button
                                        onClick={() => {
                                            const groupPerms = ALL_PERMISSIONS.filter(p=>p.group===group).map(p=>p.key);
                                            const allSelected = groupPerms.every(k => roleForm.permissions.includes(k));
                                            setRoleForm(f => ({
                                                ...f,
                                                permissions: allSelected
                                                    ? f.permissions.filter(k => !groupPerms.includes(k))
                                                    : [...new Set([...f.permissions,...groupPerms])]
                                            }));
                                        }}
                                        className="text-[9px] font-semibold" style={{color:"#589b31"}}>
                                        {ALL_PERMISSIONS.filter(p=>p.group===group).every(p=>roleForm.permissions.includes(p.key)) ? "Deselect all" : "Select all"}
                                    </button>
                                </div>
                                <div className="grid grid-cols-2 gap-1.5">
                                    {ALL_PERMISSIONS.filter(p=>p.group===group).map(perm => {
                                        const checked = roleForm.permissions.includes(perm.key);
                                        return (
                                            <button key={perm.key} onClick={() => togglePermission(perm.key)}
                                                className="flex items-center gap-1.5 p-1.5 rounded-lg text-[10px] font-medium text-left transition-colors"
                                                style={{
                                                    backgroundColor: checked?"#e6f3d8":"#f9fafb",
                                                    border: checked?"1px solid #b5da8b":"1px solid #e5e7eb",
                                                    color: checked?"#427425":"#6b7280",
                                                }}>
                                                <div className="w-3 h-3 rounded flex items-center justify-center flex-shrink-0"
                                                    style={{backgroundColor:checked?"#589b31":"white",border:checked?"1px solid #589b31":"1px solid #d1d5db"}}>
                                                    {checked && <svg className="w-2 h-2 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7"/>
                                                    </svg>}
                                                </div>
                                                {perm.label}
                                            </button>
                                        );
                                    })}
                                </div>
                            </div>
                        ))}
                    </div>
                    <div className="text-[10px] mt-2" style={{color:"#699a32"}}>{roleForm.permissions.length} of {ALL_PERMISSIONS.length} permissions selected</div>
                </div>

                <div className="flex gap-2">
                    <SBtn variant="primary" onClick={saveRole}>
                        {roleModal === "create" ? "Create Role" : "Save Role"}
                    </SBtn>
                    <SBtn onClick={() => setRoleModal(null)}>Cancel</SBtn>
                </div>
            </Modal>

            {/* Delete role */}
            <Modal show={!!delRole} onClose={() => setDelRole(null)} title="Delete Role">
                <p className="text-sm mb-1" style={{color:"#16270c"}}>Delete role <strong>{delRole?.name}</strong>?</p>
                <p className="text-xs mb-5" style={{color:"#699a32"}}>
                    {agents.filter(a=>a.role===delRole?.id).length} agent(s) will need to be reassigned.
                </p>
                <div className="flex gap-2">
                    <SBtn variant="danger" onClick={deleteRole}>Delete Role</SBtn>
                    <SBtn onClick={() => setDelRole(null)}>Cancel</SBtn>
                </div>
            </Modal>
        </div>
    );
}
import Foundation

/// Who may do what in the open thread — exactly the web's rules
/// (ConversationsView.tsx): admin/superuser, or the "agent" role, handles
/// conversations; ownership decides the rest per thread.
public struct InboxPerms: Equatable, Sendable {
    public let me: String?
    public let isAdminOrSuper: Bool
    public let canHandle: Bool
    public init(me: String?, isAdminOrSuper: Bool, canHandle: Bool) { self.me = me; self.isAdminOrSuper = isAdminOrSuper; self.canHandle = canHandle }

    /// The web's role rules: `isAdminOrSuper = is_superuser || role === "admin"`,
    /// `canHandleConversations = isAdminOrSuper || role === "agent"`. Deliberately
    /// the ROLE, not a permission list: a custom role keeps every control its
    /// legacy role gives, and a readonly (or supervisor) agent gets none.
    public static func of(role: String?, superuser: Bool, me: String?) -> InboxPerms {
        let isAdmin = superuser || role == "admin"
        return InboxPerms(me: me, isAdminOrSuper: isAdmin, canHandle: isAdmin || role == "agent")
    }

    /// Who the agent is comes from the freshest record: the team-list row, else
    /// /admin/me — never the sign-in session. No record yet means no controls yet
    /// (like the web, whose `currentAgent` is null until profileApi.me() answers).
    public static func of(agent: Agent?, sessionAgentId: String?) -> InboxPerms {
        of(role: agent?.role, superuser: agent?.isSuperuser == true, me: sessionAgentId ?? agent?.id)
    }

    /// The server's rule for PUT /admin/settings/pipeline-stages (crm.py): superuser or role admin — from the freshest record.
    public static func canEditPipelineStages(agent: Agent?) -> Bool {
        guard let a = agent else { return false }
        return a.isSuperuser || a.role == "admin"
    }
}

/// Which of the open thread's controls this agent sees — ConversationsView.tsx
/// line for line. Everything else in the thread (the per-message Reply, Ask
/// Neema, the team answer, invite, call, the whole customer panel) the web
/// shows to every signed-in agent, and so does the app.
public struct ThreadControls: Equatable, Sendable {
    public let intercept: Bool
    public let pickUp: Bool
    public let release: Bool
    public let pause: Bool
    public let resume: Bool
    public let transfer: Bool
    public let note: Bool
    public let clearHistory: Bool
    /// The reply box (with the AI draft, attachments, translation).
    public let composer: Bool
    /// The 🔒 header badge and the "Handled by …" banner.
    public let locked: Bool

    public init(intercept: Bool, pickUp: Bool, release: Bool, pause: Bool, resume: Bool, transfer: Bool, note: Bool, clearHistory: Bool, composer: Bool, locked: Bool) {
        self.intercept = intercept; self.pickUp = pickUp; self.release = release; self.pause = pause; self.resume = resume
        self.transfer = transfer; self.note = note; self.clearHistory = clearHistory; self.composer = composer; self.locked = locked
    }

    /// The names of the controls shown, for tests and logs.
    public var shown: Set<String> {
        var s = Set<String>()
        if intercept { s.insert("intercept") }; if pickUp { s.insert("pickUp") }; if release { s.insert("release") }
        if pause { s.insert("pause") }; if resume { s.insert("resume") }; if transfer { s.insert("transfer") }
        if note { s.insert("note") }; if clearHistory { s.insert("clear") }; if composer { s.insert("composer") }
        if locked { s.insert("locked") }
        return s
    }
}

public func threadControls(_ conv: Conversation, _ perms: InboxPerms) -> ThreadControls {
    let mode = conv.interceptMode
    // isOwner: this agent intercepted it; ownedByOther: a different agent holds it.
    let isOwner = conv.assignedAgentId != nil && conv.assignedAgentId == perms.me
    let ownedByOther = mode == "human" && conv.assignedAgentId != nil && conv.assignedAgentId != perms.me
    // canActOnThisConv — Pause / Resume / Transfer: owner, admin, or nobody human holds it.
    let canAct = perms.canHandle && (isOwner || perms.isAdminOrSuper || mode != "human")
    return ThreadControls(
        // Any agent can intercept an AI conversation — whoever picks it up owns it.
        intercept: mode == "ai" && perms.canHandle,
        // Auto-escalated (media) but unclaimed: first one to tap gets it.
        pickUp: mode == "human" && conv.assignedAgentId == nil && perms.canHandle,
        // Owner-restricted: only the intercepting agent or admin can release.
        release: mode == "human" && (isOwner || perms.isAdminOrSuper),
        pause: mode != "paused" && canAct,
        resume: mode == "paused" && canAct,
        transfer: canAct,
        note: perms.canHandle,
        // Admin/superuser only — and the server (DELETE /messages) refuses anyone else.
        clearHistory: perms.isAdminOrSuper,
        composer: mode == "human" && (isOwner || perms.isAdminOrSuper),
        // Regular agents see who holds it; admins never see the lock.
        locked: ownedByOther && !perms.isAdminOrSuper
    )
}

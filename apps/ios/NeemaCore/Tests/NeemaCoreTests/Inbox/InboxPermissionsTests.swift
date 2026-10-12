import Foundation
import XCTest
@testable import NeemaCore

/// Round 6 — the inbox's permission matrix against a signed-in host (the rest
/// of Android `InboxPermissionsTest`; the pure truth table, the stale session
/// and the stage editor are in `InboxPermsTests`). The web
/// (ConversationsView.tsx) gates the thread's controls on the stored ROLE and
/// ownership only:
///
///   isAdminOrSuper         = is_superuser || role === "admin"
///   canHandleConversations = isAdminOrSuper || role === "agent"
///   isOwner                = assigned_agent_id === me
///   canActOnThisConv       = canHandle && (isOwner || isAdminOrSuper || mode !== "human")
///
/// and the server (admin.py) refuses nothing on these routes but DELETE
/// /messages (admin/superuser). Permission lists (custom roles, overrides)
/// never enter into it. Everything else — the per-message Reply, Ask Neema,
/// the team answer, invite, call, bulk release, the customer panel — is open
/// to every signed-in agent.
@MainActor
final class InboxPermissionsTests: XCTestCase {
    /// The round-6 personas: who is signed in, as the server tells it — the
    /// session's role, GET /admin/me (the bare ORM row) and this agent's
    /// GET /admin/agents row (with role_permissions / custom_permissions).
    enum Persona: CaseIterable {
        /// Superuser on a plain agent role: is_superuser alone makes them an admin.
        case superuser
        case admin
        /// Legacy agent — no custom role: the LEGACY_FALLBACK agent set.
        case agent
        /// Legacy readonly — views everything, handles nothing.
        case readonly
        /// A custom Sales role on the agent enum.
        case sales
        /// A custom role WITHOUT reply_conversations / intercept_release — still the agent enum.
        case viewer
        /// A custom role that grants replying — on the readonly enum.
        case readonlyReplier
        /// A per-agent override naming only view_conversations.
        case override
        /// An empty override: the web reads it as "no override" (length check) and falls back.
        case emptyOverride
        /// A role the inbox doesn't recognise as a handler.
        case supervisor

        var role: String {
            switch self {
            case .superuser, .agent, .sales, .viewer, .override, .emptyOverride: return "agent"
            case .admin: return "admin"
            case .readonly, .readonlyReplier: return "readonly"
            case .supervisor: return "supervisor"
            }
        }
        var superuser: Bool { self == .superuser }
        var customRole: String? {
            switch self {
            case .sales: return "sales"
            case .viewer: return "viewer"
            case .readonlyReplier: return "replier"
            default: return nil
            }
        }
        var roleName: String? {
            switch self {
            case .sales: return "Sales"
            case .viewer: return "Viewer"
            case .readonlyReplier: return "Replier"
            default: return nil
            }
        }
        var rolePermissions: String {
            switch self {
            case .sales: return #"["view_conversations","reply_conversations","view_orders","manage_orders"]"#
            case .viewer: return #"["view_conversations","view_orders"]"#
            case .readonlyReplier: return #"["view_conversations","reply_conversations","intercept_release"]"#
            default: return "null"
            }
        }
        var customPermissions: String {
            switch self {
            case .override: return #"["view_conversations"]"#
            case .emptyOverride: return "[]"
            default: return "null"
            }
        }
    }

    /// GET /admin/me for `p`: the base admin ORM row with the persona's role and flag.
    static func me(_ p: Persona) -> String {
        Fixtures.meOrm
            .replacingOccurrences(of: "\"role\":\"admin\"", with: "\"role\":\"\(p.role)\"")
            .replacingOccurrences(of: "\"is_superuser\":true", with: "\"is_superuser\":\(p.superuser)")
    }

    /// The signed-in agent's GET /admin/agents row for `p`.
    static func row(_ p: Persona) -> String {
        Fixtures.agentRow(Fixtures.ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", p.role, true, p.superuser, 4, 60 * 24 * 200, 1,
                          customRole: p.customRole, roleName: p.roleName, roleColor: p.customRole == nil ? nil : "#3b82f6",
                          rolePermissions: p.rolePermissions, customPermissions: p.customPermissions)
    }

    /// The whole team list with the signed-in agent as `p` (rebuilt, not a text replace).
    static func agents(_ p: Persona) -> String {
        let base = JSONValue.parse(Fixtures.agents)?.arrayValue ?? []
        let rest = base.filter { $0.objectValue?["id"]?.stringValue != Fixtures.ME_ID }
        return JSONValue.array([JSONValue.parse(row(p))!] + rest).text
    }

    static let roles = """
    [{"id":"admin","name":"Admin","description":"Full system access","color":"#f59e0b","permissions":["view_conversations","manage_agents","manage_roles","manage_settings"],"protected":true},
      {"id":"sales","name":"Sales","description":"Handles conversations and orders","color":"#3b82f6","permissions":["view_conversations","reply_conversations","view_orders","manage_orders"],"protected":false},
      {"id":"viewer","name":"Viewer","description":"Reads conversations","color":"#3b82f6","permissions":["view_conversations","view_orders"],"protected":false},
      {"id":"replier","name":"Replier","description":"Replies on a readonly seat","color":"#3b82f6","permissions":["view_conversations","reply_conversations","intercept_release"],"protected":false}]
    """

    /// Serve `p` as the signed-in agent (after the base and inbox installs).
    static func install(_ f: FakeNeema, _ p: Persona) {
        f.on("GET", "/admin/me", body: me(p))
        f.on("GET", "/admin/agents", body: agents(p))
        f.on("GET", "/admin/roles", body: roles)
    }

    var fake: FakeNeema!
    var hosts: [TestHost] = []
    var vms: [InboxViewModel] = []

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        InboxFixtures.install(fake)
    }

    override func tearDown() async throws {
        for v in vms { v.close() }
        vms = []
        for h in hosts { h.logout() }
        hosts = []
        AppClock.reset()
        try await super.tearDown()
    }

    /// Android `dashboard(context, fake, role, super)` + `ConversationsViewModel(dash)`: the shell reads
    /// the team list and /admin/me at sign-in, and the inbox opens on it.
    func signIn(_ p: Persona, sessionRole: String? = nil, sessionSuper: Bool? = nil) async -> (TestHost, InboxViewModel) {
        Self.install(fake, p)
        let host = TestHost(fake: fake, role: sessionRole ?? p.role, superuser: sessionSuper ?? p.superuser)
        hosts.append(host)
        await rereadWhoIAm(host)
        let vm = InboxViewModel(host: host, sleep: host.clock.sleeper)
        vms.append(vm)
        await drain()
        return (host, vm)
    }

    /// The shell's reads of the team list and the signed-in row (what its 180 s agents poll and its 403 re-read store).
    func rereadWhoIAm(_ host: TestHost) async {
        _ = try? await host.refreshAgents()
        host.refetchMe()
        await drain()
        _ = await eventually(timeout: 5) { host.me.value != nil }
    }

    /// Android `inboxPermsOf(dash)`: who the agent is comes from the freshest record — the team row, else /admin/me.
    func inboxPermsOf(_ host: TestHost) -> InboxPerms {
        let row = ShellRules.teamRow(agents: host.agents.value, me: host.me.value, session: host.session.value) ?? host.me.value
        return InboxPerms.of(agent: row, sessionAgentId: host.session.value?.agentId)
    }

    /// Android `dash.can(perm)`: the core permission API, resolved from the team row.
    func can(_ host: TestHost, _ perm: String) -> Bool {
        ShellRules.access(agents: host.agents.value, me: host.me.value, session: host.session.value).can(perm)
    }

    func conv(_ vm: InboxViewModel, _ id: String) -> Conversation { vm.inbox.value.cache[id]! }

    /// The controls a persona sees on a thread, by name.
    func shown(_ host: TestHost, _ c: Conversation) -> Set<String> { threadControls(c, inboxPermsOf(host)).shown }

    /// Core folds a burst of 403s into one refetch after a short window (NeemaHTTP → the shell's onForbidden()).
    func settleForbidden(_ host: TestHost) async {
        await host.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1)
        await drain()
    }

    /// Custom roles and overrides change nothing in the inbox: the web never reads them there.
    func testPermissionListsNeverGateTheInbox() async {
        let (host, _) = await signIn(.viewer)
        // The core permission API does see the difference…
        XCTAssertFalse(can(host, "reply_conversations")); XCTAssertFalse(can(host, "intercept_release"))
        // …and the inbox, like the web, does not.
        let perms = inboxPermsOf(host)
        XCTAssertTrue(perms.canHandle); XCTAssertFalse(perms.isAdminOrSuper)
    }

    func testReadonlyEnumWithReplyPermissionStillHandlesNothing() async {
        let (host, _) = await signIn(.readonlyReplier)
        XCTAssertTrue(can(host, "reply_conversations"))
        XCTAssertFalse(inboxPermsOf(host).canHandle)
    }

    /// An empty override is "no override" on the web (a length check): legacy agent rights.
    func testEmptyOverrideFallsBackToTheLegacyRole() async {
        let (host, _) = await signIn(.emptyOverride)
        XCTAssertTrue(can(host, "reply_conversations"))
        XCTAssertTrue(inboxPermsOf(host).canHandle)
    }

    /// Persona 8: an admin demotes this agent while the inbox is open — the shell's 180 s agents poll carries it.
    func testRoleChangeReachesTheOpenInboxOnTheAgentsPoll() async {
        let (host, vm) = await signIn(.agent)
        XCTAssertEqual(["intercept", "pause", "transfer", "note"], shown(host, conv(vm, "c2")))
        fake.on("GET", "/admin/agents", body: Self.agents(.readonly))
        await rereadWhoIAm(host)   // the poll's read of the team list
        XCTAssertEqual([], shown(host, conv(vm, "c2")))
        // And back: promoted to admin, Clear history appears.
        fake.on("GET", "/admin/agents", body: Self.agents(.admin))
        await rereadWhoIAm(host)
        XCTAssertTrue(shown(host, conv(vm, "c2")).contains("clear"))
    }

    /// A 403 re-reads who this agent is at once, so the controls correct themselves.
    func testForbiddenRefetchesMeAndAgentsAndTheControlsCorrect() async {
        let (host, vm) = await signIn(.agent)
        fake.on("GET", "/admin/agents", body: Self.agents(.readonly))
        fake.on("GET", "/admin/me", body: Self.me(.readonly))
        fake.on("POST", "/admin/conversations/c2/intercept", code: 403, body: #"{"detail":"Not allowed"}"#)
        let meBefore = fake.callsTo("GET", "/admin/me").count
        let agentsBefore = fake.callsTo("GET", "/admin/agents").count
        vm.intercept("c2"); await drain(); await settleForbidden(host)
        XCTAssertTrue(fake.callsTo("GET", "/admin/me").count > meBefore)
        XCTAssertTrue(fake.callsTo("GET", "/admin/agents").count > agentsBefore)
        XCTAssertEqual(1, host.accessRereads)
        XCTAssertEqual(.error, host.toasts.last?.type)
        XCTAssertEqual("Failed to claim conversation. Not allowed", host.toasts.last?.message)
        // The shell stores what the re-read answered; the controls follow.
        await rereadWhoIAm(host)
        XCTAssertEqual([], shown(host, conv(vm, "c2")))
    }

    /// The web's own words for the one route the server does guard, and the stale 🗑️ goes away.
    func testClearHistory403WebWordingClosesTheDialogAndRefetches() async {
        let (host, vm) = await signIn(.admin)
        fake.on("DELETE", "/admin/conversations/[^/]+/messages", code: 403, body: #"{"detail":"Only admins can clear chat history"}"#)
        fake.on("GET", "/admin/agents", body: Self.agents(.agent))
        vm.select("c1"); await drain()
        vm.showClear(true); vm.clearHistory(); await drain(); await settleForbidden(host)
        XCTAssertEqual("You don't have permission to clear chat history", host.toasts.last?.message)
        XCTAssertEqual(.error, host.toasts.last?.type)
        XCTAssertFalse(vm.dialogs.value.clearConfirm)
        XCTAssertEqual(1, host.accessRereads, "the 403 re-read who this agent is")
        await rereadWhoIAm(host)
        XCTAssertFalse(shown(host, conv(vm, "c1")).contains("clear"))
        XCTAssertFalse(vm.thread.value.messages["c1"]?.isEmpty ?? true)
    }

    /// What the web leaves open stays open, even for a readonly agent — and the requests go out.
    func testUngatedActionsWorkForReadonly() async {
        let (_, vm) = await signIn(.readonly)
        // Bulk release (the web's select bar has no gate).
        vm.enterSelect("p1"); vm.toggleRow("c6"); vm.releaseSelected(); await drain()
        XCTAssertFalse(fake.callsTo("POST", "/admin/conversations/c1/release").isEmpty)
        XCTAssertFalse(fake.callsTo("POST", "/admin/conversations/c6/release").isEmpty)
        // Ask Neema and the team answer (CustomerSidebar, no gate).
        vm.select("c2"); await drain()
        fake.on("POST", "/admin/conversations/c2/ask", body: #"{"answer":"Yes — 3 in stock."}"#)
        let asked = await vm.askNeema("Purple cassock in L?")
        XCTAssertEqual("Yes — 3 in stock.", asked)
        fake.on("POST", "/admin/conversations/c2/answer", body: #"{"ok":true,"sent":"We have it in L."}"#)
        let answered = await vm.answerViaNeema("3 in stock in L")
        XCTAssertTrue(answered.0); XCTAssertEqual("Neema sent: “We have it in L.”", answered.1)
        // The per-message Reply quote.
        let inbound = vm.thread.value.messages["c2"]!.first { $0.inbound && !$0.body.trimmingCharacters(in: .whitespaces).isEmpty }!
        vm.beginReplyTo(inbound)
        XCTAssertNotNil(vm.composer.value.quoted)
    }

    /// The team answer's failures: a 403 says why in plain words and re-reads who they are; a window refusal is the web's line.
    func testAnswerViaNeemaRefusalsSpeakPlainly() async {
        let (host, vm) = await signIn(.agent)
        vm.select("c2"); await drain()
        fake.on("POST", "/admin/conversations/c2/answer", code: 400, body: #"{"detail":"Outside the 24h window"}"#)
        let window = await vm.answerViaNeema("x")
        XCTAssertFalse(window.0); XCTAssertEqual("Outside the messaging window — reply yourself when they next write.", window.1)
        let meBefore = fake.callsTo("GET", "/admin/me").count
        fake.on("POST", "/admin/conversations/c2/answer", code: 403, body: #"{"detail":"Forbidden"}"#)
        let refused = await vm.answerViaNeema("x")
        XCTAssertFalse(refused.0); XCTAssertEqual("Couldn't send right now — try again.", refused.1)
        await settleForbidden(host)
        XCTAssertTrue(fake.callsTo("GET", "/admin/me").count > meBefore)
    }
}

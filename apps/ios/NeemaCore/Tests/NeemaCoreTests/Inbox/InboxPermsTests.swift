import Foundation
import XCTest
@testable import NeemaCore

/// The inbox's permission matrix (Android `InboxPermissionsTest`): the web
/// gates the thread's controls on the stored ROLE and ownership only.
final class InboxPermsTests: XCTestCase {
    enum Persona: CaseIterable {
        case superuser, admin, agent, readonly, sales, viewer, readonlyReplier, override, emptyOverride, supervisor
        var role: String {
            switch self {
            case .superuser, .agent, .sales, .viewer, .override, .emptyOverride: return "agent"
            case .admin: return "admin"
            case .readonly, .readonlyReplier: return "readonly"
            case .supervisor: return "supervisor"
            }
        }
        var superuser: Bool { self == .superuser }
    }
    enum Kind { case admin, handler, none }
    func kind(_ p: Persona) -> Kind {
        switch p {
        case .superuser, .admin: return .admin
        case .agent, .sales, .viewer, .override, .emptyOverride: return .handler
        case .readonly, .readonlyReplier, .supervisor: return .none
        }
    }

    func conv(_ id: String, _ mode: String, agent: String?) -> Conversation {
        Conversation(id: id, waId: "254700000000", interceptMode: mode, assignedAgentId: agent, assignedAgentName: agent == nil ? nil : "Someone")
    }

    /// The web's truth table, written out by hand from ConversationsView.tsx:
    /// c1 = human, held by me · c2 = AI · c3 = paused, unassigned · c6 = human, held by Grace · h = human, unclaimed.
    let expected: [Kind: [String: Set<String>]] = [
        .admin: [
            "c1": ["release", "pause", "transfer", "note", "clear", "composer"],
            "c2": ["intercept", "pause", "transfer", "note", "clear"],
            "c3": ["resume", "transfer", "note", "clear"],
            "c6": ["release", "pause", "transfer", "note", "clear", "composer"],
            "h": ["pickUp", "release", "pause", "transfer", "note", "clear", "composer"],
        ],
        .handler: [
            "c1": ["release", "pause", "transfer", "note", "composer"],
            "c2": ["intercept", "pause", "transfer", "note"],
            "c3": ["resume", "transfer", "note"],
            "c6": ["note", "locked"],
            "h": ["pickUp", "note"],
        ],
        // The web keys Release and the reply box on ownership alone, so a readonly agent still holding a thread keeps both.
        .none: [
            "c1": ["release", "composer"],
            "c2": [],
            "c3": [],
            "c6": ["locked"],
            "h": [],
        ],
    ]

    func testMatrixEveryPersonaEveryThread() {
        let me = Fixtures.ME_ID
        let threads: [String: Conversation] = [
            "c1": conv("c1", "human", agent: me),
            "c2": conv("c2", "ai", agent: nil),
            "c3": conv("c3", "paused", agent: nil),
            "c6": conv("c6", "human", agent: Fixtures.AGENT2_ID),
            "h": conv("h", "human", agent: nil),
        ]
        for p in Persona.allCases {
            let perms = InboxPerms.of(role: p.role, superuser: p.superuser, me: me)
            for (key, c) in threads {
                XCTAssertEqual(threadControls(c, perms).shown, expected[kind(p)]![key]!, "\(p) on \(key)")
            }
        }
    }

    /// Like the web (currentAgent null until profileApi.me() answers): no record of this agent, no controls — whatever the session says.
    func testNoAgentRecordYetNoControlsEvenForAnAdminSession() {
        let perms = InboxPerms.of(agent: nil, sessionAgentId: Fixtures.ME_ID)
        XCTAssertFalse(perms.canHandle); XCTAssertFalse(perms.isAdminOrSuper)
        XCTAssertEqual(threadControls(conv("c2", "ai", agent: nil), perms).shown, [])
        XCTAssertFalse(InboxPerms.canEditPipelineStages(agent: nil))
    }

    /// The team row is the truth, not a stale sign-in: a session that still says admin doesn't win.
    func testTheServersRecordWinsOverAStaleSession() {
        let readonly = try! NeemaJSON.decode(Agent.self, from: Fixtures.agentRow(Fixtures.ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", "readonly", true, false, 4, 60 * 24 * 200, 1))
        let perms = InboxPerms.of(agent: readonly, sessionAgentId: Fixtures.ME_ID)
        XCTAssertEqual(threadControls(conv("c2", "ai", agent: nil), perms).shown, [])
        XCTAssertFalse(InboxPerms.canEditPipelineStages(agent: readonly))
    }

    /// The stage editor: the one panel control shown only to whom the server admits.
    func testPipelineStageEditorExactlyTheServersRule() {
        for p in Persona.allCases {
            let a = try! NeemaJSON.decode(Agent.self, from: Fixtures.agentRow(Fixtures.ME_ID, "Moses Mwicigi", "moses@bethanyhouse.co.ke", p.role, true, p.superuser, 4, 60 * 24 * 200, 1))
            XCTAssertEqual(InboxPerms.canEditPipelineStages(agent: a), p.superuser || p.role == "admin", "\(p)")
        }
    }
}

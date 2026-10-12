import Foundation
@testable import NeemaCore

/// A busy shop for Reports / Analytics / Team — 10,000 conversations over
/// 120 days, 1,000 orders and 200 agents in 50 roles. Deterministic (no
/// randomness: every field is a function of the row's index), dated back from
/// `ReportsFixtures.NOW`, and written in the wire shape the API handlers emit
/// so the fake answers exactly what the client reads (Android `InsightsStressFixtures`).
enum InsightsStressFixtures {
    static let NOW = ReportsFixtures.NOW

    /// The API's datetime `minutes` before NOW.
    static func iso(_ minutes: Int64) -> String { SalesFixtures.pyIso(NOW.addingTimeInterval(-Double(minutes) * 60)) }

    private static let CHANNELS = ["whatsapp", "messenger", "instagram", "facebook", "tiktok", "email", "web"]
    private static let MODES = ["ai", "ai", "ai", "human", "paused"]
    private static let STATUSES = ["pending", "confirmed", "delivered", "cancelled", "open"]

    static func agentId(_ i: Int) -> String { "stress-agent-\(i)" }
    static func roleId(_ i: Int) -> String { "stress-role-\(i)" }
    /// Customers repeat: 3,000 phone numbers across the conversations and orders.
    static func phone(_ i: Int) -> String { "2547" + String(format: "%08d", 10_000_000 + i % 3_000) }

    static func conversationRows(_ n: Int = 10_000, agents: Int = 200) -> [String] {
        (0..<n).map { i in
            let mode = MODES[i % MODES.count]
            // Spread over ~120 days (13 minutes apart), newest first; every 50th has no message yet.
            let at = iso(Int64(i) * 17 + 1)
            let agent = (mode == "human" || i % 7 == 0) ? "\"\(agentId(i % agents))\"" : "null"
            let last = i % 50 == 0 ? "null" : "\"\(at)\""
            let name = i % 4 == 0 ? "null" : "\"Customer \(i)\""
            return "{\"id\":\"stress-conv-\(i)\",\"wa_id\":\"\(phone(i))\",\"intercept_mode\":\"\(mode)\",\"assigned_agent_id\":\(agent),"
                + "\"last_message_at\":\(last),\"created_at\":\"\(iso(Int64(i) * 17 + 60))\",\"status\":\"\(i % 3 == 0 ? "closed" : "open")\","
                + "\"name\":\(name),\"channel\":\"\(CHANNELS[i % CHANNELS.count])\",\"unread\":0,\"tags\":[],\"orders_count\":0}"
        }
    }

    static func conversations(_ n: Int = 10_000, agents: Int = 200) -> [Conversation] {
        try! NeemaJSON.decode([Conversation].self, from: "[" + conversationRows(n, agents: agents).joined(separator: ",") + "]")
    }

    static func orderRows(_ n: Int = 1_000) -> [String] {
        (0..<n).map { i in
            let unit = 250.0 * Double(1 + i % 40)
            let qty = 1 + i % 5
            let items = "[{\"name\":\"Product \(i % 60)\",\"qty\":\(qty),\"unit\":\(unit),\"total\":\(unit * Double(qty))}]"
            return Fixtures.orderRow("stress-order-\(i)", phone(i * 7), items, String(unit * Double(qty)), STATUSES[i % STATUSES.count], "whatsapp", Int64(i) * 97 + 5)
        }
    }

    static func orders(_ n: Int = 1_000) -> [Order] {
        try! NeemaJSON.decode([Order].self, from: "[" + orderRows(n).joined(separator: ",") + "]")
    }

    static func agentRows(_ n: Int = 200, roles: Int = 50) -> [String] {
        (0..<n).map { i in
            let surname = ["Wanjiku", "Otieno", "Achieng", "Kamau"][i % 4]
            return Fixtures.agentRow(agentId(i), "Agent \(String(format: "%03d", i)) \(surname)", "agent\(i)@bethanyhouse.co.ke",
                                     ["agent", "admin", "readonly"][i % 3], i % 3 == 0, false, i % 11, 400 * 24 * 60 + Int64(i), Int64(i % 90),
                                     customRole: i % 4 == 3 ? nil : roleId(i % roles))
        }
    }

    static func agents(_ n: Int = 200, roles: Int = 50) -> [Agent] {
        try! NeemaJSON.decode([Agent].self, from: "[" + agentRows(n, roles: roles).joined(separator: ",") + "]")
    }

    /// The whole busy shop on `f` (over the base fixtures, which stay for /admin/me etc.).
    static func install(_ f: FakeNeema, convs: Int = 10_000, orders: Int = 1_000, agents: Int = 200, roles: Int = 50) {
        let rows = conversationRows(convs, agents: agents)
        let convBody = "[" + rows.joined(separator: ",") + "]"
        let humanBody = "{\"items\":[" + rows.filter { $0.contains("\"intercept_mode\":\"human\"") }.prefix(10).joined(separator: ",") + "],\"next_cursor\":null}"
        let firstPage = "{\"items\":[" + rows.prefix(50).joined(separator: ",") + "],\"next_cursor\":\"c50\"}"
        f.on("GET", "/admin/conversations") { r, _ in
            if r.param("limit") == nil { return (200, convBody) }
            if r.param("tab") == "human" { return (200, humanBody) }
            return (200, firstPage)
        }
        f.on("GET", "/admin/orders", body: "[" + orderRows(orders).joined(separator: ",") + "]")
        f.on("GET", "/admin/agents", body: "[" + agentRows(agents, roles: roles).joined(separator: ",") + "]")
    }
}

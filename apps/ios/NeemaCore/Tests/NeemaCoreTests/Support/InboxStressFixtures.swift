import Foundation
@testable import NeemaCore

/// The shop at peak (Android `InboxStressFixtures`): a 5,000-conversation
/// inbox served in cursor pages exactly as admin.py list_conversations pages
/// it (newest first, `limit`, an opaque `next_cursor`), and a 2,000-message
/// thread served in `before` pages as admin.py get_thread does (oldest first
/// within a page), with photos, albums, voice notes, translations and system
/// events mixed in.
enum InboxStressFixtures {
    static func pyIso(_ d: Date) -> String {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        let c = cal.dateComponents([.year, .month, .day, .hour, .minute, .second, .nanosecond], from: d)
        return String(format: "%04d-%02d-%02dT%02d:%02d:%02d.%06d+00:00", c.year!, c.month!, c.day!, c.hour!, c.minute!, c.second!, (c.nanosecond ?? 0) / 1000)
    }

    private static let CHANNELS = ["whatsapp", "whatsapp", "whatsapp", "messenger", "instagram", "facebook"]

    /// One inbox row. Every 10th is held by a human (every 20th by me), every
    /// 7th is unread, and the first `pairs` × 2 rows are the same people on two
    /// channels (so the list groups them into one row each).
    static func row(_ i: Int, _ minutesAgo: Int64, pairs: Int = 100, mode: String? = nil) -> String {
        let ch = i < pairs * 2 ? (i % 2 == 0 ? "whatsapp" : "messenger") : CHANNELS[i % CHANNELS.count]
        let phone = String(254_700_000_000 + i)
        let wa = ch == "whatsapp"
        let m = mode ?? (i % 10 == 0 ? "human" : "ai")
        let mine = m == "human" && (mode != nil || i % 20 == 0)
        return InboxFixtures.Contract.row(
            "s\(i)", "Customer \(i)", wa ? phone : nil, wa ? phone : "psid\(i)", ch, m, "Message number \(i) about the purple cassock", minutesAgo,
            unread: i % 7 == 0 ? 2 : 0, person: i < pairs * 2 ? "pp\(i / 2)" : nil,
            agentId: m == "human" ? (mine ? Fixtures.ME_ID : "agent-other") : nil,
            agentName: m == "human" ? (mine ? "Moses Mwicigi" : "Grace Wanjiru") : nil,
            stage: i % 13 == 0 ? "qualified" : nil, orders: i % 5
        )
    }

    /// A paged inbox of `total` rows on `f`: GET /admin/conversations answers
    /// `pageSize` rows per call, newest first, with a cursor to the next page.
    final class Inbox: @unchecked Sendable {
        let total: Int
        let pageSize: Int
        private let lock = NSLock()
        /// Server order: s0 (newest) … s{total-1} (oldest).
        private var _ids: [String]
        private var rows: [String: String] = [:]
        private var _cursors: [String?] = []
        private var _queries: [String?] = []
        var ids: [String] { lock.sync { _ids } }
        var cursors: [String?] { lock.sync { _cursors } }
        var queries: [String?] { lock.sync { _queries } }

        init(_ f: FakeNeema, total: Int = 5_000, pageSize: Int = 50, pairs: Int = 100, mode: String? = nil) {
            self.total = total
            self.pageSize = pageSize
            _ids = (0..<total).map { "s\($0)" }
            for i in 0..<total { rows["s\(i)"] = InboxStressFixtures.row(i, Int64(i + 1), pairs: pairs, mode: mode) }
            f.on("GET", "/admin/conversations") { r, _ in
                let cursor = r.param("cursor")
                let limit = r.param("limit").flatMap { Int($0) } ?? pageSize
                return self.lock.sync {
                    self._cursors.append(cursor)
                    self._queries.append(r.param("q"))
                    let from = cursor.flatMap { Int($0.dropFirst()) } ?? 0
                    let to = min(self._ids.count, from + limit)
                    let next = to < self._ids.count ? "\"o\(to)\"" : "null"
                    let items = self._ids[from..<to].map { self.rows[$0]! }.joined(separator: ",")
                    return (200, "{\"items\":[\(items)],\"next_cursor\":\(next)}")
                }
            }
            f.on("GET", "/admin/conversations/s\\d+") { r, _ in
                (200, self.lock.sync { self.rows[r.url.lastPathComponent]! })
            }
        }

        /// `id` just got a message: it moves to the top of page one.
        func bump(_ id: String, _ i: Int) {
            lock.sync {
                _ids.removeAll { $0 == id }
                _ids.insert(id, at: 0)
                rows[id] = InboxStressFixtures.row(i, 0)
            }
        }
    }

    /// One thread message; every 20th starts a run of photos (an album), every 50th is a voice note.
    private static func message(_ i: Int, _ at: Date) -> String {
        let inbound = i % 3 != 2
        let dir = inbound ? "inbound" : "outbound"
        let sender = inbound ? "user" : (i % 2 == 0 ? "ai" : "human_agent")
        let t = pyIso(at)
        if (0...2).contains(i % 20) && inbound {
            return "{\"id\":\"m\(i)\",\"type\":\"message\",\"direction\":\"inbound\",\"sender\":\"user\",\"text\":\"[image]\",\"media_type\":\"image\",\"media_url\":\"https://cdn.test/p\(i).jpg\",\"media_caption\":\"A purple clergy stole\",\"created_at\":\"\(t)\"}"
        }
        if i % 50 == 7 {
            return "{\"id\":\"m\(i)\",\"type\":\"message\",\"direction\":\"\(dir)\",\"sender\":\"\(sender)\",\"text\":\"voice note \(i)\",\"media_type\":\"audio\",\"media_url\":\"https://cdn.test/v\(i).ogg\",\"created_at\":\"\(t)\"}"
        }
        let tx = i % 11 == 0 ? "\"Hello \(i)\"" : "null"
        let from = i % 11 == 0 ? "\"sw\"" : "null"
        return "{\"id\":\"m\(i)\",\"type\":\"message\",\"direction\":\"\(dir)\",\"sender\":\"\(sender)\",\"text\":\"Message \(i) — *bold* _italic_ see www.bethanyhouse.co.ke/p/\(i)\",\"translation\":\(tx),\"translated_from\":\(from),\"created_at\":\"\(t)\"}"
    }

    /// The intercept timeline item admin.py get_thread mixes in (10 s after message `i`).
    private static func event(_ i: Int, _ at: Date) -> String {
        "{\"id\":\"evt-\(i)\",\"type\":\"system_event\",\"direction\":\"outbound\",\"sender\":\"ai\",\"text\":\"Escalated\",\"event_kind\":\"\(i % 2 == 0 ? "escalated" : "flag")\",\"created_at\":\"\(pyIso(at.addingTimeInterval(10)))\"}"
    }

    /// A `total`-message thread for `convId`, with a system event after every
    /// 97th message: page one is the newest `page` MESSAGES plus the events
    /// among them; `before=<created_at>` answers the `page` messages older than it.
    final class Thread: @unchecked Sendable {
        let total: Int
        let page: Int
        let stamps: [String]
        private let itemsOf: [[String]]
        /// Every item (messages and events), oldest first.
        let json: [String]
        let events: Int
        private let lock = NSLock()
        private var _befores: [String?] = []
        var befores: [String?] { lock.sync { _befores } }

        init(_ f: FakeNeema, _ convId: String, total: Int = 2_000, page: Int = 50) {
            self.total = total
            self.page = page
            let base = AppClock.date().addingTimeInterval(-60)
            func at(_ i: Int) -> Date { base.addingTimeInterval(-Double(total - i) * 30) }
            stamps = (0..<total).map { InboxStressFixtures.pyIso(at($0)) }
            itemsOf = (0..<total).map { i in [InboxStressFixtures.message(i, at(i))] + (i % 97 == 0 ? [InboxStressFixtures.event(i, at(i))] : []) }
            json = itemsOf.flatMap { $0 }
            events = (0..<total).filter { $0 % 97 == 0 }.count
            f.on("GET", "/admin/conversations/\(convId)/messages") { r, _ in
                let before = r.param("before")
                self.lock.sync { self._befores.append(before) }
                let end = before.map { b in self.stamps.firstIndex(of: b) ?? 0 } ?? self.total
                let start = max(0, end - self.page)
                return (200, "[" + self.itemsOf[start..<end].flatMap { $0 }.joined(separator: ",") + "]")
            }
        }
    }

    /// Frame JSON for the live socket.
    static func newMessage(_ convId: String, _ id: String?, _ text: String, sender: String = "user") -> String {
        "{\"type\":\"new_message\",\"conversationId\":\"\(convId)\",\(id.map { "\"id\":\"\($0)\"," } ?? "")\"sender\":\"\(sender)\",\"text\":\"\(text)\"}"
    }

    static func interceptChanged(_ convId: String, _ mode: String) -> String {
        "{\"type\":\"intercept_changed\",\"conversationId\":\"\(convId)\",\"mode\":\"\(mode)\",\"assignedAgentId\":\(mode == "human" ? "\"agent-other\"" : "null"),\"assignedAgentName\":\(mode == "human" ? "\"Grace Wanjiru\"" : "null")}"
    }

    static func typing(_ convId: String) -> String { "{\"type\":\"typing\",\"conversationId\":\"\(convId)\",\"sender\":\"user\"}" }

    /// A long WhatsApp message: `paragraphs` paragraphs full of formatting and links.
    static func longMessage(_ paragraphs: Int = 200) -> String {
        (0..<paragraphs).map { i in
            "*Item \(i)* — _handmade_ ~was KES 4,000~ now `KES 3,500`. Details: https://bethanyhouse.co.ke/p/\(i), or www.bethanyhouse.co.ke. " +
                "```size chart \(i)``` **legacy bold** and plain words to fill the line out a little more."
        }.joined(separator: "\n\n")
    }
}

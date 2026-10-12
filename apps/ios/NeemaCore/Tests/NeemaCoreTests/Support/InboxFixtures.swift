import Foundation
@testable import NeemaCore

/// Inbox + thread data beyond the base `Fixtures` (Android's `InboxFixtures`):
/// a web-chat visitor, a thread with every bubble and media type, and window
/// states. Shapes follow apps/api/app/routers/admin.py.
enum InboxFixtures {
    static var webVisitor: String { Fixtures.webVisitor }
    static var conversations: [String] { Fixtures.inbox }
    static var page: String { Fixtures.conversationPage }

    static func page(_ ids: [String], cursor: String? = nil) -> String {
        let items = ids.map { id in conversations.first { $0.contains("\"id\":\"\(id)\"") }! }
        return "{\"items\":[\(items.joined(separator: ","))],\"next_cursor\":\(cursor.map { "\"\($0)\"" } ?? "null")}"
    }

    /// Python's `datetime.isoformat()` of an aware UTC timestamp: microseconds and "+00:00", never "Z".
    static func iso(_ minutesAgo: Int64) -> String { Fixtures.pyIso(minutesAgo) }
    static func isoIn(_ minutes: Int64) -> String { iso(-minutes) }

    static func windowOpen() -> String {
        "{\"mode\":\"open\",\"channel\":\"whatsapp\",\"last_inbound_at\":\"\(iso(2))\",\"expires_at\":\"\(isoIn(1438))\",\"human_agent_until\":null,\"reason\":\"\"}"
    }
    static func windowHumanAgent() -> String {
        "{\"mode\":\"human_agent\",\"channel\":\"messenger\",\"last_inbound_at\":\"\(iso(60 * 30))\",\"expires_at\":\"\(iso(60 * 6))\",\"human_agent_until\":\"\(isoIn(60 * 24 * 5 + 190))\",\"reason\":\"24h window closed — sending as a human agent (Meta allows 7 days)\"}"
    }
    static func windowClosed() -> String {
        "{\"mode\":\"closed\",\"channel\":\"whatsapp\",\"last_inbound_at\":\"\(iso(60 * 24 * 3))\",\"expires_at\":\"\(iso(60 * 24 * 2))\",\"human_agent_until\":null,\"reason\":\"Outside the messaging window — an approved template is the only way in\"}"
    }

    /// `n` plain messages ending `minutesAgo` minutes back — for paging.
    static func plainPage(_ prefix: String, _ n: Int, _ startMinutesAgo: Int64) -> String {
        "[" + (0..<n).map { i in
            "{\"id\":\"\(prefix)\(i)\",\"type\":\"message\",\"direction\":\"\(i % 2 == 0 ? "inbound" : "outbound")\",\"sender\":\"\(i % 2 == 0 ? "user" : "ai")\",\"text\":\"\(prefix) message \(i)\",\"created_at\":\"\(Fixtures.ago(startMinutesAgo - Int64(i)))\"}"
        }.joined(separator: ",") + "]"
    }

    /// Server-exact wire shapes, built from what each handler in admin.py (and
    /// the services it calls) returns — for the contract tests.
    enum Contract {
        private static func q(_ s: String?) -> String { s.map { "\"\($0)\"" } ?? "null" }

        // admin.py _conversation_rows — the exact key set, in its order.
        static func row(_ id: String, _ name: String?, _ waId: String?, _ externalId: String, _ channel: String, _ mode: String, _ preview: String,
                        _ minutes: Int64, unread: Int = 0, person: String? = nil, agentId: String? = nil, agentName: String? = nil,
                        tags: String = "[]", stage: String? = nil, orders: Int = 0, country: String? = "KE") -> String {
            let flag = country.map { "\"https://flagcdn.com/\($0.lowercased()).svg\"" } ?? "null"
            return """
            {"id":"\(id)","wa_id":\(q(waId)),"person_id":\(q(person)),
              "external_id":"\(externalId)","intercept_mode":"\(mode)","assigned_agent_id":\(q(agentId)),
              "assigned_agent_name":\(q(agentName)),"intercept_since":\(mode == "human" ? "\"\(iso(minutes + 5))\"" : "null"),
              "last_message_at":"\(iso(minutes))","last_message":"\(preview)","last_message_preview":"\(preview)","status":"open",
              "created_at":"\(iso(minutes + 900))","updated_at":"\(iso(minutes))","name":\(q(name)),"avatar_url":null,
              "country_iso":\(q(country)),"flag_url":\(flag),
              "channel":"\(channel)","unread":\(unread),"orders_count":\(orders),"lead_stage":\(q(stage)),"tags":\(tags)}
            """
        }

        static var peterWa: String {
            row("k1", "Fr. Peter Kamau", "254712345678", "254712345678", "whatsapp", "human", "Can you deliver to Nyeri by Friday?", 2,
                unread: 2, person: "p1", agentId: Fixtures.ME_ID, agentName: "Moses Mwicigi", tags: #"["vip","clergy"]"#, stage: "proposal", orders: 3)
        }
        /// A Messenger thread: no wa_id, the PSID is the key; flag from nothing (no phone).
        static var maryMsgr: String {
            row("k2", "Rev. Mary Achieng", nil, "7123456789012345", "messenger", "ai", "Asante! How much is the purple cassock?", 9, unread: 1, person: "p2", country: nil)
        }
        /// Tags straight off a hand-edited JSONB state: a bare string, not a list.
        static var oddTags: String { row("k3", "Deacon James", "254733444555", "254733444555", "whatsapp", "ai", "Sawa", 40, tags: "\"vip\"") }
        /// Tags with a null and a number inside, as JSONB allows.
        static var mixedTags: String { row("k4", nil, "255754333222", "255754333222", "whatsapp", "paused", "📷 Photo", 60, tags: #"["bulk",null,7,""]"#, country: "TZ") }
        /// A web-chat visitor (web_chat.py): `web_<sha1[:20]>` on the default channel.
        static var visitor: String { row("k5", nil, "web_3fa9c1e20b7d4c5a9e11", "web_3fa9c1e20b7d4c5a9e11", "whatsapp", "ai", "Do you ship to Kampala?", 80, country: nil) }
        /// Peter's Facebook comment thread — the same person as k1.
        static var peterFb: String { row("k6", "Fr. Peter Kamau", nil, "25898765432101234", "facebook", "ai", "Beautiful stoles! 🙏", 240, person: "p1", country: nil) }

        static func page(_ rows: [String], cursor: String? = nil) -> String {
            "{\"items\":[\(rows.joined(separator: ","))],\"next_cursor\":\(cursor.map { "\"\($0)\"" } ?? "null")}"
        }
        static let CURSOR = "WyIyMDI2LTA5LTI1VDA5OjU4OjAwLjEyMzQ1NiswMDowMCIsInAxIl0"

        static let summary = #"{"unread":2,"human":1,"yours":1,"unread_messages":{"all":3,"whatsapp":2,"messenger":1},"tags":["bulk","clergy","vip"]}"#
        static let resolved = #"{"conversation_id":"k2"}"#
        static let unresolved = #"{"conversation_id":null}"#

        static func thread() -> String {
            """
            [
              {"id":"m1","type":"message","direction":"inbound","sender":"user","text":"Bonjour, vous livrez à Kigali ?","translation":"Hello, do you deliver to Kigali?","translated_from":"French","isNote":false,"agent_name":null,"created_at":"\(iso(30))","media_type":null,"media_id":null,"media_url":null,"media_caption":null,"mime_type":null,"filename":null,"comment_context":null,"reply_to":null},
              {"id":"evt-9f1","type":"system_event","direction":"outbound","sender":"ai","text":"Escalated — needs human","created_at":"\(iso(29))","event_kind":"escalated","event_reason":"Asked for a delivery quote","agent_name":null},
              {"id":"m2","type":"message","direction":"inbound","sender":"user","text":null,"translation":null,"translated_from":null,"isNote":false,"agent_name":null,"created_at":"\(iso(20))","media_type":"image","media_id":"wamid.MEDIA1","media_url":"https://api.bethanyhouse.co.ke/api/admin/media/a1.jpg","media_caption":"A purple clergy stole","mime_type":"image/jpeg","filename":null,"comment_context":null,"reply_to":null},
              {"id":"m3","type":"message","direction":"outbound","sender":"human_agent","text":"Oui, 5 jours.","translation":"Yes, 5 days.","translated_from":"French","isNote":false,"agent_name":"Moses Mwicigi","created_at":"\(iso(10))","media_type":null,"media_id":null,"media_url":null,"media_caption":null,"mime_type":null,"filename":null,"comment_context":null,"reply_to":{"id":"m1","text":"Bonjour, vous livrez à Kigali ?","sender":"user","media_type":null,"media_url":null}},
              {"id":"m4","type":"message","direction":"outbound","sender":"human_agent","text":"Repeat buyer","translation":null,"translated_from":null,"isNote":true,"agent_name":"Moses Mwicigi","created_at":"\(iso(8))","media_type":null,"media_id":null,"media_url":null,"media_caption":null,"mime_type":null,"filename":null,"comment_context":null,"reply_to":null},
              {"id":"m5","type":"message","direction":"inbound","sender":"user","text":"[comment] Price?","translation":null,"translated_from":null,"isNote":false,"agent_name":null,"created_at":"\(iso(5))","media_type":null,"media_id":null,"media_url":null,"media_caption":null,"mime_type":null,"filename":null,"comment_context":{"post_id":"p_77","title":"Advent stoles","permalink":"https://facebook.com/p/77","thumb":null},"reply_to":null}
            ]
            """
        }

        static func activity() -> String {
            """
            {"events":[
              {"id":"icpt-1","kind":"intercept","label":"Picked up by Moses Mwicigi","detail":"Moses Mwicigi","at":"\(iso(20))"},
              {"id":"act-2","kind":"checkin_sent","label":"Check-in sent","detail":"","at":"\(iso(60))"},
              {"id":"ord-3","kind":"order","label":"Order open · unpaid","detail":"2 items — KES 7000","at":null},
              {"id":"tool-4","kind":"tool","label":"Looked up the catalogue","detail":null,"at":"\(iso(90))"}
            ]}
            """
        }

        static var intercept: String { "{\"ok\":true,\"mode\":\"human\",\"assigned_to\":\"\(Fixtures.ME_ID)\"}" }
        static var interceptAlready: String { "{\"id\":\"k1\",\"intercept_mode\":\"human\",\"assigned_agent_id\":\"\(Fixtures.ME_ID)\",\"already\":true}" }
        static let interceptConflict = #"{"detail":"Already handled by Grace Wanjiru. They must release or transfer it first."}"#
        static let release = #"{"ok":true,"mode":"ai"}"#
        static let releaseAlready = #"{"id":"k1","intercept_mode":"ai","assigned_agent_id":null,"already":true}"#
        static var pause: String { "{\"id\":\"k1\",\"intercept_mode\":\"paused\",\"assigned_agent_id\":\"\(Fixtures.ME_ID)\"}" }
        static let pauseConflict = #"{"detail":"Handled by Grace Wanjiru — they must pause or release it."}"#
        static var transfer: String { "{\"ok\":true,\"transferred_to\":\"\(Fixtures.AGENT2_ID)\"}" }

        static func replySent(_ text: String) -> String { "{\"id\":\"srv-r1\",\"direction\":\"outbound\",\"sender\":\"human_agent\",\"text\":\"\(text)\",\"reply_to\":null,\"created_at\":\"\(iso(0))\"}" }
        static let replyFailed = #"{"ok":false,"error":"Couldn't send the reply: (#10) This message is sent outside of allowed window."}"#
        static let replyLocked = #"{"detail":"Conversation is handled by Grace Wanjiru."}"#
        static let replySms = #"{"detail":"SMS is receive-only — Neema cannot send SMS. Reach this customer on WhatsApp or by phone."}"#

        static let translated = #"{"text":"Oui, nous livrons vendredi.","lang":"French"}"#
        static let untranslated = #"{"text":"Yes, Friday.","lang":null}"#

        static func note(_ text: String) -> String { "{\"id\":\"srv-n1\",\"type\":\"message\",\"direction\":\"outbound\",\"sender\":\"human_agent\",\"text\":\"\(text)\",\"isNote\":true,\"created_at\":\"\(iso(0))\"}" }
        static func approved(_ text: String) -> String { "{\"id\":\"srv-a1\",\"direction\":\"outbound\",\"sender\":\"ai\",\"text\":\"\(text)\",\"created_at\":\"\(iso(0))\"}" }
        static let noDraft = #"{"detail":"No draft text found to approve"}"#
        static let latestDraftNone = #"{"draft":null}"#
        static let latestDraft = #"{"draft":"Bonjour 🙏 Oui, nous livrons à Kigali en 5 jours."}"#
        static let generated = #"{"draft":"Yes Father — Nyeri by Friday. Shall I send the M-Pesa details?"}"#
        static let generateNoMessages = #"{"detail":"No messages to draft from"}"#

        static let answer = #"{"answer":"Collar 16 inch, chest 42 — from BH-1042."}"#
        static let sent = #"{"ok":true,"sent":"Yes Reverend — KES 12,500, ready in 5 days 🙏"}"#
        static let outsideWindow = #"{"detail":"outside the messaging window — send it as a template, or reply yourself when they next write"}"#

        static func uploaded(_ type: String, _ url: String, _ caption: String?) -> String {
            "{\"id\":\"srv-u1\",\"direction\":\"outbound\",\"sender\":\"human_agent\",\"media_type\":\"\(type)\",\"media_url\":\"\(url)\",\"text\":\(q(caption)),\"created_at\":\"\(iso(0))\"}"
        }
        static let tooLarge = #"{"detail":"Image too large — max 5 MB."}"#
        static let unsupported = #"{"detail":"Unsupported media type: video/webm"}"#
        static let unconvertible = #"{"detail":"Couldn't convert this video for WhatsApp — try a shorter clip or export it as MP4 (H.264)."}"#
        /// nginx's own 413 page — the request never reached FastAPI.
        static let proxyTooLarge = "<html><head><title>413 Request Entity Too Large</title></head><body><center><h1>413 Request Entity Too Large</h1></center><hr><center>nginx</center></body></html>"

        static let recovered = #"{"ok":true,"media_url":"https://api.bethanyhouse.co.ke/api/admin/media/rehosted.jpg","media_type":"image"}"#
        static let recoverGone = #"{"detail":"Meta no longer has this attachment — it can't be recovered."}"#
        static let postVideo = #"{"video_url":"https://video.xx.fbcdn.net/v/t42/reel.mp4?oe=1"}"#

        static let cleared = #"{"ok":true,"cleared":true,"conversation_id":"k1"}"#
        static let clearForbidden = #"{"detail":"Only admins can clear chat history"}"#

        static let invited = #"{"ok":true,"wa_id":"250788123456"}"#
        static let inviteBadPhone = #"{"detail":"A valid phone number is required to invite to WhatsApp."}"#

        /// FastAPI's own 422 for a malformed request: a pydantic error LIST, not a string.
        static let pydantic422 = #"{"detail":[{"type":"missing","loc":["body","file"],"msg":"Field required","input":null}]}"#
    }

    static func install(_ f: FakeNeema) {
        f.on("GET", "/admin/conversations", body: page)
        let convs = conversations
        f.on("GET", "/admin/conversations/[^/]+") { r, _ in
            let id = r.url.lastPathComponent
            return (200, convs.first { $0.contains("\"id\":\"\(id)\"") } ?? convs[0])
        }
        f.on("GET", "/admin/conversations/summary", body: Fixtures.inboxSummary)
        f.on("GET", "/admin/conversations/[^/]+/messages", body: Fixtures.messages)
        f.on("GET", "/admin/conversations/[^/]+/window", body: windowOpen())
        f.on("GET", "/admin/conversations/[^/]+/latest-draft", body: #"{"draft":null}"#)
        // What the server really answers for the controls (services/conversation.py).
        f.on("POST", "/admin/conversations/[^/]+/intercept", body: Contract.intercept)
        f.on("POST", "/admin/conversations/[^/]+/release", body: Contract.release)
        f.on("POST", "/admin/conversations/[^/]+/pause", body: Contract.pause)
        f.on("POST", "/admin/conversations/[^/]+/transfer", body: Contract.transfer)
        f.on("POST", "/admin/conversations/[^/]+/note") { _, _ in (200, Contract.note("note")) }
        f.on("POST", "/admin/conversations/[^/]+/reply") { _, _ in (200, Contract.replySent("sent")) }
        f.on("POST", "/admin/conversations/[^/]+/approve-draft") { _, _ in (200, Contract.approved("sent")) }
        f.on("POST", "/admin/conversations/[^/]+/generate-draft", body: #"{"draft":"Hello Father 🙏 Yes — we deliver to Nyeri by Friday. Shall I send the M-Pesa details?"}"#)
        f.on("POST", "/admin/conversations/[^/]+/translate-reply", body: #"{"text":"Ndiyo, tutafikisha Ijumaa.","lang":"Swahili"}"#)
        f.on("GET", "/admin/conversations/[^/]+/activity", body: Contract.activity())
        f.on("DELETE", "/admin/conversations/[^/]+/messages", body: Contract.cleared)
    }
}

/// A Nairobi phone network, for the inbox (Android's `InboxNetFixtures`):
/// requests that time out, never connect, or drop halfway — thrown from
/// inside a fake route exactly where the transport would throw them — plus a
/// thread whose server rows a test can add to.
enum InboxNetFixtures {
    /// The read timed out: the server may have acted on it.
    static func timeout() throws -> (Int, String) { throw TransportError.timedOut }
    /// No route to the server at all: the request never left the phone.
    static func offline() throws -> (Int, String) { throw TransportError.network("Failed to connect to neema.test/10.0.0.1:443") }
    /// The connection died mid-transfer (a 150 MB video halfway up, a reply's answer lost).
    static func dropped() throws -> (Int, String) { throw TransportError.network("unexpected end of stream on https://neema.test/...") }

    /// One server thread row created now (admin.py get_thread's shape).
    static func row(_ id: String, _ text: String?, sender: String = "human_agent", note: Bool = false, mediaType: String? = nil, direction: String = "outbound") -> String {
        let t = text.map { "\"\($0)\"" } ?? "null"
        let mt = mediaType.map { "\"\($0)\"" } ?? "null"
        let mu = mediaType != nil ? "\"https://api.bethanyhouse.co.ke/api/admin/media/\(id)\"" : "null"
        return "{\"id\":\"\(id)\",\"type\":\"message\",\"direction\":\"\(direction)\",\"sender\":\"\(sender)\",\"text\":\(t),\"isNote\":\(note),\"media_type\":\(mt),\"media_url\":\(mu),\"created_at\":\"\(Inbox.nowIso())\"}"
    }

    /// The base thread plus `extra` rows.
    static func thread(_ extra: [String]) -> String { withRows(Fixtures.messages, extra) }

    /// A server whose thread holds whatever the test's sends have created:
    /// `rows` is the live list; GET …/messages always answers the base thread
    /// plus those rows (unless `threadDown` says the network is out).
    final class Server: @unchecked Sendable {
        let f: FakeNeema
        private let lock = NSLock()
        private var _rows: [String] = []
        private var _down: (() throws -> (Int, String))? = nil
        var rows: [String] {
            get { lock.sync { _rows } }
            set { lock.sync { _rows = newValue } }
        }
        var threadDown: (() throws -> (Int, String))? {
            get { lock.sync { _down } }
            set { lock.sync { _down = newValue } }
        }
        init(_ f: FakeNeema) {
            self.f = f
            f.on("GET", "/admin/conversations/[^/]+/messages") { [unowned self] _, _ in
                if let d = self.threadDown { _ = try d() }
                return (200, InboxNetFixtures.thread(self.rows))
            }
        }
        func add(_ row: String) { lock.sync { _rows.append(row) } }
    }
}

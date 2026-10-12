import Foundation

// The thread's wire shapes (Android `feature/conversations/InboxModels.kt`).
// The core `Message` model is the api.ts subset; the inbox reads a few more
// fields the server sends on comment threads, so it keeps its own copy.

/// What a Facebook/Instagram comment is ON (messages.comment_context).
public struct PostContext: Equatable, Hashable, Sendable {
    public var postId: String?
    public var title: String?
    public var permalink: String?
    public var thumb: String?
    public var mediaType: String?
    public var hasVideo: Bool?
    /// Set on OUR public reply: the comment id it answers.
    public var replyTo: String?

    public init(postId: String? = nil, title: String? = nil, permalink: String? = nil, thumb: String? = nil,
                mediaType: String? = nil, hasVideo: Bool? = nil, replyTo: String? = nil) {
        self.postId = postId; self.title = title; self.permalink = permalink; self.thumb = thumb
        self.mediaType = mediaType; self.hasVideo = hasVideo; self.replyTo = replyTo
    }

    /// Read field by field, so one odd value (or a non-object blob) can't sink the thread.
    public init?(raw: JSONValue?) {
        guard let o = raw?.objectValue else { return nil }
        func s(_ k: String) -> String? { let v = o[k]?.content ?? ""; return v.isEmpty ? nil : v }
        func b(_ k: String) -> Bool? {
            guard let v = o[k] else { return nil }
            switch v {
            case .bool(let x): return x
            case .string(let x): return x == "true" ? true : (x == "false" ? false : nil)
            default: return nil
            }
        }
        self.init(postId: s("post_id"), title: s("title"), permalink: s("permalink"), thumb: s("thumb"),
                  mediaType: s("media_type"), hasVideo: b("has_video"), replyTo: s("reply_to"))
    }
}

/// The message a bubble quotes (a threaded reply).
public struct QuotedRef: Equatable, Hashable, Sendable, Codable {
    public var id: String
    public var text: String?
    public var sender: String?
    public var mediaType: String?
    public var mediaUrl: String?

    public init(id: String = "", text: String? = nil, sender: String? = nil, mediaType: String? = nil, mediaUrl: String? = nil) {
        self.id = id; self.text = text; self.sender = sender; self.mediaType = mediaType; self.mediaUrl = mediaUrl
    }

    enum K: String, CodingKey { case id, text, sender, media_type, media_url }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), text: c.string(.text), sender: c.string(.sender), mediaType: c.string(.media_type), mediaUrl: c.string(.media_url))
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: K.self)
        try c.encode(id, forKey: .id)
        try c.encodeIfPresent(text, forKey: .text)
        try c.encodeIfPresent(sender, forKey: .sender)
        try c.encodeIfPresent(mediaType, forKey: .media_type)
        try c.encodeIfPresent(mediaUrl, forKey: .media_url)
    }
}

/// One item of GET /admin/conversations/{id}/messages: a message or a system event.
public struct ThreadMsg: Identifiable, Equatable, Hashable, Sendable, Codable {
    public var id: String
    public var type: String
    public var direction: String
    public var sender: String
    public var text: String?
    public var createdAt: String?
    public var isNote: Bool
    public var translation: String?
    public var translatedFrom: String?
    public var agentName: String?
    public var eventKind: String?
    public var eventReason: String?
    public var mediaType: String?
    public var mediaId: String?
    public var mediaUrl: String?
    public var mediaCaption: String?
    public var mimeType: String?
    public var filename: String?
    /// Free-form JSONB on the server, read field by field.
    public var commentContext: PostContext?
    public var replyTo: QuotedRef?
    /// A call event's row (`event_kind: "call"`), read leniently (nil when absent or unreadable — the pill still shows).
    public var call: Call?
    /// This device's own bubble on its way: "sending" (not yet confirmed) or "failed".
    public var sendState: String?
    /// Why a failed bubble didn't go, for the line under it.
    public var sendError: String?
    /// Parsed once per row, not on every comparison (sorting a 2,000-message thread).
    public private(set) var millis: Int64

    public init(id: String = "", type: String = "message", direction: String = "inbound", sender: String = "user", text: String? = nil,
                createdAt: String? = nil, isNote: Bool = false, translation: String? = nil, translatedFrom: String? = nil,
                agentName: String? = nil, eventKind: String? = nil, eventReason: String? = nil, mediaType: String? = nil,
                mediaId: String? = nil, mediaUrl: String? = nil, mediaCaption: String? = nil, mimeType: String? = nil,
                filename: String? = nil, commentContext: PostContext? = nil, replyTo: QuotedRef? = nil, call: Call? = nil,
                sendState: String? = nil, sendError: String? = nil) {
        self.id = id; self.type = type; self.direction = direction; self.sender = sender; self.text = text
        self.createdAt = createdAt; self.isNote = isNote; self.translation = translation; self.translatedFrom = translatedFrom
        self.agentName = agentName; self.eventKind = eventKind; self.eventReason = eventReason; self.mediaType = mediaType
        self.mediaId = mediaId; self.mediaUrl = mediaUrl; self.mediaCaption = mediaCaption; self.mimeType = mimeType
        self.filename = filename; self.commentContext = commentContext; self.replyTo = replyTo; self.call = call
        self.sendState = sendState; self.sendError = sendError
        self.millis = Fmt.millis(createdAt) ?? 0
    }

    enum K: String, CodingKey {
        case id, type, direction, sender, text, created_at, isNote, translation, translated_from, agent_name, event_kind, event_reason
        case media_type, media_id, media_url, media_caption, mime_type, filename, comment_context, reply_to, call
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(
            id: c.string(.id, default: ""), type: c.string(.type, default: "message"), direction: c.string(.direction, default: "inbound"),
            sender: c.string(.sender, default: "user"), text: c.string(.text), createdAt: c.string(.created_at),
            isNote: c.bool(.isNote, default: false), translation: c.string(.translation), translatedFrom: c.string(.translated_from),
            agentName: c.string(.agent_name), eventKind: c.string(.event_kind), eventReason: c.string(.event_reason),
            mediaType: c.string(.media_type), mediaId: c.string(.media_id), mediaUrl: c.string(.media_url), mediaCaption: c.string(.media_caption),
            mimeType: c.string(.mime_type), filename: c.string(.filename),
            commentContext: PostContext(raw: c.value(.comment_context)), replyTo: c.object(.reply_to), call: c.object(.call)
        )
    }

    /// The wire keys back out (an outbox bubble kept on disk); the call row and comment context are not an outgoing bubble's.
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: K.self)
        try c.encode(id, forKey: .id)
        try c.encode(type, forKey: .type)
        try c.encode(direction, forKey: .direction)
        try c.encode(sender, forKey: .sender)
        try c.encodeIfPresent(text, forKey: .text)
        try c.encodeIfPresent(createdAt, forKey: .created_at)
        try c.encode(isNote, forKey: .isNote)
        try c.encodeIfPresent(translation, forKey: .translation)
        try c.encodeIfPresent(translatedFrom, forKey: .translated_from)
        try c.encodeIfPresent(agentName, forKey: .agent_name)
        try c.encodeIfPresent(eventKind, forKey: .event_kind)
        try c.encodeIfPresent(eventReason, forKey: .event_reason)
        try c.encodeIfPresent(mediaType, forKey: .media_type)
        try c.encodeIfPresent(mediaId, forKey: .media_id)
        try c.encodeIfPresent(mediaUrl, forKey: .media_url)
        try c.encodeIfPresent(mediaCaption, forKey: .media_caption)
        try c.encodeIfPresent(mimeType, forKey: .mime_type)
        try c.encodeIfPresent(filename, forKey: .filename)
        try c.encodeIfPresent(replyTo, forKey: .reply_to)
    }

    /// `createdAt` changes carry the parsed time with them.
    public mutating func setCreatedAt(_ iso: String?) {
        createdAt = iso
        millis = Fmt.millis(iso) ?? 0
    }

    public var isSystem: Bool { type == "system_event" }
    public var inbound: Bool { direction == "inbound" }
    public var body: String { text ?? "" }
    /// A bubble this device made up (optimistic send, socket echo without an id).
    public var isLocal: Bool { id.hasPrefix("optimistic-") || id.hasPrefix("ws-") || id.hasPrefix("live-evt-") }
}

/// The message being replied to (reply-to-message / cross-channel quote).
public struct Quoted: Equatable, Hashable, Sendable, Codable {
    public var msgId: String?
    public var sender: String?
    public var text: String
    public var channel: String
    public var mediaUrl: String?
    public var mediaType: String?
    public init(msgId: String? = nil, sender: String? = nil, text: String = "", channel: String = "whatsapp", mediaUrl: String? = nil, mediaType: String? = nil) {
        self.msgId = msgId; self.sender = sender; self.text = text; self.channel = channel; self.mediaUrl = mediaUrl; self.mediaType = mediaType
    }
}

/// A file picked for sending, with its own caption (WhatsApp-style).
public struct PickedMedia: Equatable, Hashable, Sendable, Identifiable {
    public let id: String
    public var file: URL?
    public var name: String
    public var mime: String
    public var size: Int64
    /// Set when the image was re-encoded to fit the 5 MB cap.
    public var bytes: Data?
    public var caption: String
    /// Why the last attempt to send it failed; the file stays in the tray for a retry.
    public var error: String?
    /// The last attempt ended without an answer: it may have reached the customer, so a retry checks the thread first.
    public var unconfirmed: Bool

    public init(id: String, file: URL?, name: String, mime: String, size: Int64, bytes: Data? = nil, caption: String = "", error: String? = nil, unconfirmed: Bool = false) {
        self.id = id; self.file = file; self.name = name; self.mime = mime; self.size = size; self.bytes = bytes
        self.caption = caption; self.error = error; self.unconfirmed = unconfirmed
    }

    public var isImage: Bool { mime.hasPrefix("image/") }

    public static func == (a: PickedMedia, b: PickedMedia) -> Bool {
        a.id == b.id && a.caption == b.caption && a.error == b.error && a.unconfirmed == b.unconfirmed
    }
    public func hash(into h: inout Hasher) { h.combine(id); h.combine(caption); h.combine(error) }
}

/// One PERSON in the list: the newest thread plus their other channels.
public struct RowGroup: Equatable, Hashable, Sendable, Identifiable {
    public let key: String
    public let rep: Conversation
    public let siblings: [Conversation]
    public let unread: Int
    public let lastAt: String?
    public var id: String { key }
    public init(key: String, rep: Conversation, siblings: [Conversation], unread: Int, lastAt: String?) {
        self.key = key; self.rep = rep; self.siblings = siblings; self.unread = unread; self.lastAt = lastAt
    }
}

/// A photo in an album / the viewer.
public struct AlbumItem: Equatable, Hashable, Sendable, Codable {
    public var src: String
    public var caption: String?
    public init(src: String, caption: String? = nil) { self.src = src; self.caption = caption }
}

/// A full-screen viewer request (image lightbox, video player, album).
public enum Viewer: Equatable, Hashable, Sendable, Codable {
    case image(url: String)
    case video(url: String, messageId: String?)
    case album(items: [AlbumItem], start: Int)
}

public enum Inbox {
    public static let PAGE = 50
    public static let THREAD_PAGE = 50
    public static let SNAP_KEY = "inbox_v2"
    /// The agent's work in progress (InboxMemory), per agent.
    public static let MEMORY_KEY = "inbox_memory_v1"

    public static func filterKey(of f: InboxQuery) -> String {
        [f.tab, f.channel, f.mode, f.tag ?? "", f.q.trimmingCharacters(in: .whitespacesAndNewlines)].joined(separator: "\u{1}")
    }

    public static let DEFAULT_KEY = filterKey(of: InboxQuery())

    /// mapConversation(): external_id falls back to wa_id, last_message_at to created_at.
    public static func normalized(_ c: Conversation) -> Conversation {
        var out = c
        out.externalId = c.externalId ?? c.waId
        out.lastMessageAt = c.lastMessageAt ?? c.createdAt
        return out
    }

    /// Union two thread slices by id, newest state winning, ordered by time.
    public static func mergeThread(_ existing: [ThreadMsg], _ incoming: [ThreadMsg]) -> [ThreadMsg] {
        var order: [String] = []
        var byId: [String: ThreadMsg] = [:]
        for m in existing { if byId[m.id] == nil { order.append(m.id) }; byId[m.id] = m }
        for m in incoming { if byId[m.id] == nil { order.append(m.id) }; byId[m.id] = m }
        return order.compactMap { byId[$0] }.sorted { a, b in
            if a.millis != b.millis { return a.millis < b.millis }
            return (a.createdAt ?? "") < (b.createdAt ?? "")
        }
    }

    /// mergeThread for a SERVER page: bubbles this device invented are dropped once the server's own row for them has arrived.
    public static func mergeServer(_ existing: [ThreadMsg], _ incoming: [ThreadMsg]) -> [ThreadMsg] {
        let kept = existing.filter { m in
            if m.sendState != nil { return true }
            if m.id.hasPrefix("optimistic-") || m.id.hasPrefix("ws-") {
                return !incoming.contains { s in
                    !s.isSystem && s.direction == m.direction && s.isNote == m.isNote &&
                        s.body.trimmingCharacters(in: .whitespacesAndNewlines) == m.body.trimmingCharacters(in: .whitespacesAndNewlines) &&
                        (s.mediaUrl == nil || m.mediaUrl == nil || s.mediaUrl == m.mediaUrl) &&
                        abs(s.millis - m.millis) < 10 * 60_000
                }
            }
            if m.id.hasPrefix("live-evt-") {
                return !incoming.contains { s in s.isSystem && s.eventKind == m.eventKind && s.millis >= m.millis - 60_000 }
            }
            return true
        }
        return mergeThread(kept, incoming)
    }

    /// A live `new_message` frame → a thread bubble. An inbound path carries `sender: "user"` but no direction; the direction follows the sender.
    public static func wsMessage(of e: JSONValue) -> ThreadMsg? {
        if e.str("event") == "notification" { return nil }
        let dir = e.str("direction").flatMap { $0 == "inbound" || $0 == "outbound" ? $0 : nil }
        let sender = nonEmpty(e.str("sender")) ?? (dir == "inbound" ? "user" : "ai")
        return ThreadMsg(
            id: nonEmpty(e.str("id")) ?? "ws-\(UUID().uuidString.lowercased())",
            type: "message",
            direction: dir ?? (sender == "user" ? "inbound" : "outbound"),
            sender: sender,
            text: e.str("text"),
            createdAt: nonEmpty(e.str("created_at")) ?? nowIso(),
            translation: nonEmpty(e.str("translation")),
            translatedFrom: nonEmpty(e.str("translatedFrom")),
            mediaType: nonEmpty(e.str("mediaType")), mediaId: nonEmpty(e.str("mediaId")), mediaUrl: nonEmpty(e.str("mediaUrl")),
            mediaCaption: nonEmpty(e.str("mediaCaption")), mimeType: nonEmpty(e.str("mimeType")), filename: nonEmpty(e.str("filename")),
            replyTo: e["replyTo"].flatMap { v in v.objectValue == nil ? nil : (try? NeemaJSON.decode(QuotedRef.self, from: v)) }
        )
    }

    /// Add a socket bubble unless the thread already shows it (§5.2 of the inbox audit).
    public static func appendWs(_ existing: [ThreadMsg], _ msg: ThreadMsg) -> [ThreadMsg] {
        func trimmed(_ s: String) -> String { s.trimmingCharacters(in: .whitespacesAndNewlines) }
        if existing.contains(where: { $0.id == msg.id }) { return existing }
        if let url = msg.mediaUrl, existing.contains(where: { x in x.mediaUrl == url && x.direction == msg.direction && abs(x.millis - msg.millis) < 15_000 }) {
            return existing
        }
        if msg.sender == "human_agent", existing.contains(where: { x in x.id.hasPrefix("optimistic-") && !x.isNote && trimmed(x.body) == trimmed(msg.body) }) {
            return existing
        }
        if msg.id.hasPrefix("ws-"), !msg.inbound, existing.contains(where: { x in
            let window: Int64 = x.id.hasPrefix("ws-") ? 10_000 : (x.isLocal ? 0 : 120_000)
            return !x.isSystem && !x.isNote && !x.inbound && x.sender == msg.sender &&
                trimmed(x.body) == trimmed(msg.body) && abs(x.millis - msg.millis) < window
        }) {
            return existing
        }
        return existing + [msg]
    }

    /// What to tell the agent when one upload fails: the server's own `detail` when it sent one, never a proxy page or a pydantic list.
    public static func uploadError(of e: Error) -> String {
        guard let api = e as? ApiError else {
            let m = ((e as? LocalizedError)?.errorDescription ?? "").trimmingCharacters(in: .whitespaces)
            return m.isEmpty ? "failed" : m
        }
        let d = api.detail.trimmingCharacters(in: .whitespacesAndNewlines)
        let validationList = api.body.range(of: #""detail"\s*:\s*\["#, options: .regularExpression) != nil
        let readable = !d.isEmpty && !validationList && !d.hasPrefix("<") && !d.hasPrefix("[") && !d.hasPrefix("{")
        if readable && api.status != 0 { return d }
        switch api.status {
        case 413: return "too large to upload"
        case 415: return "unsupported file type"
        case 422: return "the server couldn't process this file"
        case 0: return d.contains("timed out") ? "upload timed out — check your connection and try again" : "network error — try again"
        default: return "upload failed (\(api.status))"
        }
    }

    /// upload-media's ALLOWED_MIME (admin.py) — anything else is refused with a 415.
    public static let UPLOAD_MIME: Set<String> = [
        "image/jpeg", "image/png", "image/webp", "image/gif",
        "application/pdf", "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "video/mp4", "video/3gpp", "video/quicktime", "video/hevc", "video/x-m4v",
        "audio/ogg", "audio/aac", "audio/mpeg",
    ]

    /// Whether upload-media will take this file (`.mov/.hevc/.mp4/.m4v` as octet-stream pass too).
    public static func uploadable(mime: String, name: String) -> Bool {
        if UPLOAD_MIME.contains(mime) { return true }
        guard mime.isEmpty || mime == "application/octet-stream" else { return false }
        let ext = name.split(separator: ".").last.map { String($0).lowercased() } ?? ""
        return name.contains(".") && ["mov", "hevc", "mp4", "m4v"].contains(ext)
    }

    private static let liveEvtSeq = Counter()

    /// buildSystemEventFromWs: a live divider pill from `intercept_changed`.
    public static func systemEvent(fromWs e: JSONValue) -> ThreadMsg? {
        guard let kind = nonEmpty(e.str("eventKind")) else { return nil }
        let agent = nonEmpty(e.str("eventAgentName"))
        let note = nonEmpty(e.str("eventNote"))
        let label: String
        switch kind {
        case "escalated": label = "Escalated — needs human"
        case "flag": label = "Flagged: Needs Attention"
        case "intercept": label = agent.map { "Picked up by \($0)" } ?? "Picked up by agent"
        case "release": label = agent.map { "Released to AI by \($0)" } ?? "Released to AI"
        case "transfer": label = note.map { "Transferred — \($0)" } ?? "Transferred"
        case "pause": label = agent.map { "Paused by \($0) — replies held" } ?? "Paused — replies held"
        case "approve_draft": label = "AI draft approved"
        default: label = kind
        }
        return ThreadMsg(
            id: "live-evt-\(kind)-\(AppClock.now())-\(liveEvtSeq.next())",
            type: "system_event", direction: "outbound", sender: "ai",
            text: label, createdAt: nowIso(),
            agentName: agent, eventKind: kind, eventReason: nonEmpty(e.str("eventReason"))
        )
    }

    private static let isoFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    /// `Instant.toString()`: "2026-09-25T09:00:00.123Z".
    public static func nowIso() -> String { isoFormatter.string(from: AppClock.date()) }

    /// Web-chat visitors are keyed `web_<sha1 hex>` on the default "whatsapp" channel.
    public static func isWebVisitor(_ waId: String?) -> Bool { waId?.hasPrefix("web_") == true }

    public static func inboxName(_ c: Conversation) -> String {
        if isWebVisitor(c.waId) && (c.name ?? "").trimmingCharacters(in: .whitespaces).isEmpty { return "Website visitor" }
        return Fmt.displayName(c.name, c.waId)
    }

    public static func inboxHandle(_ c: Conversation) -> String {
        isWebVisitor(c.waId) ? "Web chat" : Fmt.formatPhone(c.waId)
    }

    /// A real dialable number (7–15 digits) — never a web visitor's hash or a Meta PSID.
    public static func phoneDigits(_ c: Conversation) -> String? {
        if isWebVisitor(c.waId) { return nil }
        let d = (c.waId ?? "").filter { $0.isASCII && $0.isNumber }
        return (7...15).contains(d.count) ? d : nil
    }

    /// One thread item, decoded defensively: a row whose text is not text (a stray object) drops out; the rest show.
    public static func threadMsg(of el: JSONValue) -> ThreadMsg? {
        guard let o = el.objectValue else { return nil }
        if let t = o["text"], t.objectValue != nil || t.arrayValue != nil { return nil }
        return try? NeemaJSON.decode(ThreadMsg.self, from: el)
    }

    /// A whole thread page in one decoding pass (a 2,000-message thread is not 2,000 round trips through the
    /// encoder); only when one row refuses does it fall back to row by row, so that row alone drops out.
    public static func threadMsgs(of items: [JSONValue]) -> [ThreadMsg] {
        let sane = items.filter { el in
            guard let o = el.objectValue else { return false }
            if let t = o["text"], t.objectValue != nil || t.arrayValue != nil { return false }
            return true
        }
        if let all = try? NeemaJSON.decode([ThreadMsg].self, from: .array(sane)) { return all }
        return sane.compactMap(threadMsg(of:))
    }

    /// Inbox rows in one decoding pass; a row with no id is dropped first, and a refusing row falls back to row by row.
    public static func conversations(of items: [JSONValue]) -> [Conversation] {
        let withId = items.filter { !(($0.objectValue?["id"]?.content ?? "").isEmpty) }
        if let all = try? NeemaJSON.decode([Conversation].self, from: .array(withId)) { return all }
        return withId.compactMap(conversation(of:))
    }

    /// One inbox page off the wire: {items, next_cursor}, or the legacy bare array (one final page). Nil for anything else.
    public static func page(of el: JSONValue) -> ConversationPage? {
        var page: ConversationPage
        if case .array(let a) = el {
            page = ConversationPage(items: conversations(of: a), nextCursor: nil)
        } else {
            guard let o = el.objectValue else { return nil }
            let items = o["items"]?.arrayValue ?? []
            let cursorOut = o["next_cursor"]?.content
            page = ConversationPage(items: conversations(of: items), nextCursor: (cursorOut ?? "").isEmpty ? nil : cursorOut)
        }
        page.raw = el
        return page
    }

    /// One inbox row, decoded defensively: a row with no id is dropped; odd tags are normalised.
    public static func conversation(of el: JSONValue) -> Conversation? {
        guard let o = el.objectValue, let id = o["id"]?.content, !id.isEmpty else { return nil }
        return try? NeemaJSON.decode(Conversation.self, from: el)
    }

    static func nonEmpty(_ s: String?) -> String? { (s ?? "").isEmpty ? nil : s }
}

final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var n: Int64 = 0
    func next() -> Int64 { lock.sync { n += 1; return n } }
}

/// The server answered 200 `{ok:false, error}`: DELIVERY failed (Graph refused, window closed, page token).
public struct NotDelivered: Error, LocalizedError, Equatable {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

/// Calls the inbox makes beyond NeemaApi's typed ones: the thread in the
/// inbox's own wire shape, a reply that can answer 200 {ok:false}, and a
/// streaming media upload. Query values are form-encoded (`+` for spaces), as Android's `InboxApi`.
public final class InboxApi {
    public let http: NeemaHTTP
    public init(http: NeemaHTTP) { self.http = http }

    private func enc(_ s: String) -> String { HTTPBody.formEncodeComponent(s) }

    private func parse(_ text: String) -> JSONValue {
        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return .null }
        return JSONValue.parse(text) ?? .null
    }

    /// GET /admin/conversations/{id}/messages?limit=&before=: a bare array, oldest first, decoded item by item.
    public func messages(id: String, before: String? = nil, limit: Int = Inbox.THREAD_PAGE) async throws -> [ThreadMsg] {
        var qs = "?limit=\(limit)"
        if let b = before { qs += "&before=\(enc(b))" }
        let raw = try await http.raw("GET", "/admin/conversations/\(id)/messages\(qs)")
        let el = parse(raw)
        let arr: [JSONValue]
        switch el {
        case .array(let a): arr = a
        case .null:
            let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if t.isEmpty || t == "null" { arr = [] } else { throw ApiError(status: 200, method: "GET", path: "(thread)", body: String(raw.prefix(MAX_ERROR_BODY)), malformed: true) }
        default:
            throw ApiError(status: 200, method: "GET", path: "(thread)", body: String(raw.prefix(MAX_ERROR_BODY)), malformed: true)
        }
        return Inbox.threadMsgs(of: arr)
    }

    /// One inbox page: {items, next_cursor}. An older API answers the legacy bare array — one final page.
    public func page(_ q: InboxQuery, limit: Int, cursor: String? = nil) async throws -> ConversationPage {
        var params: [(String, String)] = [("limit", String(limit))]
        if let c = cursor { params.append(("cursor", c)) }
        if q.tab != "all" { params.append(("tab", q.tab)) }
        if q.channel != "all" { params.append(("channel", q.channel)) }
        if q.mode != "all" { params.append(("mode", q.mode)) }
        if let t = q.tag, !t.isEmpty { params.append(("tag", t)) }
        let trimmed = q.q.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { params.append(("q", trimmed)) }
        let qs = params.map { "\($0.0)=\(enc($0.1))" }.joined(separator: "&")
        let el = parse(try await http.raw("GET", "/admin/conversations?\(qs)"))
        guard let page = Inbox.page(of: el) else { throw ApiError(status: 200, method: "GET", path: "(inbox page)", body: el.text, malformed: true) }
        return page
    }

    /// GET /admin/conversations/{id}: one row, the list's shape.
    public func get(id: String) async throws -> Conversation {
        let el = parse(try await http.raw("GET", "/admin/conversations/\(id)"))
        guard let c = Inbox.conversation(of: el) else { throw ApiError(status: 200, method: "GET", path: "(conversation \(id))", body: el.text, malformed: true) }
        return c
    }

    /// GET /admin/conversations/{id}/activity: {events: [...]}, distinct by id.
    public func activity(id: String) async throws -> [ActivityEvent] {
        let el = parse(try await http.raw("GET", "/admin/conversations/\(id)/activity"))
        guard let o = el.objectValue else { return [] }
        var seen: Set<String> = []
        var out: [ActivityEvent] = []
        for (i, e) in (o["events"]?.arrayValue ?? []).enumerated() {
            guard let ev = e.objectValue, let label = Inbox.nonEmpty(ev["label"]?.content) else { continue }
            let id = Inbox.nonEmpty(ev["id"]?.content) ?? "ev-\(i)"
            if !seen.insert(id).inserted { continue }
            out.append(ActivityEvent(id: id, kind: ev["kind"]?.content ?? "", label: label, detail: Inbox.nonEmpty(ev["detail"]?.content), at: Inbox.nonEmpty(ev["at"]?.content)))
        }
        return out
    }

    /// The conversation controls: the server answers {ok, mode, …}, not a row — only the status code counts.
    public func intercept(id: String) async throws { _ = try await http.raw("POST", "/admin/conversations/\(id)/intercept", body: .json("{}")) }
    public func release(id: String) async throws { _ = try await http.raw("POST", "/admin/conversations/\(id)/release", body: .json("{}")) }
    public func pause(id: String) async throws { _ = try await http.raw("POST", "/admin/conversations/\(id)/pause", body: .json("{}")) }
    public func transfer(id: String, agentId: String) async throws {
        _ = try await http.raw("POST", "/admin/conversations/\(id)/transfer", body: .json(JSONValue.object(["agent_id": .string(agentId)]).text))
    }

    /// POST /reply. A 200 {ok:false, error} means DELIVERY failed — thrown as `NotDelivered`.
    public func reply(id: String, text: String, replyTo: String?, originalText: String?, originalLang: String?, clientMsgId: String? = nil) async throws {
        var o: [String: JSONValue] = ["text": .string(text)]
        if let v = clientMsgId { o["client_msg_id"] = .string(v) }
        if let v = replyTo { o["reply_to"] = .string(v) }
        if let v = originalText { o["original_text"] = .string(v) }
        if let v = originalLang { o["original_lang"] = .string(v) }
        let res = try await http.raw("POST", "/admin/conversations/\(id)/reply", body: .json(JSONValue.object(o).text))
        if let obj = JSONValue.parse(res)?.objectValue, case .bool(false)? = obj["ok"] {
            throw NotDelivered(Inbox.nonEmpty(obj["error"]?.content) ?? "Couldn't send the reply")
        }
    }

    /// Upload one picked file (streamed from disk, or its re-encoded bytes) with its caption.
    public func upload(convId: String, item: PickedMedia) async throws -> ThreadMsg {
        let file: UploadFile
        if let b = item.bytes { file = UploadFile(bytes: b, filename: item.name, mimeType: item.mime) }
        else if let u = item.file { file = UploadFile.of(file: u, filename: item.name, mimeType: item.mime) }
        else { throw ApiError(status: 0, method: "POST", path: "/admin/conversations/\(convId)/upload-media", body: "Can't read the file") }
        var parts = MultipartBody()
        parts.add(file, named: "file")
        let caption = item.caption.trimmingCharacters(in: .whitespacesAndNewlines)
        if !caption.isEmpty { parts.addField("caption", caption) }
        let res = try await http.raw("POST", "/admin/conversations/\(convId)/upload-media", body: .multipart(parts), upload: true)
        let fallbackId = "optimistic-up-\(AppClock.now())-\(UUID().uuidString.prefix(8))"
        if var m = try? NeemaJSON.decode(ThreadMsg.self, from: res) {
            if m.id.isEmpty { m.id = fallbackId }
            return m
        }
        return ThreadMsg(id: fallbackId, direction: "outbound", sender: "human_agent", text: item.caption, createdAt: Inbox.nowIso())
    }
}

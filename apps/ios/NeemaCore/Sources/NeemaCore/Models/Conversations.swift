import Foundation

// Wire models: a 1:1 port of apps/android/.../core/model/Models.kt (itself a
// port of apps/web/src/lib/api.ts). Every field the web and Android read is
// here; unknown keys are ignored so a newer API never breaks an older app, and
// every read is lenient (see LenientKeyed) so one odd row never fails a list.

public struct Conversation: Identifiable, Equatable, Hashable, Sendable, Decodable {
    public let id: String
    public var waId: String?
    public var personId: String?
    public var externalId: String?
    /// "ai" | "human" | "paused"
    public var interceptMode: String
    public var leadStage: String?
    public var assignedAgentId: String?
    public var assignedAgentName: String?
    public var interceptSince: String?
    public var lastMessageAt: String?
    public var lastMessagePreview: String?
    /// "open" | "closed"
    public var status: String
    public var createdAt: String?
    public var updatedAt: String?
    public var name: String?
    public var avatarUrl: String?
    /// Paid hub orders for this customer — the repeat-buyer badge.
    public var ordersCount: Int
    public var channel: String
    public var unread: Int
    public var country: String?
    public var countryIso: String?
    public var flagUrl: String?
    public var tags: [String]

    public init(id: String, waId: String? = nil, personId: String? = nil, externalId: String? = nil,
                interceptMode: String = "ai", leadStage: String? = nil, assignedAgentId: String? = nil,
                assignedAgentName: String? = nil, interceptSince: String? = nil, lastMessageAt: String? = nil,
                lastMessagePreview: String? = nil, status: String = "open", createdAt: String? = nil,
                updatedAt: String? = nil, name: String? = nil, avatarUrl: String? = nil, ordersCount: Int = 0,
                channel: String = "whatsapp", unread: Int = 0, country: String? = nil, countryIso: String? = nil,
                flagUrl: String? = nil, tags: [String] = []) {
        self.id = id; self.waId = waId; self.personId = personId; self.externalId = externalId
        self.interceptMode = interceptMode; self.leadStage = leadStage; self.assignedAgentId = assignedAgentId
        self.assignedAgentName = assignedAgentName; self.interceptSince = interceptSince; self.lastMessageAt = lastMessageAt
        self.lastMessagePreview = lastMessagePreview; self.status = status; self.createdAt = createdAt
        self.updatedAt = updatedAt; self.name = name; self.avatarUrl = avatarUrl; self.ordersCount = ordersCount
        self.channel = channel; self.unread = unread; self.country = country; self.countryIso = countryIso
        self.flagUrl = flagUrl; self.tags = tags
    }

    /// Channel-native handle: wa_id for WhatsApp, PSID/IGSID otherwise.
    public var handle: String { externalId ?? waId ?? "" }
    /// Sort key: when did this thread last move.
    public var recency: String { lastMessageAt ?? createdAt ?? "" }

    enum K: String, CodingKey {
        case id, wa_id, person_id, external_id, intercept_mode, lead_stage, assigned_agent_id, assigned_agent_name,
             intercept_since, last_message_at, last_message_preview, status, created_at, updated_at, name, avatar_url,
             orders_count, channel, unread, country, country_iso, flag_url, tags
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        guard let id = c.string(.id) else { throw DecodingError.keyNotFound(K.id, .init(codingPath: [], debugDescription: "conversation without id")) }
        self.init(id: id, waId: c.string(.wa_id), personId: c.string(.person_id), externalId: c.string(.external_id),
                  interceptMode: c.string(.intercept_mode, default: "ai"), leadStage: c.string(.lead_stage),
                  assignedAgentId: c.string(.assigned_agent_id), assignedAgentName: c.string(.assigned_agent_name),
                  interceptSince: c.string(.intercept_since), lastMessageAt: c.string(.last_message_at),
                  lastMessagePreview: c.string(.last_message_preview), status: c.string(.status, default: "open"),
                  createdAt: c.string(.created_at), updatedAt: c.string(.updated_at), name: c.string(.name),
                  avatarUrl: c.string(.avatar_url), ordersCount: c.int(.orders_count, default: 0),
                  channel: c.string(.channel, default: "whatsapp"), unread: c.int(.unread, default: 0),
                  country: c.string(.country), countryIso: c.string(.country_iso), flagUrl: c.string(.flag_url),
                  tags: c.stringList(.tags))
    }
}

public struct ConversationPage: Equatable, Sendable, Decodable {
    public var items: [Conversation]
    public var nextCursor: String?
    /// The page as it came off the wire (kept for the stale-while-revalidate snapshot); not part of equality.
    public var raw: JSONValue? = nil
    public init(items: [Conversation] = [], nextCursor: String? = nil) { self.items = items; self.nextCursor = nextCursor }
    public static func == (a: ConversationPage, b: ConversationPage) -> Bool { a.items == b.items && a.nextCursor == b.nextCursor }
    enum K: String, CodingKey { case items, next_cursor }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(items: c.list(.items), nextCursor: c.string(.next_cursor))
    }
}

public struct InboxSummary: Equatable, Sendable, Decodable {
    public var unread: Int
    public var human: Int
    public var yours: Int
    public var unreadMessages: [String: Int]
    public var tags: [String]
    public init(unread: Int = 0, human: Int = 0, yours: Int = 0, unreadMessages: [String: Int] = [:], tags: [String] = []) {
        self.unread = unread; self.human = human; self.yours = yours; self.unreadMessages = unreadMessages; self.tags = tags
    }
    enum K: String, CodingKey { case unread, human, yours, unread_messages, tags }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        var counts: [String: Int] = [:]
        if let o = c.value(.unread_messages)?.objectValue {
            for (k, v) in o { if let d = v.lenientDouble { counts[k] = Int(d) } }
        }
        self.init(unread: c.int(.unread, default: 0), human: c.int(.human, default: 0), yours: c.int(.yours, default: 0),
                  unreadMessages: counts, tags: c.stringList(.tags))
    }
}

public struct CommentContext: Equatable, Hashable, Sendable, Decodable {
    public var postId: String?
    public var title: String?
    public var permalink: String?
    public var thumb: String?
    public var replyTo: String?
    public init(postId: String? = nil, title: String? = nil, permalink: String? = nil, thumb: String? = nil, replyTo: String? = nil) {
        self.postId = postId; self.title = title; self.permalink = permalink; self.thumb = thumb; self.replyTo = replyTo
    }
    enum K: String, CodingKey { case post_id, title, permalink, thumb, reply_to }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(postId: c.string(.post_id), title: c.string(.title), permalink: c.string(.permalink), thumb: c.string(.thumb), replyTo: c.string(.reply_to))
    }
}

public struct ReplyTo: Equatable, Hashable, Sendable, Decodable {
    public let id: String
    public var text: String?
    public var sender: String?
    public var mediaType: String?
    public var mediaUrl: String?
    public init(id: String, text: String? = nil, sender: String? = nil, mediaType: String? = nil, mediaUrl: String? = nil) {
        self.id = id; self.text = text; self.sender = sender; self.mediaType = mediaType; self.mediaUrl = mediaUrl
    }
    enum K: String, CodingKey { case id, text, sender, media_type, media_url }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), text: c.string(.text), sender: c.string(.sender), mediaType: c.string(.media_type), mediaUrl: c.string(.media_url))
    }
}

/// One item of the merged thread: a chat message or an inline system event.
public struct Message: Identifiable, Equatable, Hashable, Sendable, Decodable {
    public let id: String
    /// "message" | "system_event"
    public var type: String
    /// "inbound" | "outbound"
    public var direction: String
    /// "user" | "ai" | "human_agent"
    public var sender: String
    public var text: String
    public var createdAt: String
    public var isNote: Bool
    /// Team-facing English rendering of a foreign-language message.
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
    public var commentContext: CommentContext?
    public var replyTo: ReplyTo?
    /// Local-only: an optimistic bubble not yet confirmed by the server.
    public var pending: Bool
    /// Local-only: the send failed.
    public var failed: Bool

    public init(id: String, type: String = "message", direction: String = "inbound", sender: String = "user", text: String = "",
                createdAt: String = "", isNote: Bool = false, translation: String? = nil, translatedFrom: String? = nil,
                agentName: String? = nil, eventKind: String? = nil, eventReason: String? = nil, mediaType: String? = nil,
                mediaId: String? = nil, mediaUrl: String? = nil, mediaCaption: String? = nil, mimeType: String? = nil,
                filename: String? = nil, commentContext: CommentContext? = nil, replyTo: ReplyTo? = nil,
                pending: Bool = false, failed: Bool = false) {
        self.id = id; self.type = type; self.direction = direction; self.sender = sender; self.text = text
        self.createdAt = createdAt; self.isNote = isNote; self.translation = translation; self.translatedFrom = translatedFrom
        self.agentName = agentName; self.eventKind = eventKind; self.eventReason = eventReason; self.mediaType = mediaType
        self.mediaId = mediaId; self.mediaUrl = mediaUrl; self.mediaCaption = mediaCaption; self.mimeType = mimeType
        self.filename = filename; self.commentContext = commentContext; self.replyTo = replyTo; self.pending = pending; self.failed = failed
    }

    public var isSystemEvent: Bool { type == "system_event" }
    public var isInbound: Bool { direction == "inbound" }

    enum K: String, CodingKey {
        case id, type, direction, sender, text, created_at, isNote, translation, translated_from, agent_name, event_kind,
             event_reason, media_type, media_id, media_url, media_caption, mime_type, filename, comment_context, reply_to, pending, failed
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), type: c.string(.type, default: "message"), direction: c.string(.direction, default: "inbound"),
                  sender: c.string(.sender, default: "user"), text: c.string(.text, default: ""), createdAt: c.string(.created_at, default: ""),
                  isNote: c.bool(.isNote, default: false), translation: c.string(.translation), translatedFrom: c.string(.translated_from),
                  agentName: c.string(.agent_name), eventKind: c.string(.event_kind), eventReason: c.string(.event_reason),
                  mediaType: c.string(.media_type), mediaId: c.string(.media_id), mediaUrl: c.string(.media_url),
                  mediaCaption: c.string(.media_caption), mimeType: c.string(.mime_type), filename: c.string(.filename),
                  commentContext: c.object(.comment_context), replyTo: c.object(.reply_to),
                  pending: c.bool(.pending, default: false), failed: c.bool(.failed, default: false))
    }
}

public struct ActivityEvent: Identifiable, Equatable, Hashable, Sendable, Decodable {
    public let id: String
    public var kind: String
    public var label: String
    public var detail: String?
    public var at: String?
    public init(id: String, kind: String, label: String, detail: String? = nil, at: String? = nil) {
        self.id = id; self.kind = kind; self.label = label; self.detail = detail; self.at = at
    }
    enum K: String, CodingKey { case id, kind, label, detail, at }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), kind: c.string(.kind, default: ""), label: c.string(.label, default: ""), detail: c.string(.detail), at: c.string(.at))
    }
}

public struct ConversationWindow: Equatable, Sendable, Decodable {
    /// "open" | "human_agent" | "closed" | "n/a"
    public var mode: String
    public var channel: String
    public var lastInboundAt: String?
    public var expiresAt: String?
    public var humanAgentUntil: String?
    public var reason: String?
    public init(mode: String = "n/a", channel: String = "", lastInboundAt: String? = nil, expiresAt: String? = nil, humanAgentUntil: String? = nil, reason: String? = nil) {
        self.mode = mode; self.channel = channel; self.lastInboundAt = lastInboundAt; self.expiresAt = expiresAt; self.humanAgentUntil = humanAgentUntil; self.reason = reason
    }
    enum K: String, CodingKey { case mode, channel, last_inbound_at, expires_at, human_agent_until, reason }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(mode: c.string(.mode, default: "n/a"), channel: c.string(.channel, default: ""), lastInboundAt: c.string(.last_inbound_at),
                  expiresAt: c.string(.expires_at), humanAgentUntil: c.string(.human_agent_until), reason: c.string(.reason))
    }
}

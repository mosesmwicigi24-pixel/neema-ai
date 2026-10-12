import Foundation

// ── Small response envelopes ────────────────────────────────────────────────

/// A `{ok}` answer; an empty 2xx reads as ok (Android's decode of "null"/"{}").
public struct OkResponse: Equatable, Sendable, Decodable {
    public var ok: Bool
    public init(ok: Bool = true) { self.ok = ok }
    enum K: String, CodingKey { case ok }
    public init(from decoder: Decoder) throws { self.init(ok: (try decoder.lenient(K.self)).bool(.ok, default: true)) }
}

public struct AnswerResponse: Equatable, Sendable, Decodable {
    public var answer: String
    public init(answer: String = "") { self.answer = answer }
    enum K: String, CodingKey { case answer }
    public init(from decoder: Decoder) throws { self.init(answer: (try decoder.lenient(K.self)).string(.answer, default: "")) }
}

public struct SentResponse: Equatable, Sendable, Decodable {
    public var ok: Bool
    public var sent: String
    public init(ok: Bool = true, sent: String = "") { self.ok = ok; self.sent = sent }
    enum K: String, CodingKey { case ok, sent }
    public init(from decoder: Decoder) throws { let c = try decoder.lenient(K.self); self.init(ok: c.bool(.ok, default: true), sent: c.string(.sent, default: "")) }
}

public struct DraftResponse: Equatable, Sendable, Decodable {
    public var draft: String?
    public init(draft: String? = nil) { self.draft = draft }
    enum K: String, CodingKey { case draft }
    public init(from decoder: Decoder) throws { self.init(draft: (try decoder.lenient(K.self)).string(.draft)) }
}

public struct TranslateResponse: Equatable, Sendable, Decodable {
    public var text: String
    public var lang: String?
    public init(text: String = "", lang: String? = nil) { self.text = text; self.lang = lang }
    enum K: String, CodingKey { case text, lang }
    public init(from decoder: Decoder) throws { let c = try decoder.lenient(K.self); self.init(text: c.string(.text, default: ""), lang: c.string(.lang)) }
}

public struct ResolveResponse: Equatable, Sendable, Decodable {
    public var conversationId: String?
    public init(conversationId: String? = nil) { self.conversationId = conversationId }
    enum K: String, CodingKey { case conversation_id }
    public init(from decoder: Decoder) throws { self.init(conversationId: (try decoder.lenient(K.self)).string(.conversation_id)) }
}

public struct RecoverMediaResponse: Equatable, Sendable, Decodable {
    public var ok: Bool
    public var mediaUrl: String
    public var mediaType: String?
    public init(ok: Bool = true, mediaUrl: String = "", mediaType: String? = nil) { self.ok = ok; self.mediaUrl = mediaUrl; self.mediaType = mediaType }
    enum K: String, CodingKey { case ok, media_url, media_type }
    public init(from decoder: Decoder) throws { let c = try decoder.lenient(K.self); self.init(ok: c.bool(.ok, default: true), mediaUrl: c.string(.media_url, default: ""), mediaType: c.string(.media_type)) }
}

public struct VideoUrlResponse: Equatable, Sendable, Decodable {
    public var videoUrl: String
    public init(videoUrl: String = "") { self.videoUrl = videoUrl }
    enum K: String, CodingKey { case video_url }
    public init(from decoder: Decoder) throws { self.init(videoUrl: (try decoder.lenient(K.self)).string(.video_url, default: "")) }
}

public struct DealsResponse: Equatable, Sendable, Decodable {
    public var deals: [Deal]
    public init(deals: [Deal] = []) { self.deals = deals }
    enum K: String, CodingKey { case deals }
    public init(from decoder: Decoder) throws { self.init(deals: (try decoder.lenient(K.self)).list(.deals)) }
}

public struct ActionsResponse: Equatable, Sendable, Decodable {
    public var actions: [PlannedAction]
    public init(actions: [PlannedAction] = []) { self.actions = actions }
    enum K: String, CodingKey { case actions }
    public init(from decoder: Decoder) throws { self.init(actions: (try decoder.lenient(K.self)).list(.actions)) }
}

public struct ActivityResponse: Equatable, Sendable, Decodable {
    public var events: [ActivityEvent]
    public init(events: [ActivityEvent] = []) { self.events = events }
    enum K: String, CodingKey { case events }
    public init(from decoder: Decoder) throws { self.init(events: (try decoder.lenient(K.self)).list(.events)) }
}

public struct DirectivesResponse: Equatable, Sendable, Decodable {
    public var directives: String
    public var maxChars: Int
    public init(directives: String = "", maxChars: Int = 0) { self.directives = directives; self.maxChars = maxChars }
    enum K: String, CodingKey { case directives, max_chars }
    public init(from decoder: Decoder) throws { let c = try decoder.lenient(K.self); self.init(directives: c.string(.directives, default: ""), maxChars: c.int(.max_chars, default: 0)) }
}

public struct StagesResponse: Equatable, Sendable, Decodable {
    public var stages: [String]
    public init(stages: [String] = []) { self.stages = stages }
    enum K: String, CodingKey { case stages }
    public init(from decoder: Decoder) throws { self.init(stages: (try decoder.lenient(K.self)).stringList(.stages)) }
}

public struct OfferPutResponse: Equatable, Sendable, Decodable {
    public var ok: Bool
    public var campaign: Campaign?
    public var running: Bool
    public var says: String
    public init(ok: Bool = true, campaign: Campaign? = nil, running: Bool = false, says: String = "") { self.ok = ok; self.campaign = campaign; self.running = running; self.says = says }
    enum K: String, CodingKey { case ok, campaign, running, says }
    public init(from decoder: Decoder) throws { let c = try decoder.lenient(K.self); self.init(ok: c.bool(.ok, default: true), campaign: c.object(.campaign), running: c.bool(.running, default: false), says: c.string(.says, default: "")) }
}

public struct InviteResponse: Equatable, Sendable, Decodable {
    public var ok: Bool
    public var waId: String
    public init(ok: Bool = true, waId: String = "") { self.ok = ok; self.waId = waId }
    enum K: String, CodingKey { case ok, wa_id }
    public init(from decoder: Decoder) throws { let c = try decoder.lenient(K.self); self.init(ok: c.bool(.ok, default: true), waId: c.string(.wa_id, default: "")) }
}

public struct ConnectResponse: Equatable, Sendable, Decodable {
    public var ok: Bool
    public var callId: String
    public init(ok: Bool = true, callId: String = "") { self.ok = ok; self.callId = callId }
    enum K: String, CodingKey { case ok, call_id }
    public init(from decoder: Decoder) throws { let c = try decoder.lenient(K.self); self.init(ok: c.bool(.ok, default: true), callId: c.string(.call_id, default: "")) }
}

public struct TranscribeResponse: Equatable, Sendable, Decodable {
    public var ok: Bool
    public var status: String
    public init(ok: Bool = true, status: String = "") { self.ok = ok; self.status = status }
    enum K: String, CodingKey { case ok, status }
    public init(from decoder: Decoder) throws { let c = try decoder.lenient(K.self); self.init(ok: c.bool(.ok, default: true), status: c.string(.status, default: "")) }
}

public struct RecordingResponse: Equatable, Sendable, Decodable {
    public var ok: Bool
    public var willTranscribe: Bool?
    public init(ok: Bool = true, willTranscribe: Bool? = nil) { self.ok = ok; self.willTranscribe = willTranscribe }
    enum K: String, CodingKey { case ok, will_transcribe }
    public init(from decoder: Decoder) throws { let c = try decoder.lenient(K.self); self.init(ok: c.bool(.ok, default: true), willTranscribe: c.bool(.will_transcribe)) }
}

public struct RoleAssignResponse: Equatable, Sendable, Decodable {
    public var ok: Bool
    public var permissions: [String]
    public init(ok: Bool = true, permissions: [String] = []) { self.ok = ok; self.permissions = permissions }
    enum K: String, CodingKey { case ok, permissions }
    public init(from decoder: Decoder) throws { let c = try decoder.lenient(K.self); self.init(ok: c.bool(.ok, default: true), permissions: c.stringList(.permissions)) }
}

/// The auth router's `TokenResponse`.
public struct TokenResponse: Equatable, Sendable, Decodable {
    public var accessToken: String
    public var refreshToken: String?
    public var tokenType: String
    public var agentId: String
    public var role: String
    public var isSuperuser: Bool
    public init(accessToken: String, refreshToken: String? = nil, tokenType: String = "bearer", agentId: String = "", role: String = "agent", isSuperuser: Bool = false) {
        self.accessToken = accessToken; self.refreshToken = refreshToken; self.tokenType = tokenType; self.agentId = agentId; self.role = role; self.isSuperuser = isSuperuser
    }
    enum K: String, CodingKey { case access_token, refresh_token, token_type, agent_id, role, is_superuser }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        guard let access = c.string(.access_token) else { throw DecodingError.keyNotFound(K.access_token, .init(codingPath: [], debugDescription: "no access_token")) }
        self.init(accessToken: access, refreshToken: c.string(.refresh_token), tokenType: c.string(.token_type, default: "bearer"), agentId: c.string(.agent_id, default: ""),
                  role: c.string(.role, default: "agent"), isSuperuser: c.bool(.is_superuser, default: false))
    }
}

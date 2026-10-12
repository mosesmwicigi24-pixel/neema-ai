import Foundation

/// One call row as services/call_log.py `serialize` builds it (GET /admin/calls,
/// GET /admin/calls/{id}, the `call` of a `call_update` frame and of a thread's
/// call event). Every field has a default: a legacy row, a bare row the
/// recording upload created, or a key the server adds later never fails the decode.
public struct Call: Identifiable, Equatable, Hashable, Sendable, Decodable {
    public var id: String
    public var callId: String
    public var waId: String?
    public var name: String?
    public var personId: String?
    /// The customer's WhatsApp conversation, for "Open chat" (nil before they ever wrote).
    public var conversationId: String?
    /// "whatsapp" | "messenger". A Messenger row has no `waId`: its customer is `externalId`, their PSID — never shown.
    public var channel: String
    public var externalId: String?
    public var direction: String
    /// ringing | answered | completed | missed | declined | callback | no_answer | rejected | cancelled | failed (legacy `ended` = completed).
    public var status: String
    public var duration: Int?
    public var agentId: String?
    public var agentName: String?
    public var startedAt: String?
    public var answeredAt: String?
    public var endedAt: String?
    public var summary: String?
    /// The AI's read of the call, kept raw and read field by field through `insights`.
    public var insightsRaw: JSONValue?
    /// none | recorded | pending | processing | done | failed
    public var transcriptStatus: String?
    public var hasRecording: Bool
    /// WhatsApp voicemail for this call arrived (the audio is in the chat as a normal message).
    public var hasVoicemail: Bool
    /// A missed / callback call nobody has returned or marked done yet.
    public var followUpOpen: Bool
    public var followUpDoneAt: String?

    public init(id: String = "", callId: String = "", waId: String? = nil, name: String? = nil, personId: String? = nil, conversationId: String? = nil,
                channel: String = "whatsapp", externalId: String? = nil, direction: String = "inbound", status: String = "", duration: Int? = nil,
                agentId: String? = nil, agentName: String? = nil, startedAt: String? = nil, answeredAt: String? = nil, endedAt: String? = nil,
                summary: String? = nil, insightsRaw: JSONValue? = nil, transcriptStatus: String? = nil, hasRecording: Bool = false,
                hasVoicemail: Bool = false, followUpOpen: Bool = false, followUpDoneAt: String? = nil) {
        self.id = id; self.callId = callId; self.waId = waId; self.name = name; self.personId = personId; self.conversationId = conversationId
        self.channel = channel; self.externalId = externalId; self.direction = direction; self.status = status; self.duration = duration
        self.agentId = agentId; self.agentName = agentName; self.startedAt = startedAt; self.answeredAt = answeredAt; self.endedAt = endedAt
        self.summary = summary; self.insightsRaw = insightsRaw; self.transcriptStatus = transcriptStatus; self.hasRecording = hasRecording
        self.hasVoicemail = hasVoicemail; self.followUpOpen = followUpOpen; self.followUpDoneAt = followUpDoneAt
    }

    /// `insightsRaw` read leniently (nil when absent or not an object).
    public var insights: CallInsights? { CallInsights.of(insightsRaw) }

    enum K: String, CodingKey {
        case id, call_id, wa_id, name, person_id, conversation_id, channel, external_id, direction, status, duration, agent_id, agent_name,
             started_at, answered_at, ended_at, summary, insights, transcript_status, has_recording, has_voicemail, follow_up_open, follow_up_done_at
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), callId: c.string(.call_id, default: ""), waId: c.string(.wa_id), name: c.string(.name), personId: c.string(.person_id),
                  conversationId: c.string(.conversation_id), channel: c.string(.channel, default: "whatsapp"), externalId: c.string(.external_id),
                  direction: c.string(.direction, default: "inbound"), status: c.string(.status, default: ""), duration: c.int(.duration), agentId: c.string(.agent_id),
                  agentName: c.string(.agent_name), startedAt: c.string(.started_at), answeredAt: c.string(.answered_at), endedAt: c.string(.ended_at),
                  summary: c.string(.summary), insightsRaw: c.value(.insights), transcriptStatus: c.string(.transcript_status),
                  hasRecording: c.bool(.has_recording, default: false), hasVoicemail: c.bool(.has_voicemail, default: false),
                  followUpOpen: c.bool(.follow_up_open, default: false), followUpDoneAt: c.string(.follow_up_done_at))
    }
}

/// `insights` on a call row: what the customer wanted, what was agreed, and
/// the follow-up the AI drafted. Every field is optional; lists that arrive as
/// a single string (or hold numbers / objects) still read as text.
public struct CallInsights: Equatable, Hashable, Sendable {
    public var intent: String?
    public var products: [String]
    public var objections: [String]
    public var commitments: [String]
    public var nextAction: String?
    /// A reply the agent may put in the composer ("Use as reply") — never sent by itself.
    public var followUpMessage: String?
    public var sentiment: String?
    public init(intent: String? = nil, products: [String] = [], objections: [String] = [], commitments: [String] = [], nextAction: String? = nil, followUpMessage: String? = nil, sentiment: String? = nil) {
        self.intent = intent; self.products = products; self.objections = objections; self.commitments = commitments; self.nextAction = nextAction; self.followUpMessage = followUpMessage; self.sentiment = sentiment
    }
    public var isEmpty: Bool {
        intent == nil && products.isEmpty && objections.isEmpty && commitments.isEmpty && nextAction == nil && followUpMessage == nil && sentiment == nil
    }

    static func text(_ e: JSONValue?) -> String? {
        guard let e else { return nil }
        switch e {
        case .object(let o): return text(o["name"] ?? o["text"] ?? o["title"])
        case .array, .null: return nil
        default:
            let t = (e.content ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return t.isEmpty || t == "null" ? nil : t
        }
    }
    static func texts(_ e: JSONValue?) -> [String] {
        guard let e else { return [] }
        switch e {
        case .array(let items): return items.compactMap(text)
        case .null: return []
        default: return [text(e)].compactMap { $0 }
        }
    }

    public static func of(_ raw: JSONValue?) -> CallInsights? {
        guard let o = raw?.objectValue else { return nil }
        let i = CallInsights(intent: text(o["intent"]), products: texts(o["products"]), objections: texts(o["objections"]),
                             commitments: texts(o["commitments"]), nextAction: text(o["next_action"]),
                             followUpMessage: text(o["follow_up_message"]), sentiment: text(o["sentiment"]))
        return i.isEmpty ? nil : i
    }
}

/// GET /admin/calls/permission: may we call this customer? Meta's answer is the
/// truth (`source` "meta"); our store stands in when Meta can't be reached ("store").
public struct CallPermission: Equatable, Hashable, Sendable, Decodable {
    public var waId: String?
    /// granted | denied | requested | unknown (never asked — a call may still go through).
    public var status: String
    public var expiresAt: String?
    public var permanent: Bool
    /// no_permission | temporary | permanent, or nil when Meta was unreachable.
    public var metaStatus: String?
    public var canCall: Bool?
    public var canRequest: Bool?
    public var requestAvailableAt: String?
    public var callsLeftToday: Int?
    public var revoked: Bool
    public var unansweredStreak: Int
    /// meta | store
    public var source: String?
    public var requestedAt: String?
    public var at: String?
    /// "messenger" on a Messenger answer (whose customer is `externalId`, the PSID); absent = WhatsApp.
    public var channel: String?
    public var externalId: String?
    public init(waId: String? = nil, status: String = "unknown", expiresAt: String? = nil, permanent: Bool = false, metaStatus: String? = nil, canCall: Bool? = nil,
                canRequest: Bool? = nil, requestAvailableAt: String? = nil, callsLeftToday: Int? = nil, revoked: Bool = false, unansweredStreak: Int = 0,
                source: String? = nil, requestedAt: String? = nil, at: String? = nil, channel: String? = nil, externalId: String? = nil) {
        self.waId = waId; self.status = status; self.expiresAt = expiresAt; self.permanent = permanent; self.metaStatus = metaStatus; self.canCall = canCall
        self.canRequest = canRequest; self.requestAvailableAt = requestAvailableAt; self.callsLeftToday = callsLeftToday; self.revoked = revoked
        self.unansweredStreak = unansweredStreak; self.source = source; self.requestedAt = requestedAt; self.at = at; self.channel = channel; self.externalId = externalId
    }
    enum K: String, CodingKey {
        case wa_id, status, expires_at, permanent, meta_status, can_call, can_request, request_available_at, calls_left_today, revoked,
             unanswered_streak, source, requested_at, at, channel, external_id
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(waId: c.string(.wa_id), status: c.string(.status, default: "unknown"), expiresAt: c.string(.expires_at), permanent: c.bool(.permanent, default: false),
                  metaStatus: c.string(.meta_status), canCall: c.bool(.can_call), canRequest: c.bool(.can_request), requestAvailableAt: c.string(.request_available_at),
                  callsLeftToday: c.int(.calls_left_today), revoked: c.bool(.revoked, default: false), unansweredStreak: c.int(.unanswered_streak, default: 0),
                  source: c.string(.source), requestedAt: c.string(.requested_at), at: c.string(.at), channel: c.string(.channel), externalId: c.string(.external_id))
    }
}

/// POST /admin/calls/request-permission → {ok, permission, route, already_permitted?}.
public struct PermissionRequestResponse: Equatable, Sendable, Decodable {
    public var ok: Bool
    public var permission: CallPermission?
    /// free_form (inside the 24 h window) | template (outside it).
    public var route: String?
    public var alreadyPermitted: Bool
    public init(ok: Bool = true, permission: CallPermission? = nil, route: String? = nil, alreadyPermitted: Bool = false) {
        self.ok = ok; self.permission = permission; self.route = route; self.alreadyPermitted = alreadyPermitted
    }
    enum K: String, CodingKey { case ok, permission, route, already_permitted }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(ok: c.bool(.ok, default: true), permission: c.object(.permission), route: c.string(.route), alreadyPermitted: c.bool(.already_permitted, default: false))
    }
}

public struct CallTranscript: Equatable, Sendable, Decodable {
    public var callId: String
    public var status: String
    public var transcript: String?
    public var summary: String?
    public var language: String?
    public var hasRecording: Bool
    public var recordingUrl: String?
    public var insightsRaw: JSONValue?
    public init(callId: String = "", status: String = "", transcript: String? = nil, summary: String? = nil, language: String? = nil, hasRecording: Bool = false, recordingUrl: String? = nil, insightsRaw: JSONValue? = nil) {
        self.callId = callId; self.status = status; self.transcript = transcript; self.summary = summary; self.language = language; self.hasRecording = hasRecording; self.recordingUrl = recordingUrl; self.insightsRaw = insightsRaw
    }
    public var insights: CallInsights? { CallInsights.of(insightsRaw) }
    enum K: String, CodingKey { case call_id, status, transcript, summary, language, has_recording, recording_url, insights }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(callId: c.string(.call_id, default: ""), status: c.string(.status, default: ""), transcript: c.string(.transcript), summary: c.string(.summary),
                  language: c.string(.language), hasRecording: c.bool(.has_recording, default: false), recordingUrl: c.string(.recording_url), insightsRaw: c.value(.insights))
    }
}

public struct IceServer: Equatable, Hashable, Sendable, Decodable {
    public var urls: JSONValue?
    public var username: String?
    public var credential: String?
    public init(urls: JSONValue? = nil, username: String? = nil, credential: String? = nil) { self.urls = urls; self.username = username; self.credential = credential }
    /// The server's URLs, whether `urls` came as one string or a list.
    public var urlList: [String] {
        switch urls {
        case .string(let s)?: return [s]
        case .array(let a)?: return a.compactMap { $0.content }
        default: return []
        }
    }
    enum K: String, CodingKey { case urls, username, credential }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(urls: c.value(.urls), username: c.string(.username), credential: c.string(.credential))
    }
}

/// One channel's calling, as GET /calls/channels says it.
public struct ChannelCalling: Equatable, Hashable, Sendable, Decodable {
    public var inbound: Bool
    public var outbound: Bool
    public var video: Bool
    /// What the softphone builds for a customer's call: "answer" (WhatsApp) or "offer" (Messenger).
    public var sdp: String?
    public init(inbound: Bool = false, outbound: Bool = false, video: Bool = false, sdp: String? = nil) { self.inbound = inbound; self.outbound = outbound; self.video = video; self.sdp = sdp }
    enum K: String, CodingKey { case inbound, outbound, video, sdp }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(inbound: c.bool(.inbound, default: false), outbound: c.bool(.outbound, default: false), video: c.bool(.video, default: false), sdp: c.string(.sdp))
    }
}

/// GET /calls/channels (and ice-config `channels`): which channels can take and place a call right now.
public struct CallChannels: Equatable, Hashable, Sendable, Decodable {
    public var whatsapp: ChannelCalling
    public var messenger: ChannelCalling
    public var instagram: ChannelCalling
    public init(whatsapp: ChannelCalling = ChannelCalling(inbound: true, outbound: true, sdp: "answer"), messenger: ChannelCalling = ChannelCalling(), instagram: ChannelCalling = ChannelCalling()) {
        self.whatsapp = whatsapp; self.messenger = messenger; self.instagram = instagram
    }
    enum K: String, CodingKey { case whatsapp, messenger, instagram }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(whatsapp: c.object(.whatsapp) ?? ChannelCalling(inbound: true, outbound: true, sdp: "answer"), messenger: c.object(.messenger) ?? ChannelCalling(), instagram: c.object(.instagram) ?? ChannelCalling())
    }
}

public struct IceConfig: Equatable, Sendable, Decodable {
    public var iceServers: [IceServer]
    public var record: Bool?
    public var transcribe: Bool?
    public var autoTranscribe: Bool?
    public var metaTranscription: Bool?
    public var channels: CallChannels?
    public init(iceServers: [IceServer] = [], record: Bool? = nil, transcribe: Bool? = nil, autoTranscribe: Bool? = nil, metaTranscription: Bool? = nil, channels: CallChannels? = nil) {
        self.iceServers = iceServers; self.record = record; self.transcribe = transcribe; self.autoTranscribe = autoTranscribe; self.metaTranscription = metaTranscription; self.channels = channels
    }
    enum K: String, CodingKey { case ice_servers, record, transcribe, auto_transcribe, meta_transcription, channels }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(iceServers: c.list(.ice_servers), record: c.bool(.record), transcribe: c.bool(.transcribe), autoTranscribe: c.bool(.auto_transcribe),
                  metaTranscription: c.bool(.meta_transcription), channels: c.object(.channels))
    }
}

/// The SDP Meta sends back for a Messenger call: `sdp` is Meta's answer;
/// `renegotiation`, when present, an offer to apply after it — a plain string
/// or `{sdp_type, sdp}`. A WhatsApp answer carries neither.
public struct CallSdpResponse: Equatable, Sendable, Decodable {
    public var ok: Bool
    public var callId: String
    public var channel: String?
    public var sdp: String?
    public var sdpType: String?
    public var renegotiation: JSONValue?
    public init(ok: Bool = true, callId: String = "", channel: String? = nil, sdp: String? = nil, sdpType: String? = nil, renegotiation: JSONValue? = nil) {
        self.ok = ok; self.callId = callId; self.channel = channel; self.sdp = sdp; self.sdpType = sdpType; self.renegotiation = renegotiation
    }
    /// The renegotiation offer's SDP, whichever shape it came in (nil when none).
    public var renegotiationSdp: String? {
        switch renegotiation {
        case .string(let s)?: return s.trimmingCharacters(in: .whitespaces).isEmpty ? nil : s
        case .object(let o)?: return o["sdp"]?.stringValue.flatMap { $0.trimmingCharacters(in: .whitespaces).isEmpty ? nil : $0 }
        default: return nil
        }
    }
    enum K: String, CodingKey { case ok, call_id, channel, sdp, sdp_type, renegotiation }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(ok: c.bool(.ok, default: true), callId: c.string(.call_id, default: ""), channel: c.string(.channel), sdp: c.string(.sdp), sdpType: c.string(.sdp_type), renegotiation: c.value(.renegotiation))
    }
}

public struct CallHoliday: Equatable, Hashable, Sendable, Codable {
    public var date: String?
    public var startTime: String?
    public var endTime: String?
    public init(date: String? = nil, startTime: String? = nil, endTime: String? = nil) { self.date = date; self.startTime = startTime; self.endTime = endTime }
    enum K: String, CodingKey { case date, start_time, end_time }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(date: c.string(.date), startTime: c.string(.start_time), endTime: c.string(.end_time))
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: K.self)
        try c.encodeIfPresent(date, forKey: .date); try c.encodeIfPresent(startTime, forKey: .start_time); try c.encodeIfPresent(endTime, forKey: .end_time)
    }
}

public struct CallHoursSlot: Equatable, Hashable, Sendable, Codable {
    public var dayOfWeek: String?
    public var openTime: String?
    public var closeTime: String?
    public init(dayOfWeek: String? = nil, openTime: String? = nil, closeTime: String? = nil) { self.dayOfWeek = dayOfWeek; self.openTime = openTime; self.closeTime = closeTime }
    enum K: String, CodingKey { case day_of_week, open_time, close_time }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(dayOfWeek: c.string(.day_of_week), openTime: c.string(.open_time), closeTime: c.string(.close_time))
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: K.self)
        try c.encodeIfPresent(dayOfWeek, forKey: .day_of_week); try c.encodeIfPresent(openTime, forKey: .open_time); try c.encodeIfPresent(closeTime, forKey: .close_time)
    }
}

public struct CallHours: Equatable, Hashable, Sendable, Decodable {
    /// ENABLED | DISABLED
    public var status: String?
    public var timezoneId: String?
    public var weekly: [CallHoursSlot]
    public var holidays: [CallHoliday]
    public init(status: String? = nil, timezoneId: String? = nil, weekly: [CallHoursSlot] = [], holidays: [CallHoliday] = []) { self.status = status; self.timezoneId = timezoneId; self.weekly = weekly; self.holidays = holidays }
    enum K: String, CodingKey { case status, timezone_id, weekly_operating_hours, holiday_schedule }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(status: c.string(.status), timezoneId: c.string(.timezone_id), weekly: c.list(.weekly_operating_hours), holidays: c.list(.holiday_schedule))
    }
}

public struct CallVoicemail: Equatable, Hashable, Sendable, Decodable {
    /// ENABLED | DISABLED
    public var status: String?
    /// REJECT and / or TIMEOUT
    public var triggers: [String]?
    public var timeoutSeconds: Int?
    public init(status: String? = nil, triggers: [String]? = nil, timeoutSeconds: Int? = nil) { self.status = status; self.triggers = triggers; self.timeoutSeconds = timeoutSeconds }
    enum K: String, CodingKey { case status, triggers, timeout_seconds }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(status: c.string(.status), triggers: c.value(.triggers).map { LenientKeyed<K>.lenientStrings($0) }, timeoutSeconds: c.int(.timeout_seconds))
    }
}

/// GET /admin/calls/settings: the number's WhatsApp calling settings (manage_settings).
public struct CallingSettings: Equatable, Hashable, Sendable, Decodable {
    /// ENABLED | DISABLED
    public var status: String?
    /// DEFAULT | DISABLE_ALL | HIDE_IN_CHAT
    public var callIconVisibility: String?
    /// ENABLED | DISABLED: a customer who calls us lets us call them back for 7 days.
    public var callbackPermissionStatus: String?
    public var callHours: CallHours?
    public var voicemail: CallVoicemail?
    /// Meta's restrictions on calling (read-only), kept raw: their shape isn't documented.
    public var restrictions: [JSONValue]
    public var lastRestrictionEvent: JSONValue?
    public init(status: String? = nil, callIconVisibility: String? = nil, callbackPermissionStatus: String? = nil, callHours: CallHours? = nil, voicemail: CallVoicemail? = nil, restrictions: [JSONValue] = [], lastRestrictionEvent: JSONValue? = nil) {
        self.status = status; self.callIconVisibility = callIconVisibility; self.callbackPermissionStatus = callbackPermissionStatus; self.callHours = callHours; self.voicemail = voicemail; self.restrictions = restrictions; self.lastRestrictionEvent = lastRestrictionEvent
    }
    enum K: String, CodingKey { case status, call_icon_visibility, callback_permission_status, call_hours, voicemail, restrictions, last_restriction_event }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(status: c.string(.status), callIconVisibility: c.string(.call_icon_visibility), callbackPermissionStatus: c.string(.callback_permission_status),
                  callHours: c.object(.call_hours), voicemail: c.object(.voicemail), restrictions: c.value(.restrictions)?.arrayValue ?? [], lastRestrictionEvent: c.value(.last_restriction_event))
    }
}

/// POST /admin/calls/settings → {ok, sent, settings}.
public struct CallingSettingsSaved: Equatable, Sendable, Decodable {
    public var ok: Bool
    public var settings: CallingSettings?
    public init(ok: Bool = true, settings: CallingSettings? = nil) { self.ok = ok; self.settings = settings }
    enum K: String, CodingKey { case ok, settings }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(ok: c.bool(.ok, default: true), settings: c.object(.settings))
    }
}

/// GET /admin/calls/permission-template: the call-request template used outside the 24 h window.
public struct PermissionTemplate: Equatable, Hashable, Sendable, Decodable {
    public var configured: Bool
    public var name: String?
    public var language: String?
    /// env | app
    public var source: String?
    public var wabaConfigured: Bool
    /// Nil when Meta couldn't be asked.
    public var exists: Bool?
    /// approved | pending | rejected | … | nil
    public var status: String?
    public var category: String?
    public init(configured: Bool = false, name: String? = nil, language: String? = nil, source: String? = nil, wabaConfigured: Bool = false, exists: Bool? = nil, status: String? = nil, category: String? = nil) {
        self.configured = configured; self.name = name; self.language = language; self.source = source; self.wabaConfigured = wabaConfigured; self.exists = exists; self.status = status; self.category = category
    }
    enum K: String, CodingKey { case configured, name, language, source, waba_configured, exists, status, category }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(configured: c.bool(.configured, default: false), name: c.string(.name), language: c.string(.language), source: c.string(.source),
                  wabaConfigured: c.bool(.waba_configured, default: false), exists: c.bool(.exists), status: c.string(.status), category: c.string(.category))
    }
}

public struct CallOffer: Equatable, Hashable, Sendable, Decodable {
    public var callId: String
    /// The caller's offer (WhatsApp). Nil on a Messenger call: Meta sends none.
    public var sdp: String?
    public var from: String?
    public var channel: String?
    /// Messenger: WE build the offer and send it through /answer; Meta's reply carries the answer.
    public var offerRequired: Bool
    public init(callId: String = "", sdp: String? = nil, from: String? = nil, channel: String? = nil, offerRequired: Bool = false) { self.callId = callId; self.sdp = sdp; self.from = from; self.channel = channel; self.offerRequired = offerRequired }
    enum K: String, CodingKey { case call_id, sdp, from, channel, offer_required }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(callId: c.string(.call_id, default: ""), sdp: c.string(.sdp), from: c.string(.from), channel: c.string(.channel), offerRequired: c.bool(.offer_required, default: false))
    }
}

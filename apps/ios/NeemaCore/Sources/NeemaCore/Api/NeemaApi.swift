import Foundation

/// `URLEncoder.encode(s, "UTF-8")` with `+` written `%20` — right in a path segment and a query alike.
func enc(_ s: String) -> String { HTTPBody.formEncodeComponent(s).replacingOccurrences(of: "+", with: "%20") }

func query(_ pairs: [(String, String?)]) -> String {
    let q = pairs.compactMap { (k, v) -> String? in
        guard let v = v, !v.isEmpty else { return nil }
        return "\(k)=\(enc(v))"
    }.joined(separator: "&")
    return q.isEmpty ? "" : "?" + q
}

/// A binary part for multipart uploads (file picker / recorder output).
///
/// Either bytes already in memory (a re-encoded photo), or — through `of` —
/// a file that is STREAMED into the request as it is written, so a 150 MB
/// video or an hour-long call recording never sits whole in memory. A
/// streamed part re-opens its source on every write, so the one retry
/// `NeemaHTTP` makes after a token refresh sends it again intact.
public struct UploadFile {
    public let filename: String
    public let mimeType: String
    public let source: MultipartBody.Source

    public init(bytes: Data, filename: String, mimeType: String) {
        self.filename = filename
        self.mimeType = mimeType
        self.source = .data(bytes)
    }

    private init(file: URL, filename: String, mimeType: String) {
        self.filename = filename
        self.mimeType = mimeType
        self.source = .file(file)
    }

    /// Stream `file` from disk.
    public static func of(file: URL, filename: String? = nil, mimeType: String) -> UploadFile {
        UploadFile(file: file, filename: filename ?? file.lastPathComponent, mimeType: mimeType)
    }

    func part(named name: String) -> MultipartBody.Part {
        MultipartBody.Part(name: name, filename: filename, contentType: mimeType, source: source)
    }
}

extension MultipartBody {
    mutating func add(_ file: UploadFile, named name: String) { addPart(file.part(named: name)) }
    mutating func addPart(_ p: Part) {
        switch p.source {
        case .data(let d): addFile(p.name, filename: p.filename ?? "file", contentType: p.contentType ?? "application/octet-stream", data: d)
        case .file(let u): addFile(p.name, filename: p.filename ?? u.lastPathComponent, contentType: p.contentType ?? "application/octet-stream", file: u)
        }
    }
}

/// The inbox's server-side filters. Mirrors GET /admin/conversations.
public struct InboxQuery: Equatable, Sendable {
    /// "all" | "unread" | "read" | "human" | "yours"
    public var tab: String
    public var channel: String
    public var mode: String
    public var tag: String?
    public var q: String

    public init(tab: String = "all", channel: String = "all", mode: String = "all", tag: String? = nil, q: String = "") {
        self.tab = tab
        self.channel = channel
        self.mode = mode
        self.tag = tag
        self.q = q
    }
}

/// Every endpoint the web dashboard calls (apps/web/src/lib/api.ts), grouped the
/// same way as Android's `NeemaApi`. Features may add their own calls on `http`
/// for endpoints that the web reaches outside api.ts (e.g. the CRM/leads routes).
public final class NeemaApi {
    public let http: NeemaHTTP

    /// Every conversation read teaches the phone its customer's name, so a
    /// message notification says who wrote (the notifications layer hooks this).
    public var onConversationsSeen: (([Conversation]) -> Void)?

    public init(http: NeemaHTTP) {
        self.http = http
        conversations = Conversations(self)
        deals = Deals(self)
        actions = Actions(self)
        settings = Settings(self)
        agents = Agents(self)
        catalog = CatalogApi(self)
        orders = Orders(self)
        stats = StatsApi(self)
        calls = Calls(self)
        profile = Profile(self)
        roles = Roles(self)
        crashes = Crashes(self)
    }

    public private(set) var conversations: Conversations!
    public private(set) var deals: Deals!
    public private(set) var actions: Actions!
    public private(set) var settings: Settings!
    public private(set) var agents: Agents!
    public private(set) var catalog: CatalogApi!
    public private(set) var orders: Orders!
    public private(set) var stats: StatsApi!
    public private(set) var calls: Calls!
    public private(set) var profile: Profile!
    public private(set) var roles: Roles!
    public private(set) var crashes: Crashes!

    static let empty: JSONValue = .object([:])

    // ── Ask / answer via Neema ──────────────────────────────────────────────
    // Ask, answer and generate-draft run a whole AI turn server-side: give them
    // the long-lived client so a slow model is never reported as a failure.
    public func askNeema(convId: String, question: String) async throws -> AnswerResponse {
        try http.decode(try await http.raw("POST", "/admin/conversations/\(convId)/ask", body: try http.encode(JSONValue.object(["question": .string(question)])), upload: true))
    }

    public func answerViaNeema(convId: String, facts: String) async throws -> SentResponse {
        try http.decode(try await http.raw("POST", "/admin/conversations/\(convId)/answer", body: try http.encode(JSONValue.object(["facts": .string(facts)])), upload: true))
    }

    /// Send the approved WhatsApp invite template to a customer's number.
    public func whatsappInvite(phone: String, name: String? = nil) async throws -> InviteResponse {
        var o: [String: JSONValue] = ["phone": .string(phone)]
        if let n = name { o["name"] = .string(n) }
        return try await http.post("/admin/whatsapp-invite", JSONValue.object(o))
    }

    public func attribution() async throws -> Attribution { try await http.get("/admin/attribution") }

    public final class Deals {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }
        public func list(status: String = "open") async throws -> [Deal] {
            (try await api.http.get("/admin/deals?status=\(enc(status))") as DealsResponse).deals
        }
        public func patch(id: String, body: JSONValue) async throws -> OkResponse { try await api.http.patch("/admin/deals/\(id)", body) }
    }

    public final class Actions {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }
        public func list(status: String = "pending") async throws -> [PlannedAction] {
            (try await api.http.get("/admin/actions?status=\(enc(status))") as ActionsResponse).actions
        }
        /// Approving runs the action server-side (sends the message, pushes the
        /// order to the hub), which can outlast the 30 s ceiling: the long client.
        public func approve(id: String, draft: String? = nil) async throws -> OkResponse {
            var o: [String: JSONValue] = [:]
            if let d = draft, !d.isEmpty { o["draft"] = .string(d) }
            return try api.http.decode(try await api.http.raw("POST", "/admin/actions/\(id)/approve", body: try api.http.encode(JSONValue.object(o)), upload: true))
        }
        public func veto(id: String) async throws -> OkResponse { try await api.http.post("/admin/actions/\(id)/veto", NeemaApi.empty) }
    }

    /// The phone apps' crash reports (routers/admin.py client_crash_report / client_crash_list).
    public final class Crashes {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }
        /// GET /admin/client-crashes?limit=N (manage_settings): newest first, at most 100.
        public func list(limit: Int = 20) async throws -> [ClientCrashReport] { try await api.http.get("/admin/client-crashes?limit=\(limit)") }
        /// POST /admin/client-crashes: one report `{id, kind, at, summary, trace, thread, app_version, build, device, sdk}`; a repeated id answers `{ok, duplicate}`.
        public func report(_ body: JSONValue) async throws -> JSONValue { try await api.http.post("/admin/client-crashes", body) }
    }

    public final class Settings {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }
        public func getDirectives() async throws -> DirectivesResponse { try await api.http.get("/admin/settings/directives") }
        public func putDirectives(_ directives: String) async throws -> JSONValue {
            try await api.http.put("/admin/settings/directives", JSONValue.object(["directives": .string(directives)]))
        }
        public func getPipelineStages() async throws -> [String] { (try await api.http.get("/admin/settings/pipeline-stages") as StagesResponse).stages }
        public func putPipelineStages(_ stages: [String]) async throws -> StagesResponse {
            try await api.http.put("/admin/settings/pipeline-stages", JSONValue.object(["stages": .array(stages.map { .string($0) })]))
        }
        public func getTranslation() async throws -> TranslationSetting { try await api.http.get("/admin/settings/translation") }
        public func putTranslation(enabled: Bool) async throws -> JSONValue {
            try await api.http.put("/admin/settings/translation", JSONValue.object(["enabled": .bool(enabled)]))
        }
        public func getOffer() async throws -> OfferSetting { try await api.http.get("/admin/settings/offer") }
        public func putOffer(_ campaign: Campaign?) async throws -> OfferPutResponse {
            let c: JSONValue = try campaign.map { try JSONValue(encoding: $0) } ?? .null
            return try await api.http.put("/admin/settings/offer", JSONValue.object(["campaign": c]))
        }
    }

    public final class Conversations {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }

        /// Resolve a hub deep link (phone and/or order number) to a conversation id.
        public func resolve(key: String, ref: String? = nil) async throws -> String? {
            (try await api.http.get("/admin/conversations/resolve" + query([("key", key), ("ref", ref)])) as ResolveResponse).conversationId
        }

        public func list(mode: String? = nil, status: String? = nil) async throws -> [Conversation] {
            let rows: [Conversation] = try await api.http.get("/admin/conversations" + query([("mode", mode), ("status", status)]))
            api.onConversationsSeen?(rows)
            return rows
        }

        public func get(id: String) async throws -> Conversation {
            let c: Conversation = try await api.http.get("/admin/conversations/\(id)")
            api.onConversationsSeen?([c])
            return c
        }

        /// One page of the inbox — whole PEOPLE. Tolerates the legacy bare-array reply.
        public func page(_ q: InboxQuery, limit: Int, cursor: String? = nil) async throws -> ConversationPage {
            let qs = query([
                ("limit", String(limit)),
                ("cursor", cursor),
                ("tab", q.tab == "all" ? nil : q.tab),
                ("channel", q.channel == "all" ? nil : q.channel),
                ("mode", q.mode == "all" ? nil : q.mode),
                ("tag", q.tag),
                ("q", q.q.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : q.q.trimmingCharacters(in: .whitespacesAndNewlines)),
            ])
            let text = try await api.http.raw("GET", "/admin/conversations" + qs)
            let page: ConversationPage
            if text.drop(while: { $0.isWhitespace }).hasPrefix("[") {
                page = ConversationPage(items: try api.http.decode(text), nextCursor: nil)
            } else {
                page = try api.http.decode(text)
            }
            api.onConversationsSeen?(page.items)
            return page
        }

        public func summary() async throws -> InboxSummary { try await api.http.get("/admin/conversations/summary") }
        public func activity(id: String) async throws -> [ActivityEvent] {
            (try await api.http.get("/admin/conversations/\(id)/activity") as ActivityResponse).events
        }

        /// One page of the merged message + system-event timeline (newest 50 by default).
        public func messages(id: String, before: String? = nil, limit: Int? = nil) async throws -> [Message] {
            try await api.http.get("/admin/conversations/\(id)/messages" + query([("before", before), ("limit", limit.map(String.init))]))
        }

        // These answer small envelopes ({ok, mode} / {ok, transferred_to}), not the
        // conversation row — decode loosely so a success is never read as a failure.
        public func intercept(id: String) async throws -> JSONValue { try await api.http.post("/admin/conversations/\(id)/intercept", NeemaApi.empty) }
        public func release(id: String) async throws -> JSONValue { try await api.http.post("/admin/conversations/\(id)/release", NeemaApi.empty) }
        public func pause(id: String) async throws -> JSONValue { try await api.http.post("/admin/conversations/\(id)/pause", NeemaApi.empty) }
        public func transfer(id: String, agentId: String) async throws -> JSONValue {
            try await api.http.post("/admin/conversations/\(id)/transfer", JSONValue.object(["agent_id": .string(agentId)]))
        }

        public func sendReply(id: String, text: String, replyTo: String? = nil, originalText: String? = nil,
                              originalLang: String? = nil, clientMsgId: String? = nil) async throws -> Message {
            var o: [String: JSONValue] = ["text": .string(text)]
            if let v = clientMsgId { o["client_msg_id"] = .string(v) }
            if let v = replyTo { o["reply_to"] = .string(v) }
            if let v = originalText { o["original_text"] = .string(v) }
            if let v = originalLang { o["original_lang"] = .string(v) }
            return try await api.http.post("/admin/conversations/\(id)/reply", JSONValue.object(o))
        }

        /// Reply-box translate toggle: English in, the customer's language out.
        public func translateReply(id: String, text: String) async throws -> TranslateResponse {
            try await api.http.post("/admin/conversations/\(id)/translate-reply", JSONValue.object(["text": .string(text)]))
        }

        public func approveDraft(id: String, text: String? = nil) async throws -> OkResponse {
            try await api.http.post("/admin/conversations/\(id)/approve-draft", JSONValue.object(["text": text.map { .string($0) } ?? .null]))
        }
        public func latestDraft(id: String) async throws -> String? { (try await api.http.get("/admin/conversations/\(id)/latest-draft") as DraftResponse).draft }
        public func generateDraft(id: String) async throws -> String? {
            let r: DraftResponse = try api.http.decode(try await api.http.raw("POST", "/admin/conversations/\(id)/generate-draft", body: try api.http.encode(NeemaApi.empty), upload: true))
            return r.draft
        }
        public func addNote(id: String, text: String) async throws -> Message {
            try await api.http.post("/admin/conversations/\(id)/note", JSONValue.object(["text": .string(text)]))
        }

        /// Can a free-form reply go out right now? (Meta/WhatsApp 24h window.)
        public func window(id: String) async throws -> ConversationWindow { try await api.http.get("/admin/conversations/\(id)/window") }

        /// Re-fetch an expired Meta attachment from the source and re-host it.
        public func recoverMedia(messageId: String) async throws -> RecoverMediaResponse {
            try await api.http.post("/admin/messages/\(messageId)/recover-media", NeemaApi.empty)
        }

        public func close(id: String) async throws -> OkResponse { try await api.http.post("/admin/conversations/\(id)/release", NeemaApi.empty) }
        public func clearHistory(id: String) async throws -> OkResponse { try await api.http.delete("/admin/conversations/\(id)/messages") }

        /// A fresh direct video URL for a page reel/video post (source URLs expire).
        public func postVideo(postId: String, channel: String? = nil) async throws -> String {
            (try await api.http.get("/admin/post-video/\(enc(postId))" + query([("channel", channel)])) as VideoUrlResponse).videoUrl
        }

        /// Upload a file from the device and send it to the customer.
        public func uploadMedia(convId: String, file: UploadFile, caption: String? = nil) async throws -> Message {
            var parts = MultipartBody()
            parts.add(file, named: "file")
            if let c = caption, !c.isEmpty { parts.addField("caption", c) }
            return try await api.http.multipart("/admin/conversations/\(convId)/upload-media", parts)
        }

        /// Send a media message by supplying an existing public URL.
        public func sendMediaUrl(convId: String, mediaUrl: String, mediaType: String, caption: String? = nil, filename: String? = nil) async throws -> Message {
            var o: [String: JSONValue] = ["media_url": .string(mediaUrl), "media_type": .string(mediaType)]
            if let c = caption { o["caption"] = .string(c) }
            if let f = filename { o["filename"] = .string(f) }
            return try await api.http.post("/admin/conversations/\(convId)/reply-media", JSONValue.object(o))
        }
    }

    public final class Agents {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }
        public func list() async throws -> [Agent] { try await api.http.get("/admin/agents") }
        public func create(name: String, email: String, password: String, role: String? = nil) async throws -> JSONValue {
            var o: [String: JSONValue] = ["name": .string(name), "email": .string(email), "password": .string(password)]
            if let r = role { o["role"] = .string(r) }
            return try await api.http.post("/admin/agents", JSONValue.object(o))
        }
        /// The server answers `{"ok": true}`, not the agent row.
        public func update(id: String, body: JSONValue) async throws -> OkResponse { try await api.http.patch("/admin/agents/\(id)", body) }
        public func delete(id: String) async throws -> OkResponse { try await api.http.delete("/admin/agents/\(id)") }
        public func setAvailable(id: String, available: Bool) async throws -> OkResponse {
            try await api.http.patch("/admin/agents/\(id)", JSONValue.object(["is_available": .bool(available)]))
        }
    }

    public final class CatalogApi {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }
        public func list(category: String? = nil, search: String? = nil) async throws -> [CatalogItem] {
            try await api.http.get("/admin/catalog" + query([("category", category), ("search", search)]))
        }
        public func create(_ p: CreateCatalogPayload) async throws -> CatalogItem { try await api.http.post("/admin/catalog", p) }
        public func update(id: String, body: JSONValue) async throws -> CatalogItem { try await api.http.patch("/admin/catalog/\(id)", body) }
        public func toggleStock(id: String, inStock: Bool) async throws -> CatalogItem {
            try await api.http.patch("/admin/catalog/\(id)", JSONValue.object(["in_stock": .bool(inStock)]))
        }
        public func delete(id: String) async throws { _ = try await api.http.raw("DELETE", "/admin/catalog/\(id)") }
        /// Where the hub's prices disagree with themselves.
        public func audit() async throws -> PriceAudit { try await api.http.get("/admin/catalog/audit") }
    }

    public final class Orders {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }
        public func list(status: String? = nil, waId: String? = nil) async throws -> [Order] {
            try await api.http.get("/admin/orders" + query([("status", status), ("wa_id", waId)]))
        }
        public func get(id: String) async throws -> Order { try await api.http.get("/admin/orders/\(id)") }
        public func updateStatus(id: String, status: String, paymentStatus: String? = nil, fulfillmentStatus: String? = nil) async throws -> Order {
            var o: [String: JSONValue] = ["status": .string(status)]
            if let p = paymentStatus { o["payment_status"] = .string(p) }
            if let f = fulfillmentStatus { o["fulfillment_status"] = .string(f) }
            return try await api.http.patch("/admin/orders/\(id)", JSONValue.object(o))
        }
    }

    public final class StatsApi {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }
        public func overview() async throws -> Stats { try await api.http.get("/admin/stats") }
    }

    public final class Calls {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }

        static func bare(_ waId: String) -> String { waId.hasPrefix("+") ? String(waId.dropFirst()) : waId }

        /// GET /admin/calls, newest first. `waId` narrows to one customer; `view`
        /// "follow_up" to the missed / callback calls nobody has returned yet.
        /// With no argument the request carries no query (the web's own call).
        public func list(waId: String? = nil, view: String? = nil, limit: Int? = nil, psid: String? = nil, channel: String? = nil) async throws -> [Call] {
            var q: [String] = []
            if let w = waId { q.append("wa_id=\(enc(Self.bare(w)))") }
            if let p = psid { q.append("psid=\(enc(p))") }
            if let c = channel { q.append("channel=\(enc(c))") }
            if let v = view { q.append("view=\(enc(v))") }
            if let l = limit { q.append("limit=\(l)") }
            return try await api.http.get(q.isEmpty ? "/admin/calls" : "/admin/calls?" + q.joined(separator: "&"))
        }
        /// One call's current row — how a phone that was offline learns how its call really ended.
        public func get(callId: String) async throws -> Call { try await api.http.get("/admin/calls/\(enc(callId))") }
        /// Whether this customer allowed business calls (granted | denied | requested | unknown).
        public func permission(waId: String) async throws -> CallPermission { try await api.http.get("/admin/calls/permission?wa_id=\(enc(Self.bare(waId)))") }
        /// Clear a missed / callback call from the follow-up list.
        public func followUpDone(callId: String) async throws -> OkResponse { try await api.http.post("/admin/calls/\(enc(callId))/follow-up-done", NeemaApi.empty) }
        public func iceConfig() async throws -> IceConfig { try await api.http.get("/admin/calls/ice-config") }
        public func offer(callId: String) async throws -> CallOffer { try await api.http.get("/admin/calls/\(enc(callId))/offer") }
        /// Accept the call with our SDP: the answer on WhatsApp; on Messenger our
        /// OFFER, and the reply carries Meta's answer (+ an optional renegotiation).
        public func answer(callId: String, sdp: String) async throws -> CallSdpResponse {
            try await api.http.post("/admin/calls/\(enc(callId))/answer", JSONValue.object(["sdp": .string(sdp)]))
        }
        /// GET /admin/calls/channels: which channels can take / place a call right now.
        public func channels() async throws -> CallChannels { try await api.http.get("/admin/calls/channels") }
        /// A Messenger call to `psid` with our offer: Meta's answer comes back at once.
        public func connectMessenger(psid: String, sdp: String, name: String? = nil) async throws -> CallSdpResponse {
            var o: [String: JSONValue] = ["channel": "messenger", "psid": .string(psid), "sdp": .string(sdp)]
            if let n = name, !n.trimmingCharacters(in: .whitespaces).isEmpty { o["name"] = .string(n) }
            return try await api.http.post("/admin/calls/connect", JSONValue.object(o))
        }
        /// Whether this Messenger customer accepted our call request.
        public func messengerPermission(psid: String) async throws -> CallPermission {
            try await api.http.get("/admin/calls/permission?channel=messenger&psid=\(enc(psid))")
        }
        /// Sends Messenger's `calling_optin` request (Accept / Decline); the answer arrives as `call_permission`.
        public func requestMessengerPermission(psid: String) async throws -> PermissionRequestResponse {
            try await api.http.post("/admin/calls/request-permission", JSONValue.object(["channel": "messenger", "psid": .string(psid)]))
        }
        public func terminate(callId: String) async throws -> OkResponse { try await api.http.post("/admin/calls/\(enc(callId))/terminate", NeemaApi.empty) }
        public func callback(callId: String) async throws -> OkResponse { try await api.http.post("/admin/calls/\(enc(callId))/callback", NeemaApi.empty) }
        public func connect(to: String, sdp: String, name: String? = nil) async throws -> ConnectResponse {
            var o: [String: JSONValue] = ["to": .string(to), "sdp": .string(sdp)]
            if let n = name { o["name"] = .string(n) }
            return try await api.http.post("/admin/calls/connect", JSONValue.object(o))
        }
        /// Sends the customer WhatsApp's call-permission request; their answer arrives as `call_permission`.
        public func requestPermission(to: String, name: String? = nil) async throws -> PermissionRequestResponse {
            var o: [String: JSONValue] = ["to": .string(to)]
            if let n = name, !n.trimmingCharacters(in: .whitespaces).isEmpty { o["name"] = .string(n) }
            return try await api.http.post("/admin/calls/request-permission", JSONValue.object(o))
        }
        /// GET /admin/calls/settings (manage_settings): the number's WhatsApp calling settings.
        public func settings() async throws -> CallingSettings { try await api.http.get("/admin/calls/settings") }
        /// POST /admin/calls/settings with ONLY the fields to change (call_hours / voicemail are merged server-side).
        public func saveSettings(_ change: JSONValue) async throws -> CallingSettingsSaved { try await api.http.post("/admin/calls/settings", change) }
        /// GET /admin/calls/permission-template: is the outside-the-window call-request template there and approved?
        public func permissionTemplate() async throws -> PermissionTemplate { try await api.http.get("/admin/calls/permission-template") }
        /// POST /admin/calls/permission-template: create it with the server's default wording (Meta reviews it).
        public func createPermissionTemplate() async throws -> JSONValue { try await api.http.post("/admin/calls/permission-template", NeemaApi.empty) }
        public func transcript(callId: String) async throws -> CallTranscript { try await api.http.get("/admin/calls/\(enc(callId))/transcript") }
        public func transcribe(callId: String) async throws -> TranscribeResponse { try await api.http.post("/admin/calls/\(enc(callId))/transcribe", NeemaApi.empty) }
        /// Upload the recorded call audio (both sides mixed) on hangup — pass `UploadFile.of(file:)` to stream it.
        public func uploadRecording(callId: String, file: UploadFile) async throws -> RecordingResponse {
            var parts = MultipartBody()
            parts.add(file, named: "file")
            return try await api.http.multipart("/admin/calls/\(enc(callId))/recording", parts)
        }
    }

    public final class Profile {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }
        public func me() async throws -> Agent { try await api.http.get("/admin/me") }
        public func update(name: String? = nil, email: String? = nil, password: String? = nil) async throws -> JSONValue {
            var o: [String: JSONValue] = [:]
            if let n = name { o["name"] = .string(n) }
            if let e = email { o["email"] = .string(e) }
            if let p = password { o["password"] = .string(p) }
            return try await api.http.patch("/admin/me", JSONValue.object(o))
        }
    }

    public final class Roles {
        unowned let api: NeemaApi
        init(_ api: NeemaApi) { self.api = api }
        public func list() async throws -> [CustomRole] { try await api.http.get("/admin/roles") }
        public func create(id: String, name: String, description: String, color: String, permissions: [String]) async throws -> CustomRole {
            try await api.http.post("/admin/roles", JSONValue.object([
                "id": .string(id), "name": .string(name), "description": .string(description), "color": .string(color),
                "permissions": .array(permissions.map { .string($0) }),
            ]))
        }
        public func update(id: String, body: JSONValue) async throws -> CustomRole { try await api.http.patch("/admin/roles/\(id)", body) }
        public func delete(id: String) async throws -> OkResponse { try await api.http.delete("/admin/roles/\(id)") }
        public func assignToAgent(agentId: String, roleId: String) async throws -> RoleAssignResponse {
            try await api.http.patch("/admin/agents/\(agentId)/role", JSONValue.object(["custom_role_id": .string(roleId)]))
        }
    }
}

public extension JSONValue {
    /// Any `Encodable` as a JSON tree (a `Campaign` into `{campaign: …}`).
    init<T: Encodable>(encoding value: T) throws {
        self = try NeemaJSON.decoder.decode(JSONValue.self, from: NeemaJSON.encoder.encode(value))
    }
}

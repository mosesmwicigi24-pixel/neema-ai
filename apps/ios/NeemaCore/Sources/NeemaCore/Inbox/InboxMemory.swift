import Foundation

/// What the inbox keeps on disk (per agent, in the snapshot cache) so that the
/// system reclaiming the app in the background loses none of the agent's
/// work: which filters and which conversation were open, every half-typed
/// reply (each customer keeps their own), notes, AI drafts being edited, files
/// picked but not sent, and every send that had not been confirmed
/// (Android `feature/conversations/InboxMemory.kt`).
///
/// A sign-out wipes it: the next agent on a shared phone sees nothing.
public struct InboxMemory: Codable, Equatable, Sendable {
    public var activeId: String = ""
    public var threadOpen: Bool = false
    public var tab: String = "all"
    public var channel: String = "all"
    public var mode: String = "all"
    public var tag: String? = nil
    /// The search box as typed (the query it runs is `q`, after the pause).
    public var search: String = ""
    public var q: String = ""
    public var showFilters: Bool = false
    /// Each person's composer, by composer key (the open one included).
    public var composers: [String: SavedComposer] = [:]
    public var txMode: [String: Bool] = [:]
    /// Half-written internal notes, by conversation.
    public var notes: [String: String] = [:]
    /// The open thread's dialog: "note" | "transfer" | nil.
    public var dialog: String? = nil
    /// Sends not yet confirmed (or refused and waiting for Retry / Edit).
    public var outbox: [SavedOutgoing] = []

    public init() {}

    public var filters: InboxQuery { InboxQuery(tab: tab, channel: channel, mode: mode, tag: tag, q: q) }
    public var isEmpty: Bool { self == InboxMemory() }

    enum K: String, CodingKey { case activeId, threadOpen, tab, channel, mode, tag, search, q, showFilters, composers, txMode, notes, dialog, outbox }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: K.self)
        activeId = try c.decodeIfPresent(String.self, forKey: .activeId) ?? ""
        threadOpen = try c.decodeIfPresent(Bool.self, forKey: .threadOpen) ?? false
        tab = try c.decodeIfPresent(String.self, forKey: .tab) ?? "all"
        channel = try c.decodeIfPresent(String.self, forKey: .channel) ?? "all"
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? "all"
        tag = try c.decodeIfPresent(String.self, forKey: .tag)
        search = try c.decodeIfPresent(String.self, forKey: .search) ?? ""
        q = try c.decodeIfPresent(String.self, forKey: .q) ?? ""
        showFilters = try c.decodeIfPresent(Bool.self, forKey: .showFilters) ?? false
        composers = try c.decodeIfPresent([String: SavedComposer].self, forKey: .composers) ?? [:]
        txMode = try c.decodeIfPresent([String: Bool].self, forKey: .txMode) ?? [:]
        notes = try c.decodeIfPresent([String: String].self, forKey: .notes) ?? [:]
        dialog = try c.decodeIfPresent(String.self, forKey: .dialog)
        outbox = try c.decodeIfPresent([SavedOutgoing].self, forKey: .outbox) ?? []
    }
}

public struct SavedMedia: Codable, Equatable, Sendable {
    public var uri: String
    public var name: String
    public var mime: String
    public var size: Int64
    public var caption: String = ""
    /// It was re-encoded to fit (the bytes are rebuilt from `uri` on restore).
    public var reencoded: Bool = false
    public var error: String? = nil
    public var unconfirmed: Bool = false

    public init(uri: String, name: String, mime: String, size: Int64, caption: String = "", reencoded: Bool = false, error: String? = nil, unconfirmed: Bool = false) {
        self.uri = uri; self.name = name; self.mime = mime; self.size = size; self.caption = caption
        self.reencoded = reencoded; self.error = error; self.unconfirmed = unconfirmed
    }

    enum K: String, CodingKey { case uri, name, mime, size, caption, reencoded, error, unconfirmed }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: K.self)
        uri = try c.decode(String.self, forKey: .uri)
        name = try c.decode(String.self, forKey: .name)
        mime = try c.decode(String.self, forKey: .mime)
        size = try c.decode(Int64.self, forKey: .size)
        caption = try c.decodeIfPresent(String.self, forKey: .caption) ?? ""
        reencoded = try c.decodeIfPresent(Bool.self, forKey: .reencoded) ?? false
        error = try c.decodeIfPresent(String.self, forKey: .error)
        unconfirmed = try c.decodeIfPresent(Bool.self, forKey: .unconfirmed) ?? false
    }
}

public struct SavedComposer: Codable, Equatable, Sendable {
    public var replyText: String = ""
    public var quoted: Quoted? = nil
    public var draftVisible: Bool = false
    public var draftExpanded: Bool = false
    public var draftText: String = ""
    public var draftEditing: Bool = false
    public var media: [SavedMedia] = []
    public var lostMedia: [String] = []

    public init(replyText: String = "", quoted: Quoted? = nil, draftVisible: Bool = false, draftExpanded: Bool = false, draftText: String = "",
                draftEditing: Bool = false, media: [SavedMedia] = [], lostMedia: [String] = []) {
        self.replyText = replyText; self.quoted = quoted; self.draftVisible = draftVisible; self.draftExpanded = draftExpanded
        self.draftText = draftText; self.draftEditing = draftEditing; self.media = media; self.lostMedia = lostMedia
    }

    public var isEmpty: Bool { self == SavedComposer() }

    enum K: String, CodingKey { case replyText, quoted, draftVisible, draftExpanded, draftText, draftEditing, media, lostMedia }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: K.self)
        replyText = try c.decodeIfPresent(String.self, forKey: .replyText) ?? ""
        quoted = try c.decodeIfPresent(Quoted.self, forKey: .quoted)
        draftVisible = try c.decodeIfPresent(Bool.self, forKey: .draftVisible) ?? false
        draftExpanded = try c.decodeIfPresent(Bool.self, forKey: .draftExpanded) ?? false
        draftText = try c.decodeIfPresent(String.self, forKey: .draftText) ?? ""
        draftEditing = try c.decodeIfPresent(Bool.self, forKey: .draftEditing) ?? false
        media = try c.decodeIfPresent([SavedMedia].self, forKey: .media) ?? []
        lostMedia = try c.decodeIfPresent([String].self, forKey: .lostMedia) ?? []
    }

    /// Everything but the files, which need a check that the system still lets the app read them.
    public func liveWithoutMedia() -> ComposerUi {
        ComposerUi(replyText: replyText, quoted: quoted, draftVisible: draftVisible, draftExpanded: draftExpanded,
                   draftText: draftText, draftEditing: draftEditing, lostMedia: lostMedia)
    }
}

public struct SavedOutgoing: Codable, Equatable, Sendable {
    public var localId: String
    public var convId: String
    public var kind: String
    public var text: String
    public var replyToId: String? = nil
    public var origText: String? = nil
    public var origLang: String? = nil
    public var typed: String
    public var quoted: Quoted? = nil
    public var known: [String] = []
    public var failed: Bool = false
    /// Its first attempt got no answer: a retry looks for it on the server before sending again.
    public var checking: Bool = false
    public var retried: Bool = false
    /// Refused with a 401: it never left, and goes once the agent signs in again.
    public var authHeld: Bool = false
    /// The bubble as it was drawn (text, time, quote).
    public var bubble: ThreadMsg
    public var error: String? = nil

    public init(localId: String, convId: String, kind: String, text: String, replyToId: String? = nil, origText: String? = nil, origLang: String? = nil,
                typed: String? = nil, quoted: Quoted? = nil, known: [String] = [], failed: Bool = false, checking: Bool = false, retried: Bool = false,
                authHeld: Bool = false, bubble: ThreadMsg, error: String? = nil) {
        self.localId = localId; self.convId = convId; self.kind = kind; self.text = text; self.replyToId = replyToId
        self.origText = origText; self.origLang = origLang; self.typed = typed ?? text; self.quoted = quoted; self.known = known
        self.failed = failed; self.checking = checking; self.retried = retried; self.authHeld = authHeld; self.bubble = bubble; self.error = error
    }

    enum K: String, CodingKey { case localId, convId, kind, text, replyToId, origText, origLang, typed, quoted, known, failed, checking, retried, authHeld, bubble, error }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: K.self)
        localId = try c.decode(String.self, forKey: .localId)
        convId = try c.decode(String.self, forKey: .convId)
        kind = try c.decode(String.self, forKey: .kind)
        text = try c.decode(String.self, forKey: .text)
        replyToId = try c.decodeIfPresent(String.self, forKey: .replyToId)
        origText = try c.decodeIfPresent(String.self, forKey: .origText)
        origLang = try c.decodeIfPresent(String.self, forKey: .origLang)
        typed = try c.decodeIfPresent(String.self, forKey: .typed) ?? text
        quoted = try c.decodeIfPresent(Quoted.self, forKey: .quoted)
        known = try c.decodeIfPresent([String].self, forKey: .known) ?? []
        failed = try c.decodeIfPresent(Bool.self, forKey: .failed) ?? false
        checking = try c.decodeIfPresent(Bool.self, forKey: .checking) ?? false
        retried = try c.decodeIfPresent(Bool.self, forKey: .retried) ?? false
        authHeld = try c.decodeIfPresent(Bool.self, forKey: .authHeld) ?? false
        bubble = try c.decode(ThreadMsg.self, forKey: .bubble)
        error = try c.decodeIfPresent(String.self, forKey: .error)
    }
}

extension ComposerUi {
    public func saved() -> SavedComposer {
        SavedComposer(
            replyText: replyText, quoted: quoted,
            draftVisible: draftVisible, draftExpanded: draftExpanded, draftText: draftText, draftEditing: draftEditing,
            media: media.map { SavedMedia(uri: $0.file?.absoluteString ?? "", name: $0.name, mime: $0.mime, size: $0.size, caption: $0.caption,
                                          reencoded: $0.bytes != nil, error: $0.error, unconfirmed: $0.unconfirmed) },
            lostMedia: lostMedia
        )
    }
}

import Foundation

// The inbox screen's state (Android `ConversationsViewModel.kt`'s state classes).

/// The paged inbox (hooks/useInbox.ts).
public struct InboxUi: Equatable, Sendable {
    /// Every row ever loaded — for LOOKUPS (the open thread, identities, deep links).
    public var cache: [String: Conversation] = [:]
    /// Which filter `orderIds` belongs to.
    public var orderKey: String = Inbox.DEFAULT_KEY
    /// What the current filter's server pages returned — what the LIST shows.
    public var orderIds: [String] = []
    public var filters: InboxQuery = InboxQuery()
    public var summary: InboxSummary? = nil
    public var loading: Bool = false
    public var loadingMore: Bool = false
    public var hasMore: Bool = false
    /// Page one has come from the SERVER this session (not just a snapshot).
    public var freshLoaded: Bool = false
    /// The current filter's first page FAILED: the list offers a quiet "Couldn't load — Retry".
    public var loadError: Bool = false
    /// Why the last page-one load failed, in plain words (no connection, server down…).
    public var errorText: String? = nil
    /// The next page failed. Auto-paging stops until the agent taps Retry or a refresh succeeds.
    public var moreError: Bool = false
    public init() {}
}

/// List chrome: search box text, filter panel, bulk selection.
public struct ListUi: Equatable, Sendable {
    public var search: String = ""
    public var showFilters: Bool = false
    public var selectMode: Bool = false
    public var selected: Set<String> = []
    public var bulkBusy: Bool = false
    public init() {}
}

/// GET /admin/customers/{key}?channel= (crm.py) — phone + channels, for the invite shortcut.
public struct Reach: Equatable, Sendable {
    public let convId: String
    public let phone: String?
    public let hasWhatsApp: Bool
    public init(convId: String, phone: String?, hasWhatsApp: Bool) { self.convId = convId; self.phone = phone; self.hasWhatsApp = hasWhatsApp }
}

public struct ThreadUi: Equatable, Sendable {
    public var activeId: String = ""
    /// Phone layout: the thread is the full screen (web `mobilePanel === "thread"`).
    public var threadOpen: Bool = false
    public var messages: [String: [ThreadMsg]] = [:]
    public var hasMore: [String: Bool] = [:]
    public var loading: Bool = false
    public var error: Bool = false
    /// Why the open thread failed to load, in plain words.
    public var errorText: String? = nil
    /// The conversation whose older page is being fetched ("" = none).
    public var olderLoading: String = ""
    /// The conversation whose older page failed — offers a tap to retry.
    public var olderError: String = ""
    /// Unread count when each thread was opened — places the "N new" divider.
    public var unreadSnapshot: [String: Int] = [:]
    public var window: ConversationWindow? = nil
    public var activity: [ActivityEvent] = []
    public var activityOpen: Bool = false
    /// Per conversation: "intercept" | "release" | "pause" while that control is in flight.
    public var busy: [String: String] = [:]
    /// Media re-fetched from Meta this session, by message id.
    public var recovered: [String: String] = [:]
    /// The open person's CRM profile, as far as the thread menu needs it. Nil until loaded.
    public var reach: Reach? = nil
    public init() {}

    /// The control in flight on `id`, or "".
    public func busyFor(_ id: String) -> String { busy[id] ?? "" }
}

public struct TxPreview: Equatable, Sendable {
    public let src: String
    public let text: String
    public let lang: String?
    public init(src: String, text: String, lang: String?) { self.src = src; self.text = text; self.lang = lang }
}

public struct ComposerUi: Equatable, Sendable {
    public var replyText: String = ""
    /// Per-conversation translate toggle; absent = ON when the thread reads foreign.
    public var txMode: [String: Bool] = [:]
    public var txPreview: TxPreview? = nil
    public var txBusy: Bool = false
    public var quoted: Quoted? = nil
    public var draftVisible: Bool = false
    public var draftExpanded: Bool = false
    public var draftText: String = ""
    public var draftEditing: Bool = false
    public var generatingDraft: Bool = false
    public var media: [PickedMedia] = []
    public var uploading: Bool = false
    /// Files picked before the system closed the app that it no longer lets the app read: named, so the agent knows to attach them again.
    public var lostMedia: [String] = []

    public init(replyText: String = "", txMode: [String: Bool] = [:], txPreview: TxPreview? = nil, txBusy: Bool = false, quoted: Quoted? = nil,
                draftVisible: Bool = false, draftExpanded: Bool = false, draftText: String = "", draftEditing: Bool = false,
                generatingDraft: Bool = false, media: [PickedMedia] = [], uploading: Bool = false, lostMedia: [String] = []) {
        self.replyText = replyText; self.txMode = txMode; self.txPreview = txPreview; self.txBusy = txBusy; self.quoted = quoted
        self.draftVisible = draftVisible; self.draftExpanded = draftExpanded; self.draftText = draftText; self.draftEditing = draftEditing
        self.generatingDraft = generatingDraft; self.media = media; self.uploading = uploading; self.lostMedia = lostMedia
    }
}

public struct DialogUi: Equatable, Sendable {
    public var transfer: Bool = false
    public var note: Bool = false
    public var noteText: String = ""
    public var clearConfirm: Bool = false
    public var clearing: Bool = false
    public init() {}
}

/// What a reply / approval / note is, while it is on its way.
public enum OutKind: String, Sendable, Codable { case reply = "Reply", approve = "Approve", note = "Note" }

/// A send that has left the composer and is not yet confirmed. It lives until
/// the server's own row for it turns up (or it is edited away): a timeout
/// never loses the words and never becomes a second send.
public struct Outgoing: Equatable, Sendable {
    public var localId: String
    public var convId: String
    public var kind: OutKind
    /// What goes to the server — in the customer's language when translated.
    public var text: String
    public var replyToId: String? = nil
    public var origText: String? = nil
    public var origLang: String? = nil
    /// What the agent typed, for Edit.
    public var typed: String
    public var quoted: Quoted? = nil
    /// The thread's server rows when it was sent: its own row is a NEW one.
    public var known: Set<String>
    /// The answer never came (timeout, dropped connection): checking the server.
    public var checking: Bool = false
    /// The last check has been made: an answer without its row settles it as failed.
    public var exhausted: Bool = false
    public var failed: Bool = false
    /// Sent again by the agent: a second failure keeps the bubble, never re-opens the box.
    public var retried: Bool = false
    /// Refused with a 401 (it never left): sent again as soon as the agent signs back in.
    public var authHeld: Bool = false

    public init(localId: String, convId: String, kind: OutKind, text: String, replyToId: String? = nil, origText: String? = nil, origLang: String? = nil,
                typed: String? = nil, quoted: Quoted? = nil, known: Set<String>, checking: Bool = false, exhausted: Bool = false, failed: Bool = false,
                retried: Bool = false, authHeld: Bool = false) {
        self.localId = localId; self.convId = convId; self.kind = kind; self.text = text; self.replyToId = replyToId; self.origText = origText
        self.origLang = origLang; self.typed = typed ?? text; self.quoted = quoted; self.known = known; self.checking = checking
        self.exhausted = exhausted; self.failed = failed; self.retried = retried; self.authHeld = authHeld
    }
}

/// Fetching an expired attachment back from Meta.
public enum Recovery: Equatable, Sendable {
    case found(url: String)
    /// Meta no longer has it.
    case gone
    /// Couldn't ask (no connection, server trouble): try again.
    case failed(why: String)
}

/// How a WhatsApp invite went.
public enum InviteResult: Equatable, Sendable {
    case sent
    /// Refused (not configured, a bad number, Meta said no) — open WhatsApp by hand instead.
    case refused
    /// No answer: the template may have gone — don't send it twice.
    case unknown(message: String)
}

/// The topmost inbox state back closes: the phone's full-screen thread, then
/// bulk selection, then the search, then the filter panel. Nil — a bare list —
/// lets the shell have it. The composer's text is never touched.
public enum InboxBack: Equatable, Sendable { case closeThread, exitSelect, clearSearch, closeFilters }

public func inboxBackStep(phoneThread: Bool, selectMode: Bool, searching: Bool, filtersOpen: Bool) -> InboxBack? {
    if phoneThread { return .closeThread }
    if selectMode { return .exitSelect }
    if searching { return .clearSearch }
    if filtersOpen { return .closeFilters }
    return nil
}

/// Parsed row timestamps, memoised: a regroup of 5,000 rows re-reads the same
/// few thousand ISO strings every time, and parsing them was most of its cost.
/// Bounded — cleared wholesale when it grows past a busy day's worth.
private final class RowMillisMemo: @unchecked Sendable {
    private let lock = NSLock()
    private var memo: [String: Int64] = [:]
    func millis(_ iso: String?) -> Int64 {
        guard let iso = iso else { return 0 }
        if let v = lock.sync({ memo[iso] }) { return v }
        let v = Fmt.millis(iso) ?? 0
        lock.sync {
            if memo.count > 20_000 { memo.removeAll(keepingCapacity: true) }
            memo[iso] = v
        }
        return v
    }
}

private let rowMillisMemo = RowMillisMemo()

public func rowMillis(_ iso: String?) -> Int64 { rowMillisMemo.millis(iso) }

extension Inbox {
    /// WhatsApp first (it can transact), then the social channels.
    public static let CHAN_ORDER = ["whatsapp", "messenger", "facebook", "instagram", "tiktok", "email", "sms"]

    /// The people the list shows, grouped and sorted (filteredConvs → groupedConvs):
    /// the current filter's server pages decide WHO is listed, these checks then
    /// show each person's qualifying threads, newest first (server order breaks
    /// ties, as the web's stable sort does). Linear in the rows plus one sort.
    public static func groupRows(_ s: InboxUi, me: String?) -> [RowGroup] {
        let f = s.filters
        if s.orderKey != filterKey(of: f) { return [] }
        var seen = Set<String>(minimumCapacity: s.orderIds.count * 2)
        var filtered: [Conversation] = []
        filtered.reserveCapacity(s.orderIds.count)
        for id in s.orderIds {
            if !seen.insert(id).inserted { continue }
            guard let c = s.cache[id] else { continue }
            var ok = (f.channel == "all" || c.channel == f.channel) &&
                (f.tag == nil || c.tags.contains(f.tag!)) &&
                (f.mode == "all" || c.interceptMode == f.mode)
            if ok {
                switch f.tab {
                case "unread": ok = c.unread > 0
                case "read": ok = c.unread <= 0
                case "human": ok = c.interceptMode == "human"
                // "Yours" — held by a human AND that human is me.
                case "yours": ok = c.interceptMode == "human" && c.assignedAgentId == me
                default: break
                }
            }
            if ok { filtered.append(c) }
        }
        // A stable sort, newest first (Swift's sort is not guaranteed stable, so the index breaks ties).
        let sorted = filtered.enumerated()
            .sorted { a, b in
                let ta = rowMillis(a.element.lastMessageAt ?? a.element.createdAt), tb = rowMillis(b.element.lastMessageAt ?? b.element.createdAt)
                if ta != tb { return ta > tb }
                return a.offset < b.offset
            }
            .map { $0.element }

        // Conversations sharing a person_id are the SAME customer across channels:
        // the newest is the row, the rest become channel chips on it.
        var repByPerson: [String: String] = [:]
        var siblings: [String: [Conversation]] = [:]
        var order: [Conversation] = []
        order.reserveCapacity(sorted.count)
        for c in sorted {
            guard let pid = c.personId else { order.append(c); siblings[c.id] = [c]; continue }
            if let repId = repByPerson[pid] {
                siblings[repId, default: []].append(c)
            } else {
                repByPerson[pid] = c.id; order.append(c); siblings[c.id] = [c]
            }
        }
        let chan = CHAN_ORDER
        func rank(_ ch: String) -> Int { chan.firstIndex(of: ch) ?? 99 }
        return order.map { rep in
            let l = siblings[rep.id] ?? [rep]
            let sibs = l.count == 1 ? l : l.enumerated().sorted { a, b in
                let ra = rank(a.element.channel), rb = rank(b.element.channel)
                return ra != rb ? ra < rb : a.offset < b.offset
            }.map { $0.element }
            return RowGroup(
                key: rep.personId ?? rep.id,
                rep: rep,
                siblings: sibs,
                unread: sibs.reduce(0) { $0 + $1.unread },
                lastAt: sibs.compactMap { $0.lastMessageAt }.max { rowMillis($0) < rowMillis($1) }
            )
        }
    }

    /// The customer's detected language — free, from translations cached on inbound rows.
    public static func threadLang(of t: ThreadUi) -> String? {
        t.messages[t.activeId]?.last { $0.inbound && $0.translatedFrom != nil }?.translatedFrom
    }

    /// Translate toggle: the agent's choice for this thread, else ON when the thread reads foreign.
    public static func txOn(_ t: ThreadUi, _ c: ComposerUi) -> Bool {
        !t.activeId.isEmpty && (c.txMode[t.activeId] ?? (threadLang(of: t) != nil))
    }

    /// A genuine WhatsApp thread — a web-chat visitor rides the "whatsapp" channel but is not one.
    public static func realWhatsApp(_ c: Conversation) -> Bool { c.channel == "whatsapp" && !isWebVisitor(c.waId) }

    /// The thread menu's "Invite to WhatsApp" shortcut follows CustomerSidebar:
    /// only for a person with a real 7–15-digit phone on their profile and no
    /// WhatsApp thread yet.
    public static func inviteTarget(_ reach: Reach?, _ convId: String) -> String? {
        guard let r = reach, r.convId == convId, !r.hasWhatsApp, let p = r.phone else { return nil }
        if isWebVisitor(p.trimmingCharacters(in: .whitespaces)) { return nil }
        let digits = p.filter { $0.isASCII && $0.isNumber }
        return (7...15).contains(digits.count) ? digits : nil
    }

    public static func channelLabel(_ ch: String?) -> String {
        switch ch {
        case "whatsapp": return "WhatsApp"
        case "messenger": return "Messenger"
        case "facebook": return "Facebook"
        case "instagram": return "Instagram"
        case "tiktok": return "TikTok"
        case "email": return "Email"
        case "sms": return "SMS"
        case nil: return ""
        case .some(let s): return s
        }
    }

    /// What a file is called when its type is not known.
    public static func guessMime(_ name: String) -> String {
        let ext = name.split(separator: ".").count > 1 ? String(name.split(separator: ".").last ?? "").lowercased() : ""
        switch ext {
        case "jpg", "jpeg": return "image/jpeg"
        case "png": return "image/png"
        case "webp": return "image/webp"
        case "gif": return "image/gif"
        case "heic", "heif": return "image/heic"
        case "pdf": return "application/pdf"
        case "doc": return "application/msword"
        case "docx": return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        case "xls": return "application/vnd.ms-excel"
        case "xlsx": return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        case "mp4": return "video/mp4"
        case "3gp": return "video/3gpp"
        case "mov": return "video/quicktime"
        case "hevc": return "video/hevc"
        case "m4v": return "video/x-m4v"
        case "ogg", "opus": return "audio/ogg"
        case "aac": return "audio/aac"
        case "mp3": return "audio/mpeg"
        default: return "application/octet-stream"
        }
    }
}

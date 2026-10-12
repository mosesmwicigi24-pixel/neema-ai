import Foundation

/// One entry in the bell (components/ui/Notifications.tsx), persisted — last 60.
public struct AppNotification: Codable, Equatable, Sendable, Identifiable {
    public var id: String
    /// One of the 13 types the backend sends (see LiveSocket), or the web's legacy names.
    public var type: String
    public var title: String
    public var body: String
    public var convKey: String?
    public var at: Int64
    public var read: Bool
    public init(id: String, type: String, title: String, body: String, convKey: String? = nil, at: Int64, read: Bool = false) {
        self.id = id; self.type = type; self.title = title; self.body = body; self.convKey = convKey; self.at = at; self.read = read
    }
}

/// How urgently a system notification interrupts (Android's NotificationCompat priorities;
/// iOS maps them to interruption levels).
public enum AlertPriority: String, Equatable, Sendable { case high, normal, low }

/// One system notification the notification centre wants shown — plain data,
/// so what is posted (channel, text, tap target, grouping) is tested without
/// the system's notification service. Android `core/notify/Notifier.kt`.
public struct SystemAlert: Equatable, Sendable {
    /// The notification id: one per conversation, so a thread's alerts replace each other.
    public let id: Int
    public let channel: String
    public let title: String
    public let body: String
    public let priority: AlertPriority
    /// Tap opens this conversation (wa_id / external_id / conversation id).
    public let convKey: String?
    /// …or this view (a web `?view=` name).
    public let view: String?
    /// The bell entry, marked read when the notification is tapped.
    public let notificationId: String?
    public init(id: Int, channel: String, title: String, body: String, priority: AlertPriority, convKey: String? = nil, view: String? = nil, notificationId: String? = nil) {
        self.id = id; self.channel = channel; self.title = title; self.body = body; self.priority = priority
        self.convKey = convKey; self.view = view; self.notificationId = notificationId
    }
}

/// Where the notification centre sends system notifications; a recorder in tests.
public protocol AlertSink: AnyObject {
    /// False when the system won't show them (permission denied, or switched off).
    func canPost() -> Bool
    func post(_ alert: SystemAlert)
    func cancel(_ id: Int)
    /// Ids of our notifications still showing (the agent may have swiped some away); nil if unknown.
    func active() -> Set<Int>?
    /// The group's summary row ("3 Neema alerts") once two or more are showing.
    func summary(count: Int, lines: [String])
    func cancelSummary()
}

public extension AlertSink {
    func active() -> Set<Int>? { nil }
}

/// The notification channels (Android's) — on iOS the categories the alerts carry.
public enum Notifier {
    public static let CH_ALERTS = "neema_alerts_v2"
    public static let CH_MESSAGES = "neema_messages_v2"
    public static let CH_UPDATES = "neema_updates"
    public static let CH_CALLS = "neema_calls_v2"
    public static let CH_LIVE = "neema_live"
    /// Every bell alert shares one group, so a burst stacks under one summary.
    public static let GROUP_ALERTS = "ke.co.bethanyhouse.neema.ALERTS"
    public static let SUMMARY_ID = 1002
}

/// Listens for `{"event":"notification", …}` frames (useAgentNotifications),
/// keeps the bell's list, and raises a system notification when the app isn't
/// in front — the web's `new Notification(...)` when permission is granted.
/// Android `core/notify/NotificationCenter.kt` (named for the web's hook here:
/// Foundation already has a NotificationCenter).
@MainActor
public final class AgentNotifications {
    nonisolated public static let REPEAT_WINDOW_MS: Int64 = 3_000
    /// The bell keeps the last 60 (Notifications.tsx slices to 60).
    nonisolated public static let MAX_ITEMS = 60
    nonisolated static let STORE_KEY = "neema_notifications.items"

    private let events: Signal<JSONValue>
    private let appPrefs: AppPrefs
    private let store: KeyValueStore
    private let sink: AlertSink
    private var seq: Int64 = 0
    private var subs: [Subscription] = []
    private var foreground: Watched<Bool>?

    public let items: Watched<[AppNotification]>
    /// Every notification as it lands (the shell toasts it and refetches).
    public let incoming = Signal<AppNotification>(buffer: 16)

    public var unread: Int { items.value.filter { !$0.read }.count }

    /// System notifications currently showing, oldest first: system id → bell entry.
    private var tray: [(id: Int, n: AppNotification)] = []
    /// The last few frames, to drop an exact repeat (a double publish, a replaced socket draining).
    private var recent: [(key: String, at: Int64)] = []
    private var writeQueued = false

    public init(events: Signal<JSONValue>, appPrefs: AppPrefs, store: KeyValueStore, sink: AlertSink) {
        self.events = events; self.appPrefs = appPrefs; self.store = store; self.sink = sink
        items = Watched(Self.load(store))
    }

    private static func load(_ store: KeyValueStore) -> [AppNotification] {
        guard let text = store.string(STORE_KEY) else { return [] }
        return (try? NeemaJSON.decode([AppNotification].self, from: text)) ?? []
    }

    /// The bell updates at once; the disk copy follows, one write for however
    /// many changes landed before it ran (a burst of frames costs one encode).
    private func save(_ list: [AppNotification]) {
        items.value = list
        if writeQueued { return }
        writeQueued = true
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            self.writeQueued = false
            if let data = try? JSONEncoder().encode(self.items.value), let text = String(data: data, encoding: .utf8) {
                self.store.set(text, for: Self.STORE_KEY)
            }
        }
    }

    public func start(foreground: Watched<Bool>) {
        self.foreground = foreground
        subs.append(events.observe { [weak self] e in
            onMain { self?.onFrame(e) }
        })
    }

    public func stop() {
        for s in subs { s.cancel() }
        subs.removeAll()
    }

    private func onFrame(_ e: JSONValue) {
        if e.str("event") != "notification" { return }
        let n = fromFrame(e)
        if isRepeat(n) { return }
        save(Array(([n] + items.value).prefix(Self.MAX_ITEMS)))
        incoming.emit(n)
        // In front, the toast and the bell are the alert: no second, duplicate one in the tray.
        if foreground?.value != true, let a = Self.alertFor(n, prefs: appPrefs.raw) { raise(a) }
    }

    private func isRepeat(_ n: AppNotification) -> Bool {
        let key = [n.type, n.title, n.body, n.convKey ?? ""].joined(separator: "|")
        let now = AppClock.now()
        while let first = recent.first, now - first.at > Self.REPEAT_WINDOW_MS { recent.removeFirst() }
        if recent.contains(where: { $0.key == key }) { return true }
        recent.append((key, now))
        if recent.count > 32 { recent.removeFirst() }
        return false
    }

    private func raise(_ a: SystemAlert) {
        // Denied (or switched off): the bell and the toast still have it, and nothing here ever asks again.
        if !sink.canPost() { return }
        guard let n = items.value.first(where: { $0.id == a.notificationId }) else { return }
        if let live = sink.active() { tray.removeAll { !live.contains($0.id) } }
        tray.removeAll { $0.id == a.id }
        tray.append((a.id, n))
        // Where the system can't list what is still shown, forget the oldest: the bell itself only keeps the last MAX_ITEMS.
        while tray.count > Self.MAX_ITEMS { tray.removeFirst() }
        sink.post(a)
        refreshSummary()
    }

    private func refreshSummary() {
        let shown = tray.map { $0.n }
        if shown.count >= 2 { sink.summary(count: shown.count, lines: shown.reversed().map { Self.summaryLine($0) }) }
        else if shown.isEmpty { sink.cancelSummary() }
    }

    /// The bell read/removed `ids`: take their system notifications out of the tray too.
    private func withdraw(_ ids: Set<String>) {
        let gone = tray.filter { ids.contains($0.n.id) }.map { $0.id }
        if gone.isEmpty { return }
        tray.removeAll { ids.contains($0.n.id) }
        for id in gone { sink.cancel(id) }
        refreshSummary()
    }

    private func fromFrame(_ e: JSONValue) -> AppNotification {
        seq += 1
        return AppNotification(
            // Unique even for a burst in one millisecond (the list keys on it).
            id: "\(AppClock.now())-\(seq)-\(Int.random(in: 0...9999))",
            type: e.str("type") ?? "system",
            title: e.str("title") ?? "Neema",
            body: e.str("body") ?? "",
            convKey: e.str("conversationId") ?? e.str("conv_id") ?? e.str("convId") ?? e.str("wa_id") ?? e.str("waId"),
            // The frame's own `ts` (AgentNotification.ts) when it carries one, else arrival time.
            at: Fmt.millis(e.str("ts")).flatMap { $0 > 0 ? $0 : nil } ?? AppClock.now()
        )
    }

    public func markAllRead() {
        save(items.value.map { var n = $0; n.read = true; return n })
        withdraw(Set(items.value.map { $0.id }))
    }
    public func markRead(_ id: String) {
        save(items.value.map { var n = $0; if n.id == id { n.read = true }; return n })
        withdraw([id])
    }
    /// The x on one row.
    public func dismiss(_ id: String) {
        save(items.value.filter { $0.id != id })
        withdraw([id])
    }
    /// Clear all (also on sign-out): the tray empties with the bell.
    public func clear() {
        let ids = Set(items.value.map { $0.id })
        save([])
        withdraw(ids)
        tray.removeAll()
        sink.cancelSummary()
    }

    nonisolated private static func summaryLine(_ n: AppNotification) -> String {
        n.body.trimmingCharacters(in: .whitespaces).isEmpty ? n.title : "\(n.title) — \(n.body)"
    }

    /// The phone notification for `n`, or nil when the agent's switches
    /// (Profile → Notifications, keys "notif_<name>", defaults as there)
    /// silence it. The switches only gate the phone notification; the bell
    /// and toast still record everything.
    ///
    /// Every type the backend sends, by urgency: Alerts (high) — someone must
    /// act: `new_conversation`, `human_transfer`, `media_escalation`,
    /// `intercept`, `transfer`, `take_back`, `availability_check`,
    /// `draft_ready`, `planned_action`, `hub_event`, `order_update`; Customer
    /// messages (normal) — `new_message`; Team updates (low) — `system`,
    /// `standup`, `daily_summary`, `selfcheck`, anything new.
    ///
    /// Tap: the conversation when the frame names one; order updates (and a
    /// hub event with no matching thread) open Orders; the rest open the app.
    /// One notification per conversation: a thread's newer alert replaces its
    /// older one instead of stacking a second row.
    nonisolated public static func alertFor(_ n: AppNotification, prefs: KeyValueStore) -> SystemAlert? {
        let on: Bool
        switch n.type {
        case "new_conversation", "new_message": on = prefs.bool("notif_new_conv", default: true)
        case "human_transfer", "transfer", "media_escalation": on = prefs.bool("notif_human_transfer", default: true)
        case "order_update": on = prefs.bool("notif_order_updates", default: false)
        case "daily_summary", "standup": on = prefs.bool("notif_daily_summary", default: true)
        default: on = true
        }
        if !on { return nil }
        let channel: String
        let priority: AlertPriority
        switch n.type {
        case "new_conversation", "human_transfer", "media_escalation", "intercept", "transfer", "take_back",
             "availability_check", "draft_ready", "planned_action", "hub_event", "order_update", "order":
            channel = Notifier.CH_ALERTS; priority = .high
        case "new_message": channel = Notifier.CH_MESSAGES; priority = .normal
        default: channel = Notifier.CH_UPDATES; priority = .low
        }
        return SystemAlert(id: systemId(n), channel: channel, title: n.title, body: n.body, priority: priority,
                           convKey: n.convKey, view: viewFor(n), notificationId: n.id)
    }

    /// Where tapping `n` (in the bell or the tray) goes when it names no conversation.
    nonisolated public static func viewFor(_ n: AppNotification) -> String? {
        if n.convKey != nil { return nil }
        if n.type == "order_update" || n.type == "order" || n.type == "hub_event" { return "orders" }
        return nil
    }

    /// Stable per conversation, else per entry; clear of the live (1001), summary (1002) and call ids.
    nonisolated public static func systemId(_ n: AppNotification) -> Int {
        let key = n.convKey.map { "conv:\($0)" } ?? n.id
        return 10_000 + Int(javaHash(key) & 0x7fff_ffff) % 1_000_000_000
    }

    /// `String.hashCode()` (the ids stay what Android's are for the same keys).
    nonisolated static func javaHash(_ s: String) -> Int32 {
        var h: Int32 = 0
        for u in s.utf16 { h = h &* 31 &+ Int32(u) }
        return h
    }

    /// The bell's five looks (Notifications.tsx META). The web keys them on
    /// intercept / new_message / order / transfer / system only; every type
    /// the backend actually sends is folded into the nearest one here.
    nonisolated public static func kindOf(_ type: String) -> String {
        switch type {
        case "intercept", "human_transfer", "media_escalation", "take_back", "availability_check": return "intercept"
        case "new_message", "new_conversation", "draft_ready": return "new_message"
        case "order", "order_update", "hub_event": return "order"
        case "transfer": return "transfer"
        default: return "system"
        }
    }
}

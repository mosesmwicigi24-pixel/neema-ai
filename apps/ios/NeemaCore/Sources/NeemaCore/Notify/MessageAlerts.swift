import Foundation

/// A customer's message that just landed in a thread, as the phone announces it.
public struct InboundPing: Equatable, Sendable {
    public let conversationId: String
    public let waId: String?
    /// "WhatsApp", "Messenger", "Instagram", "Facebook", "SMS"…
    public let app: String
    /// The words, or "📷 Photo" / "🎤 Voice message" for media.
    public let preview: String
    public init(conversationId: String, waId: String?, app: String, preview: String) {
        self.conversationId = conversationId; self.waId = waId; self.app = app; self.preview = preview
    }
}

/// The customer's own message in a conversation frame (`new_message`, or the
/// older `message` shape): `sender: "user"` or `direction: "inbound"`. The
/// agent-level `event: "notification"` frames, our own replies, the AI's and
/// a colleague's are not — they never beep. Android `core/notify/MessageAlerts.kt`.
public func inboundPingOf(_ e: JSONValue) -> InboundPing? {
    if e.str("event") == "notification" { return nil }
    let type = e.str("type")
    if type != "new_message" && type != "message" { return nil }
    let inbound = e.str("sender") == "user" || e.str("direction") == "inbound"
    if !inbound { return nil }
    guard let conv = e.str("conversationId"), !conv.trimmingCharacters(in: .whitespaces).isEmpty else { return nil }
    let text = (e.str("text") ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    var preview = text
    if preview.isEmpty {
        switch e.str("mediaType") {
        case "image", "sticker": preview = "📷 Photo"
        case "audio", "voice": preview = "🎤 Voice message"
        case "video": preview = "🎥 Video"
        case "document", "file": preview = "📄 Document"
        case "location": preview = "📍 Location"
        default: preview = "New message"
        }
    }
    let wa = e.str("waId").flatMap { $0.trimmingCharacters(in: .whitespaces).isEmpty ? nil : $0 }
    return InboundPing(conversationId: conv, waId: wa, app: appName(e.str("channel")), preview: preview)
}

public func appName(_ channel: String?) -> String {
    switch channel?.lowercased() {
    case nil, "", "whatsapp", "wa": return "WhatsApp"
    case "messenger": return "Messenger"
    case "instagram", "ig": return "Instagram"
    case "facebook", "fb": return "Facebook"
    case "sms": return "SMS"
    case "web", "web_chat", "webchat": return "Website chat"
    case "tiktok": return "TikTok"
    default: return channel!.prefix(1).uppercased() + channel!.dropFirst()
    }
}

/// Customer names the app has seen (every inbox page, every thread opened), so
/// a message notification says who wrote — a conversation frame carries only
/// ids. Kept for the life of the process; the last `MAX` are enough.
public final class ContactNames: @unchecked Sendable {
    public static let shared = ContactNames()
    nonisolated static let MAX = 2_000
    private let lock = NSLock()
    private var names: [String: String] = [:]
    private var order: [String] = []

    private func put(_ key: String, _ name: String) {
        if names[key] == nil { order.append(key) } else if let i = order.firstIndex(of: key) { order.remove(at: i); order.append(key) }
        names[key] = name
        while order.count > Self.MAX { names[order.removeFirst()] = nil }
    }

    public func learn(_ conversations: [Conversation]) {
        lock.sync {
            for c in conversations {
                guard let n = c.name?.trimmingCharacters(in: .whitespacesAndNewlines), !n.isEmpty else { continue }
                put(c.id, n)
                if let w = c.waId { put(w, n) }
                if let x = c.externalId { put(x, n) }
            }
        }
    }

    public func learn(_ c: Conversation) { learn([c]) }

    public func nameFor(conversationId: String?, handle: String?) -> String? {
        lock.sync {
            if let c = conversationId, let n = names[c] { return n }
            if let h = handle, let n = names[h] { return n }
            return nil
        }
    }

    public func clear() { lock.sync { names.removeAll(); order.removeAll() } }
}

/// One beep for a burst: a photo album, or a new chat's alert and its first
/// message arriving together, sound once — not a machine-gun of pings.
public final class AlertGate: @unchecked Sendable {
    private let quietMs: Int64
    private var last: Int64 = Int64.min / 2
    private let lock = NSLock()
    public init(quietMs: Int64 = 2_000) { self.quietMs = quietMs }
    public func claim(_ now: Int64) -> Bool {
        lock.sync {
            if now - last < quietMs { return false }
            last = now
            return true
        }
    }
}

/// Plays a message alert: the phone's notification sound and/or a short buzz.
public protocol AlertPlayer: AnyObject {
    func play(sound: Bool, vibrate: Bool)
}

/// The phone's ringer switch, as Android reports it (iOS has no API for its
/// silent switch — the system applies it to the sound itself).
public enum RingerMode: Equatable, Sendable { case normal, vibrate, silent }

/// What the phone does for one alert, given the ringer switch and Do Not
/// Disturb: silent mode is silent (no buzz either), vibrate mode only buzzes,
/// and Do Not Disturb is respected for messages (calls follow the system).
public func ringerPlan(sound: Bool, vibrate: Bool, ringerMode: RingerMode, dnd: Bool) -> (sound: Bool, vibrate: Bool) {
    if dnd || ringerMode == .silent { return (false, false) }
    if ringerMode == .vibrate { return (false, vibrate) }
    return (sound, vibrate)
}

/// Every customer message makes a sound. Open or not, a message from a
/// customer beeps and buzzes (per Profile → Sounds & vibration, and not while
/// muted); with the app in the background it also shows in the tray, one row
/// per customer, tapping into their chat. Alerts that already raise their own
/// notification (a new chat, a transfer, an escalation) beep the same way.
@MainActor
public final class MessageAlerts {
    private let events: Signal<JSONValue>
    private let notifications: AgentNotifications
    private let prefs: AppPrefs
    private let sink: AlertSink
    private let player: AlertPlayer
    private let gate: AlertGate
    private let now: () -> Int64
    private var subs: [Subscription] = []
    /// Message rows this posted and hasn't cleared.
    private var posted: Set<Int> = []

    public init(events: Signal<JSONValue>, notifications: AgentNotifications, prefs: AppPrefs, sink: AlertSink, player: AlertPlayer,
                gate: AlertGate = AlertGate(), now: @escaping () -> Int64 = { AppClock.now() }) {
        self.events = events; self.notifications = notifications; self.prefs = prefs; self.sink = sink; self.player = player
        self.gate = gate; self.now = now
    }

    public func start(foreground: Watched<Bool>) {
        subs.append(events.observe { [weak self] e in
            guard let p = inboundPingOf(e) else { return }
            onMain { self?.onInbound(p, foreground: foreground.value) }
        })
        subs.append(notifications.incoming.observe { [weak self] n in onMain { self?.onNotification(n) } })
        // Back in the app: the message rows have done their job (the inbox
        // shows the unread), as a messaging app clears its tray on open.
        subs.append(foreground.observe { [weak self] fg in if fg { onMain { self?.clearTray() } } })
    }

    public func stop() {
        for s in subs { s.cancel() }
        subs.removeAll()
    }

    func clearTray() {
        let ids = posted
        posted.removeAll()
        for id in ids { sink.cancel(id) }
    }

    /// A customer wrote. The "New conversations" switch (Profile) turns message alerts off entirely.
    func onInbound(_ p: InboundPing, foreground: Bool) {
        if !prefs.raw.bool("notif_new_conv", default: true) { return }
        if !foreground && sink.canPost() {
            let a = Self.messageAlert(p)
            posted.insert(a.id)
            sink.post(a)
        }
        beep()
    }

    /// A bell alert landed: the ones that raise a phone notification beep too (not team updates).
    func onNotification(_ n: AppNotification) {
        guard let a = AgentNotifications.alertFor(n, prefs: prefs.raw) else { return }
        if a.channel == Notifier.CH_UPDATES { return }
        beep()
    }

    private func beep() {
        let t = now()
        let s = prefs.alerts.value
        let sound = s.messageSoundAt(t)
        let buzz = s.messageVibrateAt(t)
        if (sound || buzz) && gate.claim(t) { player.play(sound: sound, vibrate: buzz) }
    }

    /// The tray row for `p`: one per customer (keyed like a new chat's alert, so the two merge).
    nonisolated public static func messageAlert(_ p: InboundPing) -> SystemAlert {
        let known = ContactNames.shared.nameFor(conversationId: p.conversationId, handle: p.waId)
        let phone = p.waId.flatMap { w -> String? in let f = Fmt.formatPhone(w); return f.isEmpty ? nil : f }
        let who = known ?? phone ?? "\(p.app) customer"
        let key = p.waId ?? p.conversationId
        return SystemAlert(
            id: AgentNotifications.systemId(AppNotification(id: key, type: "new_message", title: "", body: "", convKey: key, at: 0)),
            channel: Notifier.CH_MESSAGES,
            title: p.app == "WhatsApp" ? who : "\(who) · \(p.app)",
            body: p.preview,
            priority: .high,
            convKey: p.conversationId
        )
    }
}

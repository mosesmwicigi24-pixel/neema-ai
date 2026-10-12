import Foundation

/// Where small preferences live: `UserDefaults` on a device, a dictionary in tests.
public protocol KeyValueStore: AnyObject {
    func string(_ key: String) -> String?
    func set(_ value: String?, for key: String)
    func bool(_ key: String, default def: Bool) -> Bool
    func set(_ value: Bool, for key: String)
    func int64(_ key: String) -> Int64?
    func set(_ value: Int64, for key: String)
}

/// A working in-memory store (Android's test `MemoryPrefs`).
public final class MemoryPrefs: KeyValueStore, @unchecked Sendable {
    private let lock = NSLock()
    private var map: [String: Any] = [:]
    public init() {}
    public func string(_ key: String) -> String? { lock.sync { map[key] as? String } }
    public func set(_ value: String?, for key: String) { lock.sync { if let v = value { map[key] = v } else { map[key] = nil } } }
    public func bool(_ key: String, default def: Bool) -> Bool { lock.sync { map[key] as? Bool ?? def } }
    public func set(_ value: Bool, for key: String) { lock.sync { map[key] = value } }
    public func int64(_ key: String) -> Int64? { lock.sync { map[key] as? Int64 } }
    public func set(_ value: Int64, for key: String) { lock.sync { map[key] = value } }
    public var all: [String: Any] { lock.sync { map } }
}

extension UserDefaults: KeyValueStore {
    public func string(_ key: String) -> String? { string(forKey: key) }
    public func set(_ value: String?, for key: String) { if let v = value { set(v, forKey: key) } else { removeObject(forKey: key) } }
    public func bool(_ key: String, default def: Bool) -> Bool { object(forKey: key) == nil ? def : bool(forKey: key) }
    public func set(_ value: Bool, for key: String) { set(value, forKey: key) }
    public func int64(_ key: String) -> Int64? { object(forKey: key) == nil ? nil : Int64(integer(forKey: key)) }
    public func set(_ value: Int64, for key: String) { set(Int(clamping: value), forKey: key) }
}

/// How Neema sounds on this device (Profile → Sounds & vibration).
///
/// Mute silences messages and alerts — they still arrive, in the bell and the
/// tray — for an hour, eight hours, or until turned back on. Calls have their
/// own switches and are never silenced by mute: a missed customer is costly.
public struct AlertSettings: Equatable, Sendable {
    public var messageSound: Bool
    public var messageVibrate: Bool
    public var callRing: Bool
    public var callVibrate: Bool
    /// Messages are silent until this time (epoch ms): 0 = not muted, `FOREVER` = until turned back on.
    public var mutedUntil: Int64

    public static let FOREVER = Int64.max

    public init(messageSound: Bool = true, messageVibrate: Bool = true, callRing: Bool = true, callVibrate: Bool = true, mutedUntil: Int64 = 0) {
        self.messageSound = messageSound; self.messageVibrate = messageVibrate
        self.callRing = callRing; self.callVibrate = callVibrate; self.mutedUntil = mutedUntil
    }

    public func muted(_ now: Int64) -> Bool { mutedUntil > now }
    /// A message landing at `now` beeps.
    public func messageSoundAt(_ now: Int64) -> Bool { messageSound && !muted(now) }
    /// A message landing at `now` vibrates.
    public func messageVibrateAt(_ now: Int64) -> Bool { messageVibrate && !muted(now) }
}

/// Small device-level preferences (not secrets) — Android's `AppPrefs`.
public final class AppPrefs: @unchecked Sendable {
    public let raw: KeyValueStore
    public let dark: Watched<Bool>
    /// Keep the live connection (and notifications/incoming calls) running in the background.
    public let backgroundLive: Watched<Bool>
    public let alerts: Watched<AlertSettings>

    public init(store: KeyValueStore = MemoryPrefs()) {
        raw = store
        dark = Watched(store.string("theme") == "dark")
        backgroundLive = Watched(store.bool("background_live", default: true))
        alerts = Watched(AlertSettings(
            messageSound: store.bool("alert_message_sound", default: true),
            messageVibrate: store.bool("alert_message_vibrate", default: true),
            callRing: store.bool("alert_call_ring", default: true),
            callVibrate: store.bool("alert_call_vibrate", default: true),
            mutedUntil: store.int64("alert_muted_until") ?? 0
        ))
    }

    public func setDark(_ v: Bool) {
        dark.update(v)
        raw.set(v ? "dark" : "light", for: "theme")
    }

    public func setBackgroundLive(_ v: Bool) {
        backgroundLive.update(v)
        raw.set(v, for: "background_live")
    }

    public func setAlerts(_ next: AlertSettings) {
        alerts.update(next)
        raw.set(next.messageSound, for: "alert_message_sound")
        raw.set(next.messageVibrate, for: "alert_message_vibrate")
        raw.set(next.callRing, for: "alert_call_ring")
        raw.set(next.callVibrate, for: "alert_call_vibrate")
        raw.set(next.mutedUntil, for: "alert_muted_until")
    }

    /// Mute messages for `ms` from `now`; nil = until turned back on.
    public func muteFor(_ ms: Int64?, now: Int64 = AppClock.now()) {
        var a = alerts.value
        a.mutedUntil = ms.map { now + $0 } ?? AlertSettings.FOREVER
        setAlerts(a)
    }

    public func unmute() {
        var a = alerts.value
        a.mutedUntil = 0
        setAlerts(a)
    }

    /// The notification prompt is asked once, after the first sign-in.
    public var askedNotifications: Bool {
        get { raw.bool("asked_post_notifications", default: false) }
        set { raw.set(newValue, for: "asked_post_notifications") }
    }
}

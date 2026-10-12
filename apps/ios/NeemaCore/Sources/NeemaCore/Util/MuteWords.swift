import Foundation

/// Profile → Sounds & vibration: how long to mute messages for (nil = until turned back on).
public let MUTE_CHOICES: [(label: String, ms: Int64?)] = [
    ("1 hour", 3_600_000),
    ("8 hours", 8 * 3_600_000),
    ("Until I turn it back on", nil),
]

/// What the Profile screen says while messages are muted — "Muted until 3:40 PM",
/// "Muted until tomorrow, 3:40 PM", "Muted until Wed 15 Oct, 3:40 PM", or
/// "Muted until you turn it back on" — and nil when they are not.
public func muteStatus(until: Int64, now: Int64, zone: TimeZone = Fmt.timeZone) -> String? {
    if until <= now { return nil }
    if until == AlertSettings.FOREVER { return "Muted until you turn it back on" }
    var cal = Calendar(identifier: .gregorian)
    cal.timeZone = zone
    let at = Date(timeIntervalSince1970: Double(until) / 1000)
    let today = cal.startOfDay(for: Date(timeIntervalSince1970: Double(now) / 1000))
    let day = cal.startOfDay(for: at)
    let time = muteFormatter("h:mm a", zone).string(from: at)
    if day == today { return "Muted until \(time)" }
    if let tomorrow = cal.date(byAdding: .day, value: 1, to: today), day == tomorrow { return "Muted until tomorrow, \(time)" }
    return "Muted until \(muteFormatter("EEE d MMM", zone).string(from: at)), \(time)"
}

private func muteFormatter(_ pattern: String, _ zone: TimeZone) -> DateFormatter {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_US_POSIX")
    f.timeZone = zone
    f.dateFormat = pattern
    return f
}

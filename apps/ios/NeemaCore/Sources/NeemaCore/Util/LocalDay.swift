import Foundation

/// A calendar date (java.time.LocalDate): the day a timestamp falls on in a
/// time zone, with the day arithmetic the reports need. Comparable by date.
public struct LocalDay: Equatable, Hashable, Sendable, Comparable, CustomStringConvertible {
    public let year: Int
    public let month: Int
    public let day: Int

    public init(_ year: Int, _ month: Int, _ day: Int) { self.year = year; self.month = month; self.day = day }

    /// Day arithmetic and weekdays are zone-free: every date is a UTC midnight.
    private static let utc: Calendar = {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "UTC")!
        return c
    }()

    private static func calendar(_ zone: TimeZone) -> Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = zone
        return c
    }

    /// The day `millis` falls on in `zone`.
    public static func of(millis: Int64, zone: TimeZone) -> LocalDay {
        let d = Date(timeIntervalSince1970: TimeInterval(millis) / 1000)
        let c = calendar(zone).dateComponents([.year, .month, .day], from: d)
        return LocalDay(c.year ?? 1970, c.month ?? 1, c.day ?? 1)
    }

    /// The day an API timestamp falls on in `zone`; nil when it isn't a date.
    public static func of(_ iso: String?, zone: TimeZone) -> LocalDay? { Fmt.millis(iso).map { of(millis: $0, zone: zone) } }

    public static func today(zone: TimeZone, now: Int64 = AppClock.now()) -> LocalDay { of(millis: now, zone: zone) }

    /// "2026-09-25" (LocalDate.toString / parse).
    public static func parse(_ s: String) -> LocalDay? {
        let parts = s.split(separator: "-")
        guard parts.count == 3, let y = Int(parts[0]), let m = Int(parts[1]), let d = Int(parts[2]), (1...12).contains(m), (1...31).contains(d) else { return nil }
        var c = DateComponents(); c.year = y; c.month = m; c.day = d
        guard let date = utc.date(from: c) else { return nil }
        let back = utc.dateComponents([.year, .month, .day], from: date)
        guard back.year == y, back.month == m, back.day == d else { return nil }
        return LocalDay(y, m, d)
    }

    public var description: String { String(format: "%04d-%02d-%02d", year, month, day) }

    private var utcDate: Date {
        var c = DateComponents(); c.year = year; c.month = month; c.day = day
        return Self.utc.date(from: c) ?? Date(timeIntervalSince1970: 0)
    }

    public func plusDays(_ n: Int) -> LocalDay {
        let d = Self.utc.date(byAdding: .day, value: n, to: utcDate) ?? utcDate
        let c = Self.utc.dateComponents([.year, .month, .day], from: d)
        return LocalDay(c.year ?? year, c.month ?? month, c.day ?? day)
    }

    public func minusDays(_ n: Int) -> LocalDay { plusDays(-n) }

    /// java's `plusMonths`: the same day `n` months on, clamped to that month's last day (31 Jan + 1 = 28 Feb).
    public func plusMonths(_ n: Int) -> LocalDay {
        let d = Self.utc.date(byAdding: .month, value: n, to: utcDate) ?? utcDate
        let c = Self.utc.dateComponents([.year, .month, .day], from: d)
        return LocalDay(c.year ?? year, c.month ?? month, c.day ?? day)
    }

    /// Whole days from `other` to this day (negative when this day is earlier).
    public func daysSince(_ other: LocalDay) -> Int {
        Self.utc.dateComponents([.day], from: other.utcDate, to: utcDate).day ?? 0
    }

    /// "Mon" … "Sun" (java's DayOfWeek short English names).
    public var weekdayShort: String {
        let names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        let w = Self.utc.component(.weekday, from: utcDate)
        return names[max(1, min(7, w)) - 1]
    }

    /// The first instant of this day in `zone`, in epoch millis.
    public func startMillis(zone: TimeZone) -> Int64 {
        var c = DateComponents(); c.year = year; c.month = month; c.day = day
        let d = Self.calendar(zone).date(from: c) ?? utcDate
        return Int64(d.timeIntervalSince1970 * 1000)
    }

    public static func < (a: LocalDay, b: LocalDay) -> Bool {
        if a.year != b.year { return a.year < b.year }
        if a.month != b.month { return a.month < b.month }
        return a.day < b.day
    }
}

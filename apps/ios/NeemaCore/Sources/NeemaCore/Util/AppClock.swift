import Foundation

/// The app's one source of "now". Production reads the system clock; tests
/// shift it to a pinned date (it still ticks, so timeouts and dedupe windows
/// behave) so rendered dates like "Joined 9 Mar 2026" never drift day to day.
public enum AppClock {
    private static let lock = NSLock()
    private static var offsetMillis: Int64 = 0

    /// Epoch milliseconds.
    public static func now() -> Int64 {
        lock.lock(); defer { lock.unlock() }
        return Int64((Date().timeIntervalSince1970 * 1000).rounded(.down)) + offsetMillis
    }

    public static func date() -> Date { Date(timeIntervalSince1970: TimeInterval(now()) / 1000) }

    /// Tests only: make `now` read `pinned` at this moment (and advance from there).
    public static func pin(to pinned: Date) {
        lock.lock(); defer { lock.unlock() }
        offsetMillis = Int64((pinned.timeIntervalSince1970 * 1000).rounded(.down)) - Int64((Date().timeIntervalSince1970 * 1000).rounded(.down))
    }

    public static func reset() { lock.lock(); offsetMillis = 0; lock.unlock() }
}

import XCTest
@testable import NeemaCore

/// lib/utils.ts ports: dates, money, names and phones read the same on every platform.
final class FmtTests: XCTestCase {
    override func setUp() {
        AppClock.pin(to: PINNED)
        Fmt.timeZone = TimeZone(identifier: "Africa/Nairobi")!
    }

    override func tearDown() {
        AppClock.reset()
        Fmt.timeZone = .current
    }

    func testMillisReadsEveryShapeTheApiSends() {
        XCTAssertEqual(1_790_326_800_000, Fmt.millis("2026-09-25T09:00:00Z"))
        XCTAssertEqual(1_790_326_800_000, Fmt.millis("2026-09-25T09:00:00+00:00"))
        XCTAssertEqual(1_790_326_800_000, Fmt.millis("2026-09-25T12:00:00+03:00"))
        XCTAssertEqual(1_790_326_800_000, Fmt.millis("2026-09-25T09:00:00"), "naive timestamps are UTC")
        XCTAssertEqual(1_790_326_800_000, Fmt.millis("2026-09-25 09:00:00"), "SQL style is ISO with a space")
        XCTAssertEqual(1_790_326_800_123, Fmt.millis("2026-09-25T09:00:00.123456Z"))
        XCTAssertEqual(1_790_283_600_000, Fmt.millis("2026-09-25"), "a bare date is local midnight (Nairobi, +3)")
        XCTAssertEqual(1_790_283_600_000, Fmt.millis("2026-09-25junk"))
        XCTAssertNil(Fmt.millis(nil))
        XCTAssertNil(Fmt.millis(""))
        XCTAssertNil(Fmt.millis("yesterday"))
    }

    func testTimeAgo() {
        let now = AppClock.now()
        XCTAssertEqual("—", Fmt.timeAgo(nil, now: now))
        XCTAssertEqual("—", Fmt.timeAgo("1970-01-01T00:00:00Z", now: now))
        XCTAssertEqual("just now", Fmt.timeAgo("2026-09-25T09:00:05Z", now: now))
        XCTAssertEqual("30s ago", Fmt.timeAgo("2026-09-25T08:59:30Z", now: now))
        XCTAssertEqual("5m ago", Fmt.timeAgo("2026-09-25T08:55:00Z", now: now))
        XCTAssertEqual("3h ago", Fmt.timeAgo("2026-09-25T06:00:00Z", now: now))
        XCTAssertEqual("2d ago", Fmt.timeAgo("2026-09-23T09:00:00Z", now: now))
    }

    func testInitialsKeepWholeGraphemes() {
        XCTAssertEqual("MN", Fmt.initials("Mary Njeri"))
        XCTAssertEqual("M🌸", Fmt.initials("Mama 🌸 Njeri"))
        XCTAssertEqual("👩🏽‍💻K", Fmt.initials("👩🏽‍💻 Kamau"))
        XCTAssertEqual("🇰🇪", Fmt.initials("🇰🇪"))
        XCTAssertEqual("?", Fmt.initials("  "))
        XCTAssertEqual("?", Fmt.initials(nil))
        XCTAssertEqual("J", Fmt.initials("john"))
    }

    func testNumbersAndMoney() {
        XCTAssertEqual("1,234.5", Fmt.number(1234.5))
        XCTAssertEqual("0", Fmt.number(nil as Double?))
        XCTAssertEqual("2.35", Fmt.number(2.345))
        XCTAssertEqual("2.5", Fmt.number(2.5))
        XCTAssertEqual("1,000,000", Fmt.number(1_000_000.0))
        XCTAssertEqual("-45", Fmt.number(-45.0))
        XCTAssertEqual("KES 4,500", Fmt.currency(4500))
        XCTAssertEqual("USD 12.5", Fmt.currency(12.5, "USD"))
    }

    func testDatesReadAsEnKe() {
        XCTAssertEqual("5 Sept 2026", Fmt.date("2026-09-05T10:00:00Z"))
        XCTAssertEqual("9 Mar 2026", Fmt.date("2026-03-09T10:00:00Z"))
        XCTAssertEqual("—", Fmt.date(nil))
        XCTAssertEqual("12:00", Fmt.time("2026-09-25T09:00:00Z"), "Nairobi is UTC+3")
        XCTAssertEqual("", Fmt.time("nope"))
        XCTAssertEqual("25 Sept 2026, 12:00", Fmt.dateTime("2026-09-25T09:00:00Z"))
        XCTAssertEqual("1 Jan 2026", Fmt.date("2025-12-31T22:30:00Z"), "the local day, not the UTC one")
    }

    func testDayLabels() {
        XCTAssertEqual("Today", Fmt.dayLabel("2026-09-25T06:00:00Z"))
        XCTAssertEqual("Yesterday", Fmt.dayLabel("2026-09-24T06:00:00Z"))
        XCTAssertEqual("12 Mar 2026", Fmt.dayLabel("2026-03-12T06:00:00Z"))
        XCTAssertEqual("", Fmt.dayLabel(nil))
    }

    func testDuration() {
        XCTAssertEqual("00:00", Fmt.duration(nil))
        XCTAssertEqual("01:05", Fmt.duration(65))
        XCTAssertEqual("61:40", Fmt.duration(3700))
    }

    func testPhones() {
        XCTAssertEqual("+254 712 345 678", Fmt.formatPhone("254712345678"))
        XCTAssertEqual("+254 712 345 678", Fmt.formatPhone("+254 712 345 678"))
        XCTAssertEqual("+1 (415) 555-2671", Fmt.formatPhone("14155552671"))
        XCTAssertEqual("+44 7911 123456", Fmt.formatPhone("447911123456"))
        XCTAssertEqual("+49 151 2345 6789", Fmt.formatPhone("4915123456789"))
        XCTAssertEqual("+33 6 12 34 56 78", Fmt.formatPhone("33612345678"))
        XCTAssertEqual("+91 98765 43210", Fmt.formatPhone("919876543210"))
        XCTAssertEqual("+255 712 345 678", Fmt.formatPhone("255712345678"))
        XCTAssertEqual("+254 71234", Fmt.formatPhone("25471234"), "an odd length falls back to the bare rule")
        XCTAssertEqual("+999 123 456", Fmt.formatPhone("999123456"), "an unknown code groups by threes")
        XCTAssertEqual("Messenger ID 1234567890123456", Fmt.formatPhone("+1234567890123456"))
        XCTAssertEqual("Website visitor", Fmt.formatPhone("web_3f9a"))
        XCTAssertEqual("", Fmt.formatPhone(nil))
        XCTAssertEqual("abc", Fmt.formatPhone("abc"))
    }

    func testDisplayNameNeverShowsRawDigits() {
        XCTAssertEqual("Mary", Fmt.displayName("  Mary ", "254712345678"))
        XCTAssertEqual("+254 712 345 678", Fmt.displayName("", "254712345678"))
        XCTAssertEqual("Unknown", Fmt.displayName(nil, nil))
    }

    func testCountriesAndFlags() {
        XCTAssertEqual("🇰🇪", Fmt.flagEmoji("ke"))
        XCTAssertEqual("", Fmt.flagEmoji("KEN"))
        XCTAssertEqual("", Fmt.flagEmoji(nil))
        XCTAssertEqual("Kenya", Fmt.countryName("KE"))
        XCTAssertEqual("KEN", Fmt.countryName("KEN"))
        XCTAssertEqual("", Fmt.countryName(""))
    }
}

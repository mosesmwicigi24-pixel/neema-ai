import Foundation

/// Ports of lib/utils.ts (and Android's `Fmt`).
public enum Fmt {
    /// The zone dates are shown in; tests pin it (Android pins Africa/Nairobi).
    public static var timeZone: TimeZone = .current

    private static let isoRegex = try! NSRegularExpression(
        pattern: #"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?)?\s*(Z|z|[+-]\d{2}:?\d{2})?$"#
    )

    /// ISO-8601 (with or without offset) → epoch millis; nil when unparseable.
    /// Naive timestamps from the API are UTC; a bare date is local midnight.
    public static func millis(_ iso: String?) -> Int64? {
        guard let raw = iso?.trimmingCharacters(in: .whitespaces), !raw.isEmpty else { return nil }
        if let m = isoRegex.firstMatch(in: raw, range: NSRange(raw.startIndex..., in: raw)) {
            func group(_ i: Int) -> String? {
                let r = m.range(at: i)
                guard r.location != NSNotFound, let rr = Range(r, in: raw) else { return nil }
                return String(raw[rr])
            }
            var comps = DateComponents()
            comps.year = Int(group(1)!)
            comps.month = Int(group(2)!)
            comps.day = Int(group(3)!)
            let hasTime = group(4) != nil
            comps.hour = Int(group(4) ?? "0")
            comps.minute = Int(group(5) ?? "0")
            comps.second = Int(group(6) ?? "0")
            var fracMillis: Int64 = 0
            if let f = group(7) {
                let padded = (f + "000").prefix(3)
                fracMillis = Int64(padded) ?? 0
            }
            var cal = Calendar(identifier: .gregorian)
            if let off = group(8) {
                if off.lowercased() == "z" { cal.timeZone = TimeZone(identifier: "UTC")! }
                else {
                    let sign: Int = off.hasPrefix("-") ? -1 : 1
                    let digits = off.dropFirst().replacingOccurrences(of: ":", with: "")
                    let h = Int(digits.prefix(2)) ?? 0
                    let mnt = Int(digits.dropFirst(2)) ?? 0
                    cal.timeZone = TimeZone(secondsFromGMT: sign * (h * 3600 + mnt * 60)) ?? TimeZone(identifier: "UTC")!
                }
            } else {
                cal.timeZone = hasTime ? TimeZone(identifier: "UTC")! : timeZone
            }
            guard let d = cal.date(from: comps) else { return nil }
            return Int64((d.timeIntervalSince1970 * 1000).rounded(.down)) + fracMillis
        }
        // `LocalDate.parse(iso.take(10))`: anything with a date up front still reads as that day.
        if raw.count > 10 { return millis(String(raw.prefix(10))) }
        return nil
    }

    /// "5m ago" — a missing date reads "—", never an epoch date.
    public static func timeAgo(_ iso: String?, now: Int64 = AppClock.now()) -> String {
        guard let t = millis(iso), t > 0 else { return "—" }
        let d = (now - t) / 1000
        if d < 0 { return "just now" }
        if d < 60 { return "\(d)s ago" }
        if d < 3600 { return "\(d / 60)m ago" }
        if d < 86400 { return "\(d / 3600)h ago" }
        return "\(d / 86400)d ago"
    }

    /// lib/utils.ts `initials`: the first letter of the first two words, per
    /// grapheme — a Swift `Character` is one, so "Mama 🌸 Njeri" draws "M🌸".
    public static func initials(_ name: String?) -> String {
        let words = (name ?? "").split(whereSeparator: { $0.isWhitespace }).prefix(2)
        let s = words.map { firstGrapheme(String($0)).uppercased() }.joined()
        return s.isEmpty ? "?" : s
    }

    /// The first user-perceived character of `word`.
    public static func firstGrapheme(_ word: String) -> String { word.first.map { String($0) } ?? "" }

    /// `NumberFormat.getNumberInstance(Locale.US)` with at most 2 fraction digits (half-even).
    public static func number(_ n: Double?) -> String {
        let v = n ?? 0
        guard v.isFinite else { return "0" }
        let scaled = (v * 100).rounded(.toNearestOrEven)
        let negative = scaled < 0
        let whole = Int64(abs(scaled)) / 100
        let frac = Int64(abs(scaled)) % 100
        var digits = String(whole)
        var grouped = ""
        while digits.count > 3 {
            grouped = "," + digits.suffix(3) + grouped
            digits = String(digits.dropLast(3))
        }
        grouped = digits + grouped
        var out = grouped
        if frac != 0 {
            var f = String(format: "%02d", frac)
            while f.hasSuffix("0") { f.removeLast() }
            out += "." + f
        }
        return (negative && out != "0") ? "-" + out : out
    }

    public static func number(_ n: Int?) -> String { number(n.map(Double.init)) }

    public static func currency(_ n: Double?, _ currency: String = "KES") -> String { "\(currency) \(number(n))" }

    /// en-KE short months: Java's except September, which en-KE writes "Sept".
    static let enKeMonths = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec"]

    private static func calendar() -> Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = timeZone
        return c
    }

    private static func local(_ iso: String?) -> DateComponents? {
        guard let ms = millis(iso) else { return nil }
        let d = Date(timeIntervalSince1970: TimeInterval(ms) / 1000)
        return calendar().dateComponents([.year, .month, .day, .hour, .minute], from: d)
    }

    private static func dayMonthYear(_ c: DateComponents) -> String {
        "\(c.day ?? 1) \(enKeMonths[max(0, min(11, (c.month ?? 1) - 1))]) \(String(format: "%04d", c.year ?? 0))"
    }

    private static func hhmm(_ c: DateComponents) -> String { String(format: "%02d:%02d", c.hour ?? 0, c.minute ?? 0) }

    /// lib/utils.ts fmtDate: "5 Sept 2026".
    public static func date(_ iso: String?) -> String { local(iso).map(dayMonthYear) ?? "—" }
    public static func time(_ iso: String?) -> String { local(iso).map(hhmm) ?? "" }
    public static func dateTime(_ iso: String?) -> String { local(iso).map { "\(dayMonthYear($0)), \(hhmm($0))" } ?? "—" }

    /// WhatsApp-style day header: Today / Yesterday / 12 Mar 2026.
    public static func dayLabel(_ iso: String?) -> String {
        guard let c = local(iso) else { return "" }
        let cal = calendar()
        let today = cal.dateComponents([.year, .month, .day], from: AppClock.date())
        let yesterday = cal.dateComponents([.year, .month, .day], from: cal.date(byAdding: .day, value: -1, to: AppClock.date()) ?? AppClock.date())
        if c.year == today.year && c.month == today.month && c.day == today.day { return "Today" }
        if c.year == yesterday.year && c.month == yesterday.month && c.day == yesterday.day { return "Yesterday" }
        return dayMonthYear(c)
    }

    public static func duration(_ seconds: Int?) -> String {
        let s = seconds ?? 0
        return String(format: "%02d:%02d", s / 60, s % 60)
    }

    /// A real name, else the formatted phone — never a raw digit string.
    public static func displayName(_ name: String?, _ phoneOrId: String?) -> String {
        if let n = name?.trimmingCharacters(in: .whitespacesAndNewlines), !n.isEmpty { return n }
        let p = formatPhone(phoneOrId)
        return p.isEmpty ? "Unknown" : p
    }

    private static func regionCode(_ iso: String?) -> String? {
        guard let code = iso?.trimmingCharacters(in: .whitespaces).uppercased(), !code.isEmpty else { return nil }
        return code
    }

    private static func isTwoLetters(_ code: String) -> Bool {
        code.count == 2 && code.allSatisfy { ("A"..."Z").contains($0) }
    }

    /// "KE" → "Kenya" (the platform's own region names).
    public static func countryName(_ iso: String?) -> String {
        guard let code = regionCode(iso) else { return "" }
        if !isTwoLetters(code) { return code }
        let name = Locale(identifier: "en").localizedString(forRegionCode: code) ?? ""
        return name.isEmpty ? code : name
    }

    /// "KE" → 🇰🇪
    public static func flagEmoji(_ iso: String?) -> String {
        guard let code = regionCode(iso), isTwoLetters(code) else { return "" }
        return code.unicodeScalars.map { String(UnicodeScalar(0x1F1E6 + ($0.value - 65))!) }.joined()
    }

    private static func sub(_ s: String, _ from: Int, _ to: Int? = nil) -> String {
        let start = s.index(s.startIndex, offsetBy: min(from, s.count))
        let end = to.map { s.index(s.startIndex, offsetBy: min($0, s.count)) } ?? s.endIndex
        return String(s[start..<end])
    }

    private static let phoneRules: [String: (String, String) -> String] = [
        "1": { cc, s in s.count == 10 ? "+\(cc) (\(sub(s, 0, 3))) \(sub(s, 3, 6))-\(sub(s, 6))" : "+\(cc) \(s)" },
        "254": { cc, s in s.count == 9 ? "+\(cc) \(sub(s, 0, 3)) \(sub(s, 3, 6)) \(sub(s, 6))" : "+\(cc) \(s)" },
        "27": { cc, s in s.count == 9 ? "+\(cc) \(sub(s, 0, 2)) \(sub(s, 2, 5)) \(sub(s, 5))" : "+\(cc) \(s)" },
        "234": { cc, s in s.count == 10 ? "+\(cc) \(sub(s, 0, 3)) \(sub(s, 3, 6)) \(sub(s, 6))" : "+\(cc) \(s)" },
        "44": { cc, s in s.count == 10 ? "+\(cc) \(sub(s, 0, 4)) \(sub(s, 4))" : "+\(cc) \(s)" },
        "49": { cc, s in s.count >= 9 ? "+\(cc) \(sub(s, 0, 3)) \(sub(s, 3, 7))\(s.count > 7 ? " " + sub(s, 7) : "")" : "+\(cc) \(s)" },
        "33": { cc, s in s.count == 9 ? "+\(cc) \(sub(s, 0, 1)) \(sub(s, 1, 3)) \(sub(s, 3, 5)) \(sub(s, 5, 7)) \(sub(s, 7))" : "+\(cc) \(s)" },
        "91": { cc, s in s.count == 10 ? "+\(cc) \(sub(s, 0, 5)) \(sub(s, 5))" : "+\(cc) \(s)" },
        "971": { cc, s in s.count == 9 ? "+\(cc) \(sub(s, 0, 2)) \(sub(s, 2, 5)) \(sub(s, 5))" : "+\(cc) \(s)" },
        "255": { cc, s in s.count == 9 ? "+\(cc) \(sub(s, 0, 3)) \(sub(s, 3, 6)) \(sub(s, 6))" : "+\(cc) \(s)" },
        "256": { cc, s in s.count == 9 ? "+\(cc) \(sub(s, 0, 3)) \(sub(s, 3, 6)) \(sub(s, 6))" : "+\(cc) \(s)" },
        "251": { cc, s in s.count == 9 ? "+\(cc) \(sub(s, 0, 2)) \(sub(s, 2, 5)) \(sub(s, 5))" : "+\(cc) \(s)" },
        "233": { cc, s in s.count == 9 ? "+\(cc) \(sub(s, 0, 2)) \(sub(s, 2, 5)) \(sub(s, 5))" : "+\(cc) \(s)" },
        "250": { cc, s in s.count == 9 ? "+\(cc) \(sub(s, 0, 3)) \(sub(s, 3, 6)) \(sub(s, 6))" : "+\(cc) \(s)" },
        "61": { cc, s in s.count == 9 ? "+\(cc) \(sub(s, 0, 1)) \(sub(s, 1, 5)) \(sub(s, 5))" : "+\(cc) \(s)" },
    ]

    /// "254712345678" → "+254 712 345 678"; Meta PSIDs (>15 digits) are shown as ids.
    public static func formatPhone(_ raw: String?) -> String {
        guard let cleaned = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !cleaned.isEmpty else { return "" }
        // Website chat visitors are keyed by a hash ("web_3f9a…"): never read it as a phone.
        if cleaned.hasPrefix("web_") { return "Website visitor" }
        let digits = cleaned.filter { $0.isASCII && $0.isNumber }
        if digits.isEmpty { return cleaned }
        if digits.count > 15 { return "Messenger ID " + (cleaned.hasPrefix("+") ? String(cleaned.dropFirst()) : cleaned) }
        for len in [3, 2, 1] {
            if digits.count <= len { continue }
            let cc = sub(digits, 0, len)
            if let rule = phoneRules[cc] { return rule(cc, sub(digits, len)) }
        }
        var out = ""
        for (i, ch) in digits.enumerated() {
            out.append(ch)
            if (i + 1) % 3 == 0 && i + 1 < digits.count { out.append(" ") }
        }
        return "+" + out
    }
}

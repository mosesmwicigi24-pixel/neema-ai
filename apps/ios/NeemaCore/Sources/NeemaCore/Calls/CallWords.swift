import Foundation

/// How a logged call reads wherever it is listed (the Calls view, the customer
/// panel, the thread pill): a direction icon and an outcome WORD in its tone —
/// never colour alone (CALLING_UX.md §5, §7). Android `feature/calls/CallWords.kt`.
public enum CallTone: Equatable, Sendable { case live, good, bad, warn, neutral }

/// The direction glyph beside the word; the SwiftUI layer maps it to a symbol.
public enum CallDirIcon: Equatable, Sendable { case out, `in`, missed, back }

public struct CallRowWords: Equatable, Sendable {
    public let label: String
    public let tone: CallTone
    public let icon: CallDirIcon
    public init(_ label: String, _ tone: CallTone, _ icon: CallDirIcon) { self.label = label; self.tone = tone; self.icon = icon }
}

public enum CallWords {
    /// The two channels that call (CALLING_UX.md §1, §2.0).
    public static let WHATSAPP = "whatsapp"
    public static let MESSENGER = "messenger"
    /// "Messenger caller": a Messenger call with no name yet (a PSID is no number and is never shown).
    public static let MESSENGER_CALLER = "Messenger caller"
    /// A voicemail arrived for this call: the "Voicemail" badge (rows, details) and the thread pill's " · voicemail".
    public static let VOICEMAIL = "Voicemail"
}

/// Outgoing / incoming / missed / call-back icon and the outcome word for `c`'s status.
public func callRowWords(_ c: Call) -> CallRowWords {
    let out = c.direction == "outbound"
    let dir: CallDirIcon = out ? .out : .in
    switch c.status {
    case "ringing": return CallRowWords(out ? "Calling…" : "Ringing…", .live, dir)
    case "answered": return CallRowWords("On a call", .live, dir)
    case "completed", "ended": return CallRowWords(out ? "Outgoing" : "Incoming", .good, dir)
    case "missed": return CallRowWords("Missed", .bad, .missed)
    case "declined": return CallRowWords("Declined", .warn, dir)
    case "callback": return CallRowWords("Call back", .warn, .back)
    case "no_answer": return CallRowWords("No answer", .bad, dir)
    // The customer declined OUR call (Meta's REJECTED) — not a follow-up, but not a good outcome.
    case "rejected": return CallRowWords("Declined by customer", .bad, dir)
    case "cancelled": return CallRowWords("Cancelled", .neutral, dir)
    case "failed": return CallRowWords("Failed", .bad, dir)
    default:
        let words = c.status.replacingOccurrences(of: "_", with: " ")
        return CallRowWords(words.isEmpty ? "Call" : words.prefix(1).uppercased() + words.dropFirst(), .neutral, dir)
    }
}

/// A row / event's channel, WhatsApp when it says none (older rows and frames carry none).
public func channelOf(_ v: String?) -> String {
    (v ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == CallWords.MESSENGER ? CallWords.MESSENGER : CallWords.WHATSAPP
}

/// Where the call is, in words: "WhatsApp" / "Messenger".
public func channelLabel(_ ch: String?) -> String { channelOf(ch) == CallWords.MESSENGER ? "Messenger" : "WhatsApp" }

/// The customer's handle on the call's channel: the wa_id, or the PSID on Messenger (never shown).
public func callHandle(_ c: Call) -> String {
    let raw = channelOf(c.channel) == CallWords.MESSENGER ? c.externalId : (c.waId ?? c.externalId)
    guard let h = raw else { return "" }
    return h.hasPrefix("+") ? String(h.dropFirst()) : h
}

/// Who a logged call is with: the name, else "+wa_id", else "Messenger caller" on Messenger
/// (a PSID is never shown), else "Unknown caller" (a blank name falls through too).
public func rowWho(_ c: Call) -> String {
    if let n = c.name?.trimmingCharacters(in: .whitespacesAndNewlines), !n.isEmpty { return n }
    if let w = c.waId, !w.isEmpty { return "+\(w)" }
    return channelOf(c.channel) == CallWords.MESSENGER ? CallWords.MESSENGER_CALLER : "Unknown caller"
}

/// "4:12" — a finished call's length.
public func callLength(_ s: Int) -> String { "\(s / 60):" + String(format: "%02d", s % 60) }

/// mm:ss for the live timer (tabular numerals on screen).
public func mmss(_ s: Int) -> String { String(format: "%02d:%02d", s / 60, s % 60) }

/// "4:12" for a call that connected, "" otherwise.
public func callDuration(_ s: Int?) -> String {
    guard let s = s, s > 0 else { return "" }
    return callLength(s)
}

/// The agent's first name ("Moses Mwicigi" → "Moses").
public func agentFirst(_ name: String?) -> String? {
    guard let n = name else { return nil }
    return n.split(whereSeparator: { $0.isWhitespace }).first.map(String.init)
}

/// Words that come before a name ("Deacon James", "Rev Mary"): never what the customer is called by.
private let TITLES: Set<String> = [
    "fr", "father", "rev", "revd", "reverend", "sr", "sister", "br", "bro", "brother", "dr", "mr", "mrs", "ms", "prof",
    "deacon", "pastor", "bishop", "archbishop", "canon", "most", "the", "rt", "right", "very", "askofu", "mkuu",
]

/// The name to address a customer by: the first word, skipping a title
/// ("Fr. Peter Kamau" → "Peter"); nil when there is no name.
public func firstNameOf(_ name: String?) -> String? {
    let trimmed = (name ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    let words = trimmed.split(whereSeparator: { $0.isWhitespace }).map(String.init)
    if words.isEmpty || trimmed.hasPrefix("+") { return nil }
    func title(_ w: String) -> Bool { w.hasSuffix(".") || TITLES.contains(w.lowercased()) }
    return words.first(where: { !title($0) }) ?? words.first
}

/// When something becomes possible, relative to `now`: "in 12 min", "in 5 h",
/// "on 3 Oct 2026" — "now" once it is past.
public func untilText(_ iso: String, now: Int64) -> String {
    guard let t = Fmt.millis(iso) else { return "later" }
    let mins = (t - now + 59_999) / 60_000
    if mins <= 0 { return "now" }
    if mins < 60 { return "in \(mins) min" }
    if mins < 24 * 60 { return "in \((mins + 59) / 60) h" }
    return "on \(Fmt.date(iso))"
}

/// Where a customer's call permission stands, in words (CALLING_UX.md §2.1):
/// "Allowed permanently", "Allowed until {date}", "Request sent {time} —
/// waiting for {First}", "{First} declined calls", "Permission revoked after
/// unanswered calls" — nil when there is nothing to say (never asked; a
/// call may still go through).
public func permissionLine(_ p: CallPermission, first: String, now: Int64) -> String? {
    if p.status == "granted" && (p.permanent || p.metaStatus == "permanent") { return "Allowed permanently" }
    if p.status == "granted", let e = p.expiresAt { return "Allowed until \(Fmt.date(e))" }
    if p.status == "granted" { return "Allowed calls" }
    if p.status == "requested" {
        let ago = (p.requestedAt ?? p.at).map { Fmt.timeAgo($0, now: now) }.flatMap { $0 == "—" ? nil : $0 }
        return "Request sent\(ago.map { " \($0)" } ?? "") — waiting for \(first)"
    }
    if p.status == "denied" && p.revoked { return "Permission revoked after unanswered calls" }
    if p.status == "denied" { return "\(first) declined calls" }
    // Meta says they haven't allowed calls (and nobody asked yet): said, as the web does.
    if p.metaStatus == "no_permission" { return "\(first) hasn't allowed calls yet" }
    return nil
}

/// Everything the customer panel says about calling them: the `permissionLine`,
/// when a new request can go ("You can ask again {relative}"), and — only when
/// Meta gave it — "Calls left today: N".
public func permissionLines(_ p: CallPermission, first: String, now: Int64) -> [String] {
    var out: [String] = []
    if let l = permissionLine(p, first: first, now: now) { out.append(l) }
    if let at = p.requestAvailableAt, p.canRequest == false, p.status != "granted" { out.append("You can ask again \(untilText(at, now: now))") }
    if let n = p.callsLeftToday { out.append("Calls left today: \(n)") }
    return out
}

/// One turn of a speaker-separated transcript.
public struct TranscriptTurn: Equatable, Sendable {
    public let speaker: String
    public let text: String
    public init(_ speaker: String, _ text: String) { self.speaker = speaker; self.text = text }
}

private let turnLabel = try! NSRegularExpression(pattern: #"^(Agent|Customer)\s*:\s*(.*)$"#, options: [.caseInsensitive])

/// A speaker-separated transcript ("Agent: …\nCustomer: …", as the server
/// stores WhatsApp's) as turns — nil when it isn't one, i.e. when any line
/// lacks those labels (a Whisper transcript, or another labelling: plain text then).
public func transcriptTurns(_ text: String) -> [TranscriptTurn]? {
    let lines = text.split(omittingEmptySubsequences: false, whereSeparator: { $0 == "\n" || $0 == "\r\n" })
        .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    if lines.isEmpty { return nil }
    var out: [TranscriptTurn] = []
    for l in lines {
        guard let m = turnLabel.firstMatch(in: l, range: NSRange(l.startIndex..., in: l)),
              let sr = Range(m.range(at: 1), in: l), let tr = Range(m.range(at: 2), in: l) else { return nil }
        let who = l[sr].lowercased()
        out.append(TranscriptTurn(who.prefix(1).uppercased() + who.dropFirst(), String(l[tr])))
    }
    return out
}

/// Meta restricted the number's calling (the `calling_restricted` frame): the banner's facts.
public struct CallingRestriction: Equatable, Sendable {
    public let reasons: [String]
    public let at: String?
    public init(reasons: [String], at: String?) { self.reasons = reasons; self.at = at }
}

/// The restriction banner's second line: Meta's reasons, and what it means for calls.
public func restrictionText(_ r: CallingRestriction) -> String {
    let why = r.reasons.map { reason -> String in
        let w = reason.replacingOccurrences(of: "_", with: " ").lowercased()
        return w.prefix(1).uppercased() + w.dropFirst()
    }.filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
    return (why.isEmpty ? "" : why.joined(separator: " · ") + ". ") + "Calls you place may fail until it lifts (up to 7 days)."
}

/// Why a chat's app can't call right now — the "call on WhatsApp instead"
/// sheet's first line (CustomerSidebar.tsx cantCallWhy). Messenger can call
/// when the server's switch is on; Instagram has no business calling API.
public func cantCallWhy(_ app: String) -> String {
    app == "Messenger" ? "Messenger calling isn't switched on for Neema yet." : "\(app) doesn't let businesses take calls."
}

/// The thread pill's words: the server's label (else the row's word), and " · voicemail" when one came with the call.
public func threadCallLabel(_ body: String, _ call: Call?) -> String {
    let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
    let label = trimmed.isEmpty ? (call.map { callRowWords($0).label } ?? "Call") : body
    if call?.hasVoicemail == true && label.range(of: "voicemail", options: .caseInsensitive) == nil { return "\(label) · voicemail" }
    return label
}

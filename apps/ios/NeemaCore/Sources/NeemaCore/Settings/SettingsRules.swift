import Foundation

// ── Local-only sections (the web keeps these in component state, no API) ─────

/// The Business card (Android `BizSettings`): local-only on the web too.
public struct BizSettings: Equatable, Sendable {
    public var businessName = "Bethany House"
    public var currency = "KES"
    public var waNumber = "+254785490805"
    public var openHours = "08:00–18:00"
    public var timezone = "Africa/Nairobi"
    public init() {}
    public init(businessName: String, currency: String, waNumber: String, openHours: String, timezone: String) {
        self.businessName = businessName; self.currency = currency; self.waNumber = waNumber; self.openHours = openHours; self.timezone = timezone
    }
}

/// The AI Configuration card (Android `AiSettings`): local-only on the web too.
public struct AiSettings: Equatable, Sendable {
    public var autoInterceptThreshold = "3"
    public var draftApproval = true
    public var responseDelayMs = "1500"
    public var escalationKeywords = "refund, complaint, manager, urgent"
    public init() {}
    public init(autoInterceptThreshold: String, draftApproval: Bool, responseDelayMs: String, escalationKeywords: String) {
        self.autoInterceptThreshold = autoInterceptThreshold; self.draftApproval = draftApproval
        self.responseDelayMs = responseDelayMs; self.escalationKeywords = escalationKeywords
    }
}

/// One field of an integration's Configure form.
public struct ConfigField: Equatable, Sendable, Identifiable {
    public let label: String
    public let key: String
    /// A token, key or password: never written to saved state.
    public let secret: Bool
    public let placeholder: String?
    public var id: String { key }
    public init(_ label: String, _ key: String, secret: Bool = false, placeholder: String? = nil) {
        self.label = label; self.key = key; self.secret = secret; self.placeholder = placeholder
    }
}

public struct Integration: Equatable, Sendable, Identifiable {
    public let key: String
    public let name: String
    public var connected: Bool
    public let description: String
    public let fields: [ConfigField]
    public var id: String { key }
    public init(_ key: String, _ name: String, _ connected: Bool, _ description: String, _ fields: [ConfigField]) {
        self.key = key; self.name = name; self.connected = connected; self.description = description; self.fields = fields
    }
}

/// SettingsView.tsx's integrations list, verbatim.
public let INTEGRATIONS: [Integration] = [
    Integration("whatsapp", "WhatsApp Business API", true, "Primary messaging channel", [
        ConfigField("Phone Number ID", "phone_id", placeholder: "752950797900067"),
        ConfigField("Access Token", "token", secret: true, placeholder: "EAAx…"),
        ConfigField("Webhook Secret", "secret", secret: true, placeholder: "your-secret"),
    ]),
    Integration("messenger", "Facebook Messenger", true, "Meta messaging platform", [
        ConfigField("Page ID", "page_id", placeholder: "123456789"),
        ConfigField("Access Token", "page_token", secret: true, placeholder: "EAAx…"),
    ]),
    Integration("instagram", "Instagram DMs", true, "Instagram direct messages", [
        ConfigField("Business Account ID", "ig_id", placeholder: "17841…"),
        ConfigField("Access Token", "ig_token", secret: true, placeholder: "EAAx…"),
    ]),
    Integration("mpesa", "M-Pesa Daraja API", true, "Mobile payment processing", [
        ConfigField("Consumer Key", "consumer_key", secret: true),
        ConfigField("Consumer Secret", "consumer_secret", secret: true),
        ConfigField("Paybill Number", "paybill", placeholder: "542542"),
        ConfigField("Account Number", "account", placeholder: "50036"),
    ]),
    Integration("email", "Email (SMTP)", true, "Email channel integration", [
        ConfigField("SMTP Host", "smtp_host", placeholder: "smtp.gmail.com"),
        ConfigField("SMTP Port", "smtp_port", placeholder: "587"),
        ConfigField("Username", "smtp_user", placeholder: "hello@bethanyhouse.co.ke"),
        ConfigField("Password", "smtp_pass", secret: true),
    ]),
    Integration("slack", "Slack Notifications", false, "Team alert channel", [
        ConfigField("Webhook URL", "slack_url", placeholder: "https://hooks.slack.com/…"),
        ConfigField("Channel", "slack_channel", placeholder: "#neema-alerts"),
    ]),
    Integration("sheets", "Google Sheets", false, "Data export and reporting", [
        ConfigField("Sheet ID", "sheet_id", placeholder: "1BxiMVs0XRA5nFM…"),
        ConfigField("Service Account JSON", "gcp_json", secret: true, placeholder: "Paste service account JSON…"),
    ]),
]

// ── Pipeline stages (crm.py) ─────────────────────────────────────────────────

/// The pipeline's fixed stages, for the preview line (crm.py PIPELINE_CANONICAL).
public let CANONICAL_BEFORE = ["New", "Contacted", "Qualified", "Proposal"]
public let PIPELINE_CUSTOM_MAX = 4
public let PIPELINE_LABEL_MAX = 18
/// crm.py PIPELINE_CANONICAL — the server silently drops a custom stage with one of these names.
public let PIPELINE_CANONICAL: Set<String> = ["new", "contacted", "qualified", "proposal", "negotiation", "won", "lost"]

/// crm.py put_pipeline_stages's cleaning: trim, cut to 18, drop blanks, built-ins and repeats.
public func cleanStages(_ list: [String]) -> [String] {
    var out: [String] = []
    for s in list {
        let label = String(s.trimmingCharacters(in: .whitespacesAndNewlines).prefix(PIPELINE_LABEL_MAX))
        if label.isEmpty || PIPELINE_CANONICAL.contains(label.lowercased()) { continue }
        if out.contains(where: { $0.caseInsensitiveCompare(label) == .orderedSame }) { continue }
        out.append(label)
    }
    return out
}

// ── Dates ────────────────────────────────────────────────────────────────────

private let utcZone = TimeZone(identifier: "UTC")!

/// A strict "YYYY-MM-DD" (Python's `date.fromisoformat`, Java's `LocalDate.parse`): nil for anything else.
public func parseIsoDate(_ s: String?) -> LocalDay? {
    guard let s = s, s.count == 10, s.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil else { return nil }
    return LocalDay.parse(s)
}

/// The date picker works in UTC-midnight millis; offers store YYYY-MM-DD (Android `isoDateToUtcMillis`).
public func isoDateToUtcMillis(_ iso: String?) -> Int64? { parseIsoDate(iso)?.startMillis(zone: utcZone) }

public func utcMillisToIsoDate(_ ms: Int64) -> String { LocalDay.of(millis: ms, zone: utcZone).description }

// ── The offer (services/promotions.py) ───────────────────────────────────────

/// promotions.SCOPES
public let OFFER_SCOPES: Set<String> = ["all", "category", "products"]

private func blank(_ s: String) -> Bool { s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

/// What promotions.parse would refuse in `c` (set_campaign then answers 422),
/// in words that say which field to fix; nil when the server will accept it.
/// The server keeps int(percent), so the percentage must be a whole number,
/// and a category / products offer needs at least one category / SKU.
public func offerProblem(_ c: Campaign, maxPercent: Int) -> String? {
    if blank(c.name) { return "Give the offer a name" }
    if c.percent != c.percent.rounded(.down) || c.percent < 1 || c.percent > Double(maxPercent) {
        return "The discount must be a whole number from 1 to \(maxPercent)%"
    }
    if !OFFER_SCOPES.contains(c.scope) { return "Choose what the offer applies to" }
    if c.scope == "category" && !c.categories.contains(where: { !blank($0) }) { return "Pick at least one category for the offer" }
    if c.scope == "products" && !c.skus.contains(where: { !blank($0) }) { return "Pick at least one product for the offer" }
    if parseIsoDate(c.endsOn) == nil { return "Pick the offer's last day" }
    return nil
}

/// The server's own checks on an offer (promotions.set_campaign).
public func offerIsValid(_ c: Campaign, maxPercent: Int) -> Bool { offerProblem(c, maxPercent: maxPercent) == nil }

/// The web's catch-all for a refused offer.
public let OFFER_SAVE_FAILED = "Couldn't save that offer (admin only, and it needs a name, a percentage and an end date)"

// ── The toasts the live cards say (SettingsView.tsx) ─────────────────────────

public enum SettingsWords {
    public static let DIRECTIVES_SAVED = "Standing orders saved — Neema follows them within ~5 minutes"
    public static let DIRECTIVES_ADMIN_ONLY = "Couldn't save (admin only)"
    public static let DIRECTIVES_FAILED = "Couldn't save the standing orders — try again."
    public static let TRANSLATION_ON = "Translation on — foreign messages get an English line from the next thread you open"
    public static let TRANSLATION_OFF = "Translation off — no new translations will be bought. Ones already saved stay visible."
    public static let TRANSLATION_ADMIN_ONLY = "Couldn't change that (admin only)"
    public static let TRANSLATION_FAILED = "Couldn't change that — try again."
    public static let OFFER_ENDED = "Offer ended — Neema stops mentioning it from her next reply"
    public static let OFFER_ADMIN_ONLY = "Couldn't save that offer (admin only)"
    public static let OFFER_EXPIRED = "Offer saved, but its last day has passed — Neema won't mention it"
    public static let STAGES_ADMIN_ONLY = "Only an admin can change pipeline stages."
    public static let STAGES_FAILED = "Couldn't save pipeline stages."
    public static let DANGER = "Requires confirmation — coming soon"
    /// A live card that couldn't be read, with nothing better to say.
    public static let LOAD_FALLBACK = "The server couldn't send this setting just now."
}

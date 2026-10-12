import Foundation

/// The customer panel's words and rules that need no screen (Android
/// `CustomerWidgets.kt` metadata, `CustomerCalls.kt` call-button logic).
public enum CustomerWords {
    /// The web's STAGE_META labels.
    public static let PIPE_LABEL: [String: String] = [
        "new": "New", "contacted": "Contacted", "qualified": "Qualified", "proposal": "Proposal",
        "negotiation": "Negotiating", "won": "Won", "lost": "Lost",
    ]

    public static func stageLabel(_ s: String) -> String { PIPE_LABEL[s] ?? (s.prefix(1).uppercased() + s.dropFirst()) }

    /// The hero chip's label: "Won ✓" for won, as the web.
    public static func stageChipLabel(_ s: String) -> String { s == "won" ? "Won ✓" : stageLabel(s) }

    public struct TierMeta: Equatable, Sendable {
        public let label: String
        public let title: String
    }

    public static let TIER_META: [String: TierMeta] = [
        "vip": TierMeta(label: "VIP", title: "Top spender / very frequent buyer"),
        "loyal": TierMeta(label: "Loyal", title: "Repeat customer"),
        "regular": TierMeta(label: "Regular", title: "A few orders"),
        "new": TierMeta(label: "New", title: "First order"),
        "prospect": TierMeta(label: "Prospect", title: "No orders yet"),
        "at_risk": TierMeta(label: "At risk", title: "Good customer who's gone quiet — worth a nudge"),
    ]

    /// Where a lead first found us (captured by the AI or set by an operator): label and icon.
    public static let SOURCE_META: [String: (String, String)] = [
        "facebook": ("Facebook", "📘"), "instagram": ("Instagram", "📸"), "tiktok": ("TikTok", "🎵"), "youtube": ("YouTube", "▶️"),
        "whatsapp": ("WhatsApp", "💬"), "referral": ("Referral", "🤝"), "walk_in": ("Walk-in", "🚶"), "website": ("Website", "🌐"),
        "google": ("Google", "🔍"), "other": ("Other", "•"),
    ]

    /// A lead source's label + icon. The webhooks write "<base>_ad" for a click-to-message ad: those read "📘 Facebook ad".
    public static func sourceMeta(_ src: String) -> (label: String, icon: String)? {
        if let m = SOURCE_META[src] { return (m.0, m.1) }
        guard src.hasSuffix("_ad") else { return nil }
        let base = String(src.dropLast(3))
        guard let m = SOURCE_META[base] else { return nil }
        return ("\(m.0) ad", m.1)
    }

    /// A Messenger chat's PSID (digits), the handle a Messenger call goes to — nil on any other channel. Never shown.
    public static func messengerPsid(_ conversation: Conversation) -> String? {
        guard conversation.channel == "messenger" || conversation.channel == "facebook" else { return nil }
        let d = (conversation.externalId ?? "").filter { $0.isASCII && $0.isNumber }
        return d.isEmpty ? nil : d
    }

    /// A conversation whose app can't call right now: Messenger while the server's switch is off, Instagram always.
    public enum CallPlatform: String, Equatable, Sendable { case messenger = "Messenger", instagram = "Instagram" }

    public static func callPlatformOf(_ channel: String?) -> CallPlatform? {
        switch channel {
        case "messenger", "facebook": return .messenger
        case "instagram": return .instagram
        default: return nil
        }
    }

    /// What the panel's Call button does for a chat (CustomerSidebar.tsx's reach-out Call).
    public enum CallButton: Equatable, Sendable {
        /// A Messenger chat while Messenger calling is on: call them on Messenger.
        case onMessenger(psid: String)
        /// The chat's app can't call now: the "call on WhatsApp instead" sheet.
        case sheet(CallPlatform)
        /// A WhatsApp call to their number.
        case onWhatsApp(digits: String)
    }

    /// The Call button for `conversation`: Messenger only while the server says Messenger can call
    /// (`channels` unread counts as off); otherwise a Messenger or Instagram chat gets the sheet;
    /// anything else a WhatsApp call when there is a number. Nil: no Call button.
    public static func callButtonFor(_ conversation: Conversation, channels: CallChannels?, phoneDigits: String?) -> CallButton? {
        if let psid = messengerPsid(conversation), channels?.messenger.outbound == true { return .onMessenger(psid: psid) }
        if let p = callPlatformOf(conversation.channel) { return .sheet(p) }
        return phoneDigits.map { .onWhatsApp(digits: $0) }
    }

    /// `URLEncoder.encode(text, "UTF-8").replace("+", "%20")`: what a wa.me link carries.
    public static func urlEncode(_ text: String) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-_.*")
        return text.addingPercentEncoding(withAllowedCharacters: allowed) ?? text
    }

    /// A measurement's value, as the form captured it (a string shows as is, a number or bool as text).
    public static func display(_ v: JSONValue) -> String {
        if case .string(let s) = v { return s }
        return v.content ?? v.text
    }
}

/// What every tab of the panel needs, computed once (Android `PanelCtx`).
public struct PanelCtx: Equatable, Sendable {
    public let profile: CustomerProfile
    public let orders: [PanelOrder]
    public let totalSpent: Double
    public let lastOrder: PanelOrder?
    public let customStages: [String]
    public let canEdit: Bool
    public let canReply: Bool
    public let isAdmin: Bool
    /// The profile's stage matched to the pipeline's own spelling (see `Crm.canonicalStage`).
    public let stage: String

    public init(profile: CustomerProfile, orders: [PanelOrder], totalSpent: Double, lastOrder: PanelOrder?, customStages: [String],
                canEdit: Bool, canReply: Bool, isAdmin: Bool) {
        self.profile = profile; self.orders = orders; self.totalSpent = totalSpent; self.lastOrder = lastOrder; self.customStages = customStages
        self.canEdit = canEdit; self.canReply = canReply; self.isAdmin = isAdmin
        self.stage = Crm.canonicalStage(profile.leadStage, customs: customStages)
    }

    public var orderCount: Int { profile.totalOrders > 0 ? profile.totalOrders : orders.count }

    /// The panel's orders: the hub history served on the profile (POS, web AND WhatsApp), else the local
    /// WhatsApp orders for this customer; lifetime spend is the hub's, the client sum only a fallback.
    public static func make(profile p: CustomerProfile, allOrders: [Order], waId: String?, customStages: [String],
                            canEdit: Bool = true, canReply: Bool = true, isAdmin: Bool) -> PanelCtx {
        let orders = p.orders ?? allOrders.filter { $0.waId == waId || $0.contactPhone == waId }.map { PanelOrder(order: $0) }
        let totalSpent = p.totalSpent != 0 ? p.totalSpent : orders.reduce(0) { $0 + $1.amount }
        let lastOrder = orders.max { (Fmt.millis($0.createdIso) ?? 0) < (Fmt.millis($1.createdIso) ?? 0) }
        return PanelCtx(profile: p, orders: orders, totalSpent: totalSpent, lastOrder: lastOrder, customStages: customStages,
                        canEdit: canEdit, canReply: canReply, isAdmin: isAdmin)
    }
}

extension PanelOrder {
    /// Order → the panel's order shape (the fallback when the profile carries no hub history).
    public init(order o: Order) {
        self.init(id: o.id, orderNumber: o.hubOrderNumber, status: o.status, paymentStatus: o.paymentStatus, total: o.total,
                  subtotal: o.subtotal, currencyCode: o.currency, createdAt: o.createdAt,
                  items: o.items.map { PanelOrderItem(name: $0.name, qty: $0.qty, total: $0.total) }, source: "whatsapp")
    }
}

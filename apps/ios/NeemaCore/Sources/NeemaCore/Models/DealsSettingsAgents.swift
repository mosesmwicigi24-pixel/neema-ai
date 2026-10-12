import Foundation

// ── Deals & planned actions ─────────────────────────────────────────────────

public struct DealItem: Equatable, Hashable, Sendable, Decodable {
    public var name: String?
    public var qty: Double?
    public var price: Double?
    public init(name: String? = nil, qty: Double? = nil, price: Double? = nil) { self.name = name; self.qty = qty; self.price = price }
    enum K: String, CodingKey { case name, qty, price }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(name: c.string(.name), qty: c.double(.qty), price: c.double(.price))
    }
}

public struct NextAction: Equatable, Hashable, Sendable, Decodable {
    public var kind: String?
    public var owner: String?
    public var dueAt: String?
    public var note: String?
    public init(kind: String? = nil, owner: String? = nil, dueAt: String? = nil, note: String? = nil) { self.kind = kind; self.owner = owner; self.dueAt = dueAt; self.note = note }
    enum K: String, CodingKey { case kind, owner, due_at, note }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(kind: c.string(.kind), owner: c.string(.owner), dueAt: c.string(.due_at), note: c.string(.note))
    }
}

public struct Deal: Identifiable, Equatable, Hashable, Sendable, Decodable {
    public let id: String
    public var conversationId: String?
    public var customer: String
    public var waId: String?
    public var channel: String?
    public var title: String?
    public var items: [DealItem]
    public var stage: String
    public var blocking: String?
    public var nextAction: NextAction?
    public var guidance: String?
    public var status: String
    public var updatedAt: String?
    public init(id: String, conversationId: String? = nil, customer: String = "", waId: String? = nil, channel: String? = nil,
                title: String? = nil, items: [DealItem] = [], stage: String = "", blocking: String? = nil, nextAction: NextAction? = nil,
                guidance: String? = nil, status: String = "open", updatedAt: String? = nil) {
        self.id = id; self.conversationId = conversationId; self.customer = customer; self.waId = waId; self.channel = channel
        self.title = title; self.items = items; self.stage = stage; self.blocking = blocking; self.nextAction = nextAction
        self.guidance = guidance; self.status = status; self.updatedAt = updatedAt
    }
    enum K: String, CodingKey { case id, conversation_id, customer, wa_id, channel, title, items, stage, blocking, next_action, guidance, status, updated_at }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), conversationId: c.string(.conversation_id), customer: c.string(.customer, default: ""),
                  waId: c.string(.wa_id), channel: c.string(.channel), title: c.string(.title), items: c.list(.items),
                  stage: c.string(.stage, default: ""), blocking: c.string(.blocking), nextAction: c.object(.next_action),
                  guidance: c.string(.guidance), status: c.string(.status, default: "open"), updatedAt: c.string(.updated_at))
    }
}

public struct PlannedAction: Identifiable, Equatable, Hashable, Sendable, Decodable {
    public let id: String
    public var dealId: String?
    public var conversationId: String?
    public var dueAt: String?
    public var kind: String
    public var reason: String?
    public var draft: String?
    public var status: String
    public var createdBy: String
    public init(id: String, dealId: String? = nil, conversationId: String? = nil, dueAt: String? = nil, kind: String = "",
                reason: String? = nil, draft: String? = nil, status: String = "pending", createdBy: String = "") {
        self.id = id; self.dealId = dealId; self.conversationId = conversationId; self.dueAt = dueAt; self.kind = kind
        self.reason = reason; self.draft = draft; self.status = status; self.createdBy = createdBy
    }
    enum K: String, CodingKey { case id, deal_id, conversation_id, due_at, kind, reason, draft, status, created_by }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), dealId: c.string(.deal_id), conversationId: c.string(.conversation_id), dueAt: c.string(.due_at),
                  kind: c.string(.kind, default: ""), reason: c.string(.reason), draft: c.string(.draft), status: c.string(.status, default: "pending"),
                  createdBy: c.string(.created_by, default: ""))
    }
}

// ── Settings ────────────────────────────────────────────────────────────────

public struct Campaign: Equatable, Hashable, Sendable, Codable {
    public var name: String
    public var percent: Double
    /// "all" | "category" | "products"
    public var scope: String
    public var categories: [String]
    public var skus: [String]
    public var startsOn: String?
    /// Inclusive last day, YYYY-MM-DD.
    public var endsOn: String
    public init(name: String = "", percent: Double = 0, scope: String = "all", categories: [String] = [], skus: [String] = [], startsOn: String? = nil, endsOn: String = "") {
        self.name = name; self.percent = percent; self.scope = scope; self.categories = categories; self.skus = skus; self.startsOn = startsOn; self.endsOn = endsOn
    }
    enum K: String, CodingKey { case name, percent, scope, categories, skus, starts_on, ends_on }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(name: c.string(.name, default: ""), percent: c.double(.percent, default: 0), scope: c.string(.scope, default: "all"),
                  categories: c.stringList(.categories), skus: c.stringList(.skus), startsOn: c.string(.starts_on), endsOn: c.string(.ends_on, default: ""))
    }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: K.self)
        try c.encode(name, forKey: .name); try c.encode(percent, forKey: .percent); try c.encode(scope, forKey: .scope)
        try c.encode(categories, forKey: .categories); try c.encode(skus, forKey: .skus)
        try c.encodeIfPresent(startsOn, forKey: .starts_on); try c.encode(endsOn, forKey: .ends_on)
    }
}

public struct OfferSetting: Equatable, Sendable, Decodable {
    public var campaign: Campaign?
    public var running: Bool
    public var says: String
    public var maxPercent: Double
    public init(campaign: Campaign? = nil, running: Bool = false, says: String = "", maxPercent: Double = 0) {
        self.campaign = campaign; self.running = running; self.says = says; self.maxPercent = maxPercent
    }
    enum K: String, CodingKey { case campaign, running, says, max_percent }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(campaign: c.object(.campaign), running: c.bool(.running, default: false), says: c.string(.says, default: ""), maxPercent: c.double(.max_percent, default: 0))
    }
}

public struct TranslationSetting: Equatable, Sendable, Decodable {
    public var enabled: Bool
    public var isDefault: Bool
    public var spend30dUsd: Double
    public var calls30d: Int
    public init(enabled: Bool = false, isDefault: Bool = false, spend30dUsd: Double = 0, calls30d: Int = 0) {
        self.enabled = enabled; self.isDefault = isDefault; self.spend30dUsd = spend30dUsd; self.calls30d = calls30d
    }
    enum K: String, CodingKey { case enabled, `default`, spend_30d_usd, calls_30d }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(enabled: c.bool(.enabled, default: false), isDefault: c.bool(.default, default: false), spend30dUsd: c.double(.spend_30d_usd, default: 0), calls30d: c.int(.calls_30d, default: 0))
    }
}

// ── Agents & roles ──────────────────────────────────────────────────────────

public struct Agent: Identifiable, Equatable, Hashable, Sendable, Decodable {
    public let id: String
    public var name: String
    public var email: String
    /// "admin" | "agent" | "readonly" | "supervisor"
    public var role: String
    public var isAvailable: Bool
    public var isSuperuser: Bool
    public var activeConvs: Int
    public var avatarUrl: String?
    public var createdAt: String?
    public var lastSeenAt: String?
    public var customRoleId: String?
    public var customPermissions: [String]?
    public var roleName: String?
    public var roleColor: String?
    public var rolePermissions: [String]?
    public init(id: String, name: String = "", email: String = "", role: String = "agent", isAvailable: Bool = false, isSuperuser: Bool = false,
                activeConvs: Int = 0, avatarUrl: String? = nil, createdAt: String? = nil, lastSeenAt: String? = nil, customRoleId: String? = nil,
                customPermissions: [String]? = nil, roleName: String? = nil, roleColor: String? = nil, rolePermissions: [String]? = nil) {
        self.id = id; self.name = name; self.email = email; self.role = role; self.isAvailable = isAvailable; self.isSuperuser = isSuperuser
        self.activeConvs = activeConvs; self.avatarUrl = avatarUrl; self.createdAt = createdAt; self.lastSeenAt = lastSeenAt
        self.customRoleId = customRoleId; self.customPermissions = customPermissions; self.roleName = roleName; self.roleColor = roleColor
        self.rolePermissions = rolePermissions
    }
    /// mapAgent(): per-agent overrides, else the DB role's permissions.
    public var permissions: [String] { customPermissions ?? rolePermissions ?? [] }

    enum K: String, CodingKey {
        case id, name, email, role, is_available, is_superuser, active_convs, avatar_url, created_at, last_seen_at,
             custom_role_id, custom_permissions, role_name, role_color, role_permissions
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), name: c.string(.name, default: ""), email: c.string(.email, default: ""), role: c.string(.role, default: "agent"),
                  isAvailable: c.bool(.is_available, default: false), isSuperuser: c.bool(.is_superuser, default: false), activeConvs: c.int(.active_convs, default: 0),
                  avatarUrl: c.string(.avatar_url), createdAt: c.string(.created_at), lastSeenAt: c.string(.last_seen_at), customRoleId: c.string(.custom_role_id),
                  customPermissions: c.value(.custom_permissions).map { LenientKeyed<K>.lenientStrings($0) }, roleName: c.string(.role_name),
                  roleColor: c.string(.role_color), rolePermissions: c.value(.role_permissions).map { LenientKeyed<K>.lenientStrings($0) })
    }
}

public struct CustomRole: Identifiable, Equatable, Hashable, Sendable, Decodable {
    public var id: String
    public var name: String
    public var description: String
    public var color: String
    public var permissions: [String]
    public var isProtected: Bool
    public var createdAt: String?
    public init(id: String = "", name: String = "", description: String = "", color: String = "#589b31", permissions: [String] = [], isProtected: Bool = false, createdAt: String? = nil) {
        self.id = id; self.name = name; self.description = description; self.color = color; self.permissions = permissions; self.isProtected = isProtected; self.createdAt = createdAt
    }
    enum K: String, CodingKey { case id, name, description, color, permissions, `protected`, created_at }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), name: c.string(.name, default: ""), description: c.string(.description, default: ""),
                  color: c.string(.color, default: "#589b31"), permissions: c.stringList(.permissions), isProtected: c.bool(.protected, default: false), createdAt: c.string(.created_at))
    }
}

import Foundation

public struct CatalogVariant: Equatable, Hashable, Sendable, Decodable {
    public var variantId: Int64?
    public var sku: String?
    public var name: String?
    /// "<product> — <what tells it apart>"
    public var label: String?
    public var attributes: [String: String]
    public var priceKes: Double?
    public var priceUsd: Double?
    public init(variantId: Int64? = nil, sku: String? = nil, name: String? = nil, label: String? = nil, attributes: [String: String] = [:], priceKes: Double? = nil, priceUsd: Double? = nil) {
        self.variantId = variantId; self.sku = sku; self.name = name; self.label = label; self.attributes = attributes; self.priceKes = priceKes; self.priceUsd = priceUsd
    }
    enum K: String, CodingKey { case variant_id, sku, name, label, attributes, price_kes, price_usd }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(variantId: c.int64(.variant_id), sku: c.string(.sku), name: c.string(.name), label: c.string(.label),
                  attributes: c.stringMap(.attributes), priceKes: c.double(.price_kes), priceUsd: c.double(.price_usd))
    }
}

public struct CatalogItem: Identifiable, Equatable, Hashable, Sendable, Decodable {
    public var rawId: String?
    public var hubProductId: Int64?
    public var availableQty: Double?
    public var sku: String
    public var name: String
    public var aliases: [String]
    public var price: Double
    public var unit: String?
    public var rawCategory: String?
    public var description: String?
    public var inStock: Bool
    public var updatedAt: String?
    public var imageUrl: String?
    public var thumbnailUrl: String?
    public var priceKes: Double?
    public var priceUsd: Double?
    public var productType: String?
    public var variants: [CatalogVariant]
    public var priceMinKes: Double?
    public var priceMaxKes: Double?
    public init(rawId: String? = nil, hubProductId: Int64? = nil, availableQty: Double? = nil, sku: String = "", name: String = "", aliases: [String] = [],
                price: Double = 0, unit: String? = nil, rawCategory: String? = nil, description: String? = nil, inStock: Bool = true, updatedAt: String? = nil,
                imageUrl: String? = nil, thumbnailUrl: String? = nil, priceKes: Double? = nil, priceUsd: Double? = nil, productType: String? = nil,
                variants: [CatalogVariant] = [], priceMinKes: Double? = nil, priceMaxKes: Double? = nil) {
        self.rawId = rawId; self.hubProductId = hubProductId; self.availableQty = availableQty; self.sku = sku; self.name = name; self.aliases = aliases
        self.price = price; self.unit = unit; self.rawCategory = rawCategory; self.description = description; self.inStock = inStock; self.updatedAt = updatedAt
        self.imageUrl = imageUrl; self.thumbnailUrl = thumbnailUrl; self.priceKes = priceKes; self.priceUsd = priceUsd; self.productType = productType
        self.variants = variants; self.priceMinKes = priceMinKes; self.priceMaxKes = priceMaxKes
    }
    /// Hub rows have no local id — a stable synthetic one (mapCatalogItem).
    public var id: String { rawId ?? (hubProductId.map(String.init) ?? sku) }
    public var category: String { rawCategory ?? "General" }
    /// Hub-sourced rows are read-only here: edit them in the hub.
    public var isHub: Bool { rawId == nil && hubProductId != nil }

    enum K: String, CodingKey {
        case id, hub_product_id, available_qty, sku, name, aliases, price, unit, category, description, in_stock, updated_at,
             image_url, thumbnail_url, price_kes, price_usd, product_type, variants, price_min_kes, price_max_kes
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(rawId: c.string(.id), hubProductId: c.int64(.hub_product_id), availableQty: c.double(.available_qty), sku: c.string(.sku, default: ""),
                  name: c.string(.name, default: ""), aliases: c.stringList(.aliases), price: c.double(.price, default: 0), unit: c.string(.unit),
                  rawCategory: c.string(.category), description: c.string(.description), inStock: c.bool(.in_stock, default: true), updatedAt: c.string(.updated_at),
                  imageUrl: c.string(.image_url), thumbnailUrl: c.string(.thumbnail_url), priceKes: c.double(.price_kes), priceUsd: c.double(.price_usd),
                  productType: c.string(.product_type), variants: c.list(.variants), priceMinKes: c.double(.price_min_kes), priceMaxKes: c.double(.price_max_kes))
    }
}

public struct CreateCatalogPayload: Equatable, Sendable, Encodable {
    public var sku: String
    public var name: String
    public var price: Double
    public var unit: String?
    public var category: String?
    public var description: String?
    public var aliases: [String]?
    public var inStock: Bool?
    public init(sku: String, name: String, price: Double, unit: String? = nil, category: String? = nil, description: String? = nil, aliases: [String]? = nil, inStock: Bool? = nil) {
        self.sku = sku; self.name = name; self.price = price; self.unit = unit; self.category = category; self.description = description; self.aliases = aliases; self.inStock = inStock
    }
    enum K: String, CodingKey { case sku, name, price, unit, category, description, aliases, in_stock }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: K.self)
        try c.encode(sku, forKey: .sku); try c.encode(name, forKey: .name); try c.encode(price, forKey: .price)
        try c.encodeIfPresent(unit, forKey: .unit); try c.encodeIfPresent(category, forKey: .category)
        try c.encodeIfPresent(description, forKey: .description); try c.encodeIfPresent(aliases, forKey: .aliases)
        try c.encodeIfPresent(inStock, forKey: .in_stock)
    }
}

public struct PriceGap: Equatable, Hashable, Sendable, Decodable {
    public var name: String
    public var category: String?
    public var kes: Double
    public var usd: Double
    public var usdExpected: Double
    public var factor: Double?
    public init(name: String = "", category: String? = nil, kes: Double = 0, usd: Double = 0, usdExpected: Double = 0, factor: Double? = nil) {
        self.name = name; self.category = category; self.kes = kes; self.usd = usd; self.usdExpected = usdExpected; self.factor = factor
    }
    enum K: String, CodingKey { case name, category, kes, usd, usd_expected, factor }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(name: c.string(.name, default: ""), category: c.string(.category), kes: c.double(.kes, default: 0), usd: c.double(.usd, default: 0),
                  usdExpected: c.double(.usd_expected, default: 0), factor: c.double(.factor))
    }
}

public struct PerPieceRow: Equatable, Hashable, Sendable, Decodable {
    public var name: String
    public var category: String?
    public var kes: Double?
    public init(name: String = "", category: String? = nil, kes: Double? = nil) { self.name = name; self.category = category; self.kes = kes }
    enum K: String, CodingKey { case name, category, kes }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(name: c.string(.name, default: ""), category: c.string(.category), kes: c.double(.kes))
    }
}

public struct PriceAudit: Equatable, Sendable, Decodable {
    public var currencyGaps: [PriceGap]
    public var perPiece: [PerPieceRow]
    public var checked: Int
    public var rate: Double
    public init(currencyGaps: [PriceGap] = [], perPiece: [PerPieceRow] = [], checked: Int = 0, rate: Double = 0) {
        self.currencyGaps = currencyGaps; self.perPiece = perPiece; self.checked = checked; self.rate = rate
    }
    enum K: String, CodingKey { case currency_gaps, per_piece, checked, rate }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(currencyGaps: c.list(.currency_gaps), perPiece: c.list(.per_piece), checked: c.int(.checked, default: 0), rate: c.double(.rate, default: 0))
    }
}

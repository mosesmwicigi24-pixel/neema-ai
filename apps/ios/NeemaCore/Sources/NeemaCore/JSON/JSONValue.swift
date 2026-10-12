import Foundation

/// A JSON tree kept as data — the Swift twin of kotlinx's `JsonElement`.
/// Used for fields the backend shapes freely (`insights`, `state`,
/// `restrictions`, a renegotiation offer, ICE `urls`): they are read field by
/// field, leniently, so one odd value never fails a whole decode.
public enum JSONValue: Equatable, Hashable, Sendable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([JSONValue])
    case object([String: JSONValue])

    public subscript(key: String) -> JSONValue? {
        if case .object(let o) = self { return o[key] }
        return nil
    }

    public var isNull: Bool { if case .null = self { return true } else { return false } }
    public var objectValue: [String: JSONValue]? { if case .object(let o) = self { return o } else { return nil } }
    public var arrayValue: [JSONValue]? { if case .array(let a) = self { return a } else { return nil } }
    public var stringValue: String? { if case .string(let s) = self { return s } else { return nil } }
    public var boolValue: Bool? { if case .bool(let b) = self { return b } else { return nil } }
    public var doubleValue: Double? { if case .number(let d) = self { return d } else { return nil } }

    /// The primitive's text, as kotlinx `JsonPrimitive.content`: a string as
    /// is, a number or bool spelled out, null → nil.
    public var content: String? {
        switch self {
        case .string(let s): return s
        case .number(let d): return d == d.rounded() && abs(d) < 1e15 ? String(Int64(d)) : String(d)
        case .bool(let b): return b ? "true" : "false"
        default: return nil
        }
    }

    /// A number, or a numeric string ("2500", " 45.5 ", "2 pcs" → 2).
    public var lenientDouble: Double? {
        switch self {
        case .number(let d): return d
        case .string(let s):
            let t = s.trimmingCharacters(in: .whitespaces)
            if let d = Double(t) { return d }
            return Self.leadingNumber(in: t)
        case .bool(let b): return b ? 1 : 0
        default: return nil
        }
    }

    static func leadingNumber(in text: String) -> Double? {
        var end = text.startIndex
        var seenDigit = false
        var seenDot = false
        for (i, ch) in text.enumerated() {
            let idx = text.index(text.startIndex, offsetBy: i)
            if ch == "-" && i == 0 { end = text.index(after: idx); continue }
            if ch.isNumber { seenDigit = true; end = text.index(after: idx); continue }
            if ch == "." && !seenDot && seenDigit { seenDot = true; end = text.index(after: idx); continue }
            break
        }
        guard seenDigit else { return nil }
        return Double(text[text.startIndex..<end].trimmingCharacters(in: CharacterSet(charactersIn: ".")))
    }
}

extension JSONValue: Codable {
    public init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null; return }
        if let b = try? c.decode(Bool.self) { self = .bool(b); return }
        if let d = try? c.decode(Double.self) { self = .number(d); return }
        if let s = try? c.decode(String.self) { self = .string(s); return }
        if let a = try? c.decode([JSONValue].self) { self = .array(a); return }
        if let o = try? c.decode([String: JSONValue].self) { self = .object(o); return }
        throw DecodingError.dataCorruptedError(in: c, debugDescription: "not JSON")
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .null: try c.encodeNil()
        case .bool(let b): try c.encode(b)
        case .number(let d): try c.encode(d)
        case .string(let s): try c.encode(s)
        case .array(let a): try c.encode(a)
        case .object(let o): try c.encode(o)
        }
    }
}

extension JSONValue: ExpressibleByStringLiteral, ExpressibleByIntegerLiteral, ExpressibleByFloatLiteral,
                     ExpressibleByBooleanLiteral, ExpressibleByArrayLiteral, ExpressibleByDictionaryLiteral, ExpressibleByNilLiteral {
    public init(stringLiteral value: String) { self = .string(value) }
    public init(integerLiteral value: Int) { self = .number(Double(value)) }
    public init(floatLiteral value: Double) { self = .number(value) }
    public init(booleanLiteral value: Bool) { self = .bool(value) }
    public init(arrayLiteral elements: JSONValue...) { self = .array(elements) }
    public init(dictionaryLiteral elements: (String, JSONValue)...) { self = .object(Dictionary(elements, uniquingKeysWith: { $1 })) }
    public init(nilLiteral: ()) { self = .null }
}

public extension JSONValue {
    /// Parse text; nil when it is not JSON.
    static func parse(_ text: String) -> JSONValue? {
        guard let data = text.data(using: .utf8) else { return nil }
        return try? NeemaJSON.decoder.decode(JSONValue.self, from: data)
    }

    /// Compact JSON text.
    var text: String {
        (try? NeemaJSON.encoder.encode(self)).flatMap { String(data: $0, encoding: .utf8) } ?? "null"
    }
}

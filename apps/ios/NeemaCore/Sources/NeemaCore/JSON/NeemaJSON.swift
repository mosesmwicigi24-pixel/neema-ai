import Foundation

/// The one JSON configuration, as `NeemaJson` on Android: unknown keys are
/// ignored by Codable already; leniency (numbers as strings, null for a
/// non-optional) lives in the models' own decoding through `LenientKeyed`.
public enum NeemaJSON {
    public static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        return d
    }()

    public static let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return e
    }()

    public static func decode<T: Decodable>(_ type: T.Type, from text: String) throws -> T {
        try decoder.decode(type, from: Data(text.utf8))
    }

    public static func encode<T: Encodable>(_ value: T) throws -> String {
        String(decoding: try encoder.encode(value), as: UTF8.self)
    }
}

/// Lenient reads on a keyed container — what kotlinx's `isLenient` +
/// `coerceInputValues` + `explicitNulls = false` give for free: a missing
/// key or a null reads as the default; a number may arrive as text and text
/// as a number; a bool as "true"/"false"/0/1.
public struct LenientKeyed<Key: CodingKey> {
    public let container: KeyedDecodingContainer<Key>
    public init(_ container: KeyedDecodingContainer<Key>) { self.container = container }

    public func value(_ key: Key) -> JSONValue? {
        guard container.contains(key) else { return nil }
        let v = try? container.decode(JSONValue.self, forKey: key)
        if case .null? = v { return nil }
        return v
    }

    public func string(_ key: Key) -> String? { value(key)?.content }
    public func string(_ key: Key, default d: String) -> String { string(key) ?? d }
    public func double(_ key: Key) -> Double? { value(key)?.lenientDouble }
    public func double(_ key: Key, default d: Double) -> Double { double(key) ?? d }
    public func int(_ key: Key) -> Int? { double(key).map { Int($0) } }
    public func int(_ key: Key, default d: Int) -> Int { int(key) ?? d }
    public func int64(_ key: Key) -> Int64? { double(key).map { Int64($0) } }

    public func bool(_ key: Key) -> Bool? {
        guard let v = value(key) else { return nil }
        switch v {
        case .bool(let b): return b
        case .number(let d): return d != 0
        case .string(let s):
            switch s.lowercased() { case "true", "1", "yes": return true; case "false", "0", "no", "": return false; default: return nil }
        default: return nil
        }
    }
    public func bool(_ key: Key, default d: Bool) -> Bool { bool(key) ?? d }

    public func object<T: Decodable>(_ key: Key, as type: T.Type = T.self) -> T? {
        guard let v = value(key), !v.isNull else { return nil }
        return try? container.decode(T.self, forKey: key)
    }

    public func list<T: Decodable>(_ key: Key, as type: T.Type = T.self) -> [T] {
        guard let v = value(key), case .array = v else { return [] }
        return (try? container.decode([T].self, forKey: key)) ?? []
    }

    /// `LenientStringListSerializer`: null → [], a bare string → [it], and in
    /// a list numbers are kept as text, nulls and objects dropped.
    public func stringList(_ key: Key) -> [String] {
        guard let v = value(key) else { return [] }
        return Self.lenientStrings(v)
    }

    public static func lenientStrings(_ v: JSONValue) -> [String] {
        switch v {
        case .array(let items):
            return items.compactMap { $0.content }.filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        case .null: return []
        case .object: return []
        default:
            let s = v.content ?? ""
            return s.trimmingCharacters(in: .whitespaces).isEmpty ? [] : [s]
        }
    }

    /// `VariantAttributesSerializer`: an object's primitive entries as text,
    /// nulls dropped; anything else (PHP's `[]`) is no attributes.
    public func stringMap(_ key: Key) -> [String: String] {
        guard let v = value(key), case .object(let o) = v else { return [:] }
        var out: [String: String] = [:]
        for (k, val) in o { if let c = val.content { out[k] = c } }
        return out
    }
}

public extension Decoder {
    func lenient<Key: CodingKey>(_ keys: Key.Type) throws -> LenientKeyed<Key> {
        LenientKeyed(try container(keyedBy: keys))
    }
}

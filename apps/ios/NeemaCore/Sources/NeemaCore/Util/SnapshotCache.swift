import Foundation

/// Stale-while-revalidate snapshots (Android `core/util/SnapshotCache.kt`,
/// the web's hooks/useApi.ts): the last good payload per key, so a cold start
/// paints instantly from disk while the real fetch runs. Keys are scoped per
/// agent so the next person on a shared phone never sees the previous agent's
/// data. Best-effort — any failure is a cache miss.
public final class SnapshotCache: @unchecked Sendable {
    private let dir: URL
    private let lock = NSLock()

    public init(directory: URL) {
        dir = directory
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    /// `Caches/snapshots` in the app's sandbox.
    public static func standard() -> SnapshotCache {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first ?? URL(fileURLWithPath: NSTemporaryDirectory())
        return SnapshotCache(directory: base.appendingPathComponent("snapshots", isDirectory: true))
    }

    /// A fresh, empty cache in a temporary directory (tests, previews).
    public static func temporary() -> SnapshotCache {
        SnapshotCache(directory: URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("neema-snapshots-\(UUID().uuidString)", isDirectory: true))
    }

    private static func safe(_ s: String) -> String {
        String(s.map { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" ? $0 : "_" })
    }

    private func file(_ scope: String, _ key: String) -> URL { dir.appendingPathComponent("\(Self.safe(scope))_\(Self.safe(key)).json") }

    public func read<T: Decodable>(_ scope: String?, _ key: String, as type: T.Type = T.self) -> T? {
        guard let scope = scope else { return nil }
        return lock.sync {
            guard let data = try? Data(contentsOf: file(scope, key)) else { return nil }
            return try? NeemaJSON.decode(T.self, from: String(decoding: data, as: UTF8.self))
        }
    }

    public func write<T: Encodable>(_ scope: String?, _ key: String, _ value: T) {
        guard let scope = scope else { return }
        lock.sync {
            guard let text = try? NeemaJSON.encode(value) else { return }
            try? Data(text.utf8).write(to: file(scope, key), options: .atomic)
        }
    }

    /// A payload kept as the text it came in (a page re-read with the same lenient decoding).
    public func readText(_ scope: String?, _ key: String) -> String? {
        guard let scope = scope else { return nil }
        return lock.sync {
            guard let data = try? Data(contentsOf: file(scope, key)) else { return nil }
            return String(decoding: data, as: UTF8.self)
        }
    }

    public func writeText(_ scope: String?, _ key: String, _ text: String) {
        guard let scope = scope else { return }
        lock.sync { try? Data(text.utf8).write(to: file(scope, key), options: .atomic) }
    }

    /// Forget one snapshot (a draft that was sent, a conversation that was closed).
    public func delete(_ scope: String?, _ key: String) {
        guard let scope = scope else { return }
        lock.sync { try? FileManager.default.removeItem(at: file(scope, key)) }
    }

    public func clear() {
        lock.sync {
            let items = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
            for i in items { try? FileManager.default.removeItem(at: i) }
        }
    }
}

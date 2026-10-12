import Foundation

/// What the web keeps in its NextAuth JWT cookie, kept here in the Keychain.
public struct Session: Equatable, Codable, Sendable {
    public var accessToken: String
    public var refreshToken: String?
    public var agentId: String
    public var email: String
    public var name: String
    public var role: String
    public var isSuperuser: Bool
    /// "direct" = FastAPI tokens; "nextauth" = tokens minted through the web's NextAuth.
    public var mode: String
    /// NextAuth session cookie (only in "nextauth" mode) — lets us ask the web to refresh.
    public var nextAuthCookie: String?

    public init(accessToken: String, refreshToken: String?, agentId: String, email: String, name: String,
                role: String, isSuperuser: Bool, mode: String, nextAuthCookie: String? = nil) {
        self.accessToken = accessToken
        self.refreshToken = refreshToken
        self.agentId = agentId
        self.email = email
        self.name = name
        self.role = role
        self.isSuperuser = isSuperuser
        self.mode = mode
        self.nextAuthCookie = nextAuthCookie
    }
}

/// Small string storage behind the session: the Keychain on a device, memory in tests.
public protocol SecureStore: AnyObject {
    func string(_ key: String) throws -> String?
    func set(_ value: String?, for key: String) throws
    func removeAll() throws
}

public final class MemoryStore: SecureStore {
    private let lock = NSLock()
    private var values: [String: String] = [:]
    public init() {}
    public func string(_ key: String) throws -> String? { lock.lock(); defer { lock.unlock() }; return values[key] }
    public func set(_ value: String?, for key: String) throws { lock.lock(); values[key] = value; lock.unlock() }
    public func removeAll() throws { lock.lock(); values.removeAll(); lock.unlock() }
    public var snapshot: [String: String] { lock.lock(); defer { lock.unlock() }; return values }
}

/// The signed-in session, kept across launches. Opening the store can
/// succeed while READING it fails (a Keychain item from another device's
/// backup): the unreadable entry is wiped and the agent signs in afresh,
/// never a crash at launch.
public final class SessionStore {
    private let store: SecureStore
    public let session: Watched<Session?>
    public var current: Session? { session.value }
    /// Told when a stored session could not be read (recorded as a non-fatal).
    public static var onReadFailure: ((Error) -> Void)?

    public init(store: SecureStore) {
        self.store = store
        session = Watched(Self.read(store))
    }

    private static func read(_ store: SecureStore) -> Session? {
        do { return try readOrThrow(store) }
        catch {
            onReadFailure?(error)
            try? store.removeAll()
            return nil
        }
    }

    private static func readOrThrow(_ store: SecureStore) throws -> Session? {
        guard let token = try store.string("access"), let agentId = try store.string("agent_id") else { return nil }
        return Session(
            accessToken: token,
            refreshToken: try store.string("refresh"),
            agentId: agentId,
            email: try store.string("email") ?? "",
            name: try store.string("name") ?? "",
            role: try store.string("role") ?? "agent",
            isSuperuser: try store.string("superuser") == "true",
            mode: try store.string("mode") ?? "direct",
            nextAuthCookie: try store.string("na_cookie")
        )
    }

    public func save(_ s: Session) {
        try? store.set(s.accessToken, for: "access")
        try? store.set(s.refreshToken, for: "refresh")
        try? store.set(s.agentId, for: "agent_id")
        try? store.set(s.email, for: "email")
        try? store.set(s.name, for: "name")
        try? store.set(s.role, for: "role")
        try? store.set(s.isSuperuser ? "true" : "false", for: "superuser")
        try? store.set(s.mode, for: "mode")
        try? store.set(s.nextAuthCookie, for: "na_cookie")
        session.value = s
    }

    /// Forget the tokens but remember who was signed in (for the re-auth prompt).
    public func clear() {
        let email = current?.email
        try? store.removeAll()
        if let e = email { try? store.set(e, for: "last_email") }
        session.value = nil
    }

    public var lastEmail: String? { current?.email ?? ((try? store.string("last_email")) ?? nil) }
}

#if canImport(Security) && !os(Linux)
import Security

/// The Keychain, one generic-password item per key, this device only
/// (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`: the socket and calls
/// need the token before the first unlock after a restart; a backup
/// restored to another phone does not carry it).
public final class KeychainStore: SecureStore {
    public enum KeychainError: Error { case status(OSStatus) }
    private let service: String

    public init(service: String = "ke.co.bethanyhouse.neema.session") { self.service = service }

    private func query(_ key: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: key]
    }

    public func string(_ key: String) throws -> String? {
        var q = query(key)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        let status = SecItemCopyMatching(q as CFDictionary, &out)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess else { throw KeychainError.status(status) }
        guard let data = out as? Data, let s = String(data: data, encoding: .utf8) else { throw KeychainError.status(errSecDecode) }
        return s
    }

    public func set(_ value: String?, for key: String) throws {
        guard let v = value else {
            let status = SecItemDelete(query(key) as CFDictionary)
            if status != errSecSuccess && status != errSecItemNotFound { throw KeychainError.status(status) }
            return
        }
        let data = Data(v.utf8)
        let update: [String: Any] = [kSecValueData as String: data]
        let status = SecItemUpdate(query(key) as CFDictionary, update as CFDictionary)
        if status == errSecSuccess { return }
        guard status == errSecItemNotFound else { throw KeychainError.status(status) }
        var add = query(key)
        add[kSecValueData as String] = data
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let added = SecItemAdd(add as CFDictionary, nil)
        guard added == errSecSuccess else { throw KeychainError.status(added) }
    }

    public func removeAll() throws {
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
        let status = SecItemDelete(q as CFDictionary)
        if status != errSecSuccess && status != errSecItemNotFound { throw KeychainError.status(status) }
    }
}
#endif

import Foundation

/// How a CRM request failed, in the terms the panel acts on (Android
/// `CustomerErrors.kt`). The web's crmReq throws one opaque `Error` for all
/// of these and says "Failed to save"; on a Nairobi phone network the
/// difference matters — an offline tap can simply be retried, a timeout may
/// already have landed, a 404 means someone else merged or removed the
/// record, a 429 means back off.
public enum CrmFailure: Equatable, Sendable {
    case offline, uncertain, sessionExpired, forbidden, notFound, conflict, invalid, rateLimited, server, unreadable, other
}

public enum CrmErrors {
    public static func failure(of e: Error) -> CrmFailure {
        if e is DecodingError { return .unreadable }
        guard let api = e as? ApiError else {
            if let t = e as? TransportError {
                if case .timedOut = t { return .uncertain }
                if case .network = t { return NetErrors.neverConnected(e) ? .offline : .uncertain }
            }
            return .other
        }
        if api.malformed { return .unreadable }
        switch api.status {
        case 0:
            if NetErrors.timedOut(api) { return .uncertain }
            return NetErrors.neverConnected(api) ? .offline : .uncertain
        case 401: return .sessionExpired
        case 403: return .forbidden
        case 404, 410: return .notFound
        case 409: return .conflict
        case 400, 422: return .invalid
        case 429: return .rateLimited
        // A gateway that gave up waiting: the request may well be running.
        case 504: return .uncertain
        case 500...599: return .server
        default: return .other
        }
    }

    /// The request may have reached the server and been acted on: never call that a failure.
    public static func mayHaveLanded(_ e: Error) -> Bool { failure(of: e) == .uncertain }

    /// The server's `detail` when it is written for people: a JSON `{"detail": "…"}`
    /// string (not pydantic's list, not a proxy's HTML page, not a stack trace).
    public static func humanDetail(_ e: Error) -> String? {
        guard let api = e as? ApiError, api.status < 500, api.status != 0 else { return nil }
        guard let obj = JSONValue.parse(api.body)?.objectValue, let v = obj["detail"], case .string(let raw) = v else { return nil }
        let d = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if d.isEmpty || d.count > 160 || d.contains("<") || d.hasPrefix("[") || d.hasPrefix("{") { return nil }
        var t = d.prefix(1).uppercased() + d.dropFirst()
        while t.hasSuffix(".") { t.removeLast() }
        return t + "."
    }

    /// Plain words for why it failed, to follow "Failed to save — ".
    public static func reason(_ e: Error) -> String {
        switch failure(of: e) {
        case .offline: return "you're offline. Check your connection and try again."
        case .uncertain: return "the server took too long to answer."
        case .sessionExpired: return "your session expired. Sign in again, then retry."
        case .forbidden:
            if let d = humanDetail(e), d.caseInsensitiveCompare("Admin only.") != .orderedSame, d.caseInsensitiveCompare("Not authenticated.") != .orderedSame {
                return lowercaseFirst(d)
            }
            return "you don't have permission to do that."
        case .notFound: return "it no longer exists."
        case .conflict: return humanDetail(e).map(lowercaseFirst) ?? "it changed meanwhile."
        case .invalid: return humanDetail(e).map(lowercaseFirst) ?? "the server didn't accept that."
        case .rateLimited: return "too many requests. Wait a moment, then try again."
        case .server: return "the server had a problem. Try again in a moment."
        case .unreadable: return "the server sent an answer the app couldn't read."
        case .other: return "something went wrong. Try again."
        }
    }

    /// Keep acronyms, names and "I" ("WhatsApp …", "KES …") as they are.
    static func lowercaseFirst(_ s: String) -> String {
        let word = s.split(separator: " ", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? s
        guard let first = word.first, first.isUppercase, word != "I" else { return s }
        let rest = word.dropFirst()
        let plain = rest.allSatisfy { $0.isLowercase }
        return plain ? first.lowercased() + s.dropFirst() : s
    }
}

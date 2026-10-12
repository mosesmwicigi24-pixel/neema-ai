import Foundation

/// What a failed request means to the person holding the phone, for the
/// Reports, Analytics, Catalog, Team, Profile and Settings screens (Android
/// `feature/reports/NetErrors.kt`).
///
/// The web toasts `e.message`, which reads "POST /admin/agents → 500: Internal
/// Server Error" or a proxy's HTML page. Here each failure gets plain words:
/// the server's `detail` only when it was written for people, never markup, a
/// JSON dump or FastAPI's stock "Not Found" / "Internal Server Error".
public enum FriendlyErrors {
    public static let OFFLINE_TEXT = "You're offline or the server can't be reached — check your connection and try again."
    public static let TIMEOUT_TEXT = "The server took too long to answer — check your connection and try again."
    public static let DROPPED_TEXT = "The connection dropped before the answer arrived — try again."
    public static let BUSY_TEXT = "Too many requests — wait a moment, then try again."
    public static let DOWN_TEXT = "The server is unavailable right now — try again in a moment."
    public static let EXPIRED_TEXT = "Your session expired — sign in again, then retry."
    public static let GARBLED_TEXT = "The server sent an answer the app couldn't read — try again."

    /// The HTTP status of a failed call; 0 = never got an answer; nil = not an HTTP failure.
    public static func httpStatus(_ e: Error) -> Int? { (e as? ApiError)?.status }

    /// The phone never reached the server: nothing can have happened there.
    public static func neverSent(_ e: Error) -> Bool {
        guard let api = e as? ApiError, api.status == 0 else { return false }
        return NetErrors.neverConnected(api)
    }

    public static func isTimeout(_ e: Error) -> Bool {
        if let api = e as? ApiError { return api.timedOut || api.body.lowercased().contains("timed out") || api.body.lowercased().contains("timeout") }
        if let t = e as? TransportError, case .timedOut = t { return true }
        return false
    }

    /// A timeout or a connection that dropped after the request left: the server
    /// may have done it. A request that never left (no network, the host
    /// unreachable, the connection refused) did not.
    public static func mayHaveApplied(_ e: Error) -> Bool {
        let transportFailure = ((e as? ApiError)?.status == 0) || (e is TransportError && !SalesErrors.isCancellation(e))
        return transportFailure && !neverSent(e)
    }

    private static let STOCK = ["not found", "internal server error", "bad gateway", "service unavailable", "gateway timeout", "method not allowed"]

    /// The server's `detail` when it is a sentence meant for a person, else nil.
    public static func readableDetail(_ api: ApiError) -> String? {
        let d = api.detail.trimmingCharacters(in: .whitespacesAndNewlines)
        if d.isEmpty || d.count > 200 { return nil }
        if d.hasPrefix("<") || d.hasPrefix("{") || d.hasPrefix("[") { return nil }
        // Only FastAPI's own `{"detail": …}` speaks for the server; a bare body is
        // a proxy's page or a stack's stock text.
        if !api.body.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("{") { return nil }
        if STOCK.contains(d.lowercased()) { return nil }
        return d
    }

    /// Plain words for `e`. `fallback` is what a failure with nothing better to
    /// say reads (a 500, an unknown status); `notFound` what a 404 says when the
    /// server gave no sentence of its own.
    public static func text(
        of e: Error,
        fallback: String = "Something went wrong — please try again.",
        notFound: String = "That no longer exists — someone else may have removed it."
    ) -> String {
        if let api = e as? ApiError {
            // The core flags a 2xx it couldn't parse (captive portal, cut-off body).
            if api.malformed { return GARBLED_TEXT }
            switch api.status {
            case 0:
                if isTimeout(api) { return TIMEOUT_TEXT }
                if neverSent(api) { return OFFLINE_TEXT }
                return DROPPED_TEXT
            case 401: return EXPIRED_TEXT
            case 403:
                if let d = readableDetail(api), d.caseInsensitiveCompare("Not authenticated") != .orderedSame, d.caseInsensitiveCompare("Forbidden") != .orderedSame { return d }
                return "You don't have permission to do that."
            case 404:
                if let d = readableDetail(api), !d.lowercased().hasSuffix(" not found") { return d }
                return notFound
            case 409: return readableDetail(api) ?? "That changed on the server meanwhile — showing the latest."
            case 422: return readableDetail(api) ?? "The server couldn't accept that — check the fields and try again."
            case 429: return BUSY_TEXT
            case 502, 503, 504: return DOWN_TEXT
            case 500...599: return fallback
            default: return readableDetail(api) ?? fallback
            }
        }
        if e is DecodingError { return GARBLED_TEXT }
        if let t = e as? TransportError {
            if case .timedOut = t { return TIMEOUT_TEXT }
            return DROPPED_TEXT
        }
        return fallback
    }

    /// `text` with every occurrence of `secret` masked — a typed password is never read back in a toast.
    public static func masking(_ text: String, secret: String) -> String {
        secret.count < 3 ? text : text.replacingOccurrences(of: secret, with: "••••••")
    }
}

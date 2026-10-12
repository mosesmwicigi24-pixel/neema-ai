import Foundation

/// What to tell a person when a request failed — one voice for the whole app.
///
/// The server's own `detail` wins when it is written for people ("Order not
/// found", "Stock is too low for 3 × Kiondo"); FastAPI's stock phrases
/// ("Not Found", "Internal Server Error"), pydantic field lists and proxy
/// HTML pages never reach the screen — the status speaks instead.
public enum ErrorText {
    public static let OFFLINE = "Network problem — check your connection"
    public static let TIMED_OUT = "The server is taking too long to answer. Check your connection and try again."
    public static let SESSION = "Your session has expired. Sign in again to continue."
    public static let FORBIDDEN = "You don't have permission to do that."
    public static let GONE = "That's no longer there — someone may have deleted it."
    public static let CONFLICT = "That changed in the meantime. Refresh to see the latest."
    public static let TOO_LARGE = "That's too large to send."
    public static let INVALID = "Some details weren't accepted. Please check them and try again."
    public static let SERVER = "Something went wrong on the server. Please try again."
    public static let DOWN = "Neema's server can't be reached right now. Please try again in a moment."
    public static let UNREADABLE = "The server sent an answer the app couldn't read. Please try again."
    public static let UNKNOWN = "Something went wrong"

    /// Detail strings FastAPI / Starlette / proxies use that say nothing to a person.
    private static let STOCK: Set<String> = [
        "not found", "method not allowed", "internal server error", "bad gateway", "service unavailable",
        "gateway timeout", "bad request", "unprocessable entity", "too many requests", "forbidden",
        "unauthorized", "not authenticated", "conflict", "request entity too large", "payload too large",
    ]

    /// A `detail` that reads as a sentence for people, or nil.
    public static func humanDetail(_ e: ApiError) -> String? {
        let d = e.detail.trimmingCharacters(in: .whitespacesAndNewlines)
        if d.isEmpty || d.count > 300 { return nil }
        if let f = d.first, "<{[".contains(f) { return nil }
        var lowered = d.lowercased()
        while lowered.hasSuffix(".") { lowered.removeLast() }
        if STOCK.contains(lowered) { return nil }
        // A pydantic 422 list names fields ("field required; value is not a valid email").
        if e.status == 422, e.body.range(of: #""detail"\s*:\s*\["#, options: .regularExpression) != nil { return nil }
        return d
    }

    public static func of(_ t: Error) -> String {
        switch t {
        case let e as ApiError: return ofApi(e)
        case let e as AuthError: return e.message.isEmpty ? UNKNOWN : e.message
        case is DecodingError: return UNREADABLE
        case let e as RefreshUnavailable: return e.timedOut ? TIMED_OUT : (e.status == 0 ? OFFLINE : DOWN)
        default:
            let m = ((t as? LocalizedError)?.errorDescription ?? "").trimmingCharacters(in: .whitespaces)
            return m.isEmpty ? UNKNOWN : m
        }
    }

    private static func ofApi(_ e: ApiError) -> String {
        if e.malformed { return UNREADABLE }
        let human = humanDetail(e)
        switch e.status {
        case 0: return e.timedOut ? TIMED_OUT : OFFLINE
        case 401: return SESSION
        case 403: return human ?? FORBIDDEN
        case 404: return human ?? GONE
        case 409: return human ?? CONFLICT
        case 413: return TOO_LARGE
        case 422, 400: return human ?? INVALID
        case 429: return tooMany(e.retryAfterSeconds)
        // FastAPI uses these for real answers too ("WhatsApp sending is not
        // configured.", "Hub rejected the order: …"); a bare gateway page is an outage.
        case 502, 503, 504: return human ?? DOWN
        case 500...599: return human ?? SERVER
        default: return human ?? "Something went wrong (\(e.status)). Please try again."
        }
    }

    private static func tooMany(_ after: Int64?) -> String {
        guard let after = after, after > 1 else { return "Too many requests. Please wait a moment and try again." }
        if after < 90 { return "Too many requests. Please wait \(after) seconds and try again." }
        return "Too many requests. Please wait \((after + 59) / 60) minutes and try again."
    }
}

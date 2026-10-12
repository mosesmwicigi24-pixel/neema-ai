import Foundation

/// How much of an error body is kept (plenty for any FastAPI `detail`).
public let MAX_ERROR_BODY = 64 * 1024

/// Thrown for any non-2xx answer; `status` is the HTTP code (0 = the request
/// never got an answer: offline, connection refused or dropped, timed out).
///
/// `retryAfterSeconds` is a 429/503's `Retry-After` (seconds form) when sent.
/// `malformed` marks a 2xx whose body could not be read as what was asked
/// for (a captive portal's page, a cut-off answer); `status` is then the
/// code that came back. The Swift twin of Android's `ApiException`.
public struct ApiError: Error, CustomStringConvertible, LocalizedError {
    public let status: Int
    public let method: String
    public let path: String
    public let body: String
    public let retryAfterSeconds: Int64?
    public let malformed: Bool
    /// The transport failure behind a status-0 answer (kept for crash reports and logs).
    public let cause: Error?
    /// The `X-Neema-Reason` header a calling route's refusal carries (its `code`).
    public let reasonHeader: String?

    public init(
        status: Int, method: String, path: String, body: String,
        retryAfterSeconds: Int64? = nil, malformed: Bool = false,
        cause: Error? = nil, reasonHeader: String? = nil
    ) {
        self.status = status
        self.method = method
        self.path = path
        self.body = body
        self.retryAfterSeconds = retryAfterSeconds
        self.malformed = malformed
        self.cause = cause
        self.reasonHeader = reasonHeader
    }

    public var message: String { "\(method) \(path) → \(status): \(String(body.prefix(500)))" }
    public var description: String { message }
    public var errorDescription: String? { message }

    /// The request ran out of time (the 30 s ceiling, or the long client's).
    public var timedOut: Bool { status == 0 && body.hasPrefix("timed out") }

    /// The server's `detail` when it sent one (FastAPI convention): a plain
    /// string from `HTTPException(detail=…)`, or — for a request pydantic
    /// rejected (422) — a list of `{loc, msg, type}` errors, read as their
    /// messages. A plain-text answer ("Internal Server Error") is shown
    /// trimmed; a proxy's HTML page never is: it reads as no detail at all.
    public var detail: String {
        if let d = bodyObject?["detail"] {
            switch d {
            case .null:
                break
            case .string, .number, .bool:
                if let c = d.content { return c }
            case .array(let items):
                let msgs = items.compactMap { e -> String? in
                    if let o = e.objectValue { return o["msg"]?.content }
                    return e.content
                }
                if !msgs.isEmpty { return msgs.joined(separator: "; ") }
            case .object(let o):
                return o["message"]?.content ?? o["error"]?.content ?? d.text
            }
        }
        let t = body.trimmingCharacters(in: .whitespacesAndNewlines)
        return Self.looksLikeHtml(t) ? "" : String(t.prefix(200))
    }

    /// The error body as a JSON object (nil when it is not one).
    private var bodyObject: [String: JSONValue]? { JSONValue.parse(body)?.objectValue }

    /// A structured refusal's string field (`{detail, code, action, …}` —
    /// CALLING_UX.md §2.1), e.g. `request_available_at`. Nil when absent,
    /// not a string, or the body isn't JSON: every older answer reads as none.
    public func field(_ name: String) -> String? {
        guard let v = bodyObject?[name], case .string(let s) = v else { return nil }
        return s.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : s
    }

    /// Meta's error code ("138006", "190") or ours (template_required, …): the body's `code`, else `X-Neema-Reason`.
    public var code: String? {
        if let f = field("code") { return f }
        if let c = bodyObject?["code"]?.content, !c.trimmingCharacters(in: .whitespaces).isEmpty, c != "null" { return c }
        if let r = reasonHeader?.trimmingCharacters(in: .whitespaces), !r.isEmpty { return r }
        return nil
    }

    /// What to offer: retry | request_permission | wait | admin | none (nil: an older answer that doesn't say).
    public var action: String? { field("action") }

    /// A web page rather than an API answer (a proxy's error page, a captive portal).
    public static func looksLikeHtml(_ text: String) -> Bool {
        let t = String(text.drop(while: { $0.isWhitespace }).prefix(64)).lowercased()
        return t.hasPrefix("<!doctype") || t.hasPrefix("<html") || t.hasPrefix("<head") ||
            t.hasPrefix("<body") || t.hasPrefix("<?xml") || (t.hasPrefix("<") && text.contains("</"))
    }
}

/// The auth server could not be asked (offline, timed out, 5xx, 429): the
/// session may be perfectly good, so this must never read as "signed out".
/// `status` is 0 for no answer, else the auth server's code.
public struct RefreshUnavailable: Error, LocalizedError {
    public let status: Int
    public let timedOut: Bool
    public let message: String
    public init(status: Int, timedOut: Bool, message: String) {
        self.status = status
        self.timedOut = timedOut
        self.message = message
    }
    public var errorDescription: String? { message }
}

/// Every sign-in failure, with a message meant for people (Android's `AuthException`).
public struct AuthError: Error, Equatable, LocalizedError {
    public let message: String
    public init(_ message: String) { self.message = message }
    public var errorDescription: String? { message }
}

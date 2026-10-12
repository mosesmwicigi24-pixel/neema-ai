import Foundation

/// A call request's structured refusal (routers/admin.py: `{"detail", "code", "action"}`).
public struct CallRefusal: Equatable, Sendable {
    public let code: String
    public let action: String?
    public let detail: String
    /// `template_required`, and this agent can fix it in Settings → WhatsApp calling.
    public let adminCanFix: Bool
    public init(code: String, action: String?, detail: String, adminCanFix: Bool) {
        self.code = code; self.action = action; self.detail = detail; self.adminCanFix = adminCanFix
    }
}

/// The words of a call-permission request that didn't go (Android `CallManager.permissionRequestError` / `requestRefusal`).
public enum CallRequests {
    public static let SESSION_EXPIRED = "Your session expired — sign in again"

    /// A call request's structured refusal (nil for a plain network failure).
    public static func refusal(_ e: Error?, admin: Bool) -> CallRefusal? {
        guard let api = e as? ApiError, let code = api.code else { return nil }
        return CallRefusal(code: code, action: api.field("action"), detail: api.detail.trimmingCharacters(in: .whitespacesAndNewlines),
                           adminCanFix: admin && code == "template_required")
    }

    public static func permissionRequestError(_ e: Error?) -> String {
        guard let e = e else { return "Couldn't send the call request" }
        if let api = e as? ApiError {
            if api.status == 0 && api.body.hasPrefix("timed out") {
                return "No answer from the server — the request may still arrive. Check the chat before sending again."
            }
            if api.status == 0 { return "No connection — the call request wasn't sent" }
            if api.status == 401 { return SESSION_EXPIRED }
            // A structured refusal: the server's sentence, without its "permission request failed:" prefix.
            if api.code != nil {
                var d = api.detail.trimmingCharacters(in: .whitespacesAndNewlines)
                if d.lowercased().hasPrefix("permission request failed:") { d = String(d.dropFirst("permission request failed:".count)).trimmingCharacters(in: .whitespaces) }
                if !d.isEmpty && !d.hasPrefix("<") && d.count <= 200 { return d.prefix(1).uppercased() + d.dropFirst() }
                return "Couldn't send the call request"
            }
        }
        return "Couldn't send the call request"
    }
}

import XCTest
@testable import NeemaCore

/// dash.errorText: one voice for every failure, with words for people.
final class ErrorTextTests: XCTestCase {
    private func of(_ status: Int, _ body: String = "", retryAfter: Int64? = nil) -> String {
        ErrorText.of(ApiError(status: status, method: "POST", path: "/admin/x", body: body, retryAfterSeconds: retryAfter))
    }

    func testNetworkAndTimeout() {
        XCTAssertEqual(ErrorText.OFFLINE, of(0, "Unable to resolve host"))
        XCTAssertEqual(ErrorText.OFFLINE, of(0, "Connection reset"))
        XCTAssertEqual(ErrorText.TIMED_OUT, of(0, "timed out after 30s"))
        XCTAssertEqual(ErrorText.TIMED_OUT, of(0, "timed out after 10 min"))
    }

    func testTheServersOwnWordsWinWhenMeantForPeople() {
        XCTAssertEqual("Order not found", of(404, #"{"detail":"Order not found"}"#))
        XCTAssertEqual("Only admins can do this", of(403, #"{"detail":"Only admins can do this"}"#))
        XCTAssertEqual("Conversation is already assigned", of(409, #"{"detail":"Conversation is already assigned"}"#))
        XCTAssertEqual("WhatsApp sending is not configured.", of(503, #"{"detail":"WhatsApp sending is not configured."}"#))
        XCTAssertEqual("Could not compose the message", of(500, #"{"detail":"Could not compose the message"}"#))
        XCTAssertEqual("Email already registered", of(422, #"{"detail":"Email already registered"}"#))
    }

    func testStockPhrasesPagesAndFieldListsGetPlainWords() {
        XCTAssertEqual(ErrorText.SESSION, of(401, "Session expired"))
        XCTAssertEqual(ErrorText.FORBIDDEN, of(403, #"{"detail":"Not authenticated"}"#))
        XCTAssertEqual(ErrorText.GONE, of(404, #"{"detail":"Not Found"}"#))
        XCTAssertEqual(ErrorText.CONFLICT, of(409, ""))
        XCTAssertEqual(ErrorText.TOO_LARGE, of(413, "<html><head><title>413 Request Entity Too Large</title></head></html>"))
        XCTAssertEqual(ErrorText.INVALID, of(422, #"{"detail":[{"loc":["body","email"],"msg":"field required","type":"missing"}]}"#))
        XCTAssertEqual(ErrorText.SERVER, of(500, #"{"detail":"Internal Server Error"}"#))
        XCTAssertEqual(ErrorText.SERVER, of(500, "Internal Server Error"))
        XCTAssertEqual(ErrorText.DOWN, of(502, "<html>Bad Gateway</html>"))
        XCTAssertEqual(ErrorText.DOWN, of(503, ""))
        XCTAssertEqual(ErrorText.DOWN, of(504, "<!DOCTYPE html><html><body>Gateway Time-out</body></html>"))
        XCTAssertEqual("Something went wrong (418). Please try again.", of(418, ""))
    }

    func testBackOffWordsFollowRetryAfter() {
        XCTAssertEqual("Too many requests. Please wait a moment and try again.", of(429, ""))
        XCTAssertEqual("Too many requests. Please wait 30 seconds and try again.", of(429, "", retryAfter: 30))
        XCTAssertEqual("Too many requests. Please wait 2 minutes and try again.", of(429, "", retryAfter: 120))
    }

    func testOtherThrowables() {
        XCTAssertEqual(ErrorText.UNREADABLE, ErrorText.of(ApiError(status: 200, method: "", path: "(response)", body: "<html>", malformed: true)))
        XCTAssertEqual(ErrorText.UNREADABLE, ErrorText.of(DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "Unexpected JSON token"))))
        XCTAssertEqual("Invalid email or password. Please try again.", ErrorText.of(AuthError("Invalid email or password. Please try again.")))
        XCTAssertEqual(ErrorText.OFFLINE, ErrorText.of(RefreshUnavailable(status: 0, timedOut: false, message: "reset")))
        XCTAssertEqual(ErrorText.TIMED_OUT, ErrorText.of(RefreshUnavailable(status: 0, timedOut: true, message: "timed out")))
        XCTAssertEqual("boom", ErrorText.of(PlainError("boom")))
        XCTAssertEqual(ErrorText.UNKNOWN, ErrorText.of(PlainError()))
    }

    func testStructuredRefusalFields() {
        let e = ApiError(status: 409, method: "POST", path: "/admin/calls/connect",
                         body: #"{"detail":"Ask first","code":"permission_required","action":"request_permission","request_available_at":"2026-10-12T10:00:00Z"}"#)
        XCTAssertEqual("permission_required", e.code)
        XCTAssertEqual("request_permission", e.action)
        XCTAssertEqual("2026-10-12T10:00:00Z", e.field("request_available_at"))
        XCTAssertNil(e.field("missing"))
        let header = ApiError(status: 502, method: "POST", path: "/x", body: "<html>", reasonHeader: " 138006 ")
        XCTAssertEqual("138006", header.code)
        XCTAssertNil(ApiError(status: 400, method: "POST", path: "/x", body: #"{"code":null}"#).code)
        XCTAssertEqual("190", ApiError(status: 400, method: "POST", path: "/x", body: #"{"code":190}"#).code)
    }

    func testDetailShapes() {
        XCTAssertEqual("a; b", ApiError(status: 422, method: "POST", path: "/x", body: #"{"detail":[{"msg":"a"},"b",{"loc":[]}]}"#).detail)
        XCTAssertEqual("nope", ApiError(status: 500, method: "POST", path: "/x", body: #"{"detail":{"message":"nope"}}"#).detail)
        XCTAssertEqual("", ApiError(status: 502, method: "POST", path: "/x", body: "  <!doctype html><html>…</html>").detail)
        XCTAssertEqual("{}", ApiError(status: 500, method: "POST", path: "/x", body: "{}").detail)
        XCTAssertTrue(ApiError(status: 0, method: "GET", path: "/x", body: "timed out after 30s").timedOut)
        XCTAssertFalse(ApiError(status: 0, method: "GET", path: "/x", body: "Connection reset").timedOut)
    }
}

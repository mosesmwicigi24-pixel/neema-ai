import Foundation
import XCTest
@testable import NeemaCore

/// The plain words the data screens use for a failure (Android `feature/reports/NetErrors.kt`).
final class FriendlyErrorsTests: XCTestCase {
    private func api(_ status: Int, _ body: String, malformed: Bool = false) -> ApiError {
        ApiError(status: status, method: "GET", path: "/admin/catalog", body: body, malformed: malformed)
    }

    func testNoAnswerReadsOfflineTimeoutOrDropped() {
        XCTAssertEqual(FriendlyErrors.text(of: api(0, "Failed to connect to neema.test/10.0.0.1:443")), FriendlyErrors.OFFLINE_TEXT)
        XCTAssertEqual(FriendlyErrors.text(of: api(0, "Unable to resolve host \"neema.test\": No address associated with hostname")), FriendlyErrors.OFFLINE_TEXT)
        XCTAssertEqual(FriendlyErrors.text(of: api(0, "timed out after 30s")), FriendlyErrors.TIMEOUT_TEXT)
        XCTAssertEqual(FriendlyErrors.text(of: api(0, "unexpected end of stream on https://neema.test/...")), FriendlyErrors.DROPPED_TEXT)
        XCTAssertTrue(FriendlyErrors.mayHaveApplied(api(0, "unexpected end of stream")))
        XCTAssertFalse(FriendlyErrors.mayHaveApplied(api(0, "Connection refused")))
        XCTAssertFalse(FriendlyErrors.mayHaveApplied(api(500, "{}")))
    }

    func testStatusesReadTheirOwnWords() {
        XCTAssertEqual(FriendlyErrors.text(of: api(401, #"{"detail":"Could not validate credentials"}"#)), FriendlyErrors.EXPIRED_TEXT)
        XCTAssertEqual(FriendlyErrors.text(of: api(403, #"{"detail":"Not allowed for your role"}"#)), "Not allowed for your role")
        XCTAssertEqual(FriendlyErrors.text(of: api(403, #"{"detail":"Forbidden"}"#)), "You don't have permission to do that.")
        XCTAssertEqual(FriendlyErrors.text(of: api(403, #"{"detail":"Not authenticated"}"#)), "You don't have permission to do that.")
        XCTAssertEqual(FriendlyErrors.text(of: api(404, #"{"detail":"Order not found"}"#)), "That no longer exists — someone else may have removed it.")
        XCTAssertEqual(FriendlyErrors.text(of: api(404, #"{"detail":"Nothing here any more"}"#)), "Nothing here any more")
        XCTAssertEqual(FriendlyErrors.text(of: api(404, "{}"), notFound: "Gone"), "Gone")
        XCTAssertEqual(FriendlyErrors.text(of: api(409, "{}")), "That changed on the server meanwhile — showing the latest.")
        XCTAssertEqual(FriendlyErrors.text(of: api(422, #"{"detail":[{"loc":["body","name"],"msg":"field required","type":"value_error"}]}"#)), "field required")
        XCTAssertEqual(FriendlyErrors.text(of: api(422, "{}")), "The server couldn't accept that — check the fields and try again.")
        XCTAssertEqual(FriendlyErrors.text(of: api(429, "{}")), FriendlyErrors.BUSY_TEXT)
        XCTAssertEqual(FriendlyErrors.text(of: api(502, "<html>Bad Gateway</html>")), FriendlyErrors.DOWN_TEXT)
        XCTAssertEqual(FriendlyErrors.text(of: api(503, "{}")), FriendlyErrors.DOWN_TEXT)
        XCTAssertEqual(FriendlyErrors.text(of: api(500, #"{"detail":"Internal Server Error"}"#)), "Something went wrong — please try again.")
        XCTAssertEqual(FriendlyErrors.text(of: api(500, "{}"), fallback: "The server couldn't send the catalogue just now."), "The server couldn't send the catalogue just now.")
        XCTAssertEqual(FriendlyErrors.text(of: api(418, #"{"detail":"I'm a teapot"}"#)), "I'm a teapot")
    }

    func testOnlyASentenceForAPersonIsRepeated() {
        XCTAssertNil(FriendlyErrors.readableDetail(api(500, "<!doctype html><h1>500</h1>")))
        XCTAssertNil(FriendlyErrors.readableDetail(api(404, #"{"detail":"Not Found"}"#)))
        XCTAssertNil(FriendlyErrors.readableDetail(api(500, "Internal Server Error")))
        XCTAssertNil(FriendlyErrors.readableDetail(api(400, "{\"detail\":\"\(String(repeating: "x", count: 201))\"}")))
        XCTAssertNil(FriendlyErrors.readableDetail(api(400, #"{"detail":{"code":"x"}}"#)))
        XCTAssertEqual(FriendlyErrors.readableDetail(api(400, #"{"detail":"Pick a shorter name"}"#)), "Pick a shorter name")
    }

    func testUnreadableAnswersAndOtherErrors() {
        XCTAssertEqual(FriendlyErrors.text(of: api(200, "<html>OK</html>", malformed: true)), FriendlyErrors.GARBLED_TEXT)
        XCTAssertEqual(FriendlyErrors.text(of: TransportError.timedOut), FriendlyErrors.TIMEOUT_TEXT)
        XCTAssertEqual(FriendlyErrors.text(of: TransportError.network("reset")), FriendlyErrors.DROPPED_TEXT)
        XCTAssertEqual(FriendlyErrors.text(of: PlainError("x")), "Something went wrong — please try again.")
        XCTAssertEqual(FriendlyErrors.masking("Wrong password: hunter2", secret: "hunter2"), "Wrong password: ••••••")
        XCTAssertEqual(FriendlyErrors.masking("ab", secret: "ab"), "ab")
    }
}

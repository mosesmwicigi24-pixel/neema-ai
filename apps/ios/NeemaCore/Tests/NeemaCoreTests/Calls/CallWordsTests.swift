import XCTest
@testable import NeemaCore

/// The words of CALLING_UX.md §2.1, §3, §5 and §7 as Android's CallUxTest /
/// CallAcceptanceTest check them: rows, handles, the permission card, the
/// transcript turns, the restriction banner and the thread pill.
final class CallWordsTests: XCTestCase {
    private let james = "254733444555"
    private let grace = "7788990011"
    private let peter = "254712345678"
    private var tz: TimeZone!

    override func setUp() {
        super.setUp()
        tz = Fmt.timeZone
        Fmt.timeZone = TimeZone(identifier: "Africa/Nairobi")!
    }
    override func tearDown() { Fmt.timeZone = tz; super.tearDown() }

    private func meta(status: String = "unknown", canCall: Bool? = nil, canRequest: Bool? = true, streak: Int = 0, at: String? = nil,
                      permanent: Bool = false, expires: String? = nil, revoked: Bool = false, left: Int? = nil) -> CallPermission {
        CallPermission(waId: james, status: status, expiresAt: expires, permanent: permanent, metaStatus: canCall == false ? "no_permission" : "temporary",
                       canCall: canCall, canRequest: canRequest, requestAvailableAt: at, callsLeftToday: left, revoked: revoked,
                       unansweredStreak: streak, source: "meta")
    }
    private func iso(_ ms: Int64) -> String { Inbox.iso(ofMillis: ms) }
    private func inHours(_ h: Int, now: Int64) -> String { iso(now + Int64(h) * 3_600_000 - 1_000) }

    // §5, §7: the outcome word, its tone and the direction glyph.
    func testRowWords() {
        XCTAssertEqual(callRowWords(Call(callId: "x", direction: "outbound", status: "rejected")).label, "Declined by customer")
        XCTAssertEqual(callRowWords(Call(callId: "x", direction: "outbound", status: "rejected")).tone, .bad)
        XCTAssertEqual(callRowWords(Call(callId: "x", direction: "inbound", status: "missed")), CallRowWords("Missed", .bad, .missed))
        XCTAssertEqual(callRowWords(Call(callId: "x", direction: "inbound", status: "callback")), CallRowWords("Call back", .warn, .back))
        XCTAssertEqual(callRowWords(Call(callId: "x", direction: "outbound", status: "completed")), CallRowWords("Outgoing", .good, .out))
        XCTAssertEqual(callRowWords(Call(callId: "x", direction: "inbound", status: "ended")), CallRowWords("Incoming", .good, .in))
        XCTAssertEqual(callRowWords(Call(callId: "x", direction: "outbound", status: "ringing")).label, "Calling…")
        XCTAssertEqual(callRowWords(Call(callId: "x", direction: "inbound", status: "ringing")).label, "Ringing…")
        XCTAssertEqual(callRowWords(Call(callId: "x", direction: "inbound", status: "answered")), CallRowWords("On a call", .live, .in))
        XCTAssertEqual(callRowWords(Call(callId: "x", status: "declined")).tone, .warn)
        XCTAssertEqual(callRowWords(Call(callId: "x", status: "no_answer")).label, "No answer")
        XCTAssertEqual(callRowWords(Call(callId: "x", status: "cancelled")).tone, .neutral)
        XCTAssertEqual(callRowWords(Call(callId: "x", status: "failed")), CallRowWords("Failed", .bad, .in))
        XCTAssertEqual(callRowWords(Call(callId: "x", status: "on_hold")).label, "On hold")
        XCTAssertEqual(callRowWords(Call(callId: "x", status: "")).label, "Call")
    }

    // M6. The history says which app, and the words match the web.
    func testHistoryAndThreadSayWhichApp() {
        let row = Call(callId: "c_1", waId: nil, channel: "messenger", externalId: grace, direction: "outbound", status: "rejected")
        XCTAssertEqual(callRowWords(row).label, "Declined by customer")
        XCTAssertEqual(rowWho(row), "Messenger caller")
        XCTAssertEqual(callHandle(row), grace)
        XCTAssertEqual(channelLabel(row.channel), "Messenger")
        XCTAssertEqual(channelLabel(nil), "WhatsApp")
        XCTAssertEqual(channelLabel(" Messenger "), "Messenger")
        XCTAssertEqual(channelOf("instagram"), "whatsapp")
        let wa = Call(callId: "w_1", waId: peter, direction: "inbound", status: "completed")
        XCTAssertEqual(callHandle(wa), peter)
        XCTAssertEqual(rowWho(wa), "+\(peter)")
        XCTAssertEqual(callHandle(Call(callId: "p", waId: "+\(peter)")), peter)
        XCTAssertEqual(callHandle(Call(callId: "n")), "")
        XCTAssertEqual(rowWho(Call(callId: "n", name: "  ")), "Unknown caller")
        XCTAssertEqual(rowWho(Call(callId: "n", waId: peter, name: "Grace Wanjiku")), "Grace Wanjiku")
    }

    func testLengthsAndFirstNames() {
        XCTAssertEqual(callLength(252), "4:12")
        XCTAssertEqual(callLength(5), "0:05")
        XCTAssertEqual(mmss(252), "04:12")
        XCTAssertEqual(callDuration(nil), "")
        XCTAssertEqual(callDuration(0), "")
        XCTAssertEqual(callDuration(61), "1:01")
        XCTAssertEqual(agentFirst("Moses Mwicigi"), "Moses")
        XCTAssertEqual(agentFirst("  "), nil)
        XCTAssertNil(agentFirst(nil))
        XCTAssertEqual(firstNameOf("Fr. Peter Kamau"), "Peter")
        XCTAssertEqual(firstNameOf("Grace"), "Grace")
        XCTAssertEqual(firstNameOf("  Rev.  Mary Achieng "), "Mary")
        XCTAssertEqual(firstNameOf("Deacon James Mwangi"), "James")
        XCTAssertEqual(firstNameOf("Most Rev. Bishop"), "Most", "every word a title: the first")
        XCTAssertEqual(firstNameOf("Bishop Peter Kamau"), "Peter")
        XCTAssertNil(firstNameOf(nil)); XCTAssertNil(firstNameOf("  ")); XCTAssertNil(firstNameOf("+254712345678"))
    }

    func testUntilText() {
        let now: Int64 = 1_790_000_000_000
        XCTAssertEqual(untilText(iso(now - 1), now: now), "now")
        XCTAssertEqual(untilText(iso(now + 12 * 60_000), now: now), "in 12 min")
        XCTAssertEqual(untilText(iso(now + 5 * 3_600_000 - 1_000), now: now), "in 5 h")
        XCTAssertEqual(untilText(iso(now + 3 * 86_400_000), now: now).hasPrefix("on "), true)
        XCTAssertEqual(untilText("nonsense", now: now), "later")
    }

    // §2.1: the permission is said honestly.
    func testThePermissionIsSaidHonestly() {
        let now = AppClock.now()
        func lines(_ p: CallPermission) -> [String] { permissionLines(p, first: "James", now: now) }
        XCTAssertEqual(lines(meta(status: "granted", canCall: true, permanent: true)), ["Allowed permanently"])
        XCTAssertEqual(lines(meta(status: "granted", canCall: true, expires: "2026-10-03T10:00:00+00:00")), ["Allowed until 3 Oct 2026"])
        var requested = meta(status: "requested", canCall: false, canRequest: false)
        requested.at = iso(now - 2 * 3_600_000)
        XCTAssertEqual(lines(requested), ["Request sent 2h ago — waiting for James"])
        XCTAssertEqual(lines(meta(status: "requested", canCall: false, canRequest: false)), ["Request sent — waiting for James"])
        XCTAssertEqual(lines(meta(status: "denied", canCall: false)), ["James declined calls"])
        XCTAssertEqual(lines(meta(status: "denied", canCall: false, revoked: true)), ["Permission revoked after unanswered calls"])
        XCTAssertEqual(lines(meta(status: "denied", canCall: false, canRequest: false, at: inHours(5, now: now))), ["James declined calls", "You can ask again in 5 h"])
        XCTAssertEqual(lines(meta(status: "granted", canCall: true, permanent: true, left: 3)), ["Allowed permanently", "Calls left today: 3"], "only when Meta gave it")
        XCTAssertTrue(lines(meta()).isEmpty)
        XCTAssertEqual(permissionLines(CallPermission(status: "granted"), first: "James", now: now).first, "Allowed calls")
        XCTAssertEqual(permissionLines(CallPermission(status: "unknown", metaStatus: "no_permission"), first: "James", now: now).first, "James hasn't allowed calls yet")
        XCTAssertEqual(permissionLine(CallPermission(status: "granted", metaStatus: "permanent"), first: "James", now: now), "Allowed permanently")
        // Granted: no "ask again" line even when Meta says a request is throttled.
        XCTAssertEqual(lines(meta(status: "granted", canCall: true, canRequest: false, at: inHours(5, now: now))), ["Allowed calls"])
    }

    func testVoicemailShowsOnTheRowAndThePill() throws {
        let row = try NeemaJSON.decode(Call.self, from: #"{"call_id":"wacid.9","wa_id":"\#(james)","direction":"inbound","status":"missed","has_voicemail":true}"#)
        XCTAssertTrue(row.hasVoicemail)
        XCTAssertEqual(threadCallLabel("Missed call", row), "Missed call · voicemail")
        XCTAssertEqual(threadCallLabel("", row), "Missed · voicemail")
        var noVoicemail = row; noVoicemail.hasVoicemail = false
        XCTAssertEqual(threadCallLabel("Missed call", noVoicemail), "Missed call")
        XCTAssertEqual(threadCallLabel("Voicemail left", row), "Voicemail left")
        XCTAssertEqual(threadCallLabel("   ", nil), "Call")
        let older = try NeemaJSON.decode(Call.self, from: #"{"call_id":"x","status":"missed"}"#)
        XCTAssertFalse(older.hasVoicemail, "an older row")
    }

    func testTwoSpeakerTranscriptsSplitIntoTurns() {
        XCTAssertEqual(
            transcriptTurns("Agent: Hello, Bethany House.\n\ncustomer:  Hi, I need a cassock size 54 please."),
            [TranscriptTurn("Agent", "Hello, Bethany House."), TranscriptTurn("Customer", "Hi, I need a cassock size 54 please.")]
        )
        XCTAssertNil(transcriptTurns("Hello there, this is a transcript."), "plain text stays plain")
        XCTAssertNil(transcriptTurns("Agent: Good afternoon.\nCaller: Hello, Father Peter here."), "another labelling stays plain")
        XCTAssertNil(transcriptTurns("  \n "))
    }

    func testTheRestrictionBannerAndWhyAnAppCantCall() {
        XCTAssertEqual(restrictionText(CallingRestriction(reasons: ["LOW_PICKUP_RATE"], at: "2026-09-27T09:00:00Z")),
                       "Low pickup rate. Calls you place may fail until it lifts (up to 7 days).")
        XCTAssertEqual(restrictionText(CallingRestriction(reasons: ["LOW_PICKUP_RATE", "HIGH_BLOCK_RATE"], at: nil)),
                       "Low pickup rate · High block rate. Calls you place may fail until it lifts (up to 7 days).")
        XCTAssertEqual(restrictionText(CallingRestriction(reasons: [], at: nil)), "Calls you place may fail until it lifts (up to 7 days).")
        XCTAssertEqual(cantCallWhy("Messenger"), "Messenger calling isn't switched on for Neema yet.")
        XCTAssertEqual(cantCallWhy("Instagram"), "Instagram doesn't let businesses take calls.")
    }
}

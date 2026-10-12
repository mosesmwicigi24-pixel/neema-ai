import Foundation
@testable import NeemaCore

/// The call console's data, built from what the real handlers return
/// (apps/api/app/routers/admin.py, the `/calls*` routes), so the fake cannot
/// hide a contract mismatch (Android `testing/fixtures/CallsFixtures.kt`):
///  - `id` is the Call row's UUID; `call_id` is Meta's wacid (`wacid.` + base64,
///    usually ending in `==`, so it must be percent-encoded in a path);
///  - every key is always present (the handler builds a plain dict), nullable
///    ones as JSON null;
///  - `started_at` is `datetime.isoformat()` of an aware timestamptz:
///    microseconds and a `+00:00` offset, never a `Z`;
///  - `recording_url` is `{MEDIA_PUBLIC_URL}/api/admin/media/call_<hex>.m4a`.
enum CallsFixtures {
    /// A Meta call id, the shape the `calls` webhook delivers (routers/whatsapp_webhook.py `_handle_calls`).
    static func wacid(_ tag: String) -> String {
        "wacid.HBgMMjU0NzEyMzQ1Njc4FQIAEhgg\(tag)QTFCMkMzRDRFNUY2QTdCOEM5RDBFMUYyHBgMMjU0NzAwMDAwMDAwFQIAAA=="
    }

    static let C1 = wacid("QUFB")
    static let C2 = wacid("QkJC")
    static let C3 = wacid("Q0ND")
    static let C4 = wacid("RERE")
    static let C5 = wacid("RUVF")
    static let C6 = wacid("RkZG")
    static let C7 = wacid("R0dH")

    /// The Call row UUID of the C1 row (list_calls `id`).
    static let K1 = "5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b01"

    /// routers/admin.py calls_transcribe: the 409 when WHISPER_ENABLED is off.
    static let WHISPER_OFF = #"{"detail":"Transcription isn't enabled yet. Set WHISPER_ENABLED=1 (self-hosted faster-whisper) on the server to turn it on."}"#
    /// routers/admin.py calls_transcribe: the 409 when the call has no recording.
    static let NO_RECORDING = #"{"detail":"No recording was captured for this call."}"#

    /// The encoded path the app requests for `callId` (what FakeNeema's calls log records).
    static func path(_ callId: String, _ suffix: String) -> String { "/admin/calls/\(enc(callId))/\(suffix)" }
    /// The id as `encodeURIComponent` / the client's path encoder spell it (`=` → `%3D`).
    static func enc(_ callId: String) -> String {
        var allowed = CharacterSet.alphanumerics
        allowed.insert(charactersIn: "-_.~")
        return callId.addingPercentEncoding(withAllowedCharacters: allowed) ?? callId
    }
    /// A FakeNeema route pattern for `path` (the id's `.` and `%` are regex-escaped).
    static func route(_ callId: String, _ suffix: String) -> String { NSRegularExpression.escapedPattern(for: path(callId, suffix)) }

    /// `datetime.isoformat()` of an aware UTC timestamp, `minutes` ago.
    static func pyIso(_ minutes: Int64) -> String { Fixtures.pyIso(minutes) }

    /// routers/admin.py `calls_upload_recording`: the served URL when MEDIA_PUBLIC_URL is set.
    static func recordingUrl(_ tag: String) -> String { "https://neema.bethanyhouse.co.ke/api/admin/media/call_\(tag)0f3e9a2b7c4d41e8a6b5c3d2e1f0a9b8.m4a" }

    private static func q(_ s: String?) -> String {
        guard let s = s else { return "null" }
        return "\"" + s.replacingOccurrences(of: "\"", with: "\\\"").replacingOccurrences(of: "\n", with: "\\n") + "\""
    }

    /// One row exactly as services/call_log.py `serialize` builds it (every key present, nullable ones null).
    static func row(_ id: String, _ callId: String, _ waId: String?, _ name: String?, _ direction: String, _ status: String,
                    _ duration: Int?, _ agentName: String?, _ startedAt: String?, _ summary: String?, _ transcriptStatus: String?,
                    _ hasRecording: Bool, answeredAt: String? = nil, endedAt: String? = nil, insights: String? = nil,
                    conversationId: String? = nil, followUpOpen: Bool? = nil) -> String {
        let fu = followUpOpen ?? (status == "missed" || status == "callback")
        return """
        {"id":"\(id)","call_id":"\(callId)","wa_id":\(q(waId)),"name":\(q(name)),"person_id":null,
        "conversation_id":\(q(conversationId)),"channel":"whatsapp","direction":"\(direction)",
        "status":"\(status)","duration":\(duration.map { "\($0)" } ?? "null"),"agent_id":\(agentName != nil ? "\"9c1e0f7a-agent\"" : "null"),
        "agent_name":\(q(agentName)),"started_at":\(q(startedAt)),"answered_at":\(q(answeredAt)),"ended_at":\(q(endedAt)),
        "summary":\(q(summary)),"insights":\(insights ?? "null"),"transcript_status":\(q(transcriptStatus)),"has_recording":\(hasRecording),
        "follow_up_open":\(fu),"follow_up_done_at":null}
        """
    }

    /// `insights` as call_transcribe.py writes it.
    static let PETER_INSIGHTS = #"{"intent":"Two black clergy shirts, size 16","products":["Clergy Shirt (Black 16\")"],"objections":["Delivery to Nyeri by Friday"],"commitments":["KES 7,000 via M-Pesa on delivery"],"next_action":"Confirm Friday delivery to Nyeri","follow_up_message":"Hello Father Peter, confirming your two black clergy shirts (16\") will reach Nyeri by Friday. Total KES 7,000 via M-Pesa on delivery.","sentiment":"positive"}"#

    // routers/admin.py list_calls → a bare JSON list (no envelope), newest first.
    static var calls: String {
        "[" + [
            row(K1, C1, "254712345678", "Fr. Peter Kamau", "inbound", "completed", 184,
                "Moses Mwicigi", pyIso(40), "Wants two black clergy shirts delivered to Nyeri by Friday.", "done", true,
                answeredAt: pyIso(40), endedAt: pyIso(37), insights: PETER_INSIGHTS, conversationId: "c1"),
            row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b02", C2, "254722000111", "Rev. Mary Achieng", "inbound", "missed", nil,
                nil, pyIso(130), nil, "none", false),
            row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b03", C3, "254733444555", "Deacon James Mwangi", "outbound", "completed", 61,
                "Grace Wanjiru", pyIso(60 * 20), nil, "pending", true, answeredAt: pyIso(60 * 20), endedAt: pyIso(60 * 20 - 1)),
            row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b04", C4, "254712345678", "Fr. Peter Kamau", "inbound", "callback", nil,
                nil, pyIso(60 * 26), nil, "none", false),
            row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b05", C5, "254744555666", "The Most Reverend Archbishop Emmanuel Wabukala Onyango-Kipchumba",
                "inbound", "declined", nil, nil, pyIso(60 * 30), nil, "recorded", true),
            // A recording uploaded for a call the webhook never logged: the handler
            // creates a bare row (no wa_id, no name) — see calls_upload_recording.
            row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b06", C6, nil, nil, "inbound", "ended", 732,
                "Brian Otieno", pyIso(60 * 50), nil, "failed", true),
            row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b07", C7, "254712345678", "Fr. Peter Kamau", "inbound", "missed", nil,
                nil, pyIso(60 * 72), nil, "none", false),
        ].joined(separator: ",") + "]"
    }

    /// A long day: 14 rows, an emoji in a name, a no-name caller, every outcome — the card runs well past the screen.
    static var longLog: String {
        let names: [String?] = ["Mama 🌸 Njeri", "Sr. Agnes Wairimu", nil, "Bro. Kevin Ouma", "Canon Joseph Kiprono", "Mrs. Faith Chebet", "Dr. Samuel Mutua"]
        let statuses = ["completed", "missed", "declined", "callback", "no_answer", "ringing", "answered", "cancelled", "failed", "ended"]
        return "[" + (0..<14).map { i -> String in
            let n = names[i % names.count]
            let st = statuses[i % statuses.count]
            return row(String(format: "7c1d2e3f-4a5b-4c6d-8e7f-%012d", i), wacid("TDA" + String(format: "%02d", i)),
                       n == nil ? nil : "2547\(10_000_000 + i * 7_919)", n,
                       (st == "no_answer" || st == "cancelled" || st == "failed") ? "outbound" : "inbound", st,
                       (st == "completed" || st == "ended") ? 45 + i * 37 : nil,
                       i % 3 == 0 ? "Moses" : nil, pyIso(Int64(20 + i * 95)), nil, "none", i % 4 == 0)
        }.joined(separator: ",") + "]"
    }

    /// routers/admin.py `calls_get_transcript`: every key always present.
    static func transcript(_ callId: String, _ status: String?, summary: String? = nil, transcript: String? = nil,
                           language: String? = nil, hasRecording: Bool = true) -> String {
        let tag = String(callId.suffix(6).filter { $0.isLetter || $0.isNumber })
        return """
        {"call_id":"\(callId)","status":\(q(status)),"transcript":\(q(transcript)),"summary":\(q(summary)),
        "language":\(q(language)),"has_recording":\(hasRecording),"recording_url":\(hasRecording ? q(recordingUrl(tag)) : "null")}
        """
    }

    static var doneTranscript: String {
        transcript(C1, "done",
                   summary: "Fr. Peter wants two black clergy shirts (16\") delivered to Nyeri by Friday. Agreed KES 7,000 total; will pay via M-Pesa on delivery confirmation.",
                   transcript: "Agent: Bethany House, good afternoon.\nCaller: Hello, this is Father Peter from Nyeri. I need two black clergy shirts, size sixteen.\nAgent: Certainly Father — we can deliver by Friday.",
                   language: "en")
    }

    static var profile: String {
        """
        {"id":"254712345678","wa_id":"254712345678","name":"Fr. Peter Kamau","phone":"+254712345678",
        "location":"Nyeri","lead_stage":"proposal","role":"Priest","organization":"St. Mary's Parish, Nyeri","lead_score":78,
        "total_orders":3,"total_spent":21500,"tier":"regular","tier_label":"Regular","tags":["clergy","repeat"],
        "channels":[{"channel":"whatsapp","external_id":"254712345678"}],"first_seen_at":"\(pyIso(60 * 24 * 90))","last_seen_at":"\(pyIso(40))"}
        """
    }

    // routers/admin.py calls_ice_config → {"ice_servers": wa_calling.ice_servers(), "record": call_recording_enabled}.
    // Our coturn (single-string urls + credentials), the STUN (string, no
    // credentials), then the openrelay fallback (a urls LIST).
    static let iceConfig = """
    {"ice_servers":[
    {"urls":"turn:turn.bethanyhouse.co.ke:3478","username":"neema","credential":"s3cret"},
    {"urls":"stun:stun.l.google.com:19302"},
    {"urls":["turn:openrelay.metered.ca:80","turn:openrelay.metered.ca:443","turn:openrelay.metered.ca:443?transport=tcp"],
    "username":"openrelayproject","credential":"openrelayproject"}],"record":true}
    """

    /// routers/admin.py calls_get_offer: `sdp` / `from` are whatever the webhook stashed (either may be null).
    static func offer(_ callId: String) -> String {
        #"{"call_id":"\#(callId)","sdp":"v=0\r\no=- 1 2 IN IP4 157.240.0.1\r\ns=-\r\nt=0 0\r\na=group:BUNDLE 0\r\nm=audio 3480 UDP/TLS/RTP/SAVPF 111 126\r\na=setup:actpass\r\na=rtpmap:111 opus/48000/2\r\n","from":"254712345678"}"#
    }

    static func install(_ f: FakeNeema) {
        f.on("GET", "/admin/calls", body: calls)
        f.on("GET", "/admin/calls/ice-config", body: iceConfig)
        f.on("GET", route(C1, "transcript"), body: doneTranscript)
        f.on("GET", route(C3, "transcript"), body: transcript(C3, "pending"))
        f.on("GET", route(C5, "transcript"), body: transcript(C5, "recorded"))
        f.on("GET", route(C6, "transcript"), body: transcript(C6, "failed"))
        f.on("GET", route(C2, "transcript"), body: transcript(C2, "none", hasRecording: false))
        f.on("GET", "/admin/customers/254712345678", body: profile)
        f.on("GET", "/admin/customers/254712345678/merge_suggestions", body: #"{"suggestions":[]}"#)
    }
}

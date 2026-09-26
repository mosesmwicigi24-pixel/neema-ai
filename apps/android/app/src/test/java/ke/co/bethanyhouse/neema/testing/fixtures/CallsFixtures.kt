package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.core.util.AppClock

import ke.co.bethanyhouse.neema.testing.FakeNeema
import java.net.URLEncoder
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

/**
 * The call console's data, built from what the real handlers return
 * (apps/api/app/routers/admin.py, the `/calls*` routes), so the fake cannot
 * hide a contract mismatch:
 *  - `id` is the Call row's UUID; `call_id` is Meta's wacid (`wacid.` + base64,
 *    usually ending in `==`, so it must be percent-encoded in a path);
 *  - every key is always present (the handler builds a plain dict), nullable
 *    ones as JSON null;
 *  - `started_at` is `datetime.isoformat()` of an aware timestamptz:
 *    microseconds and a `+00:00` offset, never a `Z`;
 *  - `recording_url` is `{MEDIA_PUBLIC_URL}/api/admin/media/call_<hex>.m4a`, or
 *    the bare file name when MEDIA_PUBLIC_URL is unset.
 * Every outcome (answered, ended, missed, declined, callback, ringing), long
 * names, a call with no wa_id, and transcripts in every status.
 */
object CallsFixtures {
    /** A Meta call id, the shape the `calls` webhook delivers (routers/whatsapp_webhook.py `_handle_calls`). */
    fun wacid(tag: String) =
        "wacid.HBgMMjU0NzEyMzQ1Njc4FQIAEhgg${tag}QTFCMkMzRDRFNUY2QTdCOEM5RDBFMUYyHBgMMjU0NzAwMDAwMDAwFQIAAA=="

    val C1 = wacid("QUFB")
    val C2 = wacid("QkJC")
    val C3 = wacid("Q0ND")
    val C4 = wacid("RERE")
    val C5 = wacid("RUVF")
    val C6 = wacid("RkZG")
    val C7 = wacid("R0dH")

    /** The Call row UUID of the C1 row (list_calls `id`). */
    const val K1 = "5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b01"

    /** routers/admin.py calls_transcribe: the 409 when WHISPER_ENABLED is off. */
    const val WHISPER_OFF = """{"detail":"Transcription isn't enabled yet. Set WHISPER_ENABLED=1 (self-hosted faster-whisper) on the server to turn it on."}"""
    /** routers/admin.py calls_transcribe: the 409 when the call has no recording. */
    const val NO_RECORDING = """{"detail":"No recording was captured for this call."}"""

    /** The encoded path the app requests for [callId] (what FakeNeema's calls log records). */
    fun path(callId: String, suffix: String) = "/admin/calls/${URLEncoder.encode(callId, "UTF-8")}/$suffix"

    /** A FakeNeema route pattern for [path] (the id's `.` and `%` are regex-escaped). */
    fun route(callId: String, suffix: String) = Regex.escape(path(callId, suffix))

    private val PY_ISO = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSSSSxxx")

    /** `datetime.isoformat()` of an aware UTC timestamp, [minutes] ago: `2026-09-25T09:20:13.482915+00:00`. */
    fun pyIso(minutes: Long): String =
        AppClock.instant().minus(minutes, ChronoUnit.MINUTES).atOffset(ZoneOffset.UTC).format(PY_ISO)

    /** routers/admin.py `calls_upload_recording`: the served URL when MEDIA_PUBLIC_URL is set. */
    fun recordingUrl(tag: String) = "https://neema.bethanyhouse.co.ke/api/admin/media/call_${tag}0f3e9a2b7c4d41e8a6b5c3d2e1f0a9b8.m4a"

    private fun q(s: String?) = if (s == null) "null" else "\"" + s.replace("\"", "\\\"").replace("\n", "\\n") + "\""

    /** One row exactly as routers/admin.py `list_calls` builds it. */
    fun row(
        id: String, callId: String, waId: String?, name: String?, direction: String, status: String,
        duration: Int?, agentName: String?, startedAt: String?, summary: String?, transcriptStatus: String?,
        hasRecording: Boolean,
    ) = """{"id":"$id","call_id":"$callId","wa_id":${q(waId)},"name":${q(name)},"direction":"$direction",
        "status":"$status","duration":${duration ?: "null"},"agent_name":${q(agentName)},"started_at":${q(startedAt)},
        "summary":${q(summary)},"transcript_status":${q(transcriptStatus)},"has_recording":$hasRecording}"""

    // routers/admin.py list_calls → a bare JSON list (no envelope), newest first.
    val calls get() = listOf(
        row(K1, C1, "254712345678", "Fr. Peter Kamau", "inbound", "answered", 184,
            "Moses Mwicigi", pyIso(40), "Wants two black clergy shirts delivered to Nyeri by Friday.", "done", true),
        row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b02", C2, "254722000111", "Rev. Mary Achieng", "inbound", "missed", null,
            null, pyIso(130), null, "none", false),
        row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b03", C3, "254733444555", "Deacon James Mwangi", "outbound", "answered", 61,
            "Grace Wanjiru", pyIso(60 * 20), null, "pending", true),
        row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b04", C4, "254712345678", "Fr. Peter Kamau", "inbound", "callback", null,
            null, pyIso(60 * 26), null, "none", false),
        row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b05", C5, "254744555666", "The Most Reverend Archbishop Emmanuel Wabukala Onyango-Kipchumba",
            "inbound", "declined", null, null, pyIso(60 * 30), null, "recorded", true),
        // A recording uploaded for a call the webhook never logged: the handler
        // creates a bare row (no wa_id, no name) — see calls_upload_recording.
        row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b06", C6, null, null, "inbound", "ended", 732,
            "Brian Otieno", pyIso(60 * 50), null, "failed", true),
        row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b07", C7, "254712345678", "Fr. Peter Kamau", "inbound", "missed", null,
            null, pyIso(60 * 72), null, "none", false),
    ).joinToString(",", "[", "]")

    /** A long day: 14 rows, an emoji in a name, a no-name caller, every outcome — the card runs well past the screen. */
    val longLog get() = (0 until 14).joinToString(",", "[", "]") { i ->
        val names = listOf("Mama 🌸 Njeri", "Sr. Agnes Wairimu", null, "Bro. Kevin Ouma", "Canon Joseph Kiprono", "Mrs. Faith Chebet", "Dr. Samuel Mutua")
        val statuses = listOf("answered", "missed", "declined", "callback", "ended", "ringing", "answered")
        val n = names[i % names.size]
        val st = statuses[i % statuses.size]
        row(
            id = "7c1d2e3f-4a5b-4c6d-8e7f-%012d".format(i), callId = wacid("TDA${i.toString().padStart(2, '0')}"),
            waId = if (n == null) null else "2547${10_000_000 + i * 7_919}", name = n, direction = "inbound", status = st,
            duration = if (st == "answered" || st == "ended") 45 + i * 37 else null,
            agentName = if (i % 3 == 0) "Moses" else null, startedAt = pyIso(20L + i * 95), summary = null,
            transcriptStatus = "none", hasRecording = i % 4 == 0,
        )
    }

    /** routers/admin.py `calls_get_transcript`: every key always present. */
    fun transcript(callId: String, status: String?, summary: String? = null, transcript: String? = null,
                   language: String? = null, hasRecording: Boolean = true) =
        """{"call_id":"$callId","status":${q(status)},"transcript":${q(transcript)},"summary":${q(summary)},
           "language":${q(language)},"has_recording":$hasRecording,"recording_url":${if (hasRecording) q(recordingUrl(callId.takeLast(6).filter { it.isLetterOrDigit() })) else "null"}}"""

    val doneTranscript get() = transcript(
        C1, "done",
        summary = "Fr. Peter wants two black clergy shirts (16\") delivered to Nyeri by Friday. Agreed KES 7,000 total; will pay via M-Pesa on delivery confirmation.",
        transcript = "Agent: Bethany House, good afternoon.\nCaller: Hello, this is Father Peter from Nyeri. I need two black clergy shirts, size sixteen.\nAgent: Certainly Father — we can deliver by Friday.",
        language = "en",
    )

    val profile get() = """{"id":"254712345678","wa_id":"254712345678","name":"Fr. Peter Kamau","phone":"+254712345678",
      "location":"Nyeri","lead_stage":"proposal","role":"Priest","organization":"St. Mary's Parish, Nyeri","lead_score":78,
      "total_orders":3,"total_spent":21500,"tier":"regular","tier_label":"Regular","tags":["clergy","repeat"],
      "channels":[{"channel":"whatsapp","external_id":"254712345678"}],"first_seen_at":"${pyIso(60 * 24 * 90)}","last_seen_at":"${pyIso(40)}"}"""

    // routers/admin.py calls_ice_config → {"ice_servers": wa_calling.ice_servers(), "record": call_recording_enabled}.
    // Our coturn (single-string urls + credentials), the STUN (string, no
    // credentials), then the openrelay fallback (a urls LIST).
    val iceConfig = """{"ice_servers":[
        {"urls":"turn:turn.bethanyhouse.co.ke:3478","username":"neema","credential":"s3cret"},
        {"urls":"stun:stun.l.google.com:19302"},
        {"urls":["turn:openrelay.metered.ca:80","turn:openrelay.metered.ca:443","turn:openrelay.metered.ca:443?transport=tcp"],
         "username":"openrelayproject","credential":"openrelayproject"}],"record":true}"""

    /** routers/admin.py calls_get_offer: `sdp` / `from` are whatever the webhook stashed (either may be null). */
    fun offer(callId: String) = """{"call_id":"$callId","sdp":"v=0\r\no=- 1 2 IN IP4 157.240.0.1\r\ns=-\r\nt=0 0\r\na=group:BUNDLE 0\r\nm=audio 3480 UDP/TLS/RTP/SAVPF 111 126\r\na=setup:actpass\r\na=rtpmap:111 opus/48000/2\r\n","from":"254712345678"}"""

    fun install(f: FakeNeema) {
        f.on("GET", "/admin/calls", body = calls)
        f.on("GET", "/admin/calls/ice-config", body = iceConfig)
        f.on("GET", route(C1, "transcript"), body = doneTranscript)
        f.on("GET", route(C3, "transcript"), body = transcript(C3, "pending"))
        f.on("GET", route(C5, "transcript"), body = transcript(C5, "recorded"))
        f.on("GET", route(C6, "transcript"), body = transcript(C6, "failed"))
        f.on("GET", route(C2, "transcript"), body = transcript(C2, "none", hasRecording = false))
        f.on("GET", "/admin/customers/254712345678", body = profile)
        f.on("GET", "/admin/customers/254712345678/merge_suggestions", body = """{"suggestions":[]}""")
    }
}

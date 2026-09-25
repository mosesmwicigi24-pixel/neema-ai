package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures.ago

/**
 * The call console's data, shaped like GET /admin/calls,
 * /admin/calls/{id}/transcript and /admin/customers/{wa_id} (routers/admin.py):
 * every outcome (answered, ended, missed, declined, callback, ringing), long
 * names, a call with no wa_id, and transcripts in every status.
 */
object CallsFixtures {
    val calls get() = """[
      {"id":"k1","call_id":"wacid.1","wa_id":"254712345678","name":"Fr. Peter Kamau","direction":"inbound","status":"answered","duration":184,
       "agent_name":"Moses Mwicigi","started_at":"${ago(40)}","summary":"Wants two black clergy shirts delivered to Nyeri by Friday.","transcript_status":"done","has_recording":true},
      {"id":"k2","call_id":"wacid.2","wa_id":"254722000111","name":"Rev. Mary Achieng","direction":"inbound","status":"missed","duration":null,
       "agent_name":null,"started_at":"${ago(130)}","transcript_status":"none","has_recording":false},
      {"id":"k3","call_id":"wacid.3","wa_id":"254733444555","name":"Deacon James Mwangi","direction":"outbound","status":"answered","duration":61,
       "agent_name":"Grace Wanjiru","started_at":"${ago(60 * 20)}","transcript_status":"pending","has_recording":true},
      {"id":"k4","call_id":"wacid.4","wa_id":"254712345678","name":"Fr. Peter Kamau","direction":"inbound","status":"callback","duration":null,
       "agent_name":null,"started_at":"${ago(60 * 26)}","transcript_status":"none","has_recording":false},
      {"id":"k5","call_id":"wacid.5","wa_id":"254744555666","name":"The Most Reverend Archbishop Emmanuel Wabukala Onyango-Kipchumba","direction":"inbound","status":"declined","duration":null,
       "agent_name":null,"started_at":"${ago(60 * 30)}","transcript_status":"recorded","has_recording":true},
      {"id":"k6","call_id":"wacid.6","wa_id":null,"name":null,"direction":"inbound","status":"ended","duration":732,
       "agent_name":"Brian Otieno","started_at":"${ago(60 * 50)}","transcript_status":"failed","has_recording":true},
      {"id":"k7","call_id":"wacid.7","wa_id":"254712345678","name":"Fr. Peter Kamau","direction":"inbound","status":"missed","duration":null,
       "agent_name":null,"started_at":"${ago(60 * 72)}","transcript_status":"none","has_recording":false}
    ]"""

    fun transcript(callId: String, status: String, summary: String? = null, transcript: String? = null,
                   language: String? = null, hasRecording: Boolean = true) =
        """{"call_id":"$callId","status":"$status","transcript":${q(transcript)},"summary":${q(summary)},
           "language":${q(language)},"has_recording":$hasRecording,"recording_url":${if (hasRecording) "\"call_$callId.m4a\"" else "null"}}"""

    private fun q(s: String?) = if (s == null) "null" else "\"" + s.replace("\"", "\\\"").replace("\n", "\\n") + "\""

    val doneTranscript = transcript(
        "wacid.1", "done",
        summary = "Fr. Peter wants two black clergy shirts (16\") delivered to Nyeri by Friday. Agreed KES 7,000 total; will pay via M-Pesa on delivery confirmation.",
        transcript = "Agent: Bethany House, good afternoon.\nCaller: Hello, this is Father Peter from Nyeri. I need two black clergy shirts, size sixteen.\nAgent: Certainly Father — we can deliver by Friday.",
        language = "en",
    )

    val profile get() = """{"id":"254712345678","wa_id":"254712345678","name":"Fr. Peter Kamau","phone":"+254712345678",
      "location":"Nyeri","lead_stage":"proposal","role":"Priest","organization":"St. Mary's Parish, Nyeri","lead_score":78,
      "total_orders":3,"total_spent":21500,"tier":"regular","tier_label":"Regular","tags":["clergy","repeat"],
      "channels":[{"channel":"whatsapp","external_id":"254712345678"}],"first_seen_at":"${ago(60 * 24 * 90)}","last_seen_at":"${ago(40)}"}"""

    fun install(f: FakeNeema) {
        f.on("GET", "/admin/calls", body = calls)
        f.on("GET", "/admin/calls/wacid.1/transcript", body = doneTranscript)
        f.on("GET", "/admin/calls/wacid.3/transcript", body = transcript("wacid.3", "pending"))
        f.on("GET", "/admin/calls/wacid.5/transcript", body = transcript("wacid.5", "recorded"))
        f.on("GET", "/admin/calls/wacid.6/transcript", body = transcript("wacid.6", "failed"))
        f.on("GET", "/admin/calls/wacid.2/transcript", body = transcript("wacid.2", "none", hasRecording = false))
        f.on("GET", "/admin/customers/254712345678", body = profile)
        f.on("GET", "/admin/customers/254712345678/merge_suggestions", body = """{"suggestions":[]}""")
    }
}

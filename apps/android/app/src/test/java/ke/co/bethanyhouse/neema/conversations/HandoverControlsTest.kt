package ke.co.bethanyhouse.neema.conversations

import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.HandoverRequest
import ke.co.bethanyhouse.neema.feature.conversations.inboxPermsOf
import ke.co.bethanyhouse.neema.feature.conversations.threadControls
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Ask the colleague holding a chat to hand it over (owner, 2026-11-04): anyone
 * locked out may ask; the holder — or the super admin — hands it over or keeps it.
 */
class HandoverControlsTest {
    private val grace = "grace"
    private val held = Conversation(id = "c6", interceptMode = "human", assignedAgentId = grace, assignedAgentName = "Grace Wanjiru")
    private val ask = HandoverRequest(id = "r1", fromAgentId = "sam", fromAgentName = "Sam Otieno", holderAgentId = grace)

    @Test fun anAgentLockedOut_mayAsk_butNeverAnswers() {
        val c = threadControls(held.copy(handoverRequest = ask), inboxPermsOf("agent", false, "sam"))
        assertTrue(c.locked && c.askHandover)
        assertFalse(c.answerHandover)
    }

    @Test fun anAdminLockedOut_asksLikeEveryoneElse() {
        val c = threadControls(held, inboxPermsOf("admin", false, "bea"))
        assertTrue(c.locked && c.askHandover)
    }

    @Test fun readonly_cannotAsk() {
        assertFalse(threadControls(held, inboxPermsOf("readonly", false, "ro")).askHandover)
    }

    @Test fun theHolder_answers_andTheSuperAdminMayToo() {
        val withAsk = held.copy(handoverRequest = ask)
        assertTrue(threadControls(withAsk, inboxPermsOf("agent", false, grace)).answerHandover)
        val sup = threadControls(withAsk, inboxPermsOf("admin", true, "boss"))
        assertTrue(sup.answerHandover && !sup.askHandover && sup.takeOver)
        assertFalse(threadControls(held, inboxPermsOf("agent", false, grace)).answerHandover)
    }

    @Test fun theRowCarriesTheAsk() {
        val row = Json { ignoreUnknownKeys = true }.decodeFromString(Conversation.serializer(),
            """{"id":"c6","intercept_mode":"human","assigned_agent_id":"grace",
               "handover_request":{"id":"r1","from_agent_id":"sam","from_agent_name":"Sam Otieno","holder_agent_id":"grace","at":"2026-11-04T09:30:00+00:00"}}""")
        assertEquals("Sam Otieno", row.handoverRequest?.fromAgentName)
        assertEquals(null, Json { ignoreUnknownKeys = true }.decodeFromString(Conversation.serializer(), """{"id":"c1"}""").handoverRequest)
    }
}

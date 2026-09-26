package ke.co.bethanyhouse.neema.deals

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.deals.DealsViewModel
import ke.co.bethanyhouse.neema.orders.ClockedMainRule
import ke.co.bethanyhouse.neema.orders.SeededStore
import ke.co.bethanyhouse.neema.orders.ToastLog
import ke.co.bethanyhouse.neema.orders.dropped
import ke.co.bethanyhouse.neema.orders.expiredOnce
import ke.co.bethanyhouse.neema.orders.htmlPage
import ke.co.bethanyhouse.neema.orders.offline
import ke.co.bethanyhouse.neema.orders.timeout
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fakeJwt
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * The Deals board and Neema's action queue on a bad network: every load and
 * every action under offline, timeout, lost answers, 401/404/409/429/5xx,
 * HTML pages, garbage bodies, double taps and leaving mid-request.
 *
 * The one rule above all: a follow-up is words in front of a customer — it
 * must never be sent twice, and never be called "failed" when it went.
 */
class DealsNetworkTest {
    @get:Rule val main = ClockedMainRule()
    @get:Rule val paparazzi = Paparazzi()

    private val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
    private lateinit var toasts: ToastLog
    private lateinit var dash: DashboardViewModel

    /** The server's queue: ids still pending. Approve/veto (when they reach it) take them out. */
    private val pending = mutableSetOf("x1", "x2")
    /** Messages that actually went to a customer, in order. */
    private val sent = mutableListOf<String>()

    private fun queueJson(): String {
        val all = Json.parseToJsonElement(SalesFixtures.actions).jsonObject["actions"]!!.jsonArray
        return JsonObject(mapOf("actions" to JsonArray(all.filter { it.jsonObject["id"]!!.jsonPrimitive.content in pending }))).toString()
    }

    /** What crm.py approve_action does: 409 once resolved, else send and mark sent. */
    private fun serverApprove(id: String): Pair<Int, String> {
        if (id !in pending) return 409 to """{"detail":"Action is sent"}"""
        sent += id; pending -= id
        return 200 to """{"ok":true,"sent":"Hello 🙏"}"""
    }

    private fun installServer() {
        fake.on("GET", "/admin/actions") { _, _ -> 200 to queueJson() }
        fake.on("POST", "/admin/actions/([^/]+)/approve") { r, _ -> serverApprove(r.url.pathSegments[r.url.pathSize - 2]) }
        fake.on("POST", "/admin/actions/([^/]+)/veto") { r, _ -> pending -= r.url.pathSegments[r.url.pathSize - 2]; 200 to """{"ok":true}""" }
    }

    private fun vm(): DealsViewModel {
        dash = dashboard(paparazzi.context, fake)
        toasts = ToastLog(dash)
        return DealsViewModel(dash)
    }

    @After fun tearDown() { if (::toasts.isInitialized) toasts.close() }

    private fun posts(id: String) = fake.callsTo("POST", "/admin/actions/$id/approve")
    private val errors get() = toasts.all.filter { it.type == ToastType.Error }.map { it.message }
    private fun noRawHtml() = toasts.all.forEach { assertFalse(it.message, it.message.contains("<")) }

    // ── Approve: the answer is lost ─────────────────────────────────────────

    @Test fun approveThatTimesOutButWentIsSentNotFailed() {
        installServer()
        fake.timeout("POST", "/admin/actions/x1/approve") { serverApprove("x1") }
        val vm = vm()
        vm.act("x1", "approve")
        // The first re-read already shows x1 gone: it went.
        assertEquals(listOf("x1"), sent)
        assertEquals("Sent ✓", toasts.all.last().message)
        assertTrue(errors.isEmpty())
        assertTrue(vm.acting.value.isEmpty() && vm.checking.value.isEmpty())
        assertTrue(vm.actions.value!!.none { it.id == "x1" })
    }

    @Test fun whileSettlingTheRowStaysLockedSoASecondTapCannotSendTwice() {
        installServer()
        // The request reached the server and is still composing when the client gives up.
        fake.timeout("POST", "/admin/actions/x1/approve")
        val vm = vm()
        vm.act("x1", "approve")
        assertEquals(setOf("x1"), vm.checking.value)
        assertEquals(ToastType.Info, toasts.all.last().type)
        assertTrue(toasts.all.last().message.startsWith("No answer from the server — checking whether it was sent"))

        // Impatient taps while it is being settled: nothing goes out.
        vm.act("x1", "approve"); vm.act("x1", "approve", "edited"); vm.act("x1", "veto")
        assertEquals(1, posts("x1").size)
        assertTrue(fake.callsTo("POST", "/admin/actions/x1/veto").isEmpty())

        // Meanwhile the server finishes: the next re-read sees it gone.
        serverApprove("x1")
        main.advance(DealsViewModel.SETTLE_MS)
        assertEquals("Sent ✓", toasts.all.last().message)
        assertTrue(vm.acting.value.isEmpty())
        assertEquals(listOf("x1"), sent)
    }

    @Test fun aSendThatNeverLandsIsReleasedAfterSettlingAndSaysSo() {
        installServer()
        fake.timeout("POST", "/admin/actions/x1/approve")
        val vm = vm()
        vm.act("x1", "approve")
        main.advance(DealsViewModel.SETTLE_MS * DealsViewModel.SETTLE_READS)
        assertEquals("Not sent — the server never confirmed it. You can send it again.", errors.last())
        assertTrue(vm.acting.value.isEmpty() && vm.checking.value.isEmpty())
        // Now a deliberate retry goes through, once.
        installServer()
        vm.act("x1", "approve")
        assertEquals(listOf("x1"), sent)
        assertEquals("Sent ✓", toasts.all.last().message)
    }

    @Test fun whenTheQueueCannotBeReadEitherItSaysCheckTheChat() {
        installServer()
        fake.timeout("POST", "/admin/actions/x1/approve")
        val vm = vm()
        fake.offline("GET", "/admin/actions")
        vm.act("x1", "approve")
        main.advance(DealsViewModel.SETTLE_MS * DealsViewModel.SETTLE_READS)
        assertEquals(
            "Couldn't confirm whether it was sent — the server can't be reached. Open the chat to see whether it went before sending again.",
            errors.last(),
        )
        assertTrue(vm.acting.value.isEmpty())
    }

    @Test fun aDroppedConnectionInTheDialogClosesItOnceItIsKnownToHaveGone() {
        installServer()
        fake.dropped("POST", "/admin/actions/x2/approve") { serverApprove("x2") }
        val vm = vm()
        vm.openDraft(vm.actions.value!!.first { it.id == "x2" })
        vm.setDraftText("Habari Deacon James — did choir practice go well? 🙏")
        vm.act("x2", "approve", vm.draftText.value)
        assertNull(vm.draftFor.value)
        assertEquals("", vm.draftText.value)
        assertEquals("Sent ✓", toasts.all.last().message)
        assertEquals(listOf("x2"), sent)
    }

    @Test fun a502PageIsNeverShownAndIsSettledLikeATimeout() {
        installServer()
        fake.htmlPage("POST", "/admin/actions/x1/approve", 502)
        val vm = vm()
        vm.act("x1", "approve")
        assertEquals(setOf("x1"), vm.checking.value)
        main.advance(DealsViewModel.SETTLE_MS * DealsViewModel.SETTLE_READS)
        assertEquals("Not sent — the server never confirmed it. You can send it again.", errors.last())
        noRawHtml()
    }

    // ── Approve: the answer says no ─────────────────────────────────────────

    @Test fun offlineSendKeepsTheDialogAndEveryWordTyped() {
        installServer()
        fake.offline("POST", "/admin/actions/x1/approve")
        val vm = vm()
        vm.openDraft(vm.actions.value!!.first { it.id == "x1" })
        vm.setDraftText("Father, Friday it is — M-Pesa details below.")
        vm.act("x1", "approve", vm.draftText.value)
        // Nothing reached the server: it is plainly not sent, no settling.
        assertTrue(vm.checking.value.isEmpty() && vm.acting.value.isEmpty())
        assertNotNull(vm.draftFor.value)
        assertEquals("Father, Friday it is — M-Pesa details below.", vm.draftText.value)
        assertEquals("Couldn't send — no connection — check your internet and try again", vm.draftError.value)
        // Back online, Send again: once.
        installServer()
        vm.act("x1", "approve", vm.draftText.value)
        assertEquals(listOf("x1"), sent)
        assertNull(vm.draftFor.value)
        assertNull(vm.draftError.value)
    }

    @Test fun closingAndReopeningTheDialogKeepsTheText() {
        val vm = vm()
        val x1 = vm.actions.value!!.first { it.id == "x1" }
        vm.openDraft(x1)
        vm.setDraftText("my words")
        vm.openDraft(null)
        vm.openDraft(x1)
        assertEquals("my words", vm.draftText.value)
        // Another action starts from its own draft.
        vm.openDraft(vm.actions.value!!.first { it.id == "x2" })
        assertEquals("", vm.draftText.value)
    }

    @Test fun conflictMeansAlreadySentAndTheQueueShowsTheTruth() {
        installServer()
        val vm = vm()
        vm.openDraft(vm.actions.value!!.first { it.id == "x1" })
        serverApprove("x1") // the scheduler got there first
        val reads = fake.callsTo("GET", "/admin/actions").size
        vm.act("x1", "approve", "edited")
        assertEquals("Already sent — nothing was sent twice", errors.last())
        assertEquals(listOf("x1"), sent)
        assertNull(vm.draftFor.value)
        assertEquals(reads + 1, fake.callsTo("GET", "/admin/actions").size)
        assertTrue(vm.actions.value!!.none { it.id == "x1" })
    }

    @Test fun vetoedElsewhereSaysSo() {
        fake.on("POST", "/admin/actions/.*/approve", code = 409, body = """{"detail":"Action is vetoed"}""")
        val vm = vm()
        vm.act("x1", "approve")
        assertEquals("Already vetoed — nothing was sent", errors.last())
    }

    @Test fun goneConversationRemovesTheRowAndSaysWhy() {
        installServer()
        val vm = vm()
        fake.on("POST", "/admin/actions/x1/approve", code = 404, body = """{"detail":"Conversation gone"}""")
        pending -= "x1"
        vm.act("x1", "approve")
        assertEquals("This follow-up is gone — its conversation was deleted", errors.last())
        assertTrue(vm.actions.value!!.none { it.id == "x1" })
        fake.on("POST", "/admin/actions/x2/veto", code = 404, body = """{"detail":"Action not found"}""")
        vm.act("x2", "veto")
        assertEquals("This follow-up is gone — someone else removed it", errors.last())
    }

    @Test fun eachStatusGetsItsOwnWords() {
        val vm = vm()
        fun after(code: Int, body: String): String {
            fake.on("POST", "/admin/actions/x1/approve", code = code, body = body)
            vm.act("x1", "approve")
            return errors.last()
        }
        assertEquals("Couldn't send — could not compose the message", after(500, """{"detail":"Could not compose the message"}"""))
        assertEquals("Couldn't send — the server hit an error — try again", after(500, "Internal Server Error"))
        assertEquals("Couldn't send — the server hit an error — try again", after(500, "<html><body>Traceback…</body></html>"))
        assertEquals("Couldn't send — too many requests — wait a moment and try again", after(429, """{"detail":"Rate limit exceeded"}"""))
        assertEquals("Couldn't send — your role doesn't allow that", after(403, """{"detail":""}"""))
        assertEquals("Couldn't send — the server is unavailable right now — try again shortly", after(503, "<html>Service Unavailable</html>"))
        assertEquals("Couldn't send — invalid action id", after(422, """{"detail":"Invalid action id"}"""))
        noRawHtml()
        assertTrue(vm.acting.value.isEmpty())
    }

    // ── 401 mid-action ──────────────────────────────────────────────────────

    @Test fun anExpiredTokenIsRefreshedSilentlyAndTheSendCompletesOnce() {
        installServer()
        fake.expiredOnce("POST", "/admin/actions/x1/approve") { serverApprove("x1") }
        // A genuinely new token (the fixture's would be byte-identical within the same second).
        fake.on("POST", "/(agent-auth|auth)/refresh") { _, _ -> 200 to Fixtures.tokenResponse(access = fakeJwt() + "r") }
        val vm = vm()
        vm.act("x1", "approve")
        assertEquals(listOf("x1"), sent)
        assertEquals(2, posts("x1").size) // the rejected one never reached the handler's send
        assertEquals("Sent ✓", toasts.all.last().message)
        assertFalse(dash.sessionExpired.value)
    }

    @Test fun aDeadSessionKeepsTheDialogAndTextUntilSignedInAgain() {
        installServer()
        fake.on("POST", "/admin/actions/x1/approve", code = 401, body = """{"detail":"Could not validate credentials"}""")
        fake.on("POST", "/(agent-auth|auth)/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        val vm = vm()
        vm.openDraft(vm.actions.value!!.first { it.id == "x1" })
        vm.setDraftText("Father, Friday delivery confirmed.")
        vm.act("x1", "approve", vm.draftText.value)
        assertTrue(dash.sessionExpired.value)
        assertNotNull(vm.draftFor.value)
        assertEquals("Father, Friday delivery confirmed.", vm.draftText.value)
        assertEquals("Your session expired — sign in again, then send.", vm.draftError.value)
        assertTrue(errors.isEmpty())

        // Signed in again: the same words go, once.
        SalesFixtures.install(fake); installServer()
        fake.on("POST", "/(agent-auth|auth)/(login|refresh)") { _, _ -> 200 to Fixtures.tokenResponse(access = fakeJwt() + "r") }
        dash.onReauthenticated()
        vm.act("x1", "approve", vm.draftText.value)
        assertEquals(listOf("x1"), sent)
        assertEquals("""{"draft":"Father, Friday delivery confirmed."}""", posts("x1").last().body)
    }

    // ── Double taps ─────────────────────────────────────────────────────────

    @Test fun aSecondTapWhileTheFirstIsInFlightSendsNothing() {
        installServer()
        lateinit var vm: DealsViewModel
        fake.on("POST", "/admin/actions/x1/approve") { _, _ ->
            // The operator taps Send, and Edit & send, again while the first is on the wire.
            vm.act("x1", "approve"); vm.act("x1", "approve", "again")
            serverApprove("x1")
        }
        vm = vm()
        vm.act("x1", "approve")
        assertEquals(1, posts("x1").size)
        assertEquals(listOf("x1"), sent)
    }

    @Test fun wonTappedTwiceWhileSavingPatchesOnce() {
        lateinit var vm: DealsViewModel
        fake.on("PATCH", "/admin/deals/d1") { _, _ -> vm.markWon("d1"); vm.markLost("d1"); 200 to """{"ok":true}""" }
        vm = vm()
        vm.markWon("d1")
        assertEquals(1, fake.callsTo("PATCH", "/admin/deals/d1").size)
        assertTrue(vm.patching.value.isEmpty())
    }

    // ── Leaving mid-request ─────────────────────────────────────────────────

    @Test fun leavingWhileSettlingStopsQuietly() {
        installServer()
        fake.timeout("POST", "/admin/actions/x1/approve")
        dash = dashboard(paparazzi.context, fake)
        toasts = ToastLog(dash)
        val store = SeededStore()
        val vm = store.seed(DealsViewModel(dash))
        vm.act("x1", "approve")
        val before = toasts.all.size
        store.viewModelStore.clear() // signed out / the agent's screens discarded
        main.advance(DealsViewModel.SETTLE_MS * DealsViewModel.SETTLE_READS)
        assertEquals(before, toasts.all.size)
        assertEquals(1, posts("x1").size)
    }

    // ── Loads ───────────────────────────────────────────────────────────────

    @Test fun offlineFirstLoadSaysSoInsteadOfAnEmptyBoard() {
        fake.offline("GET", "/admin/deals")
        fake.offline("GET", "/admin/actions")
        val vm = vm()
        assertNull("not an empty board", vm.deals.value)
        assertNull("not 'Nothing queued'", vm.actions.value)
        assertEquals("No connection — check your internet and try again", vm.loadError.value)
        // Back online: Retry loads it and the error goes.
        SalesFixtures.install(fake)
        vm.reload()
        assertEquals(4, vm.deals.value!!.size)
        assertEquals(2, vm.actions.value!!.size)
        assertNull(vm.loadError.value)
    }

    @Test fun aFailedRefreshKeepsTheBoardAndStopsTheSpinner() {
        val vm = vm()
        fake.timeout("GET", "/admin/deals")
        fake.htmlPage("GET", "/admin/actions", 502)
        vm.refresh()
        assertFalse(vm.refreshing.value)
        assertEquals(4, vm.deals.value!!.size)
        assertEquals(2, vm.actions.value!!.size)
        assertEquals("The server took too long to answer — try again", vm.loadError.value)
    }

    @Test fun garbageBodiesDoNotCrash() {
        fake.on("GET", "/admin/deals", body = """{"deals":[{"id":""" )
        fake.on("GET", "/admin/actions", body = "<html>ok</html>")
        val vm = vm()
        assertNull(vm.deals.value)
        assertEquals("The server sent an answer the app couldn't read", vm.loadError.value)
        // An empty 200 is an empty list, not an error.
        fake.on("GET", "/admin/deals", body = "")
        fake.on("GET", "/admin/actions", body = "")
        vm.reload()
        assertEquals(emptyList<Any>(), vm.deals.value)
        assertEquals(emptyList<Any>(), vm.actions.value)
        assertNull(vm.loadError.value)
    }

    @Test fun aSlowStaleLoadCannotOverwriteANewerOne() {
        var n = 0
        lateinit var vm: DealsViewModel
        fake.on("GET", "/admin/deals") { r, _ ->
            if (r.url.queryParameter("status") == "won") return@on 200 to SalesFixtures.wonDeals
            n++
            // The second load's reply is stale: while it is on the wire a newer load starts and lands.
            if (n == 2) { fake.on("GET", "/admin/deals") { rr, _ -> 200 to (if (rr.url.queryParameter("status") == "won") SalesFixtures.wonDeals else """{"deals":[]}""") }; vm.reload() }
            200 to SalesFixtures.deals
        }
        vm = vm()
        vm.reload()
        assertEquals(emptyList<Any>(), vm.deals.value)
    }

    // ── Deal patches ────────────────────────────────────────────────────────

    @Test fun guidanceThatFailsStaysOpenWithTheTextAndTheReason() {
        val vm = vm()
        vm.startGuidance(vm.deals.value!!.first { it.id == "d2" })
        vm.setGuidanceDraft("No discount — parish rate already.")
        fake.offline("PATCH", "/admin/deals/d2")
        vm.saveGuidance("d2")
        assertEquals("d2", vm.editing.value)
        assertEquals("No discount — parish rate already.", vm.guidanceDraft.value)
        assertEquals("Update failed — no connection — check your internet and try again", vm.guidanceError.value)
        // Retry once back online: saved, closed.
        fake.on("PATCH", "/admin/deals/[^/]+", body = """{"ok":true}""")
        vm.saveGuidance("d2")
        assertNull(vm.editing.value)
        assertNull(vm.guidanceError.value)
        assertEquals("Guidance saved — Neema obeys it now", toasts.all.last().message)
    }

    @Test fun guidanceThatTimedOutButLandedIsSaved() {
        val vm = vm()
        vm.startGuidance(vm.deals.value!!.first { it.id == "d1" })
        vm.setGuidanceDraft("Free delivery, no discount")
        fake.timeout("PATCH", "/admin/deals/d1") {
            fake.on("GET", "/admin/deals") { r, _ ->
                200 to (if (r.url.queryParameter("status") == "won") SalesFixtures.wonDeals
                else SalesFixtures.deals.replace("Offer free delivery to Nyeri", "Free delivery, no discount"))
            }
        }
        vm.saveGuidance("d1")
        assertNull(vm.editing.value)
        assertEquals("Guidance saved — Neema obeys it now", toasts.all.last().message)
        assertEquals("Free delivery, no discount", vm.deals.value!!.first { it.id == "d1" }.guidance)
    }

    @Test fun guidanceThatTimedOutAndDidNotLandStaysOpen() {
        val vm = vm()
        vm.startGuidance(vm.deals.value!!.first { it.id == "d1" })
        vm.setGuidanceDraft("Free delivery, no discount")
        fake.timeout("PATCH", "/admin/deals/d1")
        vm.saveGuidance("d1")
        assertEquals("d1", vm.editing.value)
        assertEquals("Free delivery, no discount", vm.guidanceDraft.value)
        assertEquals("Not saved — the server took too long to answer — try again", vm.guidanceError.value)
    }

    @Test fun wonThatTimedOutButLandedIsWon() {
        val vm = vm()
        fake.timeout("PATCH", "/admin/deals/d2") {
            fake.on("GET", "/admin/deals") { r, _ ->
                200 to (if (r.url.queryParameter("status") == "won") SalesFixtures.wonDeals
                else SalesFixtures.deals.replace("\"id\":\"d2\"", "\"id\":\"gone\""))
            }
        }
        vm.markWon("d2")
        assertEquals("Marked won 🎉", toasts.all.last().message)
        assertTrue(errors.isEmpty())
    }

    @Test fun aDeletedDealLeavesTheBoardAndSaysSo() {
        val vm = vm()
        fake.on("PATCH", "/admin/deals/d3", code = 404, body = """{"detail":"Deal not found"}""")
        fake.on("GET", "/admin/deals") { r, _ ->
            200 to (if (r.url.queryParameter("status") == "won") SalesFixtures.wonDeals
            else SalesFixtures.deals.replace("\"id\":\"d3\"", "\"id\":\"d3-deleted\""))
        }
        vm.startGuidance(vm.deals.value!!.first { it.id == "d3" })
        vm.saveGuidance("d3")
        assertEquals("This deal no longer exists — someone may have deleted it", errors.last())
        assertTrue(vm.deals.value!!.none { it.id == "d3" })
        assertNull("the editor for a deleted deal closes", vm.editing.value)
    }
}

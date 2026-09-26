package ke.co.bethanyhouse.neema.customer

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerViewModel
import ke.co.bethanyhouse.neema.feature.conversations.customer.StageCache
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CustomerFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.CustomerFixtures.Net
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 5 — errors and network stress. Every load and every action of the CRM
 * panel against a Nairobi phone network: offline (nothing sent), a timeout (it
 * may have landed), a 401 mid-action, each error status, malformed bodies,
 * double taps, leaving mid-request — and, through all of it, what the agent
 * typed survives.
 *
 * "In flight" is simulated re-entrantly: a FakeNeema handler runs while its
 * request is outstanding, so a second tap made from inside it is exactly a tap
 * made while the first request is still on the wire.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CustomerNetworkStressTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private lateinit var fake: FakeNeema
    private lateinit var dash: DashboardViewModel
    private val toasts = mutableListOf<Toast>()
    private val scheduler = kotlinx.coroutines.test.TestCoroutineScheduler()
    private val scope = CoroutineScope(UnconfinedTestDispatcher(scheduler))
    private fun settle(ms: Long = CustomerViewModel.RELOAD_COALESCE_MS + 1) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }

    private val peterPath = "/admin/customers/${CustomerFixtures.PETER}"
    private val pushPath = "/admin/production/${CustomerFixtures.ENQUIRY_ID}/push"
    private val declinePath = "/admin/production/${CustomerFixtures.ENQUIRY_ID}/decline"

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher(scheduler))
        StageCache.stages = null
        fake = FakeNeema.withFixtures().also(CustomerFixtures::install)
    }

    @After fun tearDown() {
        scope.cancel()
        Dispatchers.resetMain()
        StageCache.stages = null
    }

    private fun vm(
        conv: Conversation = CustomerFixtures.conversation("c1"),
        placeCall: suspend (String, String?) -> Result<Unit> = { _, _ -> Result.success(Unit) },
    ): CustomerViewModel {
        if (!::dash.isInitialized) {
            dash = dashboard(paparazzi.context, fake, "admin", true)
            scope.launch { dash.toasts.collect { toasts += it } }
        }
        return CustomerViewModel(dash, conv, placeCall = placeCall)
    }

    private fun calls(method: String, path: String) = fake.calls.filter { it.method == method && it.path == path }
    private fun last() = toasts.last()
    private fun errors() = toasts.filter { it.type == ToastType.Error }
    private fun peterWith(from: String, to: String) = CustomerFixtures.peter.replace(from, to).also { check(it != CustomerFixtures.peter) }

    // ── Loading the profile ─────────────────────────────────────────────────

    @Test fun offlineAtFirstOpenShowsTheChatsFallbackSaysWhyAndRetryRecovers() {
        fake.on("GET", peterPath) { _, _ -> Net.offline() }
        val vm = vm()
        assertFalse("the spinner stops", vm.loading.value)
        assertEquals("the fallback from the chat row", "Fr. Peter Kamau", vm.profile.value!!.name)
        assertEquals(
            "Couldn't load the full profile — you're offline. Check your connection and try again. Showing what this chat knows.",
            vm.loadError.value,
        )
        fake.on("GET", peterPath, body = CustomerFixtures.peter)
        vm.refresh()
        assertNull(vm.loadError.value)
        assertEquals(listOf("vip", "clergy", "bulk"), vm.profile.value!!.tags)
        assertFalse(vm.refreshing.value)
    }

    @Test fun aFailedRefreshKeepsTheLastGoodProfileOnScreen() {
        val vm = vm()
        fake.on("GET", peterPath, code = 503, body = """{"detail":"db down"}""")
        vm.refresh()
        assertEquals("cached data stays", listOf("vip", "clergy", "bulk"), vm.profile.value!!.tags)
        assertEquals(
            "Couldn't refresh — the server had a problem. Try again in a moment. Showing the profile as last loaded.",
            vm.loadError.value,
        )
        assertFalse(vm.refreshing.value)
    }

    @Test fun aProxysHtmlPageIsNeverShown() {
        fake.on("GET", peterPath, code = 502, body = Net.HTML_502)
        val vm = vm()
        assertFalse(vm.loadError.value!!, vm.loadError.value!!.contains("<"))
        assertFalse(vm.loadError.value!!.contains("nginx"))
    }

    @Test fun aTimedOutLoadSaysTheServerTookTooLong() {
        fake.on("GET", peterPath) { _, _ -> Net.timeout() }
        val vm = vm()
        assertFalse(vm.loading.value)
        assertTrue(vm.loadError.value!!, vm.loadError.value!!.contains("the server took too long to answer"))
    }

    @Test fun anEmptyOrMalformedBodyIsNoCrashAndNoBlankProfile() {
        fake.on("GET", peterPath, body = "")
        val vm = vm()
        assertEquals("fallback, not an all-defaults profile", CustomerFixtures.PETER, vm.profile.value!!.waId)
        assertTrue(vm.loadError.value!!.contains("couldn't read"))
        fake.on("GET", peterPath, body = "{\"id\": 12, \"tags\": ")
        vm.refresh()
        assertEquals(CustomerFixtures.PETER, vm.profile.value!!.waId)
        assertNotNull(vm.loadError.value)
    }

    @Test fun aCustomerWithNoSavedProfileSaysItMayHaveBeenMerged() {
        fake.on("GET", peterPath, code = 404, body = """{"detail":"Customer not found"}""")
        val vm = vm()
        assertEquals(
            "No saved profile for this customer — it may have been merged into another. Showing what this chat knows.",
            vm.loadError.value,
        )
        assertEquals("Fr. Peter Kamau", vm.profile.value!!.name)
    }

    @Test fun aReconnectOrForegroundRetriesAFailedLoadByItself() {
        fake.on("GET", peterPath) { _, _ -> Net.offline() }
        val vm = vm()
        vm.onShown()
        fake.on("GET", peterPath, body = CustomerFixtures.peter)
        dash.container.foreground.value = false
        dash.container.foreground.value = true
        settle()
        assertNull(vm.loadError.value)
        assertEquals(listOf("vip", "clergy", "bulk"), vm.profile.value!!.tags)
    }

    /** The auth server hands out a NEW access token (the rejected one is never reused). */
    private fun freshTokensOnRefresh() =
        fake.on("POST", "/agent-auth/refresh", body = """{"access_token":"${ke.co.bethanyhouse.neema.testing.fakeJwt()}.x","refresh_token":"r2"}""")

    @Test fun aTokenThatExpiredMidLoadRefreshesSilently() {
        freshTokensOnRefresh()
        var n = 0
        fake.on("GET", peterPath) { _, _ -> if (n++ == 0) 401 to """{"detail":"Token expired"}""" else 200 to CustomerFixtures.peter }
        val vm = vm()
        assertNull(vm.loadError.value)
        assertEquals(listOf("vip", "clergy", "bulk"), vm.profile.value!!.tags)
        assertEquals(1, calls("POST", "/agent-auth/refresh").size)
        assertFalse(dash.sessionExpired.value)
    }

    @Test fun aFailedStageListIsNotCachedAsNoStagesForTheRestOfTheDay() {
        fake.on("GET", "/admin/settings/pipeline-stages") { _, _ -> Net.offline() }
        vm()
        assertNull("a failure is not cached", StageCache.stages)
        fake.on("GET", "/admin/settings/pipeline-stages", body = """{"stages":["measuring"]}""")
        val vm2 = vm()
        assertEquals(listOf("measuring"), vm2.customStages.value)
    }

    // ── Field edits (PATCH) ─────────────────────────────────────────────────

    @Test fun anOfflineSaveRollsBackAndGivesTheTypedTextBack() {
        val vm = vm()
        fake.on("PATCH", peterPath) { _, _ -> Net.offline() }
        vm.saveField("email", "fr.peter@parish.ke") { it.copy(email = "fr.peter@parish.ke") }
        assertEquals("peter.kamau@stmarks.or.ke", vm.profile.value!!.email)
        assertEquals("the editor reopens with it", "fr.peter@parish.ke", vm.drafts.value["email"])
        assertEquals("Failed to save — you're offline. Check your connection and try again.", last().message)
        assertEquals(ToastType.Error, last().type)
        assertFalse(vm.saving.value)
        vm.takeDraft("email")
        assertNull(vm.drafts.value["email"])
    }

    @Test fun aTimedOutSaveIsNeverCalledAFailureAndIsConfirmedByRefetching() {
        val vm = vm()
        fake.on("PATCH", peterPath) { _, _ -> Net.timeout() }
        // It did land: the server now has Mombasa.
        fake.on("GET", peterPath, body = peterWith("\"location\":\"Nyeri\"", "\"location\":\"Mombasa\""))
        vm.saveField("location", "Mombasa") { it.copy(location = "Mombasa") }
        assertEquals("the edit stays while we check", "Mombasa", vm.profile.value!!.location)
        assertEquals("Couldn't confirm the save — checking with the server…", last().message)
        assertEquals(ToastType.Info, last().type)
        val gets = calls("GET", peterPath).size
        settle()
        assertEquals(gets + 1, calls("GET", peterPath).size)
        assertEquals("Saved", last().message)
        assertTrue(errors().isEmpty())
        assertTrue(vm.drafts.value.isEmpty())
    }

    @Test fun aTimedOutSaveThatDidNotLandComesBackToTheEditor() {
        val vm = vm()
        fake.on("PATCH", peterPath) { _, _ -> Net.timeout() }
        vm.saveField("location", "Mombasa") { it.copy(location = "Mombasa") }
        settle()
        assertEquals("the server's truth", "Nyeri", vm.profile.value!!.location)
        assertEquals("Mombasa", vm.drafts.value["location"])
        assertEquals("That change didn't reach the server — it's back in the editor to try again.", last().message)
    }

    @Test fun aRefusalRollsBackOnlyItsOwnEditNotAnotherInFlight() {
        lateinit var vm: CustomerViewModel
        var once = true
        fake.on("PATCH", peterPath) { _, body ->
            if (body!!.contains("\"role\"")) {
                // While the role save is on the wire, the agent saves the location too (it succeeds).
                if (once) { once = false; vm.saveField("location", "Karatina") { it.copy(location = "Karatina") } }
                500 to """{"detail":"db down"}"""
            } else 200 to """{"ok":true}"""
        }
        vm = vm()
        vm.saveField("role", "Archdeacon") { it.copy(role = "Archdeacon") }
        assertEquals("the role rolled back", "Parish Priest", vm.profile.value!!.role)
        assertEquals("the location that saved is not undone with it", "Karatina", vm.profile.value!!.location)
        assertEquals("Archdeacon", vm.drafts.value["role"])
    }

    @Test fun aDoubleTapOnAStageSendsOnePatchAndAdvanceNeverSkipsAStage() {
        lateinit var vm: CustomerViewModel
        var busyWhileInFlight = false
        fake.on("PATCH", peterPath) { _, _ ->
            busyWhileInFlight = vm.stageBusy.value
            vm.setStage("won")          // the same tap again
            vm.setStage("negotiation")  // "Advance" tapped again from the optimistic stage
            200 to """{"ok":true}"""
        }
        vm = vm()
        vm.setStage("won")
        assertEquals(1, calls("PATCH", peterPath).size)
        assertTrue("the stage buttons disable while it saves", busyWhileInFlight)
        assertFalse(vm.stageBusy.value)
        assertEquals("won", vm.profile.value!!.leadStage)
    }

    @Test fun aTokenThatExpiredMidSaveRefreshesAndTheSaveCompletes() {
        freshTokensOnRefresh()
        val vm = vm()
        var n = 0
        fake.on("PATCH", peterPath) { _, _ -> if (n++ == 0) 401 to """{"detail":"Token expired"}""" else 200 to """{"ok":true}""" }
        vm.saveField("location", "Othaya") { it.copy(location = "Othaya") }
        assertEquals(2, calls("PATCH", peterPath).size)
        assertEquals("Saved", last().message)
        assertEquals("Othaya", vm.profile.value!!.location)
        assertFalse(dash.sessionExpired.value)
    }

    @Test fun aSessionThatCannotBeRescuedKeepsTheTextForAfterSigningIn() {
        val vm = vm()
        fake.on("PATCH", peterPath, code = 401, body = """{"detail":"Could not validate credentials"}""")
        fake.on("POST", "/agent-auth/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        vm.saveField("email", "fr.peter@parish.ke") { it.copy(email = "fr.peter@parish.ke") }
        assertTrue("the session-expired prompt opens", dash.sessionExpired.value)
        assertEquals("Failed to save — your session expired. Sign in again, then retry.", last().message)
        assertEquals("fr.peter@parish.ke", vm.drafts.value["email"])

        // Signed in again: the draft is still there and the save goes through.
        fake.on("PATCH", peterPath, body = """{"ok":true}""")
        freshTokensOnRefresh()
        dash.onReauthenticated()
        val draft = vm.drafts.value["email"]!!
        vm.saveField("email", draft) { it.copy(email = draft) }
        assertEquals("Saved", last().message)
        assertEquals("fr.peter@parish.ke", vm.profile.value!!.email)
    }

    @Test fun aSaveOnACustomerMergedAwayByAColleagueSaysSoAndRefetches() {
        val vm = vm()
        fake.on("PATCH", peterPath, code = 404, body = """{"detail":"Customer not found"}""")
        val gets = calls("GET", peterPath).size
        vm.saveField("location", "Nanyuki") { it.copy(location = "Nanyuki") }
        assertEquals(
            "Failed to save — this customer's profile is gone (it may have been merged into another). Refreshing.",
            last().message,
        )
        settle()
        assertEquals(gets + 1, calls("GET", peterPath).size)
        assertEquals("Nanyuki", vm.drafts.value["location"])
    }

    @Test fun aConflictRefetchesTheTruth() {
        val vm = vm()
        fake.on("PATCH", peterPath, code = 409, body = """{"detail":"Profile changed"}""")
        val gets = calls("GET", peterPath).size
        vm.setStage("won")
        assertEquals("Failed to save — it changed meanwhile. Refreshing to show the latest.", last().message)
        assertEquals("proposal", vm.profile.value!!.leadStage)
        settle()
        assertEquals(gets + 1, calls("GET", peterPath).size)
    }

    @Test fun eachErrorStatusGetsItsOwnPlainWords() {
        val vm = vm()
        val cases = listOf(
            403 to """{"detail":"Not enough permissions"}""" to "Failed to save — not enough permissions.",
            422 to """{"detail":[{"loc":["body","age"],"msg":"value is not a valid integer","type":"int"}]}""" to
                "Failed to save — the server didn't accept that.",
            429 to """{"detail":"Too Many Requests"}""" to "Failed to save — too many requests. Wait a moment, then try again.",
            500 to "Internal Server Error" to "Failed to save — the server had a problem. Try again in a moment.",
            502 to Net.HTML_502 to "Failed to save — the server had a problem. Try again in a moment.",
            503 to "" to "Failed to save — the server had a problem. Try again in a moment.",
        )
        cases.forEachIndexed { i, (reply, want) ->
            fake.on("PATCH", peterPath, code = reply.first, body = reply.second)
            vm.saveField("location", "Town $i") { it.copy(location = "Town $i") }
            assertEquals("HTTP ${reply.first}", want, last().message)
            assertEquals("Nyeri", vm.profile.value!!.location)
        }
    }

    @Test fun aFailedNotesSaveReopensTheEditorOnTheSameDraftAndBase() {
        val vm = vm()
        val base = vm.profile.value!!.notes!!
        vm.startEditNotes()
        vm.noteDraft.value = "$base\n\nMeasured for a cassock, size L."
        fake.on("PATCH", peterPath) { _, _ -> Net.offline() }
        vm.saveNotes()
        assertTrue(vm.editNotes.value)
        assertEquals("$base\n\nMeasured for a cassock, size L.", vm.noteDraft.value)
        assertEquals(base, vm.notesBase.value)
        assertEquals(base, vm.profile.value!!.notes)
        // Retried when back online: the base is still the snapshot the edit began from.
        fake.on("PATCH", peterPath, body = """{"ok":true}""")
        vm.saveNotes()
        val body = NeemaJson.parseToJsonElement(calls("PATCH", peterPath).last().body!!).jsonObject
        assertEquals(base, body["notes_base"]!!.jsonPrimitive.content)
        assertFalse(vm.editNotes.value)
    }

    @Test fun aTagThatFailedToSaveGoesBackIntoTheTagBox() {
        val vm = vm()
        vm.tagInput.value = "easter-2027"
        fake.on("PATCH", peterPath) { _, _ -> Net.offline() }
        vm.addTag()
        assertEquals("easter-2027", vm.tagInput.value)
        assertEquals(listOf("vip", "clergy", "bulk"), vm.profile.value!!.tags)
        fake.on("PATCH", peterPath, body = """{"ok":true}""")
        vm.addTag()
        assertEquals("", vm.tagInput.value)
        assertEquals(listOf("vip", "clergy", "bulk", "easter-2027"), vm.profile.value!!.tags)
    }

    @Test fun leavingMidSaveShowsNoConfirmationAndNamesTheCustomerOnFailure() {
        lateinit var vm: CustomerViewModel
        fake.on("PATCH", peterPath) { _, _ -> vm.onHidden(); 200 to """{"ok":true}""" }
        vm = vm()
        vm.onShown()
        val before = toasts.size
        vm.saveField("location", "Nyeri Town") { it.copy(location = "Nyeri Town") }
        assertEquals("no 'Saved' for a panel that is gone", before, toasts.size)
        assertEquals("Nyeri Town", vm.profile.value!!.location)

        fake.on("PATCH", peterPath, code = 500, body = "{}")
        vm.saveField("location", "Karatina") { it.copy(location = "Karatina") }
        assertEquals("Fr. Peter Kamau: Failed to save — the server had a problem. Try again in a moment.", last().message)
    }

    // ── Merge / unmerge ─────────────────────────────────────────────────────

    @Test fun aDoubleTapOnMergeSendsOneMerge() {
        lateinit var vm: CustomerViewModel
        var busy = false
        fake.on("POST", "$peterPath/merge") { _, _ ->
            busy = vm.merging.value
            vm.merge("254799000222")
            200 to """{"ok":true}"""
        }
        vm = vm()
        vm.toggleMerge(true)
        vm.merge("254799000222")
        assertEquals(1, calls("POST", "$peterPath/merge").size)
        assertTrue("Merge disables while it runs", busy)
        assertFalse(vm.merging.value)
    }

    @Test fun anOfflineMergeKeepsTheTypedTargetAndSaysWhy() {
        val vm = vm()
        vm.toggleMerge(true)
        vm.mergeQuery.value = "254700999888"
        fake.on("POST", "$peterPath/merge") { _, _ -> Net.offline() }
        vm.merge()
        assertEquals("Failed to merge profiles — you're offline. Check your connection and try again.", last().message)
        assertEquals("254700999888", vm.mergeQuery.value)
        assertTrue(vm.showMerge.value)
        fake.on("POST", "$peterPath/merge", body = """{"ok":true}""")
        vm.merge()
        assertEquals("", vm.mergeQuery.value)
        assertFalse(vm.showMerge.value)
    }

    @Test fun aTimedOutMergeChecksWhereItStandsInsteadOfFailing() {
        val vm = vm()
        vm.toggleMerge(true)
        vm.mergeQuery.value = "254799000222"
        fake.on("POST", "$peterPath/merge") { _, _ -> Net.timeout() }
        val gets = calls("GET", peterPath).size
        vm.merge()
        assertEquals("Couldn't confirm the merge — refreshing to show where it stands.", last().message)
        assertTrue(errors().isEmpty())
        assertEquals(gets + 1, calls("GET", peterPath).size)
        assertEquals("254799000222", vm.mergeQuery.value)
    }

    @Test fun mergingAProfileAColleagueAlreadyMergedAwaySaysSoAndRefetches() {
        val vm = vm()
        vm.toggleMerge(true)
        fake.on("POST", "$peterPath/merge", code = 404, body = """{"detail":"Primary customer not found"}""")
        val gets = calls("GET", peterPath).size
        vm.merge("254799000222")
        assertEquals(
            "Failed to merge profiles — this profile is gone (it may already have been merged into another). Refreshing.",
            last().message,
        )
        assertEquals(gets + 1, calls("GET", peterPath).size)
    }

    @Test fun aFailedDuplicateScanSaysSoAndCanBeRetried() {
        fake.on("GET", "$peterPath/merge_suggestions") { _, _ -> Net.offline() }
        val vm = vm()
        vm.toggleMerge(true)
        assertEquals(emptyList<Any>(), vm.mergeSugs.value)
        assertEquals("Couldn't scan for duplicates — you're offline. Check your connection and try again.", vm.mergeSugsError.value)
        fake.on("GET", "$peterPath/merge_suggestions", body = CustomerFixtures.suggestions)
        vm.retryMergeScan()
        assertNull(vm.mergeSugsError.value)
        assertEquals(2, vm.mergeSugs.value!!.size)
    }

    @Test fun unmergingWhatAColleagueAlreadyUnmergedRefreshesQuietly() {
        val vm = vm()
        fake.on("POST", "$peterPath/unmerge", code = 404, body = """{"detail":"No active merge to undo for this pair"}""")
        val gets = calls("GET", peterPath).size
        vm.unmerge("254799000111")
        assertEquals("Already unmerged — refreshed to show where it stands.", last().message)
        assertEquals(ToastType.Info, last().type)
        assertEquals(gets + 1, calls("GET", peterPath).size)
    }

    @Test fun aDoubleTapOnUnmergeSendsOneAndATimeoutIsChecked() {
        lateinit var vm: CustomerViewModel
        fake.on("POST", "$peterPath/unmerge") { _, _ ->
            assertTrue("254799000111" in vm.unmerging.value)
            vm.unmerge("254799000111")
            Net.timeout()
        }
        vm = vm()
        vm.unmerge("254799000111")
        assertEquals(1, calls("POST", "$peterPath/unmerge").size)
        assertEquals("Couldn't confirm the unmerge — refreshing to show where it stands.", last().message)
        assertTrue(vm.unmerging.value.isEmpty())
    }

    // ── Made-to-order: push to production / dismiss ─────────────────────────

    @Test fun aPushAlreadyMadeByAColleagueShowsTheExistingOrder() {
        fake.on("POST", pushPath, body = CustomerFixtures.alreadyPushed)
        val vm = vm()
        vm.pushProduction()
        assertEquals("Already in production · BH-2001", last().message)
        assertEquals("pushed", vm.enquiry.value!!.status)
        assertEquals("BH-2001", vm.enquiry.value!!.hubOrderNumber)
    }

    @Test fun aConflictingPushRefetchesAndShowsTheCurrentTruth() {
        val vm = vm()
        fake.on("POST", pushPath, code = 409, body = """{"detail":"Enquiry already pushed"}""")
        fake.on("GET", "/admin/production/conversation/c1", body = CustomerFixtures.enquiry("pushed", order = "BH-2001"))
        vm.pushProduction()
        assertEquals("This request was already handled — showing where it stands.", last().message)
        assertEquals("pushed", vm.enquiry.value!!.status)
        assertEquals("BH-2001", vm.enquiry.value!!.hubOrderNumber)
        assertFalse(vm.pushing.value)
    }

    @Test fun aTimedOutPushIsCheckedNotFailed() {
        val vm = vm()
        fake.on("POST", pushPath) { _, _ -> Net.timeout() }
        fake.on("GET", "/admin/production/conversation/c1", body = CustomerFixtures.enquiry("pushed", order = "BH-2001"))
        vm.pushProduction()
        assertEquals(
            "Couldn't confirm it reached production — checking. Pushing again is safe: it never makes a second order.",
            last().message,
        )
        assertTrue(errors().isEmpty())
        assertEquals("pushed", vm.enquiry.value!!.status)
        assertFalse(vm.pushing.value)
    }

    @Test fun anEnquiryRemovedMeanwhileDisappearsWithAWord() {
        val vm = vm()
        fake.on("POST", pushPath, code = 404, body = """{"detail":"Enquiry not found"}""")
        vm.pushProduction()
        assertNull(vm.enquiry.value)
        assertEquals("This made-to-order request no longer exists — someone may have removed it.", last().message)
    }

    @Test fun aDoubleTapOnPushSendsOneAndDismissWaitsForIt() {
        lateinit var vm: CustomerViewModel
        fake.on("POST", pushPath) { _, _ ->
            vm.pushProduction()
            vm.declineProduction()
            200 to CustomerFixtures.pushed
        }
        vm = vm()
        vm.pushProduction()
        assertEquals(1, calls("POST", pushPath).size)
        assertTrue(calls("POST", declinePath).isEmpty())
        assertEquals("Sent to production · BH-2001", last().message)
    }

    @Test fun aNoHubProductPushShowsTheServersAdvice() {
        val vm = vm()
        fake.on("POST", pushPath, code = 422, body = """{"detail":"This enquiry has no linked hub product — create the order in the hub manually."}""")
        vm.pushProduction()
        assertEquals("This enquiry has no linked hub product — create the order in the hub manually.", last().message)
        assertEquals("new", vm.enquiry.value!!.status)
    }

    @Test fun dismissOfflineRevertsAndATimedOutDismissIsChecked() {
        val vm = vm()
        fake.on("POST", declinePath) { _, _ -> Net.offline() }
        vm.declineProduction()
        assertEquals("new", vm.enquiry.value!!.status)
        assertEquals("Couldn't dismiss — you're offline. Check your connection and try again.", last().message)

        fake.on("POST", declinePath) { _, _ -> Net.timeout() }
        fake.on("GET", "/admin/production/conversation/c1", body = CustomerFixtures.enquiry("declined"))
        val n = toasts.size
        vm.declineProduction()
        assertEquals("declined", vm.enquiry.value!!.status)
        assertEquals("no error for what may have worked", n, toasts.size)
    }

    @Test fun anEnquiryThatFailedToLoadArrivesOnTheNextRefresh() {
        fake.on("GET", "/admin/production/conversation/c1") { _, _ -> Net.offline() }
        val vm = vm()
        assertNull(vm.enquiry.value)
        fake.on("GET", "/admin/production/conversation/c1", body = CustomerFixtures.enquiry())
        vm.refresh()
        assertEquals(CustomerFixtures.ENQUIRY_ID, vm.enquiry.value!!.id)
    }

    // ── Pipeline stages ─────────────────────────────────────────────────────

    @Test fun aStageLabelStaysInTheBoxUntilTheServerKeptItAndAddCannotDoubleSend() {
        val vm = vm()
        vm.newStage.value = "Sampling"
        fake.on("PUT", "/admin/settings/pipeline-stages") { _, _ -> Net.offline() }
        vm.addCustomStage()
        assertEquals("Sampling", vm.newStage.value)
        assertEquals("Couldn't save pipeline stages — you're offline. Check your connection and try again.", last().message)

        fake.on("PUT", "/admin/settings/pipeline-stages") { _, _ ->
            vm.addCustomStage()   // tapped again while saving
            200 to """{"stages":["measuring","Sampling"]}"""
        }
        val puts = calls("PUT", "/admin/settings/pipeline-stages").size
        vm.addCustomStage()
        assertEquals(puts + 1, calls("PUT", "/admin/settings/pipeline-stages").size)
        assertEquals("", vm.newStage.value)
        assertEquals(listOf("measuring", "Sampling"), vm.customStages.value)
    }

    @Test fun aTimedOutStageSaveRefetchesTheStages() {
        val vm = vm()
        vm.newStage.value = "Sampling"
        fake.on("PUT", "/admin/settings/pipeline-stages") { _, _ -> Net.timeout() }
        fake.on("GET", "/admin/settings/pipeline-stages", body = """{"stages":["measuring","Sampling"]}""")
        vm.addCustomStage()
        assertEquals("Couldn't confirm the stage change — refreshing the stages.", last().message)
        assertEquals(listOf("measuring", "Sampling"), vm.customStages.value)
        assertEquals("it landed, so the box clears", "", vm.newStage.value)
    }

    // ── Reach-out: invite, template, call ───────────────────────────────────

    @Test fun aTimedOutInviteNeverOpensASecondMessageAndADoubleTapSendsOne() {
        lateinit var vm: CustomerViewModel
        var opened: String? = null
        fake.on("POST", "/admin/whatsapp-invite") { _, _ ->
            vm.inviteToWhatsApp(CustomerFixtures.PETER) { opened = it }
            Net.timeout()
        }
        vm = vm()
        vm.inviteToWhatsApp(CustomerFixtures.PETER) { opened = it }
        assertEquals(1, calls("POST", "/admin/whatsapp-invite").size)
        assertNull("no wa.me fallback for an invite that may have gone out", opened)
        assertEquals("Couldn't confirm the invite went out — check the WhatsApp thread before sending again.", last().message)
        assertFalse(vm.inviteBusy.value)
    }

    @Test fun anOfflineInviteStillOffersTheWaMeFallback() {
        fake.on("POST", "/admin/whatsapp-invite") { _, _ -> Net.offline() }
        val vm = vm()
        var opened: String? = null
        vm.inviteToWhatsApp(CustomerFixtures.PETER) { opened = it }
        assertTrue(opened!!.startsWith("https://wa.me/254712345678?text="))
    }

    @Test fun anInviteThatFailsAfterThePanelLeftNeverThrowsWhatsAppOpen() {
        lateinit var vm: CustomerViewModel
        fake.on("POST", "/admin/whatsapp-invite") { _, _ -> vm.onHidden(); 503 to """{"detail":"WhatsApp sending is not configured."}""" }
        vm = vm()
        var opened: String? = null
        vm.inviteToWhatsApp(CustomerFixtures.PETER) { opened = it }
        assertNull(opened)
        assertEquals("Fr. Peter Kamau: Couldn't send the WhatsApp invite — the server had a problem. Try again in a moment.", last().message)
    }

    @Test fun aTemplateCannotBeSentTwiceByADoubleTapAndATimeoutIsNotAFailure() {
        lateinit var vm: CustomerViewModel
        fake.on("POST", "/admin/whatsapp-invite") { _, _ ->
            vm.sendTemplate(CustomerFixtures.PETER)
            Net.timeout()
        }
        vm = vm()
        vm.sendTemplate(CustomerFixtures.PETER)
        assertEquals(1, calls("POST", "/admin/whatsapp-invite").size)
        assertEquals("Couldn't confirm the template went out — check the WhatsApp thread before sending again.", last().message)
        assertTrue(errors().isEmpty())
        assertFalse(vm.templateBusy.value)
    }

    @Test fun aDoubleTapOnCallPlacesOneCall() {
        lateinit var vm: CustomerViewModel
        var dialled = 0
        vm = vm(placeCall = { _, _ ->
            dialled++
            vm.call(CustomerFixtures.PETER)   // tapped again while dialling
            Result.success(Unit)
        })
        assertFalse(vm.callBusy.value)
        vm.call(CustomerFixtures.PETER)
        assertEquals(1, dialled)
        assertFalse(vm.callBusy.value)
    }

    @Test fun aTimedOutPermissionRequestIsNotReportedAsFailed() {
        fake.on("POST", "/admin/calls/request-permission") { _, _ -> Net.timeout() }
        val vm = vm(placeCall = { _, _ -> Result.failure(IllegalStateException("Customer hasn't granted call permission.")) })
        vm.call(CustomerFixtures.PETER)
        assertEquals("Couldn't confirm the call request went out — check the thread before asking again.", last().message)
        assertTrue(errors().isEmpty())
        fake.on("POST", "/admin/calls/request-permission") { _, _ -> Net.offline() }
        vm.call(CustomerFixtures.PETER)
        assertEquals("Couldn't send the call request — you're offline. Check your connection and try again.", last().message)
    }

    // ── Ask Neema / Answer via Neema ────────────────────────────────────────

    @Test fun askSaysWhatWentWrongAndNeverAsksTwice() {
        lateinit var vm: CustomerViewModel
        var n = 0
        fake.on("POST", "/admin/conversations/c1/ask") { _, _ -> n++; vm.ask("sizes?"); Net.offline() }
        vm = vm()
        vm.askDraft.value = "sizes?"
        vm.ask()
        assertEquals(1, n)
        assertEquals("You're offline — ask again once you're connected.", vm.askAnswer.value)
        assertEquals("the question stays", "sizes?", vm.askDraft.value)
        fake.on("POST", "/admin/conversations/c1/ask") { _, _ -> Net.timeout() }
        vm.ask()
        assertEquals("Neema took too long to answer — try again.", vm.askAnswer.value)
        fake.on("POST", "/admin/conversations/c1/ask", code = 429, body = """{"detail":"rate limited"}""")
        vm.ask()
        assertEquals("Neema is busy — wait a moment, then ask again.", vm.askAnswer.value)
        assertFalse(vm.askBusy.value)
    }

    @Test fun aTimedOutAnswerIsNeverCalledUnsentAndTheFactsStay() {
        val vm = vm()
        vm.answerDraft.value = "yes, KES 3,500, ~5 days"
        fake.on("POST", "/admin/conversations/c1/answer") { _, _ -> Net.timeout() }
        vm.answerViaNeema()
        assertEquals("Couldn't confirm Neema sent it — check the thread before sending again.", vm.answerStatus.value)
        assertEquals("yes, KES 3,500, ~5 days", vm.answerDraft.value)
        assertFalse(vm.answerBusy.value)
    }

    @Test fun anOfflineAnswerKeepsTheFactsAndASentOneClearsThem() {
        lateinit var vm: CustomerViewModel
        var n = 0
        fake.on("POST", "/admin/conversations/c1/answer") { _, _ -> n++; vm.answerViaNeema(); Net.offline() }
        vm = vm()
        vm.answerDraft.value = "yes, we make it"
        vm.answerViaNeema()
        assertEquals("a double tap sends once", 1, n)
        assertEquals("You're offline — your answer is kept; send it once you're connected.", vm.answerStatus.value)
        assertEquals("yes, we make it", vm.answerDraft.value)
        fake.on("POST", "/admin/conversations/c1/answer", body = """{"ok":true,"sent":"Yes Father, we make it 🙏"}""")
        vm.answerViaNeema()
        assertEquals("", vm.answerDraft.value)
        assertEquals("Neema sent: “Yes Father, we make it 🙏”", vm.answerStatus.value)
    }
}

package ke.co.bethanyhouse.neema.customer

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerTab
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerViewModel
import ke.co.bethanyhouse.neema.feature.conversations.customer.StageCache
import ke.co.bethanyhouse.neema.feature.conversations.customer.canEditPipelineStages
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CustomerFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Every CRM-panel action against the fake backend: the endpoint, the body,
 * the optimistic state, the rollback and the toast — each checked against
 * CustomerSidebar.tsx and routers/crm.py.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CustomerViewModelTest {
    // Paparazzi only to get an Android context on the JVM.
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private lateinit var fake: FakeNeema
    private lateinit var dash: DashboardViewModel
    private val toasts = mutableListOf<Toast>()
    private val scope = CoroutineScope(UnconfinedTestDispatcher())

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        StageCache.stages = null
        fake = FakeNeema.withFixtures().also(CustomerFixtures::install)
    }

    @After fun tearDown() {
        scope.cancel()
        Dispatchers.resetMain()
        StageCache.stages = null
    }

    private fun signIn(role: String = "agent", superuser: Boolean = false) {
        if (role != "admin" && !superuser) {
            // /me and the roster as a plain agent, so the panel sees who the server sees.
            val agent = Fixtures.me.replace("\"role\":\"admin\"", "\"role\":\"$role\"").replace("\"is_superuser\":true", "\"is_superuser\":false")
            fake.on("GET", "/admin/me", body = agent)
            fake.on("GET", "/admin/agents", body = "[$agent]")
        }
        dash = dashboard(paparazzi.context, fake, role, superuser)
        scope.launch { dash.toasts.collect { toasts += it } }
    }

    private fun vm(
        convId: String = "c1",
        conv: Conversation = CustomerFixtures.conversation(convId),
        placeCall: suspend (String, String?) -> Result<Unit> = { _, _ -> Result.success(Unit) },
    ): CustomerViewModel {
        if (!::dash.isInitialized) signIn()
        return CustomerViewModel(dash, conv, placeCall)
    }

    private fun calls(method: String, path: String) = fake.calls.filter { it.method == method && it.path == path }
    private fun lastBody(method: String, path: String): JsonObject =
        NeemaJson.parseToJsonElement(calls(method, path).last().body!!).jsonObject
    private fun lastToast() = toasts.lastOrNull()

    // ── Load ────────────────────────────────────────────────────────────────

    @Test fun loadsTheProfileKeyedOnWaIdWithTheChannel() {
        val vm = vm()
        val get = calls("GET", "/admin/customers/${CustomerFixtures.PETER}").single()
        assertEquals("channel=whatsapp", get.query)
        assertFalse(vm.loading.value)
        val p = vm.profile.value!!
        assertEquals("Fr. Peter Kamau", p.name)
        assertEquals(4, p.orders!!.size)
        assertEquals(listOf("vip", "clergy", "bulk"), p.tags)
        assertEquals(CustomerTab.Profile, vm.tab.value)
    }

    @Test fun nonWhatsAppContactsKeyOnTheirChannelHandle() {
        // wa_id null (Messenger PSID) — the web uses external_id so edits don't hit /customers/null.
        val conv = CustomerFixtures.conversation("c2").copy(waId = null, externalId = "PSID77")
        fake.on("GET", "/admin/customers/PSID77", body = CustomerFixtures.mary.replace("\"wa_id\":\"${CustomerFixtures.MARY}\"", "\"wa_id\":null"))
        val vm = vm(conv = conv)
        assertEquals("channel=messenger", calls("GET", "/admin/customers/PSID77").single().query)
        vm.saveField("location", "Kisumu") { it.copy(location = "Kisumu") }
        assertEquals(1, calls("PATCH", "/admin/customers/PSID77").size)
    }

    @Test fun aFailedLoadFallsBackToAMinimalProfileFromTheConversation() {
        fake.on("GET", "/admin/customers/${CustomerFixtures.PETER}", code = 500, body = """{"detail":"boom"}""")
        val vm = vm()
        val p = vm.profile.value!!
        assertEquals("Fr. Peter Kamau", p.name)
        assertEquals(CustomerFixtures.PETER, p.waId)
        assertEquals(CustomerFixtures.PETER, p.phone)
        assertEquals("new", p.leadStage)
        assertEquals(0.0, p.leadScore, 0.0)
        assertEquals(1, p.channels.size)
        assertEquals("whatsapp", p.channels[0].channel)
        assertEquals(1, p.channels[0].conversationCount)
        assertEquals("KE", p.countryIso)
        assertFalse(vm.loading.value)
    }

    @Test fun aNewMessageOrRenameOnTheRowReloadsQuietly() {
        val conv = CustomerFixtures.conversation("c1")
        val vm = vm(conv = conv)
        val path = "/admin/customers/${CustomerFixtures.PETER}"
        vm.sync(conv)
        assertEquals(1, calls("GET", path).size)
        vm.sync(conv.copy(lastMessageAt = Fixtures.ago(0)))
        assertEquals(2, calls("GET", path).size)
        vm.sync(conv.copy(lastMessageAt = Fixtures.ago(0), name = "Fr. Peter K."))
        assertEquals(3, calls("GET", path).size)
        assertFalse("a quiet reload never blanks the panel", vm.loading.value)
    }

    // ── PATCH edits ─────────────────────────────────────────────────────────

    @Test fun editingAFieldPatchesItOptimisticallyAndToastsSaved() {
        val vm = vm()
        vm.saveField("role", "Archdeacon") { it.copy(role = "Archdeacon") }
        val path = "/admin/customers/${CustomerFixtures.PETER}"
        assertEquals("channel=whatsapp", calls("PATCH", path).single().query)
        assertEquals("""{"role":"Archdeacon"}""", calls("PATCH", path).single().body)
        assertEquals("Archdeacon", vm.profile.value!!.role)
        assertEquals("Saved", lastToast()!!.message)
        assertFalse(vm.saving.value)
    }

    @Test fun everyContactFieldSendsItsOwnKey() {
        val vm = vm()
        val path = "/admin/customers/${CustomerFixtures.PETER}"
        listOf("organization", "email", "phone", "country", "location").forEach { f ->
            vm.saveField(f, "x-$f") { it }
            assertEquals("x-$f", lastBody("PATCH", path)[f]!!.jsonPrimitive.content)
        }
    }

    @Test fun aFailedSaveRollsBackAndToastsAnError() {
        val vm = vm()
        fake.on("PATCH", "/admin/customers/.*", code = 500, body = """{"detail":"db down"}""")
        vm.saveField("location", "Mombasa") { it.copy(location = "Mombasa") }
        assertEquals("Nyeri", vm.profile.value!!.location)
        assertEquals("Failed to save", lastToast()!!.message)
        assertEquals(ToastType.Error, lastToast()!!.type)
        assertFalse(vm.saving.value)
    }

    @Test fun renamingTellsTheInboxOnlyAfterTheServerAccepts() {
        val vm = vm()
        val renamed = mutableListOf<Pair<String, String>>()
        vm.saveName("Fr. Peter M. Kamau") { id, n -> renamed += id to n }
        assertEquals(listOf(CustomerFixtures.PETER to "Fr. Peter M. Kamau"), renamed)
        assertEquals("""{"name":"Fr. Peter M. Kamau"}""", calls("PATCH", "/admin/customers/${CustomerFixtures.PETER}").last().body)

        fake.on("PATCH", "/admin/customers/.*", code = 500, body = "{}")
        vm.saveName("Oops") { id, n -> renamed += id to n }
        assertEquals(1, renamed.size)
        assertEquals("Fr. Peter M. Kamau", vm.profile.value!!.name)
    }

    @Test fun clearingTheNameSavesButDoesNotRenameTheInboxRow() {
        val vm = vm()
        var told = false
        vm.saveName("") { _, _ -> told = true }
        assertEquals("""{"name":""}""", calls("PATCH", "/admin/customers/${CustomerFixtures.PETER}").last().body)
        assertFalse(told)
    }

    @Test fun ageFollowsParseIntOrNull() {
        val vm = vm()
        val path = "/admin/customers/${CustomerFixtures.PETER}"
        vm.saveAge("35 yrs")
        assertEquals("35", lastBody("PATCH", path)["age"]!!.jsonPrimitive.content)
        assertEquals(35, vm.profile.value!!.age)
        vm.saveAge("abc")
        assertEquals(JsonNull, lastBody("PATCH", path)["age"])
        vm.saveAge("0")
        assertEquals(JsonNull, lastBody("PATCH", path)["age"])
    }

    @Test fun movingTheStagePatchesLeadStageAndClearsTheAiHint() {
        val vm = vm()
        assertEquals("auto", vm.profile.value!!.leadStageSource)
        vm.setStage("negotiation")
        assertEquals("""{"lead_stage":"negotiation"}""", calls("PATCH", "/admin/customers/${CustomerFixtures.PETER}").last().body)
        assertEquals("negotiation", vm.profile.value!!.leadStage)
        assertEquals("manual", vm.profile.value!!.leadStageSource)
    }

    @Test fun movingToACustomStageSendsItsLabel() {
        val vm = vm()
        vm.setStage("measuring")
        assertEquals("measuring", lastBody("PATCH", "/admin/customers/${CustomerFixtures.PETER}")["lead_stage"]!!.jsonPrimitive.content)
    }

    @Test fun tagsAreSentAsTheWholeNewList() {
        val vm = vm()
        val path = "/admin/customers/${CustomerFixtures.PETER}"
        vm.addTag("  choir  ")
        assertEquals(listOf("vip", "clergy", "bulk", "choir"), lastBody("PATCH", path)["tags"]!!.jsonArray.map { it.jsonPrimitive.content })
        assertEquals(listOf("vip", "clergy", "bulk", "choir"), vm.profile.value!!.tags)
        vm.removeTag("clergy")
        assertEquals(listOf("vip", "bulk", "choir"), lastBody("PATCH", path)["tags"]!!.jsonArray.map { it.jsonPrimitive.content })
        val before = calls("PATCH", path).size
        vm.addTag("   ")
        assertEquals("a blank tag sends nothing", before, calls("PATCH", path).size)
    }

    @Test fun removingTheLastTagSendsAnEmptyList() {
        fake.on("GET", "/admin/customers/${CustomerFixtures.PETER}", body = CustomerFixtures.peter.replace("\"tags\":[\"vip\",\"clergy\",\"bulk\"]", "\"tags\":[\"vip\"]"))
        val vm = vm()
        vm.removeTag("vip")
        assertEquals(JsonArray(emptyList()), lastBody("PATCH", "/admin/customers/${CustomerFixtures.PETER}")["tags"])
    }

    @Test fun notesCarryTheBaseTheEditStartedFromSoTheServerCanMerge() {
        val vm = vm()
        val base = vm.profile.value!!.notes!!
        vm.saveNotes("$base\nCall back Friday.")
        val body = lastBody("PATCH", "/admin/customers/${CustomerFixtures.PETER}")
        assertEquals("$base\nCall back Friday.", body["notes"]!!.jsonPrimitive.content)
        assertEquals(base, body["notes_base"]!!.jsonPrimitive.content)
        assertEquals("$base\nCall back Friday.", vm.profile.value!!.notes)
    }

    @Test fun notesOnAProfileWithNoneSendAnEmptyBase() {
        val vm = vm("c2")
        vm.saveNotes("Wants a quote for 3 cassocks")
        val body = lastBody("PATCH", "/admin/customers/${CustomerFixtures.MARY}")
        assertEquals("", body["notes_base"]!!.jsonPrimitive.content)
        assertEquals("channel=messenger", calls("PATCH", "/admin/customers/${CustomerFixtures.MARY}").last().query)
    }

    // ── Custom pipeline stages ──────────────────────────────────────────────

    @Test fun customStagesAreFetchedOncePerProcess() {
        val a = vm()
        assertEquals(listOf("measuring"), a.customStages.value)
        vm()
        assertEquals(1, calls("GET", "/admin/settings/pipeline-stages").size)
    }

    @Test fun savingStagesPutsTheListAndAdoptsTheServersCleanedCopy() {
        signIn("admin", true)
        fake.on("PUT", "/admin/settings/pipeline-stages", body = """{"ok":true,"stages":["measuring","Sampling"]}""")
        val vm = vm()
        vm.saveCustomStages(listOf("measuring", "Sampling", "sampling"))
        assertEquals(listOf("measuring", "Sampling", "sampling"),
            lastBody("PUT", "/admin/settings/pipeline-stages")["stages"]!!.jsonArray.map { it.jsonPrimitive.content })
        assertEquals(listOf("measuring", "Sampling"), vm.customStages.value)
        assertEquals(listOf("measuring", "Sampling"), StageCache.stages)
    }

    @Test fun aRefusedStageSaveExplainsItIsAdminOnly() {
        val vm = vm()
        fake.on("PUT", "/admin/settings/pipeline-stages", code = 403, body = """{"detail":"Admin only"}""")
        vm.saveCustomStages(listOf("measuring", "x"))
        assertEquals("Only an admin can change pipeline stages.", lastToast()!!.message)
        assertEquals(listOf("measuring"), vm.customStages.value)
        fake.on("PUT", "/admin/settings/pipeline-stages", code = 422, body = """{"detail":"At most 6"}""")
        vm.saveCustomStages(listOf("a"))
        assertEquals("Couldn't save pipeline stages.", lastToast()!!.message)
    }

    @Test fun theStageEditorIsShownExactlyToWhomTheServerAdmits() {
        signIn("admin", false)
        assertTrue(canEditPipelineStages(dash))
    }

    @Test fun superusersMayEditStages() {
        signIn("agent", true)
        assertTrue(canEditPipelineStages(dash))
    }

    @Test fun plainAgentsDoNotGetTheStageEditor() {
        signIn("agent", false)
        assertFalse(canEditPipelineStages(dash))
    }

    // ── Merge / unmerge ─────────────────────────────────────────────────────

    @Test fun openingMergeScansForDuplicatesAndClosingForgetsThem() {
        val vm = vm()
        assertNull(vm.mergeSugs.value)
        vm.toggleMerge()
        assertTrue(vm.showMerge.value)
        val get = calls("GET", "/admin/customers/${CustomerFixtures.PETER}/merge_suggestions").single()
        assertEquals("channel=whatsapp", get.query)
        assertEquals(listOf("254799000222", "17840000000000077"), vm.mergeSugs.value!!.map { it.mergeWith })
        assertEquals("strong", vm.mergeSugs.value!![0].strength)
        vm.toggleMerge()
        assertFalse(vm.showMerge.value)
        assertNull(vm.mergeSugs.value)
    }

    @Test fun aFailedScanShowsNoSuggestionsRatherThanSpinningForever() {
        fake.on("GET", "/admin/customers/[^/]+/merge_suggestions", code = 500, body = "{}")
        val vm = vm()
        vm.toggleMerge(true)
        assertEquals(emptyList<Any>(), vm.mergeSugs.value)
    }

    @Test fun mergingPostsTheTrimmedTargetThenClosesAndReloads() {
        val vm = vm()
        vm.toggleMerge(true)
        var cleared = false
        vm.merge("  254799000222 ") { cleared = true }
        val path = "/admin/customers/${CustomerFixtures.PETER}/merge"
        assertEquals("""{"merge_with":"254799000222"}""", calls("POST", path).single().body)
        assertEquals("channel=whatsapp", calls("POST", path).single().query)
        assertEquals("Profiles merged successfully", lastToast()!!.message)
        assertFalse(vm.showMerge.value)
        assertTrue(cleared)
        assertEquals(2, calls("GET", "/admin/customers/${CustomerFixtures.PETER}").size)
    }

    @Test fun aBlankMergeTargetDoesNothing() {
        val vm = vm()
        vm.merge("   ")
        assertTrue(calls("POST", "/admin/customers/${CustomerFixtures.PETER}/merge").isEmpty())
    }

    @Test fun aRefusedMergeKeepsTheFormOpen() {
        val vm = vm()
        vm.toggleMerge(true)
        fake.on("POST", "/admin/customers/[^/]+/merge", code = 404, body = """{"detail":"Secondary customer not found"}""")
        vm.merge("254700000000")
        assertEquals("Failed to merge profiles", lastToast()!!.message)
        assertEquals(ToastType.Error, lastToast()!!.type)
        assertTrue(vm.showMerge.value)
    }

    @Test fun unmergePostsTheMergedIdAndReloads() {
        val vm = vm()
        vm.unmerge("254799000111")
        val path = "/admin/customers/${CustomerFixtures.PETER}/unmerge"
        assertEquals("""{"merge_with":"254799000111"}""", calls("POST", path).single().body)
        assertEquals("Unmerged", lastToast()!!.message)
        assertEquals(2, calls("GET", "/admin/customers/${CustomerFixtures.PETER}").size)
        fake.on("POST", "/admin/customers/[^/]+/unmerge", code = 409, body = "{}")
        vm.unmerge("254799000111")
        assertEquals("Failed to unmerge", lastToast()!!.message)
    }

    // ── Made-to-order enquiry ───────────────────────────────────────────────

    @Test fun theConversationsEnquiryLoadsAndAThreadWithoutOneShowsNothing() {
        assertEquals("e1", vm().enquiry.value!!.id)
        assertTrue(calls("GET", "/admin/production/conversation/c1").isNotEmpty())
        assertNull(vm("c2").enquiry.value)
    }

    @Test fun pushingSendsToProductionAndShowsTheHubOrder() {
        fake.on("POST", "/admin/production/e1/push", body = """{"ok":true,"hub_order_id":88,"hub_order_number":"BH-2001"}""")
        val vm = vm()
        vm.pushProduction()
        assertEquals(1, calls("POST", "/admin/production/e1/push").size)
        assertEquals("pushed", vm.enquiry.value!!.status)
        assertEquals("BH-2001", vm.enquiry.value!!.hubOrderNumber)
        assertEquals("Sent to production · BH-2001", lastToast()!!.message)
        assertFalse(vm.pushing.value)
    }

    @Test fun aPushWithoutAnOrderNumberStillConfirms() {
        val vm = vm()
        vm.pushProduction()
        assertEquals("Sent to production", lastToast()!!.message)
        assertNull(vm.enquiry.value!!.hubOrderNumber)
    }

    @Test fun aRejectedPushLeavesTheEnquiryNew() {
        fake.on("POST", "/admin/production/e1/push", code = 502, body = """{"detail":"Hub rejected the order"}""")
        val vm = vm()
        vm.pushProduction()
        assertEquals("new", vm.enquiry.value!!.status)
        assertEquals("Couldn't send to production", lastToast()!!.message)
        assertFalse(vm.pushing.value)
    }

    @Test fun dismissIsOptimisticAndRevertsOnFailure() {
        val vm = vm()
        vm.declineProduction()
        assertEquals(1, calls("POST", "/admin/production/e1/decline").size)
        assertEquals("declined", vm.enquiry.value!!.status)
        assertTrue("a dismiss that worked is silent", toasts.none { it.message.contains("dismiss") })

        val vm2 = vm()
        fake.on("POST", "/admin/production/e1/decline", code = 500, body = "{}")
        vm2.declineProduction()
        assertEquals("new", vm2.enquiry.value!!.status)
        assertEquals("Couldn't dismiss", lastToast()!!.message)
    }

    // ── Reach-out: invite, template, call ───────────────────────────────────

    @Test fun inviteSendsTheTemplateToTheProfilePhone() {
        val vm = vm()
        var opened: String? = null
        vm.inviteToWhatsApp(CustomerFixtures.PETER) { opened = it }
        val body = lastBody("POST", "/admin/whatsapp-invite")
        assertEquals("+${CustomerFixtures.PETER}", body["phone"]!!.jsonPrimitive.content)
        assertEquals("Fr. Peter Kamau", body["name"]!!.jsonPrimitive.content)
        assertEquals("WhatsApp invite sent ✓", lastToast()!!.message)
        assertNull(opened)
    }

    @Test fun aFailedInviteOpensWhatsAppWithAWarmPrefilledMessage() {
        fake.on("POST", "/admin/whatsapp-invite", code = 503, body = """{"detail":"template not configured"}""")
        val vm = vm()
        var opened: String? = null
        val before = toasts.size
        vm.inviteToWhatsApp(CustomerFixtures.PETER) { opened = it }
        assertEquals(
            "https://wa.me/254712345678?text=Hello%20Fr.%2C%20this%20is%20Bethany%20House.%20Continuing%20our%20chat%20here%20on%20WhatsApp%20so%20we%20can%20finalise%20your%20order.",
            opened,
        )
        assertEquals("no error toast — the fallback is the answer", before, toasts.size)
    }

    @Test fun sendTemplateToastsAndClearsBusy() {
        val vm = vm()
        vm.sendTemplate(CustomerFixtures.PETER)
        assertEquals(1, calls("POST", "/admin/whatsapp-invite").size)
        assertEquals("Template sent ✓", lastToast()!!.message)
        assertFalse(vm.templateBusy.value)
        fake.on("POST", "/admin/whatsapp-invite", code = 500, body = "{}")
        vm.sendTemplate(CustomerFixtures.PETER)
        assertEquals("Couldn't send the template", lastToast()!!.message)
        assertEquals(ToastType.Error, lastToast()!!.type)
        assertFalse(vm.templateBusy.value)
    }

    @Test fun aConnectedCallNeedsNoToast() {
        var dialled: Pair<String, String?>? = null
        val vm = vm(placeCall = { to, name -> dialled = to to name; Result.success(Unit) })
        val before = toasts.size
        vm.call(CustomerFixtures.PETER)
        assertEquals(CustomerFixtures.PETER to "Fr. Peter Kamau", dialled)
        assertEquals(before, toasts.size)
    }

    @Test fun noCallPermissionYetAsksTheCustomerForIt() {
        val vm = vm(placeCall = { _, _ ->
            Result.failure(IllegalStateException("Customer hasn't granted call permission. Send the WhatsApp template first."))
        })
        vm.call(CustomerFixtures.PETER)
        assertEquals("""{"to":"254712345678"}""", calls("POST", "/admin/calls/request-permission").single().body)
        assertEquals("Asked Fr. for permission to call — you can call once they tap Allow.", lastToast()!!.message)

        fake.on("POST", "/admin/calls/request-permission", code = 500, body = "{}")
        vm.call(CustomerFixtures.PETER)
        assertEquals("Couldn't send the call request", lastToast()!!.message)
    }

    @Test fun aBlockedMicrophoneIsTheAgentsProblemNotTheCustomers() {
        val vm = vm(placeCall = { _, _ -> Result.failure(IllegalStateException(CallManager.MIC_BLOCKED)) })
        vm.call(CustomerFixtures.PETER)
        assertTrue(calls("POST", "/admin/calls/request-permission").isEmpty())
        assertEquals(CallManager.MIC_BLOCKED, lastToast()!!.message)
        assertEquals(ToastType.Error, lastToast()!!.type)
    }

    @Test fun anyOtherCallFailureIsToastedAsIs() {
        val vm = vm(placeCall = { _, _ -> Result.failure(IllegalStateException("Already in a call")) })
        vm.call(CustomerFixtures.PETER)
        assertEquals("Already in a call", lastToast()!!.message)
        val vm2 = vm(placeCall = { _, _ -> Result.failure(IllegalStateException("")) })
        vm2.call(CustomerFixtures.PETER)
        assertEquals("Couldn't place the call", lastToast()!!.message)
    }

    // ── Ask Neema / Answer via Neema ────────────────────────────────────────

    @Test fun askNeemaPostsTheQuestionAndShowsTheAnswer() {
        fake.on("POST", "/admin/conversations/c1/ask", body = """{"answer":"16 inch collar, size L cassock."}""")
        val vm = vm()
        vm.ask("  what were his sizes?  ")
        assertEquals("""{"question":"what were his sizes?"}""", calls("POST", "/admin/conversations/c1/ask").single().body)
        assertEquals("16 inch collar, size L cassock.", vm.askAnswer.value)
        assertFalse(vm.askBusy.value)
        vm.ask("   ")
        assertEquals(1, calls("POST", "/admin/conversations/c1/ask").size)
        fake.on("POST", "/admin/conversations/c1/ask", code = 500, body = "{}")
        vm.ask("again?")
        assertEquals("Couldn't check right now — try again.", vm.askAnswer.value)
    }

    @Test fun answerViaNeemaReportsWhatWasSentAndClearsTheBox() {
        fake.on("POST", "/admin/conversations/c1/answer", body = """{"ok":true,"sent":"Yes Father, we make it — KES 3,500, about 5 days 🙏"}""")
        val vm = vm()
        var cleared = false
        vm.answerViaNeema("yes, KES 3,500, ~5 days") { cleared = true }
        assertEquals("""{"facts":"yes, KES 3,500, ~5 days"}""", calls("POST", "/admin/conversations/c1/answer").single().body)
        assertEquals("Neema sent: “Yes Father, we make it — KES 3,500, about 5 days 🙏”", vm.answerStatus.value)
        assertTrue(cleared)
    }

    @Test fun answerViaNeemaExplainsAClosedWindow() {
        val vm = vm()
        var cleared = false
        fake.on("POST", "/admin/conversations/c1/answer", code = 409, body = """{"detail":"Outside the 24h window"}""")
        vm.answerViaNeema("facts") { cleared = true }
        assertEquals("Outside the messaging window — reply yourself when they next write.", vm.answerStatus.value)
        fake.on("POST", "/admin/conversations/c1/answer", code = 500, body = """{"detail":"boom"}""")
        vm.answerViaNeema("facts") { cleared = true }
        assertEquals("Couldn't send right now — try again.", vm.answerStatus.value)
        assertFalse(cleared)
    }
}

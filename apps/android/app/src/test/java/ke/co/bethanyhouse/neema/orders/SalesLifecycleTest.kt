package ke.co.bethanyhouse.neema.orders

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.saveable.LocalSaveableStateRegistry
import androidx.compose.runtime.saveable.SaveableStateRegistry
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.deals.DealsScreen
import ke.co.bethanyhouse.neema.feature.deals.DealsViewModel
import ke.co.bethanyhouse.neema.feature.leads.LeadDetail
import ke.co.bethanyhouse.neema.feature.leads.LeadsScreen
import ke.co.bethanyhouse.neema.feature.leads.LeadsViewModel
import ke.co.bethanyhouse.neema.feature.orders.OrdersScreen
import ke.co.bethanyhouse.neema.feature.orders.OrdersViewModel
import ke.co.bethanyhouse.neema.core.util.RestoreUi
import ke.co.bethanyhouse.neema.core.util.SavesUi
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.io.Serializable

/**
 * Round 9 — lifecycle and state. What a phone does to Orders, Leads and
 * Deals: a rotation (the ViewModel survives; nothing may be replayed over it),
 * process death (a fresh ViewModel gets the saved UI state back through the
 * activity's saved state), a sheet swiped away with half-typed fields, and a
 * restored open row that must wait for the first read instead of closing.
 */
class SalesLifecycleTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private fun fake() = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
    private fun dash(f: FakeNeema = fake()) = dashboard(paparazzi.context, f)

    /** What the activity would put in its Bundle: only types a Bundle can hold. */
    private fun assertBundleSafe(saved: Map<String, Any?>) = saved.forEach { (k, v) ->
        assertTrue("$k=$v can't go in a Bundle", v == null || v is String || v is Int || v is Boolean || (v is ArrayList<*> && v.all { it is String }) || v is Serializable)
    }

    private fun processDeath(before: SavesUi, after: SavesUi) = paparazzi.processDeath(before, after)

    // ── Orders ────────────────────────────────────────────────────────────────
    @Test fun ordersFilterSearchPageAndOpenOrderSurviveProcessDeath() {
        val d = dash()
        val a = OrdersViewModel(d)
        a.setFilter("confirmed"); a.setSearch("peter"); a.setPage(2)
        a.select(d.orders.value.first())
        assertBundleSafe(a.saveUi())
        val b = OrdersViewModel(dash())
        processDeath(a, b)
        assertEquals("confirmed", b.filter.value)
        assertEquals("peter", b.search.value)
        assertEquals(2, b.page.value)
        assertEquals(a.selectedId.value, b.selectedId.value)
    }

    /** Round 10: the ❌ from round 9 — where the list was scrolled comes back too. */
    @Test fun ordersScrollSurvivesProcessDeathUntilApplied() {
        val a = OrdersViewModel(dash())
        a.scroll = 9 to 42
        assertBundleSafe(a.saveUi())
        val b = OrdersViewModel(dash())
        processDeath(a, b)
        assertEquals(9 to 42, b.pendingScroll.value)
        // A second death before the orders came in still remembers it.
        b.scroll = 0 to 0
        assertEquals(9, b.saveUi()["scrollIndex"]); assertEquals(42, b.saveUi()["scrollOffset"])
        b.scrollRestored()
        assertNull(b.pendingScroll.value)
        // Never scrolled: nothing to apply.
        val c = OrdersViewModel(dash())
        c.restoreUi(OrdersViewModel(dash()).saveUi())
        assertNull(c.pendingScroll.value)
    }

    @Test fun rotationNeverReplaysAnOlderCopyOverTheLiveViewModel() {
        // The screen was composed on this ViewModel before the rotation, and the
        // agent typed on after the activity saved: the restore must not win.
        val live = OrdersViewModel(dash()).also { it.setSearch("typed after the save"); it.uiAttached = true }
        processDeath(OrdersViewModel(dash()).also { it.setSearch("stale") }, live)
        assertEquals("typed after the save", live.search.value)
    }

    @Test fun aSavedFilterThatIsNoLongerAStatusIsIgnored() {
        val vm = OrdersViewModel(dash())
        vm.restoreUi(mapOf("filter" to "shipped", "page" to -3))
        assertEquals("all", vm.filter.value)
        assertEquals(1, vm.page.value)
    }

    /**
     * Restored after process death, the open order is kept until the list has
     * really been read: a first read that failed proves nothing, a good read
     * without the row does.
     */
    @Test fun restoredOpenOrderWaitsForAGoodReadBeforeClosing() {
        val f = fake()
        f.on("GET", "/admin/orders", code = 500, body = "{}")
        val d = dash(f)
        val vm = OrdersViewModel(d)
        vm.restoreUi(mapOf("selected" to "o1"))
        assertTrue(d.orders.value.isEmpty())
        assertFalse("never read: the missing row is not proof it is gone", vm.loaded)

        val ok = OrdersViewModel(dash(fake().also { SalesFixtures.install(it, emptyList()) }))
        assertTrue("read, and empty: an open order missing from it is gone", ok.loaded)
    }

    // ── Leads ─────────────────────────────────────────────────────────────────
    @Test fun leadSheetDraftSurvivesProcessDeathWithItsBase() {
        val d = dash()
        val a = LeadsViewModel(d)
        val lead = a.leads.value.first { it.id == "u1" }
        a.filterStage.value = "proposal"; a.search.value = "peter"
        a.select(lead.id)
        val draft = a.sheetFor(lead)
        a.editSheet(draft.copy(notes = draft.notes + "\n\nCall after Mass on Sunday.", tags = "vip, clergy", stage = "negotiation"))
        assertBundleSafe(a.saveUi())

        val b = LeadsViewModel(dash())
        processDeath(a, b)
        assertEquals("proposal", b.filterStage.value)
        assertEquals("peter", b.search.value)
        assertEquals("u1", b.selectedId.value)
        val back = b.sheet.value!!
        assertEquals(a.sheet.value, back)
        // The restored sheet still diffs against the lead as it first opened.
        val edit = back.edit()
        assertEquals("negotiation", edit.stage)
        assertEquals(listOf("vip", "clergy"), edit.tags)
        assertEquals(lead.notes, edit.notesBase)
    }

    @Test fun swipingTheSheetAwayKeepsWhatWasTypedCancelThrowsItAway() {
        val vm = LeadsViewModel(dash())
        val lead = vm.leads.value.first { it.id == "u2" }
        vm.select(lead.id)
        vm.editSheet(vm.sheetFor(lead).copy(notes = "Half a thought"))
        vm.dismissSheet()                               // back / swipe / scrim
        assertNull(vm.selectedId.value)
        vm.select(lead.id)
        assertEquals("reopening shows it as typed", "Half a thought", vm.sheetFor(lead).notes)

        vm.select(null)                                 // Cancel / close
        vm.select(lead.id)
        assertEquals("Cancel starts over from the lead", lead.notes.orEmpty(), vm.sheetFor(lead).notes)

        // Another lead never shows the first one's leftovers.
        vm.editSheet(vm.sheetFor(lead).copy(notes = "for u2"))
        vm.dismissSheet()
        val other = vm.leads.value.first { it.id == "u5" }
        vm.select(other.id)
        assertEquals(other.notes.orEmpty(), vm.sheetFor(other).notes)
    }

    @Test fun aSavedSheetSendsOnlyWhatChangedAndClosesItsDraft() {
        val f = fake()
        val vm = LeadsViewModel(dash(f))
        val lead = vm.leads.value.first { it.id == "u1" }
        vm.select(lead.id)
        vm.editSheet(vm.sheetFor(lead).copy(tags = "vip"))
        vm.save(lead, vm.sheet.value!!.edit())
        val body = f.bodies("PATCH", "/admin/leads/u1").last()
        assertEquals(setOf("tags"), body.keys)
        assertNull(vm.selectedId.value)
        assertNull("the typed draft goes once the server has it", vm.sheet.value)
    }

    @Test fun anEditForALeadThatIsNotOpenIsIgnored() {
        val vm = LeadsViewModel(dash())
        val lead = vm.leads.value.first()
        vm.editSheet(ke.co.bethanyhouse.neema.feature.leads.LeadSheetDraft.of(lead, vm.stages.value))
        assertNull(vm.sheet.value)
    }

    // ── Deals ─────────────────────────────────────────────────────────────────
    @Test fun dealsGuidanceAndEditAndSendDraftSurviveProcessDeath() {
        val a = DealsViewModel(dash())
        val deal = a.deals.value!!.first { it.id == "d2" }
        a.startGuidance(deal); a.setGuidanceDraft("No discount — he is a regular")
        val action = a.actions.value!!.first { it.id == "x1" }
        a.openDraft(action); a.setDraftText("Father, both shirts go out Friday 🙏")
        assertBundleSafe(a.saveUi())

        val b = DealsViewModel(dash())
        processDeath(a, b)
        assertEquals("d2", b.editing.value)
        assertEquals("No discount — he is a regular", b.guidanceDraft.value)
        assertEquals("the dialog reopens on its action once the queue is read", "x1", b.draftFor.value?.id)
        assertEquals("Father, both shirts go out Friday 🙏", b.draftText.value)
    }

    @Test fun aRestoredDialogWhoseActionLeftTheQueueStaysClosed() {
        val b = DealsViewModel(dash())
        b.restoreUi(mapOf("draftFor" to "x-gone", "draftTextFor" to "x-gone", "draftText" to "words"))
        assertNull(b.draftFor.value)
    }

    @Test fun closingTheDialogWithBackKeepsTheText() {
        val vm = DealsViewModel(dash())
        val action = vm.actions.value!!.first { it.id == "x1" }
        vm.openDraft(action); vm.setDraftText("my words")
        vm.openDraft(null)                      // back / outside tap
        vm.openDraft(action)
        assertEquals("my words", vm.draftText.value)
    }

    // ── Restored screens, as the agent comes back to them ─────────────────────
    private fun restoredShot(dark: Boolean = false, device: DeviceConfig? = null, screen: String, setup: (SavesUi) -> Unit) {
        if (device != null) paparazzi.unsafeUpdateConfig(deviceConfig = device)
        val f = fake()
        val old: SavesUi = when (screen) {
            "orders" -> OrdersViewModel(dash(f)); "leads" -> LeadsViewModel(dash(f)); else -> DealsViewModel(dash(f))
        }
        setup(old)
        val saved = old.saveUi()
        val d = dash(f)
        val store = SeededStore()
        val fresh: SavesUi = when (screen) {
            "orders" -> store.seed(OrdersViewModel(d)); "leads" -> store.seed(LeadsViewModel(d)); else -> store.seed(DealsViewModel(d))
        }
        // The saved state as the restored registry holds it for RestoreUi's slot.
        fresh.restoreUi(saved)
        paparazzi.snapshot {
            AppFrame(dark) {
                store.Provide {
                    when (screen) {
                        "orders" -> OrdersScreen(d)
                        "leads" -> LeadsScreen(d)
                        else -> DealsScreen(d)
                    }
                }
            }
        }
    }

    @Test fun restoredOrdersFilteredAndSearched() = restoredShot(screen = "orders") { (it as OrdersViewModel).apply { setFilter("pending"); setSearch("722000") } }

    @Test fun restoredOrdersTabletWithTheOrderOpen() = restoredShot(device = DeviceConfig.PIXEL_C, screen = "orders") {
        (it as OrdersViewModel).select(null); it.restoreUi(mapOf("selected" to "o1", "filter" to "all", "search" to "", "page" to 1))
    }

    @Test fun restoredLeadsSearchedDark() = restoredShot(dark = true, screen = "leads") { (it as LeadsViewModel).apply { search.value = "Sr"; filterStage.value = "contacted" } }

    @Test fun restoredDealsGuidanceHalfTyped() = restoredShot(screen = "deals") {
        val vm = it as DealsViewModel
        vm.startGuidance(vm.deals.value!!.first { d -> d.id == "d3" })
        vm.setGuidanceDraft("Measurements first — don't quote the alb until he sends them")
    }

    /** The lead sheet as it comes back: the notes and tags exactly as they were typed. */
    @Test fun restoredLeadSheetHalfTyped() {
        val vm = LeadsViewModel(dash())
        val lead = vm.leads.value.first { it.id == "u1" }
        vm.select(lead.id)
        vm.editSheet(vm.sheetFor(lead).copy(notes = lead.notes + "\n\nCall after Mass on Sunday — ", tags = "vip, clergy, nyeri, choir", stage = "negotiation"))
        val fresh = LeadsViewModel(dash())
        fresh.restoreUi(vm.saveUi())
        val draft = fresh.sheet.value!!
        paparazzi.snapshot {
            AppFrame(false) {
                SheetFrame { LeadDetail(lead, fresh.stages.value, onClose = {}, onOpenChat = {}, onSave = {}, draft = draft) }
            }
        }
    }
}

/**
 * The activity's save → a new process → restore, through a real
 * [SaveableStateRegistry]: the first composition saves [before]'s state, the
 * second composes [after] (a fresh ViewModel) on the restored values. Both
 * frames run the very same composable lambda, so RestoreUi sits at the same
 * key in each — as it does in the real app across a restore.
 */
fun Paparazzi.processDeath(before: SavesUi, after: SavesUi) {
    var registry = SaveableStateRegistry(null) { true }
    var vm = before
    var saving = true
    var saved: Map<String, List<Any?>> = emptyMap()
    val frame: @androidx.compose.runtime.Composable () -> Unit = {
        CompositionLocalProvider(LocalSaveableStateRegistry provides registry) {
            RestoreUi(vm)
            SideEffect { if (saving) saved = registry.performSave() }
        }
    }
    snapshot(name = "saved", composable = frame)
    assertTrue("the UI state was saved", saved.isNotEmpty())
    saving = false
    registry = SaveableStateRegistry(saved) { true }
    vm = after
    snapshot(name = "restored", composable = frame)
}

package ke.co.bethanyhouse.neema.conversations

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.feature.conversations.ConversationsViewModel
import ke.co.bethanyhouse.neema.feature.conversations.customer.canEditPipelineStages
import ke.co.bethanyhouse.neema.feature.conversations.inboxPermsOf
import ke.co.bethanyhouse.neema.feature.conversations.threadControls
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxPersonaFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxPersonaFixtures.Persona
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 6 — the inbox's permission matrix. The web (ConversationsView.tsx)
 * gates the thread's controls on the stored ROLE and ownership only:
 *
 *   isAdminOrSuper         = is_superuser || role === "admin"
 *   canHandleConversations = isAdminOrSuper || role === "agent"
 *   isOwner                = assigned_agent_id === me
 *   canActOnThisConv       = canHandle && (isOwner || isAdminOrSuper || mode !== "human")
 *
 * and the server (admin.py) refuses nothing on these routes but DELETE
 * /messages (admin/superuser). Permission lists (custom roles, overrides)
 * never enter into it. Everything else — the per-message Reply, Ask Neema,
 * the team answer, invite, call, bulk release, the customer panel — is open
 * to every signed-in agent.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InboxPermissionsTest {
    @get:Rule val paparazzi = Paparazzi()

    private val sched = TestCoroutineScheduler()
    private val scope = CoroutineScope(UnconfinedTestDispatcher(sched))
    private lateinit var fake: FakeNeema
    private val toasts = mutableListOf<Toast>()

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher(sched))
        fake = FakeNeema.withFixtures().also(InboxFixtures::install)
    }

    @After fun tearDown() { scope.cancel(); Dispatchers.resetMain() }

    private fun signIn(p: Persona, sessionRole: String = p.role, sessionSuper: Boolean = p.superuser): Pair<DashboardViewModel, ConversationsViewModel> {
        InboxPersonaFixtures.install(fake, p)
        val dash = dashboard(paparazzi.context, fake, sessionRole, sessionSuper)
        scope.launch { dash.toasts.collect { toasts += it } }
        return dash to ConversationsViewModel(dash)
    }

    private fun ConversationsViewModel.conv(id: String): Conversation = inbox.value.cache.getValue(id)

    /** The controls a persona sees on a thread, by name — the table below speaks the same words. */
    private fun shown(dash: DashboardViewModel, c: Conversation): Set<String> {
        val t = threadControls(c, inboxPermsOf(dash))
        return buildSet {
            if (t.intercept) add("intercept"); if (t.pickUp) add("pickUp"); if (t.release) add("release")
            if (t.pause) add("pause"); if (t.resume) add("resume"); if (t.transfer) add("transfer")
            if (t.note) add("note"); if (t.clearHistory) add("clear"); if (t.composer) add("composer")
            if (t.locked) add("locked")
        }
    }

    private enum class Kind { Admin, Handler, None }

    private fun kindOf(p: Persona) = when (p) {
        Persona.Superuser, Persona.Admin -> Kind.Admin
        Persona.Agent, Persona.Sales, Persona.Viewer, Persona.Override, Persona.EmptyOverride -> Kind.Handler
        Persona.Readonly, Persona.ReadonlyReplier, Persona.Supervisor -> Kind.None
    }

    /**
     * The web's truth table, written out by hand from ConversationsView.tsx:
     * c1 = human, held by me · c2 = AI · c3 = paused, unassigned ·
     * c6 = human, held by Grace · h = human, unclaimed (auto-escalated).
     */
    private val expected: Map<Kind, Map<String, Set<String>>> = mapOf(
        Kind.Admin to mapOf(
            "c1" to setOf("release", "pause", "transfer", "note", "clear", "composer"),
            "c2" to setOf("intercept", "pause", "transfer", "note", "clear"),
            "c3" to setOf("resume", "transfer", "note", "clear"),
            "c6" to setOf("release", "pause", "transfer", "note", "clear", "composer"),
            "h" to setOf("pickUp", "release", "pause", "transfer", "note", "clear", "composer"),
        ),
        Kind.Handler to mapOf(
            "c1" to setOf("release", "pause", "transfer", "note", "composer"),
            "c2" to setOf("intercept", "pause", "transfer", "note"),
            "c3" to setOf("resume", "transfer", "note"),
            "c6" to setOf("note", "locked"),
            "h" to setOf("pickUp", "note"),
        ),
        // The web keys Release and the reply box on ownership alone, so a readonly
        // agent still holding a thread (their role changed after they took it)
        // keeps both — the server allows it too.
        Kind.None to mapOf(
            "c1" to setOf("release", "composer"),
            "c2" to emptySet(),
            "c3" to emptySet(),
            "c6" to setOf("locked"),
            "h" to emptySet(),
        ),
    )

    @Test fun matrix_everyPersona_everyThread() {
        for (p in Persona.entries) {
            fake = FakeNeema.withFixtures().also(InboxFixtures::install)
            val (dash, vm) = signIn(p)
            val threads = mapOf(
                "c1" to vm.conv("c1"), "c2" to vm.conv("c2"), "c3" to vm.conv("c3"), "c6" to vm.conv("c6"),
                "h" to vm.conv("c6").copy(id = "h", assignedAgentId = null, assignedAgentName = null),
            )
            for ((key, c) in threads) assertEquals("$p on $key", expected.getValue(kindOf(p)).getValue(key), shown(dash, c))
        }
    }

    /** Custom roles and overrides change nothing in the inbox: the web never reads them there. */
    @Test fun permissionLists_neverGateTheInbox() {
        val (dash, _) = signIn(Persona.Viewer)
        // The core permission API does see the difference…
        assertFalse(dash.can("reply_conversations")); assertFalse(dash.can("intercept_release"))
        // …and the inbox, like the web, does not.
        val perms = inboxPermsOf(dash)
        assertTrue(perms.canHandle); assertFalse(perms.isAdminOrSuper)
    }

    @Test fun readonlyEnum_withReplyPermission_stillHandlesNothing() {
        val (dash, _) = signIn(Persona.ReadonlyReplier)
        assertTrue(dash.can("reply_conversations"))
        assertFalse(inboxPermsOf(dash).canHandle)
    }

    /** An empty override is "no override" on the web (a length check): legacy agent rights. */
    @Test fun emptyOverride_fallsBackToTheLegacyRole() {
        val (dash, _) = signIn(Persona.EmptyOverride)
        assertTrue(dash.can("reply_conversations"))
        assertTrue(inboxPermsOf(dash).canHandle)
    }

    /** The team row is the truth, not a stale sign-in: a session that still says admin doesn't win. */
    @Test fun theServersRecordWinsOverAStaleSession() {
        val (dash, vm) = signIn(Persona.Readonly, sessionRole = "admin", sessionSuper = true)
        assertEquals(emptySet<String>(), shown(dash, vm.conv("c2")))
        assertFalse(canEditPipelineStages(dash))
    }

    /** Persona 8: an admin demotes this agent while the inbox is open — the 180 s agents poll carries it. */
    @Test fun roleChange_reachesTheOpenInbox_onTheAgentsPoll() {
        val (dash, vm) = signIn(Persona.Agent)
        assertEquals(setOf("intercept", "pause", "transfer", "note"), shown(dash, vm.conv("c2")))
        fake.on("GET", "/admin/agents", body = InboxPersonaFixtures.agents(Persona.Readonly))
        sched.advanceTimeBy(180_001); sched.runCurrent()
        assertEquals(emptySet<String>(), shown(dash, vm.conv("c2")))
        // And back: promoted to admin, Clear history appears.
        fake.on("GET", "/admin/agents", body = InboxPersonaFixtures.agents(Persona.Admin))
        sched.advanceTimeBy(180_001); sched.runCurrent()
        assertTrue("clear" in shown(dash, vm.conv("c2")))
    }

    /** A 403 re-reads who this agent is at once, so the controls correct themselves. */
    @Test fun forbidden_refetchesMeAndAgents_andTheControlsCorrect() {
        val (dash, vm) = signIn(Persona.Agent)
        fake.on("GET", "/admin/agents", body = InboxPersonaFixtures.agents(Persona.Readonly))
        fake.on("GET", "/admin/me", body = InboxPersonaFixtures.me(Persona.Readonly))
        fake.on("POST", "/admin/conversations/c2/intercept", code = 403, body = """{"detail":"Not allowed"}""")
        val meBefore = fake.callsTo("GET", "/admin/me").size
        val agentsBefore = fake.callsTo("GET", "/admin/agents").size
        vm.intercept("c2")
        assertTrue(fake.callsTo("GET", "/admin/me").size > meBefore)
        assertTrue(fake.callsTo("GET", "/admin/agents").size > agentsBefore)
        assertEquals(ToastType.Error, toasts.last().type)
        assertEquals("Failed to claim conversation. Not allowed", toasts.last().message)
        assertEquals(emptySet<String>(), shown(dash, vm.conv("c2")))
    }

    /** The web's own words for the one route the server does guard, and the stale 🗑️ goes away. */
    @Test fun clearHistory_403_webWording_closesTheDialog_andRefetches() {
        val (dash, vm) = signIn(Persona.Admin)
        fake.on("DELETE", "/admin/conversations/[^/]+/messages", code = 403, body = """{"detail":"Only admins can clear chat history"}""")
        fake.on("GET", "/admin/agents", body = InboxPersonaFixtures.agents(Persona.Agent))
        vm.select("c1"); vm.showClear(true); vm.clearHistory()
        assertEquals("You don't have permission to clear chat history", toasts.last().message)
        assertEquals(ToastType.Error, toasts.last().type)
        assertFalse(vm.dialogs.value.clearConfirm)
        assertFalse("clear" in shown(dash, vm.conv("c1")))
        assertTrue(vm.thread.value.messages["c1"].orEmpty().isNotEmpty())
    }

    /** What the web leaves open stays open, even for a readonly agent — and the requests go out. */
    @Test fun ungatedActions_workForReadonly() {
        val (_, vm) = signIn(Persona.Readonly)
        // Bulk release (the web's select bar has no gate).
        vm.enterSelect("p1"); vm.toggleRow("c6"); vm.releaseSelected()
        assertTrue(fake.callsTo("POST", "/admin/conversations/c1/release").isNotEmpty())
        assertTrue(fake.callsTo("POST", "/admin/conversations/c6/release").isNotEmpty())
        // Ask Neema and the team answer (CustomerSidebar, no gate).
        vm.select("c2")
        fake.on("POST", "/admin/conversations/c2/ask", body = """{"answer":"Yes — 3 in stock."}""")
        assertEquals("Yes — 3 in stock.", runBlocking { vm.askNeema("Purple cassock in L?") })
        fake.on("POST", "/admin/conversations/c2/answer", body = """{"ok":true,"sent":"We have it in L."}""")
        assertEquals(true to "Neema sent: “We have it in L.”", runBlocking { vm.answerViaNeema("3 in stock in L") })
        // The per-message Reply quote.
        vm.beginReplyTo(vm.thread.value.messages["c2"].orEmpty().first { it.inbound && it.body.isNotBlank() })
        assertNotNull(vm.composer.value.quoted)
    }

    /** The stage editor: the one panel control shown only to whom the server admits (documented exception). */
    @Test fun pipelineStageEditor_exactlyTheServersRule() {
        for (p in Persona.entries) {
            fake = FakeNeema.withFixtures().also(InboxFixtures::install)
            val (dash, _) = signIn(p)
            assertEquals("$p", p.superuser || p.role == "admin", canEditPipelineStages(dash))
        }
    }

    /** The team answer's failures: a 403 says why in plain words and re-reads who they are; a window refusal is the web's line. */
    @Test fun answerViaNeema_refusals_speakPlainly() {
        val (_, vm) = signIn(Persona.Agent)
        vm.select("c2")
        fake.on("POST", "/admin/conversations/c2/answer", code = 400, body = """{"detail":"Outside the 24h window"}""")
        assertEquals(false to "Outside the messaging window — reply yourself when they next write.", runBlocking { vm.answerViaNeema("x") })
        val meBefore = fake.callsTo("GET", "/admin/me").size
        fake.on("POST", "/admin/conversations/c2/answer", code = 403, body = """{"detail":"Forbidden"}""")
        assertEquals(false to "Couldn't send right now — try again.", runBlocking { vm.answerViaNeema("x") })
        assertTrue(fake.callsTo("GET", "/admin/me").size > meBefore)
    }
}

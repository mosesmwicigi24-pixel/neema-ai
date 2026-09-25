package ke.co.bethanyhouse.neema.customer

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.VerticalDivider
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import com.android.resources.Density
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerPanel
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerTab
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerViewModel
import ke.co.bethanyhouse.neema.feature.conversations.customer.StageCache
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CustomerFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * The customer panel in every state: each tab on a rich and a sparse profile,
 * merge (with and without suggestions), the stage editor, notes editing, the
 * made-to-order card's states, loading and fallback, dark mode, and the two
 * frames it lives in — the phone sheet (hideHeader) and the tablet side pane.
 *
 * "Tall" shots are a 340dp pane (the tablet pane's width) long enough to show
 * the whole scroll, so every section is visible in one image.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CustomerPanelScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = TALL, showSystemUi = false, maxPercentDifference = 0.1)

    private lateinit var fake: FakeNeema

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        StageCache.stages = null
        fake = FakeNeema.withFixtures().also(CustomerFixtures::install)
    }

    @After fun tearDown() {
        Dispatchers.resetMain()
        StageCache.stages = null
    }

    private fun asAgent() {
        val agent = Fixtures.me.replace("\"role\":\"admin\"", "\"role\":\"agent\"").replace("\"is_superuser\":true", "\"is_superuser\":false")
        fake.on("GET", "/admin/me", body = agent)
        fake.on("GET", "/admin/agents", body = "[$agent]")
    }

    private fun dash(admin: Boolean = true): DashboardViewModel =
        if (admin) dashboard(paparazzi.context, fake) else { asAgent(); dashboard(paparazzi.context, fake, "agent", false) }

    /** The panel, with its ViewModel prepared (tab, open editors) before first paint. */
    @Composable
    private fun Panel(
        dash: DashboardViewModel,
        conv: Conversation,
        modifier: Modifier = Modifier.fillMaxSize(),
        hideHeader: Boolean = false,
        prepare: (CustomerViewModel) -> Unit = {},
    ) {
        val vm: CustomerViewModel = viewModel(key = "customer:${conv.id}") { CustomerViewModel(dash, conv) }
        remember(vm) { prepare(vm); 0 }
        CustomerPanel(dash, conv, onClose = {}, onOpenIdentity = { _, _ -> }, onNameChange = { _, _ -> }, modifier = modifier, hideHeader = hideHeader)
    }

    private fun tall(
        name: String? = null,
        conv: String = "c1",
        dark: Boolean = false,
        admin: Boolean = true,
        prepare: (CustomerViewModel) -> Unit = {},
    ) {
        val d = dash(admin)
        val c = CustomerFixtures.conversation(conv)
        paparazzi.snapshot(name) {
            AppFrame(dark) {
                // The whole scroll as three consecutive 1000dp slices of one 3000dp-tall panel.
                Row(Modifier.fillMaxSize().background(Color(0xFF94A3B8)), horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                    repeat(3) { k ->
                        Box(Modifier.width(COL).fillMaxHeight().clipToBounds()) {
                            Panel(
                                d, c,
                                Modifier.wrapContentHeight(Alignment.Top, unbounded = true).height(SLICE * 3)
                                    .offset(y = -SLICE * k).fillMaxWidth(),
                                prepare = prepare,
                            )
                        }
                    }
                }
            }
        }
    }

    // ── Rich profile, each tab ──────────────────────────────────────────────

    @Test fun profileTab() = tall()
    @Test fun insightsTab() = tall(prepare = { it.tab.value = CustomerTab.Insights })
    @Test fun activityTab() = tall(prepare = { it.tab.value = CustomerTab.Activity })

    @Test fun profileTabDark() = tall(dark = true)
    @Test fun insightsTabDark() = tall(dark = true, prepare = { it.tab.value = CustomerTab.Insights })
    @Test fun activityTabDark() = tall(dark = true, prepare = { it.tab.value = CustomerTab.Activity })

    // ── Sparse profile (Messenger lead, nothing known) ──────────────────────

    @Test fun sparseProfileTab() = tall(conv = "c2")
    @Test fun sparseInsightsTab() = tall(conv = "c2", prepare = { it.tab.value = CustomerTab.Insights })
    @Test fun sparseActivityTab() = tall(conv = "c2", prepare = { it.tab.value = CustomerTab.Activity })
    @Test fun sparseProfileTabDark() = tall(conv = "c2", dark = true)

    /** A Messenger lead who gave a phone: the "Invite to WhatsApp" chip plus Call / Send template. */
    @Test fun inviteToWhatsApp() {
        fake.on("GET", "/admin/customers/${CustomerFixtures.MARY}", body = CustomerFixtures.mary.replace("\"phone\":null", "\"phone\":\"+254722000111\""))
        tall(conv = "c2")
    }

    // ── Website chat visitor (`web_<hash>` on the default channel) ──────────

    /** No phone: "Website visitor" / "Web chat", a web badge, and no Call, template or Invite. */
    @Test fun webVisitor() = tall(conv = "c7")
    @Test fun webVisitorActivity() = tall(conv = "c7", prepare = { it.tab.value = CustomerTab.Activity })
    @Test fun webVisitorDark() = tall(conv = "c7", dark = true)

    /** The profile call failed: the fallback still never turns the hash into a phone. */
    @Test fun webVisitorFallback() {
        fake.on("GET", "/admin/customers/${CustomerFixtures.WEB}", code = 500, body = """{"detail":"boom"}""")
        tall(conv = "c7")
    }

    /** A visitor who typed a real number: that number, the Invite (no WhatsApp thread exists yet) and Call. */
    @Test fun webVisitorWithPhone() {
        fake.on("GET", "/admin/customers/${CustomerFixtures.WEB}", body = CustomerFixtures.webVisitor(phone = "+256772123456", name = "Br. Joseph Okello"))
        tall(conv = "c7")
    }

    // ── Open sub-editors ────────────────────────────────────────────────────

    @Test fun mergeWithSuggestions() = tall(prepare = { it.toggleMerge(true) })

    @Test fun mergeWithoutSuggestions() {
        fake.on("GET", "/admin/customers/[^/]+/merge_suggestions", body = """{"suggestions":[]}""")
        tall(prepare = { it.toggleMerge(true) })
    }

    @Test fun mergeScanning() {
        // The suggestions call is held (its coroutine never runs): the "Scanning…" line.
        tall(prepare = { Dispatchers.setMain(StandardTestDispatcher()); it.toggleMerge(true) })
    }

    @Test fun mergeDark() = tall(dark = true, prepare = { it.toggleMerge(true) })

    @Test fun stageEditorAdmin() = tall(prepare = { it.stageEditorOpen.value = true })
    @Test fun stageEditorDark() = tall(dark = true, prepare = { it.stageEditorOpen.value = true })

    /** A plain agent: everything editable except the stage editor (no "+ Add stage"). */
    @Test fun plainAgentNoStageEditor() = tall(admin = false)

    @Test fun notesEditing() = tall(prepare = { it.editNotes.value = true })

    @Test fun customStageActive() {
        fake.on("GET", "/admin/customers/${CustomerFixtures.PETER}",
            body = CustomerFixtures.peter.replace("\"lead_stage\":\"proposal\",\"lead_stage_source\":\"auto\"", "\"lead_stage\":\"measuring\",\"lead_stage_source\":\"manual\""))
        tall()
    }

    /**
     * crm.py normalise_stage lower-cases the stored stage, so a customer on the
     * custom stage "Sampling" comes back as "sampling": the node still lights and
     * the chip keeps the operator's spelling.
     */
    @Test fun customStageAsTheServerReturnsIt() {
        fake.on("GET", "/admin/settings/pipeline-stages", body = """{"stages":["Sampling","Fitting"]}""")
        fake.on("GET", "/admin/customers/${CustomerFixtures.PETER}",
            body = CustomerFixtures.peter.replace("\"lead_stage\":\"proposal\",\"lead_stage_source\":\"auto\"", "\"lead_stage\":\"sampling\",\"lead_stage_source\":\"manual\""))
        tall()
    }

    /**
     * Hub orders as _map_hub_order passes them through: a USD order in its own
     * currency, a SQL-style "YYYY-MM-DD HH:MM:SS" created_at, a null total (the
     * subtotal stands in) and a quantity sent as a decimal string.
     */
    @Test fun hubOrdersAsTheHubSendsThem() {
        val hubOrders = """"orders":[
          {"id":"95001","order_number":"WEB-7710","status":"confirmed","payment_status":"paid","order_type":"online",
           "total":null,"subtotal":240.0,"currency_code":"USD","created_at":"${java.time.LocalDateTime.now(java.time.ZoneOffset.UTC).minusHours(5).withNano(0).toString().replace('T', ' ')}",
           "items":[{"name":"Chasuble — Purple","qty":"2.00","quantity":"2.00","unit_price":120.0,"total":240.0}],"source":"hub"},
          {"id":"90412","order_number":"BH-1042","status":"delivered","payment_status":"paid","order_type":"pos",
           "total":8000.0,"subtotal":8000.0,"currency_code":"KES","created_at":"${CustomerFixtures.py(60L * 24 * 70)}",
           "items":[{"name":"Clergy Shirt — Black, 16 inch","qty":2,"quantity":2,"unit_price":3500.0,"total":7000.0}],"source":"hub"}
        ],"""
        fake.on("GET", "/admin/customers/${CustomerFixtures.PETER}",
            body = CustomerFixtures.peter.replace(Regex("\"orders\":\\[.*?\"source\":\"hub\"\\}\\s*],", RegexOption.DOT_MATCHES_ALL), hubOrders)
                // The newest order was stamped a few hours "ahead" by the hub's clock: _buying_rhythm floors to -1.
                .replace("\"days_since_last\":70", "\"days_since_last\":-1").replace("\"overdue\":true", "\"overdue\":false"))
        tall(prepare = { it.tab.value = CustomerTab.Activity })
    }

    @Test fun hubOrdersInsights() {
        fake.on("GET", "/admin/customers/${CustomerFixtures.PETER}",
            body = CustomerFixtures.peter.replace("\"days_since_last\":70", "\"days_since_last\":-1").replace("\"overdue\":true", "\"overdue\":false"))
        tall(prepare = { it.tab.value = CustomerTab.Insights })
    }

    @Test fun lostStage() {
        fake.on("GET", "/admin/customers/${CustomerFixtures.PETER}",
            body = CustomerFixtures.peter.replace("\"lead_stage\":\"proposal\",\"lead_stage_source\":\"auto\"", "\"lead_stage\":\"lost\",\"lead_stage_source\":\"manual\""))
        tall()
    }

    // ── Made-to-order card ──────────────────────────────────────────────────

    @Test fun enquiryPushed() {
        fake.on("GET", "/admin/production/conversation/c1", body = CustomerFixtures.enquiry("pushed", pushable = false, order = "BH-2001"))
        tall(prepare = { it.tab.value = CustomerTab.Activity })
    }

    @Test fun enquiryDismissed() {
        fake.on("GET", "/admin/production/conversation/c1", body = CustomerFixtures.enquiry("declined", pushable = false))
        tall(prepare = { it.tab.value = CustomerTab.Activity })
    }

    @Test fun enquiryNotPushable() {
        fake.on("GET", "/admin/production/conversation/c1", body = CustomerFixtures.enquiry("new", pushable = false))
        tall(prepare = { it.tab.value = CustomerTab.Activity })
    }

    @Test fun enquiryDark() = tall(dark = true, prepare = { it.tab.value = CustomerTab.Activity })

    // ── Loading and fallback ────────────────────────────────────────────────

    @Test fun loading() {
        val d = dash()
        val c = CustomerFixtures.conversation("c1")
        // Hold every ViewModel coroutine: the profile never arrives.
        Dispatchers.setMain(StandardTestDispatcher())
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_6)
        paparazzi.snapshot { AppFrame { Panel(d, c) } }
    }

    @Test fun fallbackWhenTheProfileFails() {
        fake.on("GET", "/admin/customers/${CustomerFixtures.PETER}", code = 500, body = """{"detail":"boom"}""")
        tall()
    }

    // ── The two frames ──────────────────────────────────────────────────────

    /** Phones: a bottom sheet with its own "Customer Profile" header; the panel hides its own. */
    @Test fun phoneSheet() = phoneSheet(dark = false)
    @Test fun phoneSheetDark() = phoneSheet(dark = true)

    private fun phoneSheet(dark: Boolean) {
        val d = dash()
        val c = CustomerFixtures.conversation("c1")
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_6)
        paparazzi.snapshot {
            AppFrame(dark) {
                Box(Modifier.fillMaxSize().background(Color(0x66000000)), contentAlignment = Alignment.BottomCenter) {
                    val col = Neema.colors
                    Column(
                        Modifier.fillMaxWidth().fillMaxHeight(0.94f)
                            .clip(RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp)).background(col.bg2),
                    ) {
                        Box(Modifier.fillMaxWidth().padding(vertical = 12.dp), contentAlignment = Alignment.Center) {
                            Box(Modifier.size(32.dp, 4.dp).clip(RoundedCornerShape(2.dp)).background(col.muted.copy(alpha = 0.4f)))
                        }
                        Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("Customer Profile", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, color = col.text, modifier = Modifier.weight(1f))
                            Box(Modifier.size(40.dp), contentAlignment = Alignment.Center) {
                                Icon(Icons.Filled.Close, "Close", tint = Color(0xFF589B31))
                            }
                        }
                        HorizontalDivider(color = col.hairline)
                        Panel(d, c, Modifier.fillMaxWidth().weight(1f), hideHeader = true)
                    }
                }
            }
        }
    }

    /** Tablets: the 340dp pane beside the thread, with its own "CUSTOMER" header and collapse chevron. */
    @Test fun tabletPane() = tabletPane(dark = false)
    @Test fun tabletPaneDark() = tabletPane(dark = true)

    private fun tabletPane(dark: Boolean) {
        val d = dash()
        val c = CustomerFixtures.conversation("c1")
        paparazzi.unsafeUpdateConfig(deviceConfig = TABLET)
        paparazzi.snapshot {
            AppFrame(dark) {
                Row(Modifier.fillMaxSize()) {
                    Box(Modifier.weight(1f).fillMaxHeight(), contentAlignment = Alignment.Center) {
                        Text("(thread)", color = Neema.colors.muted)
                    }
                    VerticalDivider(color = Neema.colors.hairline)
                    Panel(d, c, Modifier.width(340.dp).fillMaxHeight())
                }
            }
        }
    }

    companion object {
        /** 1000×1000 at 1px/dp: three 320dp columns (the web's w-80 pane) side by side, unscaled. */
        val TALL = DeviceConfig.NEXUS_5.copy(screenWidth = 1000, screenHeight = 1000, xdpi = 160, ydpi = 160, density = Density.MEDIUM)
        /** A small landscape tablet at 1px/dp, so the 340dp pane is legible after Paparazzi's 1000px cap. */
        val TABLET = DeviceConfig.PIXEL_C.copy(screenWidth = 1000, screenHeight = 700, xdpi = 160, ydpi = 160, density = Density.MEDIUM)
        val COL = 320.dp
        val SLICE = 1000.dp
    }
}

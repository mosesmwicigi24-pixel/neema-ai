package ke.co.bethanyhouse.neema.team

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Before
import org.junit.Rule

/**
 * Base for the Team / Profile / Settings behaviour tests: a signed-in
 * dashboard on a [FakeNeema] (Paparazzi only supplies an Android context),
 * every coroutine run eagerly, and every toast recorded.
 */
@OptIn(ExperimentalCoroutinesApi::class)
abstract class AreaTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    lateinit var fake: FakeNeema
    lateinit var dash: DashboardViewModel
    val toasts = mutableListOf<Toast>()
    private var collector: Job? = null

    /** Extra routes for this test class, installed on top of the base fixtures. */
    open fun install(f: FakeNeema) {}

    @Before fun setUpArea() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        fake = FakeNeema.withFixtures().also(::install)
        dash = dashboard(paparazzi.context, fake)
        collector = CoroutineScope(Dispatchers.Unconfined).launch { dash.toasts.collect { toasts += it } }
        dash.refetchAgents()
        fake.calls.clear()
    }

    @After fun tearDownArea() {
        collector?.cancel()
        Dispatchers.resetMain()
    }

    /** The writes (non-GET calls) the screen made, in order. */
    fun writes() = fake.calls.filter { it.method != "GET" }

    fun FakeNeema.Call.json(): JsonObject = Json.parseToJsonElement(body ?: "{}").jsonObject

    fun lastToast() = toasts.lastOrNull()

    /** Make [method] [path] fail with [code] and a FastAPI-style detail. */
    fun fail(method: String, path: String, code: Int = 403, detail: String = "Admin only") =
        fake.on(method, path, code = code, body = """{"detail":"$detail"}""")

    fun el(s: String): JsonElement = Json.parseToJsonElement(s)
}

package ke.co.bethanyhouse.neema.orders

import ke.co.bethanyhouse.neema.testing.FakeNeema
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.rules.TestWatcher
import org.junit.runner.Description
import java.net.ConnectException
import java.net.SocketTimeoutException

/*
 * Network faults for the sales screens' stress tests, on top of FakeNeema.
 * An interceptor that throws is exactly what OkHttp does on a phone network:
 * NeemaHttp turns it into ApiException(0, …) as it would the real thing.
 */

/** Connection refused / no route: nothing reached the server. */
fun FakeNeema.offline(method: String, path: String) =
    on(method, path) { _, _ -> throw ConnectException("Failed to connect to neema.test/10.0.0.1:443") }

/** The 30 s ceiling hit. [serverDid] runs first: the server may well have done the work. */
fun FakeNeema.timeout(method: String, path: String, serverDid: (String?) -> Unit = {}) =
    on(method, path) { _, body -> serverDid(body); throw SocketTimeoutException("timeout") }

/** The connection dropped mid-answer after the server did the work. */
fun FakeNeema.dropped(method: String, path: String, serverDid: (String?) -> Unit = {}) =
    on(method, path) { _, body -> serverDid(body); throw java.io.IOException("unexpected end of stream on https://neema.test/...") }

/** A proxy's HTML error page (nginx 502, Cloudflare 503…) — never to be shown raw. */
fun FakeNeema.htmlPage(method: String, path: String, code: Int) =
    on(method, path, code = code, body = "<html><head><title>$code Bad Gateway</title></head><body><center><h1>$code Bad Gateway</h1></center><hr><center>nginx</center></body></html>")

/** 401 on the first [times] calls, then [then]: an access token that expired mid-action. */
fun FakeNeema.expiredOnce(method: String, path: String, times: Int = 1, then: () -> Pair<Int, String>) {
    var n = 0
    on(method, path) { _, _ -> if (n++ < times) 401 to """{"detail":"Token expired"}""" else then() }
}

/**
 * Main = an unconfined test dispatcher on a scheduler the test can move:
 * launches run inline, and delays (settling re-reads, polls) fire only when
 * the test advances [scheduler].
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ClockedMainRule : TestWatcher() {
    val scheduler = TestCoroutineScheduler()
    override fun starting(description: Description) = Dispatchers.setMain(UnconfinedTestDispatcher(scheduler))
    override fun finished(description: Description) = Dispatchers.resetMain()

    fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }
}

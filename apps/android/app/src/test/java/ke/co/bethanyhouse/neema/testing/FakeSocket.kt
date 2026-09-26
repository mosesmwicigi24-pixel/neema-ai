package ke.co.bethanyhouse.neema.testing

import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.util.concurrent.CopyOnWriteArrayList

/**
 * A WebSocket factory for tests: every `newWebSocket` is recorded as a
 * [FakeWs]; the test drives the server side through it (open, frames,
 * failure) and inspects what the app sent.
 */
class FakeSocketFactory : WebSocket.Factory {
    val sockets = CopyOnWriteArrayList<FakeWs>()
    val last: FakeWs get() = sockets.last()

    override fun newWebSocket(request: Request, listener: WebSocketListener): WebSocket =
        FakeWs(request, listener).also { sockets += it }

    /**
     * Drop the connection and let LiveSocket come back (its first retry is
     * 2 s): [advance] moves the test clock, e.g. `{ scheduler.advanceTimeBy(it); scheduler.runCurrent() }`.
     * Frames pushed in between are lost, as in real life; the reopen fires
     * `LiveSocket.reconnected`, which screens use to catch up.
     */
    fun dropAndReconnect(advance: (Long) -> Unit) {
        last.fail()
        advance(2_001)
        last.open()
    }
}

class FakeWs(private val req: Request, val listener: WebSocketListener) : WebSocket {
    val sent = CopyOnWriteArrayList<String>()
    var closedWith: Int? = null
    var cancelled = false

    val url: String get() = req.url.toString()

    private fun response() = Response.Builder().request(req).protocol(Protocol.HTTP_1_1).code(101).message("Switching Protocols").build()

    /** The server accepted the upgrade. */
    fun open() = listener.onOpen(this, response())
    /** The server sent a text frame. */
    fun frame(text: String) = listener.onMessage(this, text)
    /** The connection dropped. */
    fun fail(t: Throwable = java.io.IOException("reset")) = listener.onFailure(this, t, null)
    /** The server closed cleanly. */
    fun serverClose(code: Int = 1001) = listener.onClosed(this, code, "")

    override fun request(): Request = req
    override fun queueSize(): Long = 0
    override fun send(text: String): Boolean { sent += text; return true }
    override fun send(bytes: ByteString): Boolean = true
    override fun close(code: Int, reason: String?): Boolean { closedWith = code; return true }
    override fun cancel() { cancelled = true }
}

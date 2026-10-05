package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.crash.TombstoneText
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.ByteArrayOutputStream

/**
 * The owner's report from 1 Oct: a native SIGTRAP on answering a call, kept as
 * the tombstone's raw protobuf read as text — unreadable, and the parked
 * "DefaultDispatch" threads first. Decoded, the crashing thread's frames lead.
 */
class TombstoneTextTest {
    /** A protobuf writer, enough to build a tombstone as debuggerd does (tombstone.proto). */
    private class Pb {
        val out = ByteArrayOutputStream()
        fun varint(v: Long) { var x = v; while (true) { val b = (x and 0x7f).toInt(); x = x ushr 7; if (x == 0L) { out.write(b); return }; out.write(b or 0x80) } }
        fun tag(field: Int, wire: Int) = varint(((field shl 3) or wire).toLong())
        fun int(field: Int, v: Long) { tag(field, 0); varint(v) }
        fun str(field: Int, s: String) = bytes(field, s.toByteArray())
        fun bytes(field: Int, b: ByteArray) { tag(field, 2); varint(b.size.toLong()); out.write(b) }
        fun msg(field: Int, build: Pb.() -> Unit) = bytes(field, Pb().apply(build).out.toByteArray())
    }

    private fun frame(fn: String, file: String, pc: Long): Pb.() -> Unit = {
        int(1, pc); int(2, pc + 0x7000000000); str(4, fn); int(5, 0x24); str(6, file); str(8, "ab12")
    }

    private fun tombstone() = Pb().apply {
        int(1, 3)                                         // arch ARM64
        str(2, "samsung/e3qxxx/e3q:16/BP4A.251205.006/S928BXXS6DZH2:user/release-keys")
        str(4, "2026-10-01 23:37:54.168414619+0300")
        int(5, 1234); int(6, 1301); int(7, 10456)
        str(8, "u:r:untrusted_app:s0:c46,c257,c512,c768")
        str(9, "ke.co.bethanyhouse.neema")
        msg(10) { int(1, 5); str(2, "SIGTRAP"); int(3, 1); str(4, "TRAP_BRKPT"); int(8, 1); int(9, 0x7b1c2d3e4f) }
        msg(15) { str(1, "libc++ hardening assertion") }
        // Threads (a map), the parked worker first — as in the owner's report.
        msg(16) { int(1, 1288); msg(2) {
            int(1, 1288); str(2, "DefaultDispatch")
            msg(4, frame("syscall", "/apex/com.android.runtime/lib64/bionic/libc.so", 0x9f2c))
            msg(4, frame("art::Thread::Park(bool, long)", "/apex/com.android.art/lib64/libart.so", 0x4a1b0))
        } }
        msg(16) { int(1, 1301); msg(2) {
            int(1, 1301); str(2, "worker_thread")
            msg(4, frame("webrtc::SdpOfferAnswerHandler::ApplyRemoteDescription", "/data/app/~~x/lib/arm64/libjingle_peerconnection_so.so", 0x5f3a10))
            msg(4, frame("webrtc::PeerConnection::SetRemoteDescription", "/data/app/~~x/lib/arm64/libjingle_peerconnection_so.so", 0x5e1200))
            str(7, "backtrace note")
        } }
        // The process's last log lines.
        msg(18) {
            str(1, "main")
            msg(2) { str(1, "10-01 23:37:53.900"); int(2, 1234); int(3, 1301); int(4, 4); str(5, "CallManager"); str(6, "answering wacid.1") }
            msg(2) { str(1, "10-01 23:37:54.100"); int(2, 1234); int(3, 1301); int(4, 6); str(5, "libjingle"); str(6, "(sdp_offer_answer.cc:1234): Failed to apply") }
        }
        msg(17) { int(1, 0x1000); int(2, 0x2000) }        // memory mappings (skipped)
    }.out.toByteArray()

    @Test fun theCrashingThreadLeadsReadably() {
        val text = TombstoneText.decode(tombstone())!!
        val lines = text.lines()
        assertEquals("SIGTRAP (TRAP_BRKPT) fault address 0x7b1c2d3e4f in thread \"worker_thread\" (tid 1301, pid 1234)", lines[0])
        assertTrue(text.contains("Cause: libc++ hardening assertion"))
        val crashed = text.indexOf("--- crashed thread: worker_thread ---")
        val parked = text.indexOf("\"DefaultDispatch\" tid 1288")
        assertTrue("crashed thread first", crashed in 0 until parked)
        assertTrue(text.contains("#00 pc 005f3a10  /data/app/~~x/lib/arm64/libjingle_peerconnection_so.so (webrtc::SdpOfferAnswerHandler::ApplyRemoteDescription+36) (BuildId: ab12)"))
        assertTrue(text.contains("#01 pc 005e1200"))
        assertTrue(text.contains("10-01 23:37:54.100 1301 E libjingle: (sdp_offer_answer.cc:1234): Failed to apply"))
        assertTrue(text.contains("Build: samsung/e3qxxx/e3q:16/"))
    }

    @Test fun notATombstoneIsLeftAlone() {
        assertNull(TombstoneText.decode("----- pid 1234 at 2026-10-01 -----\nCmd line: ke.co.bethanyhouse.neema\n".toByteArray()))
        assertNull(TombstoneText.decode(ByteArray(0)))
    }

    @Test fun aTruncatedTombstoneDoesNotThrow() {
        val b = tombstone()
        for (cut in listOf(1, 7, 40, b.size / 2, b.size - 3)) TombstoneText.decode(b.copyOf(cut))
    }
}

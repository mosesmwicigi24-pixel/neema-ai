package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.feature.calls.candidateKinds
import org.junit.Assert.assertEquals
import org.junit.Test

/** The candidate counts a failed call reports (owner, 2026-11-20: calls stuck on "Connecting…"). */
class CallDiagnosticsTest {
    @Test fun countsEachKindOfPathInAnSdp() {
        val sdp = """
            v=0
            a=candidate:1 1 udp 2122260223 192.168.1.20 50000 typ host generation 0
            a=candidate:2 1 udp 1686052607 41.90.1.2 50000 typ srflx raddr 192.168.1.20 rport 50000
            a=candidate:3 1 udp 41885439 157.240.1.1 3478 typ relay raddr 41.90.1.2 rport 50000
            a=candidate:4 1 tcp 1518280447 192.168.1.20 9 typ host tcptype active
        """.trimIndent()
        assertEquals(mapOf("host" to 2, "srflx" to 1, "relay" to 1), candidateKinds(sdp))
    }

    @Test fun aTrickledCandidateAndNothingAtAll() {
        assertEquals(mapOf("relay" to 1), candidateKinds("candidate:9 1 udp 1 1.2.3.4 5 typ relay raddr 0.0.0.0 rport 0"))
        assertEquals(emptyMap<String, Int>(), candidateKinds(null))
        assertEquals(emptyMap<String, Int>(), candidateKinds("v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111"))
    }
}

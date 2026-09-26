package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.feature.calls.CallRecorder
import ke.co.bethanyhouse.neema.feature.calls.PcmMixer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.webrtc.audio.JavaAudioDeviceModule
import java.io.ByteArrayInputStream
import java.io.InputStream

/**
 * The call recorder under stress: both sides go to disk as they arrive, and
 * the hang-up mix streams block by block into the encoder — an hour-long call
 * never sits in memory, and nothing caps how long finalising may take.
 */
class CallRecorderTest {
    @get:Rule val tmp = TemporaryFolder()

    private fun le(vararg s: Int) = ByteArray(s.size * 2).also { b ->
        s.forEachIndexed { i, v -> b[2 * i] = (v and 0xff).toByte(); b[2 * i + 1] = ((v shr 8) and 0xff).toByte() }
    }
    private fun samples(b: ByteArray, n: Int) = IntArray(n / 2) { i -> (b[2 * i + 1].toInt() shl 8) or (b[2 * i].toInt() and 0xff) }

    private fun drain(m: PcmMixer, block: Int = PcmMixer.BLOCK): ByteArray {
        val out = java.io.ByteArrayOutputStream()
        val buf = ByteArray(block)
        while (true) { val n = m.read(buf, buf.size); if (n < 0) break; out.write(buf, 0, n) }
        return out.toByteArray()
    }

    // ── The mixer ────────────────────────────────────────────────────────────
    @Test fun mixerSumsClipsAndPadsTheShorterSide() {
        val a = ByteArrayInputStream(le(100, -200, 30_000, -30_000, 7))
        val b = ByteArrayInputStream(le(1, 2, 10_000, -10_000))
        val m = PcmMixer(a, b)
        assertFalse(m.isEmpty)
        val out = drain(m, block = 4)   // odd block boundaries on purpose
        assertEquals(listOf(101, -198, 32_767, -32_768, 7), samples(out, out.size).toList())
    }

    @Test fun mixerWithOneSideMissingOrBothEmpty() {
        val only = PcmMixer(null, ByteArrayInputStream(le(5, 6)))
        assertEquals(listOf(5, 6), samples(drain(only), 4).toList())
        assertTrue(PcmMixer(ByteArrayInputStream(ByteArray(0)), null).isEmpty)
        assertTrue(PcmMixer(null, null).isEmpty)
        assertEquals(-1, PcmMixer(null, null).read(ByteArray(8), 8))
    }

    /** A synthetic PCM stream of [samples] samples, generated as it is read — never held in memory. */
    private class Tone(private val samples: Long, private val step: Int) : InputStream() {
        private var pos = 0L   // bytes
        private val total = samples * 2
        override fun read(): Int {
            if (pos >= total) return -1
            return byteAt(pos++)
        }
        override fun read(b: ByteArray, off: Int, len: Int): Int {
            if (pos >= total) return -1
            val n = minOf(len.toLong(), total - pos).toInt()
            for (i in 0 until n) b[off + i] = byteAt(pos + i).toByte()
            pos += n
            return n
        }
        private fun byteAt(p: Long): Int {
            val v = (((p / 2) * step) % 2_000 - 1_000).toInt()
            return if (p % 2 == 0L) v and 0xff else (v shr 8) and 0xff
        }
    }

    @Test fun anHourLongCallMixesInConstantMemory() {
        val hour = CallRecorder.OUT_RATE.toLong() * 60 * 60        // 57.6M samples a side
        // The customer's side ends 3s early (they hung up first): padded with silence.
        val m = PcmMixer(Tone(hour, 3), Tone(hour - 3 * CallRecorder.OUT_RATE, 7))
        val buf = ByteArray(PcmMixer.BLOCK)
        var bytes = 0L
        var checksum = 0L
        var maxAbs = 0
        val heapBefore = usedHeap()
        var peakHeap = heapBefore
        while (true) {
            val n = m.read(buf, buf.size)
            if (n < 0) break
            var i = 0
            while (i < n) {
                val v = (buf[i + 1].toInt() shl 8) or (buf[i].toInt() and 0xff)
                checksum += v; if (kotlin.math.abs(v) > maxAbs) maxAbs = kotlin.math.abs(v)
                i += 2
            }
            bytes += n
            if ((bytes and 0x3FFFFFF) == 0L) peakHeap = maxOf(peakHeap, usedHeap())
        }
        assertEquals("every sample of the hour", hour * 2, bytes)
        assertTrue("sums stay in range", maxAbs <= 2_000)
        assertTrue("mixed, not one side", checksum != 0L)
        // Loose on purpose (GC timing): an in-memory hour would be 115 MB.
        assertTrue("heap grew ${(peakHeap - heapBefore) / 1_000_000} MB", peakHeap - heapBefore < 40_000_000)
    }

    private fun usedHeap(): Long { val r = Runtime.getRuntime(); return r.totalMemory() - r.freeMemory() }

    // ── The recorder, end to end (the encoder swapped for a counter) ─────────
    private fun buffer(frames: Int, channels: Int, value: Int) =
        JavaAudioDeviceModule.AudioSamples(2 /* ENCODING_PCM_16BIT */, channels, 48_000, le(*IntArray(frames * channels) { value }))

    @Test fun fiveMinutesCaptureToDiskAlignAndEncodeWhole() {
        val dir = tmp.newFolder()
        var now = 1_000_000L
        var encodedBytes = 0L
        var diskDuringCall = 0L
        val head = java.io.ByteArrayOutputStream()
        val rec = CallRecorder(dir, clock = { now }) { mixer, out ->
            val buf = ByteArray(PcmMixer.BLOCK)
            out.outputStream().use { o ->
                while (true) {
                    val n = mixer.read(buf, buf.size); if (n < 0) break
                    if (head.size() < 20_000) head.write(buf, 0, n)
                    encodedBytes += n; o.write(1)
                }
            }
        }
        rec.start()
        // The customer's audio starts 500ms after the agent's.
        val tenMs = 480
        val calls = 5 * 60 * 100   // 5 minutes of 10ms buffers
        for (i in 0 until calls) {
            rec.onMicSamples(buffer(tenMs, 2, 1_000))
            if (i >= 50) rec.onRemoteSamples(buffer(tenMs, 1, 2_000))
            now += 10
            if (i == calls / 2) {
                Thread.sleep(100)
                diskDuringCall = dir.listFiles()!!.filter { it.name.endsWith(".pcm") }.sumOf { it.length() }
            }
        }
        rec.micMuted = true
        rec.onMicSamples(buffer(tenMs, 2, 1_000))   // muted: silence, still counted
        val out = rec.stop()!!
        assertTrue("PCM streamed to disk while the call runs (${diskDuringCall} B)", diskDuringCall > 1_000_000)
        val expected = (calls + 1) * 160L * 2   // 16 kHz: 160 samples per 10ms
        assertEquals(expected, encodedBytes)
        // Wall-clock alignment: 500ms (8000 samples) of the agent alone, then both sides summed.
        val first = samples(head.toByteArray(), 20_000)
        assertEquals(1_000, first[0]); assertEquals(1_000, first[7_999]); assertEquals(3_000, first[8_000])
        assertTrue(out.exists())
        assertEquals("only the output is left in the cache", listOf(out.name), dir.list()!!.toList())
        out.delete()
    }

    @Test fun nothingCapturedGivesNoFileAndLeavesNothingBehind() {
        val dir = tmp.newFolder()
        val rec = CallRecorder(dir) { _, _ -> error("must not encode") }
        rec.start()
        assertNull(rec.stop())
        assertTrue(dir.list()!!.isEmpty())
    }

    @Test fun anEncoderFailureCleansUp() {
        val dir = tmp.newFolder()
        val rec = CallRecorder(dir) { _, out -> out.writeText("partial"); error("codec died") }
        rec.start()
        rec.onMicSamples(buffer(480, 1, 500))
        Thread.sleep(20)
        assertNull(rec.stop())
        assertTrue("no partial .m4a or .pcm left: ${dir.list()!!.toList()}", dir.list()!!.isEmpty())
    }
}

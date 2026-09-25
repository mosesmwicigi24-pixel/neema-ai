package ke.co.bethanyhouse.neema.feature.calls

import android.media.AudioFormat
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import android.util.Log
import org.webrtc.audio.JavaAudioDeviceModule
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.Closeable
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.InputStream
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Records one call, the native equivalent of the web's Web-Audio mix +
 * MediaRecorder (lib/callContext.tsx startRecording/stopRecording).
 *
 * WHAT IS CAPTURED:
 *  - the agent's side: the microphone PCM WebRTC records, from
 *    JavaAudioDeviceModule's SamplesReadyCallback (after the platform's
 *    hardware AEC/NS; silence is written while the agent is muted, as the
 *    web's disabled track yields silence);
 *  - the customer's side: the decoded remote PCM WebRTC plays, from this
 *    build's PlaybackSamplesReadyCallback (io.github.webrtc-sdk exposes it).
 * Both are down-mixed to mono, resampled to 16 kHz (Whisper's native rate),
 * aligned on the wall clock from the moment recording starts, summed with
 * clipping, and encoded to AAC-LC 32 kbps in an MPEG-4 (.m4a) container.
 *
 * MEMORY: nothing grows with the call's length. During the call each side is
 * streamed to its own raw PCM file (32 KB/s); at hang-up the two files are
 * mixed block by block straight into the encoder ([PcmMixer], 16 KB at a
 * time) and the .m4a is uploaded from disk. An hour-long call peaks at
 * ~230 MB of cache (deleted at once) and a ~15 MB upload, never in the heap.
 *
 * WHY .m4a: POST /admin/calls/{id}/recording stores any extension; the
 * transcriber (faster-whisper via PyAV, or the OpenAI/Groq Whisper APIs)
 * decodes m4a, and /admin/media serves it as audio/mp4 so ExoPlayer and
 * browsers can play it back. ~4 KB/s keeps an hour-long call far under the
 * endpoint's 60 MB cap (raw WAV would pass it after ~30 minutes).
 *
 * Samples arrive on WebRTC's audio threads; they are copied and handed to a
 * single writer thread so the audio path never blocks on disk I/O.
 */
class CallRecorder(
    private val dir: File,
    /** Tests only: the wall clock samples are aligned on. */
    private val clock: () -> Long = System::currentTimeMillis,
    /** Mixed 16 kHz mono PCM16 → the output file. MediaCodec AAC in the app; a fake on the JVM. */
    private val encode: (PcmMixer, File) -> Unit = ::encodeAac,
) {
    @Volatile private var active = false
    /** Mirrors the mute button: the agent's side is recorded as silence. */
    @Volatile var micMuted = false

    private val io = Executors.newSingleThreadExecutor { r -> Thread(r, "neema-call-rec").apply { isDaemon = true } }
    private val micFile = File(dir, "call_mic_${System.nanoTime()}.pcm")
    private val remoteFile = File(dir, "call_remote_${System.nanoTime()}.pcm")
    private var mic: Track? = null
    private var remote: Track? = null
    private var startedAt = 0L

    /** One side of the call: a raw 16 kHz mono PCM16 file plus its resampler. */
    private inner class Track(file: File) {
        val out = BufferedOutputStream(FileOutputStream(file), 64 * 1024)
        val rs = Resampler(OUT_RATE)
        var written = 0L    // output samples so far
        var started = false

        fun write(samples: ShortArray, rate: Int, channels: Int, arrivedAt: Long) {
            if (!started) {
                // Pad with silence so both sides line up on the wall clock.
                started = true
                val lead = ((arrivedAt - startedAt).coerceAtLeast(0) * OUT_RATE / 1000)
                repeat(lead.toInt()) { writeShort(0) }
            }
            rs.process(samples, rate, channels) { writeShort(it) }
        }

        private fun writeShort(v: Short) {
            out.write(v.toInt() and 0xff); out.write((v.toInt() shr 8) and 0xff)
            written++
        }
    }

    fun start() {
        startedAt = clock()
        mic = Track(micFile)
        remote = Track(remoteFile)
        active = true
    }

    fun onMicSamples(s: JavaAudioDeviceModule.AudioSamples) = enqueue(s, isMic = true)
    fun onRemoteSamples(s: JavaAudioDeviceModule.AudioSamples) = enqueue(s, isMic = false)

    private fun enqueue(s: JavaAudioDeviceModule.AudioSamples, isMic: Boolean) {
        if (!active) return
        if (s.audioFormat != AudioFormat.ENCODING_PCM_16BIT) return
        val now = clock()
        val raw = s.data
        val shorts = ShortArray(raw.size / 2)
        val silent = isMic && micMuted
        if (!silent) for (i in shorts.indices) {
            shorts[i] = ((raw[2 * i].toInt() and 0xff) or (raw[2 * i + 1].toInt() shl 8)).toShort()
        }
        val rate = s.sampleRate
        val ch = s.channelCount.coerceAtLeast(1)
        runCatching {
            // Everything queued before stop() is still written (the writer is
            // FIFO and stop()'s finalise task queues behind it): hang-up doesn't
            // clip the last words. A straggler after finalise hits a closed file.
            io.execute {
                runCatching { (if (isMic) mic else remote)?.write(shorts, rate, ch, now) }
            }
        }
    }

    /**
     * Stops capture, mixes both sides and encodes. BLOCKING — call off the
     * main thread. Returns the .m4a (caller deletes it), or null when nothing
     * was captured.
     */
    fun stop(): File? {
        active = false
        val abandoned = AtomicBoolean(false)
        val result = runCatching {
            io.submit<File?> {
                val m = mic; val r = remote
                m?.out?.close(); r?.out?.close()
                val out = File(dir, "call_${System.nanoTime()}.m4a")
                try {
                    val any = PcmMixer(micFile, remoteFile).use { mixer ->
                        if (mixer.isEmpty) false else { encode(mixer, out); true }
                    }
                    // Given up on (see below): don't leave the file behind in the cache.
                    if (!any || abandoned.get()) { out.delete(); null } else out.takeIf { it.exists() && it.length() > 0 }
                } catch (e: Throwable) {
                    out.delete(); throw e
                } finally {
                    micFile.delete(); remoteFile.delete()
                }
            }.get(FINALISE_TIMEOUT_MIN, TimeUnit.MINUTES)
        }.onFailure { abandoned.set(true); logW("recording finalise failed", it) }.getOrNull()
        io.shutdown()
        return result
    }

    /**
     * Down-mix + box-filter resampler to a fixed output rate. Averages the
     * inputs falling in each output period (anti-aliasing enough for speech);
     * repeats the last value when upsampling. Keeps its phase across buffers.
     */
    private class Resampler(private val outRate: Int) {
        private var phase = 0.0
        private var acc = 0L
        private var n = 0
        private var last: Short = 0

        inline fun process(samples: ShortArray, rate: Int, channels: Int, emit: (Short) -> Unit) {
            if (rate <= 0) return
            val step = rate.toDouble() / outRate
            var i = 0
            while (i + channels <= samples.size) {
                var sum = 0
                for (c in 0 until channels) sum += samples[i + c]
                acc += sum / channels; n++
                phase += 1.0
                while (phase >= step) {
                    if (n > 0) { last = (acc / n).toInt().toShort(); acc = 0; n = 0 }
                    emit(last)
                    phase -= step
                }
                i += channels
            }
        }
    }

    companion object {
        private const val TAG = "CallRecorder"
        const val OUT_RATE = 16_000
        /** Mixing + encoding an hour takes well under a minute; this only catches a wedged codec. */
        private const val FINALISE_TIMEOUT_MIN = 10L

        // android.util.Log is a stub on the plain JVM (unit tests): never let logging throw.
        private fun logW(msg: String, e: Throwable) { runCatching { Log.w(TAG, msg, e) } }
    }
}

/**
 * Sums two little-endian PCM16 mono streams sample by sample (with clipping),
 * a block at a time; the shorter side is padded with silence. Holds only two
 * fixed buffers, whatever the length of the call.
 */
class PcmMixer internal constructor(private val a: InputStream?, private val b: InputStream?) : Closeable {
    constructor(a: File, b: File) : this(open(a), open(b))

    private var bufA = ByteArray(BLOCK)
    private var bufB = ByteArray(BLOCK)
    private var aDone = a == null
    private var bDone = b == null
    private var pendingA = -1   // a byte read ahead by isEmpty
    private var pendingB = -1

    /** True when neither side captured a single sample. */
    val isEmpty: Boolean by lazy {
        if (!aDone) { pendingA = a!!.read(); if (pendingA < 0) aDone = true }
        if (!bDone) { pendingB = b!!.read(); if (pendingB < 0) bDone = true }
        aDone && bDone
    }

    /**
     * Fills [out] from offset 0 with up to [max] mixed bytes (an even count);
     * returns how many, or -1 once both sides are exhausted.
     */
    fun read(out: ByteArray, max: Int): Int {
        isEmpty // settle the read-ahead
        val want = (minOf(max, out.size) and 1.inv()).coerceAtLeast(0)
        if (want == 0) return if (aDone && bDone) -1 else 0
        if (bufA.size < want) { bufA = ByteArray(want); bufB = ByteArray(want) }
        val na = fill(a, bufA, want, isA = true)
        val nb = fill(b, bufB, want, isA = false)
        val n = maxOf(na, nb) and 1.inv()
        if (n <= 0) return -1
        var i = 0
        while (i < n) {
            val sa = if (i + 1 < na) ((bufA[i + 1].toInt() shl 8) or (bufA[i].toInt() and 0xff)) else 0
            val sb = if (i + 1 < nb) ((bufB[i + 1].toInt() shl 8) or (bufB[i].toInt() and 0xff)) else 0
            val v = (sa + sb).coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
            out[i] = (v and 0xff).toByte()
            out[i + 1] = ((v shr 8) and 0xff).toByte()
            i += 2
        }
        return n
    }

    /** Reads up to [want] bytes (fewer only at the end of the stream). */
    private fun fill(s: InputStream?, buf: ByteArray, want: Int, isA: Boolean): Int {
        if (s == null || (if (isA) aDone else bDone)) return 0
        var n = 0
        val pending = if (isA) pendingA else pendingB
        if (pending >= 0) {
            buf[n++] = pending.toByte()
            if (isA) pendingA = -1 else pendingB = -1
        }
        while (n < want) {
            val r = s.read(buf, n, want - n)
            if (r < 0) { if (isA) aDone = true else bDone = true; break }
            n += r
        }
        return n
    }

    override fun close() {
        runCatching { a?.close() }
        runCatching { b?.close() }
    }

    companion object {
        const val BLOCK = 16 * 1024
        private fun open(f: File): InputStream? = if (f.exists()) BufferedInputStream(FileInputStream(f), 64 * 1024) else null
    }
}

/** Mixed PCM16 mono 16 kHz → AAC-LC in an MPEG-4 container, with MediaCodec + MediaMuxer. */
private fun encodeAac(mixer: PcmMixer, out: File) {
    val rate = CallRecorder.OUT_RATE
    val fmt = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, rate, 1).apply {
        setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
        setInteger(MediaFormat.KEY_BIT_RATE, 32_000)
        setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, PcmMixer.BLOCK)
    }
    val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
    codec.configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
    codec.start()
    val muxer = MediaMuxer(out.path, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
    var track = -1
    var muxing = false
    val info = MediaCodec.BufferInfo()
    val buf = ByteArray(PcmMixer.BLOCK)
    var readBytes = 0L
    var inputDone = false
    try {
        outer@ while (true) {
            if (!inputDone) {
                val ii = codec.dequeueInputBuffer(1_000)
                if (ii >= 0) {
                    val ib = codec.getInputBuffer(ii)!!
                    ib.clear()
                    val n = mixer.read(buf, minOf(ib.remaining(), buf.size))
                    val pts = (readBytes / 2) * 1_000_000L / rate
                    if (n < 0) {
                        codec.queueInputBuffer(ii, 0, 0, pts, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                        inputDone = true
                    } else {
                        ib.put(buf, 0, n)
                        codec.queueInputBuffer(ii, 0, n, pts, 0)
                        readBytes += n
                    }
                }
            }
            // Drain everything ready; wait a little only once all input is in.
            while (true) {
                val oi = codec.dequeueOutputBuffer(info, if (inputDone) 10_000 else 0)
                when {
                    oi == MediaCodec.INFO_TRY_AGAIN_LATER -> break
                    oi == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                        track = muxer.addTrack(codec.outputFormat)
                        muxer.start(); muxing = true
                    }
                    oi >= 0 -> {
                        val ob = codec.getOutputBuffer(oi)!!
                        if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0) info.size = 0
                        if (info.size > 0 && muxing) {
                            ob.position(info.offset); ob.limit(info.offset + info.size)
                            muxer.writeSampleData(track, ob, info)
                        }
                        codec.releaseOutputBuffer(oi, false)
                        if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break@outer
                    }
                }
            }
        }
    } finally {
        runCatching { codec.stop() }; runCatching { codec.release() }
        if (muxing) runCatching { muxer.stop() }
        runCatching { muxer.release() }
    }
}

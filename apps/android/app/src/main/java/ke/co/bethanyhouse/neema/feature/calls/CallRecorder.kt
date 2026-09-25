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
import java.io.DataInputStream
import java.io.EOFException
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

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
 * WHY .m4a: POST /admin/calls/{id}/recording stores any extension; the
 * transcriber (faster-whisper via PyAV, or the OpenAI/Groq Whisper APIs)
 * decodes m4a, and /admin/media serves it as audio/mp4 so ExoPlayer and
 * browsers can play it back. ~4 KB/s keeps an hour-long call far under the
 * endpoint's 60 MB cap (raw WAV would pass it after ~30 minutes).
 *
 * Samples arrive on WebRTC's audio threads; they are copied and handed to a
 * single writer thread so the audio path never blocks on disk I/O.
 */
class CallRecorder(private val dir: File) {
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
        startedAt = System.currentTimeMillis()
        mic = Track(micFile)
        remote = Track(remoteFile)
        active = true
    }

    fun onMicSamples(s: JavaAudioDeviceModule.AudioSamples) = enqueue(s, isMic = true)
    fun onRemoteSamples(s: JavaAudioDeviceModule.AudioSamples) = enqueue(s, isMic = false)

    private fun enqueue(s: JavaAudioDeviceModule.AudioSamples, isMic: Boolean) {
        if (!active) return
        if (s.audioFormat != AudioFormat.ENCODING_PCM_16BIT) return
        val now = System.currentTimeMillis()
        val raw = s.data
        val shorts = ShortArray(raw.size / 2)
        val silent = isMic && micMuted
        if (!silent) for (i in shorts.indices) {
            shorts[i] = ((raw[2 * i].toInt() and 0xff) or (raw[2 * i + 1].toInt() shl 8)).toShort()
        }
        val rate = s.sampleRate
        val ch = s.channelCount.coerceAtLeast(1)
        runCatching {
            io.execute {
                if (!active) return@execute
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
        val result = runCatching {
            io.submit<File?> {
                val m = mic; val r = remote
                m?.out?.close(); r?.out?.close()
                val mixed = File(dir, "call_mix_${System.nanoTime()}.pcm")
                val total = mix(micFile, remoteFile, mixed)
                micFile.delete(); remoteFile.delete()
                if (total <= 0) { mixed.delete(); return@submit null }
                val m4a = File(dir, "call_${System.nanoTime()}.m4a")
                try { encodeAac(mixed, m4a) } finally { mixed.delete() }
                m4a.takeIf { it.exists() && it.length() > 0 }
            }.get(60, TimeUnit.SECONDS)
        }.onFailure { Log.w(TAG, "recording finalise failed", it) }.getOrNull()
        io.shutdown()
        micFile.delete(); remoteFile.delete()
        return result
    }

    /** Sum two PCM16 mono files sample by sample (with clipping); returns samples written. */
    private fun mix(a: File, b: File, out: File): Long {
        var n = 0L
        val ia = if (a.exists()) DataInputStream(BufferedInputStream(FileInputStream(a), 64 * 1024)) else null
        val ib = if (b.exists()) DataInputStream(BufferedInputStream(FileInputStream(b), 64 * 1024)) else null
        BufferedOutputStream(FileOutputStream(out), 64 * 1024).use { o ->
            var aDone = ia == null; var bDone = ib == null
            while (!aDone || !bDone) {
                val sa = if (aDone) null else readLe(ia!!).also { if (it == null) aDone = true }
                val sb = if (bDone) null else readLe(ib!!).also { if (it == null) bDone = true }
                if (sa == null && sb == null) break
                val v = ((sa ?: 0) + (sb ?: 0)).coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt())
                o.write(v and 0xff); o.write((v shr 8) and 0xff)
                n++
            }
        }
        ia?.close(); ib?.close()
        return n
    }

    private fun readLe(s: DataInputStream): Int? = try {
        val lo = s.readUnsignedByte(); val hi = s.readByte().toInt()
        (hi shl 8) or lo
    } catch (_: EOFException) { null }

    /** PCM16 mono 16 kHz → AAC-LC in an MPEG-4 container, with MediaCodec + MediaMuxer. */
    private fun encodeAac(pcm: File, out: File) {
        val fmt = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, OUT_RATE, 1).apply {
            setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
            setInteger(MediaFormat.KEY_BIT_RATE, 32_000)
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, 16 * 1024)
        }
        val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
        codec.configure(fmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        codec.start()
        val muxer = MediaMuxer(out.path, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        var track = -1
        var muxing = false
        val info = MediaCodec.BufferInfo()
        val buf = ByteArray(4096)
        var readBytes = 0L
        var inputDone = false
        try {
            FileInputStream(pcm).use { ins ->
                while (true) {
                    if (!inputDone) {
                        val ii = codec.dequeueInputBuffer(10_000)
                        if (ii >= 0) {
                            val ib = codec.getInputBuffer(ii)!!
                            ib.clear()
                            val want = minOf(ib.remaining(), buf.size) and 1.inv()
                            val n = ins.read(buf, 0, want)
                            val pts = (readBytes / 2) * 1_000_000L / OUT_RATE
                            if (n <= 0) {
                                codec.queueInputBuffer(ii, 0, 0, pts, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                                inputDone = true
                            } else {
                                ib.put(buf, 0, n)
                                codec.queueInputBuffer(ii, 0, n, pts, 0)
                                readBytes += n
                            }
                        }
                    }
                    val oi = codec.dequeueOutputBuffer(info, 10_000)
                    when {
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
                            if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
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
    }
}

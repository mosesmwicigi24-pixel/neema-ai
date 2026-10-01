package ke.co.bethanyhouse.neema.core.crash

/**
 * Android 12+ keeps a native crash as a protobuf tombstone
 * (system/core/debuggerd/proto/tombstone.proto), which
 * ApplicationExitInfo.traceInputStream hands back as raw bytes. Read as text
 * it is unreadable, and the thread that crashed is buried among the parked
 * ones. This turns it into what a person (or a fix) needs, most useful first:
 * the signal and abort message, the crashing thread's frames — library,
 * function, offset — then the process's last log lines, then a few frames of
 * every other thread.
 *
 * Only the fields used here are read; anything else is skipped by wire type,
 * so newer tombstone versions still decode. Null when the bytes aren't a
 * tombstone (an ANR's trace is plain text and is kept as it is).
 */
internal object TombstoneText {
    private class Frame(val relPc: Long, val function: String, val offset: Long, val file: String, val buildId: String)
    private class Thread(val id: Int, val name: String, val frames: List<Frame>, val notes: List<String>)
    private class Log(val time: String, val tid: Int, val priority: Int, val tag: String, val message: String)

    fun decode(bytes: ByteArray, maxLogLines: Int = 150, otherFrames: Int = 6): String? = runCatching {
        var fingerprint = ""; var timestamp = ""; var pid = 0; var tid = 0
        var signal = ""; var code = ""; var fault: Long? = null; var abort = ""
        val causes = ArrayList<String>()
        val threads = ArrayList<Thread>()
        val logs = ArrayList<Log>()
        val r = Reader(bytes, 0, bytes.size)
        while (r.more()) {
            val (field, wire) = r.tag()
            when (field) {
                2 -> fingerprint = r.string()
                4 -> timestamp = r.string()
                5 -> pid = r.varint().toInt()
                6 -> tid = r.varint().toInt()
                10 -> r.message { s ->
                    var hasFault = false; var addr = 0L
                    while (s.more()) {
                        val (f, w) = s.tag()
                        when (f) {
                            2 -> signal = s.string()
                            4 -> code = s.string()
                            8 -> hasFault = s.varint() != 0L
                            9 -> addr = s.varint()
                            else -> s.skip(w)
                        }
                    }
                    if (hasFault) fault = addr
                }
                14 -> abort = r.string()
                15 -> r.message { c -> while (c.more()) { val (f, w) = c.tag(); if (f == 1) causes += c.string() else c.skip(w) } }
                16 -> r.message { e ->   // map<uint32, Thread> entry: 1 = key, 2 = Thread
                    while (e.more()) { val (f, w) = e.tag(); if (f == 2) e.message { threads += thread(it) } else e.skip(w) }
                }
                18 -> r.message { b ->   // LogBuffer: 1 = name, 2 = LogMessage
                    while (b.more()) { val (f, w) = b.tag(); if (f == 2) b.message { logs += log(it) } else b.skip(w) }
                }
                else -> r.skip(wire)
            }
        }
        if (signal.isEmpty() && threads.isEmpty()) return null
        val crashed = threads.firstOrNull { it.id == tid }
        buildString {
            append(signal.ifEmpty { "native crash" })
            if (code.isNotEmpty()) append(" (").append(code).append(')')
            fault?.let { append(" fault address 0x").append(java.lang.Long.toHexString(it)) }
            append(" in thread \"").append(crashed?.name ?: "?").append("\" (tid ").append(tid).append(", pid ").append(pid).append(")\n")
            if (abort.isNotEmpty()) append("Abort message: ").append(abort).append('\n')
            causes.forEach { append("Cause: ").append(it).append('\n') }
            if (timestamp.isNotEmpty()) append("At: ").append(timestamp).append('\n')
            if (fingerprint.isNotEmpty()) append("Build: ").append(fingerprint).append('\n')
            append("\n--- crashed thread: ").append(crashed?.name ?: "tid $tid").append(" ---\n")
            crashed?.notes?.forEach { append("  note: ").append(it).append('\n') }
            crashed?.frames?.forEachIndexed { i, f -> frameLine(i, f) }
                ?: append("  (no backtrace)\n")
            val mine = logs.filter { it.message.isNotBlank() }.takeLast(maxLogLines)
            if (mine.isNotEmpty()) {
                append("\n--- last log lines ---\n")
                mine.forEach { l ->
                    append(l.time).append(' ').append(l.tid).append(' ').append(PRIORITY.getOrElse(l.priority) { '?' })
                        .append(' ').append(l.tag).append(": ").append(l.message.trimEnd()).append('\n')
                }
            }
            val others = threads.filter { it !== crashed }
            if (others.isNotEmpty()) {
                append("\n--- other threads (").append(others.size).append(") ---\n")
                others.forEach { t ->
                    append("\"").append(t.name).append("\" tid ").append(t.id).append('\n')
                    t.frames.take(otherFrames).forEachIndexed { i, f -> frameLine(i, f) }
                }
            }
        }
    }.getOrNull()

    private fun StringBuilder.frameLine(i: Int, f: Frame) {
        append("  #").append(i.toString().padStart(2, '0')).append(" pc ")
            .append(java.lang.Long.toHexString(f.relPc).padStart(8, '0')).append("  ").append(f.file.ifEmpty { "?" })
        if (f.function.isNotEmpty()) append(" (").append(f.function).append('+').append(f.offset).append(')')
        if (f.buildId.isNotEmpty()) append(" (BuildId: ").append(f.buildId).append(')')
        append('\n')
    }

    private fun thread(r: Reader): Thread {
        var id = 0; var name = ""; val frames = ArrayList<Frame>(); val notes = ArrayList<String>()
        while (r.more()) {
            val (f, w) = r.tag()
            when (f) {
                1 -> id = r.varint().toInt()
                2 -> name = r.string()
                4 -> r.message { frames += frame(it) }
                7 -> notes += r.string()
                else -> r.skip(w)
            }
        }
        return Thread(id, name, frames, notes)
    }

    private fun frame(r: Reader): Frame {
        var relPc = 0L; var fn = ""; var off = 0L; var file = ""; var build = ""
        while (r.more()) {
            val (f, w) = r.tag()
            when (f) {
                1 -> relPc = r.varint()
                4 -> fn = r.string()
                5 -> off = r.varint()
                6 -> file = r.string()
                8 -> build = r.string()
                else -> r.skip(w)
            }
        }
        return Frame(relPc, fn, off, file, build)
    }

    private fun log(r: Reader): Log {
        var time = ""; var tid = 0; var prio = 0; var tag = ""; var msg = ""
        while (r.more()) {
            val (f, w) = r.tag()
            when (f) {
                1 -> time = r.string()
                3 -> tid = r.varint().toInt()
                4 -> prio = r.varint().toInt()
                5 -> tag = r.string()
                6 -> msg = r.string()
                else -> r.skip(w)
            }
        }
        return Log(time, tid, prio, tag, msg)
    }

    /** android_LogPriority → logcat's letter. */
    private val PRIORITY = listOf('?', '?', 'V', 'D', 'I', 'W', 'E', 'F', 'S')

    /** A protobuf reader over [buf] from [pos] to [end]. */
    private class Reader(private val buf: ByteArray, private var pos: Int, private val end: Int) {
        fun more() = pos < end

        fun tag(): Pair<Int, Int> { val t = varint(); return (t ushr 3).toInt() to (t and 7).toInt() }

        fun varint(): Long {
            var shift = 0; var out = 0L
            while (true) {
                check(pos < end) { "truncated varint" }
                val b = buf[pos++].toInt()
                out = out or ((b and 0x7f).toLong() shl shift)
                if (b and 0x80 == 0) return out
                shift += 7
                check(shift < 64) { "bad varint" }
            }
        }

        private fun length(): Int {
            val n = varint()
            check(n >= 0 && pos + n <= end) { "bad length" }
            return n.toInt()
        }

        fun string(): String { val n = length(); return String(buf, pos, n, Charsets.UTF_8).also { pos += n } }

        fun message(block: (Reader) -> Unit) {
            val n = length()
            block(Reader(buf, pos, pos + n))
            pos += n
        }

        fun skip(wire: Int) {
            when (wire) {
                0 -> varint()
                1 -> pos += 8
                2 -> { val n = length(); pos += n }
                5 -> pos += 4
                else -> error("unsupported wire type $wire")
            }
            check(pos <= end) { "truncated field" }
        }
    }
}

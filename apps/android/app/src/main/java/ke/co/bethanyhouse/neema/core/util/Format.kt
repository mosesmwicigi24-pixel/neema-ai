package ke.co.bethanyhouse.neema.core.util

import java.text.NumberFormat
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/** Ports of lib/utils.ts. */
object Fmt {
    /** ISO-8601 (with or without offset) → epoch millis; null when unparseable. */
    fun millis(iso: String?): Long? {
        if (iso.isNullOrBlank()) return null
        return runCatching { OffsetDateTime.parse(iso).toInstant().toEpochMilli() }.getOrNull()
            ?: runCatching { Instant.parse(iso).toEpochMilli() }.getOrNull()
            // Naive timestamps from the API are UTC.
            ?: runCatching { LocalDateTime.parse(iso).atZone(ZoneId.of("UTC")).toInstant().toEpochMilli() }.getOrNull()
            ?: runCatching { LocalDate.parse(iso.take(10)).atStartOfDay(ZoneId.systemDefault()).toInstant().toEpochMilli() }.getOrNull()
    }

    /** "5m ago" — a missing date reads "—", never an epoch date. */
    fun timeAgo(iso: String?, now: Long = System.currentTimeMillis()): String {
        val t = millis(iso) ?: return "—"
        if (t <= 0) return "—"
        val d = (now - t) / 1000
        return when {
            d < 0 -> "just now"
            d < 60 -> "${d}s ago"
            d < 3600 -> "${d / 60}m ago"
            d < 86400 -> "${d / 3600}h ago"
            else -> "${d / 86400}d ago"
        }
    }

    fun initials(name: String?): String =
        name?.trim()?.split(Regex("\\s+"))?.filter { it.isNotEmpty() }
            ?.joinToString("") { it.first().toString() }?.take(2)?.uppercase()?.ifEmpty { "?" } ?: "?"

    private val grouping: NumberFormat = NumberFormat.getNumberInstance(Locale.US).apply { maximumFractionDigits = 2 }

    fun number(n: Number?): String = grouping.format(n ?: 0)

    fun currency(n: Number?, currency: String = "KES"): String = "$currency ${number(n)}"

    /**
     * The web formats dates with `toLocaleDateString("en-KE", { month: "short" })`,
     * whose short months are Java's except September, which en-KE writes "Sept".
     */
    private val enKeMonths: Map<Long, String> = (1L..12L).associateWith { m ->
        if (m == 9L) "Sept" else java.time.Month.of(m.toInt()).getDisplayName(java.time.format.TextStyle.SHORT, Locale.ENGLISH)
    }

    private fun dayMonthYear() = java.time.format.DateTimeFormatterBuilder()
        .appendValue(java.time.temporal.ChronoField.DAY_OF_MONTH)
        .appendLiteral(' ')
        .appendText(java.time.temporal.ChronoField.MONTH_OF_YEAR, enKeMonths)
        .appendLiteral(' ')
        .appendValue(java.time.temporal.ChronoField.YEAR, 4)

    /** lib/utils.ts fmtDate: "5 Sept 2026". */
    private val dateFmt: DateTimeFormatter = dayMonthYear().toFormatter(Locale.ENGLISH)
    private val timeFmt = DateTimeFormatter.ofPattern("HH:mm", Locale.ENGLISH)
    private val dateTimeFmt: DateTimeFormatter = dayMonthYear().appendLiteral(", ")
        .appendPattern("HH:mm").toFormatter(Locale.ENGLISH)

    private fun local(iso: String?) = millis(iso)?.let { Instant.ofEpochMilli(it).atZone(ZoneId.systemDefault()) }

    fun date(iso: String?): String = local(iso)?.format(dateFmt) ?: "—"
    fun time(iso: String?): String = local(iso)?.format(timeFmt) ?: ""
    fun dateTime(iso: String?): String = local(iso)?.format(dateTimeFmt) ?: "—"

    /** WhatsApp-style day header: Today / Yesterday / 12 Mar 2026. */
    fun dayLabel(iso: String?): String {
        val z = local(iso) ?: return ""
        val today = LocalDate.now()
        val d = z.toLocalDate()
        return when (d) {
            today -> "Today"
            today.minusDays(1) -> "Yesterday"
            else -> z.format(dateFmt)
        }
    }

    fun duration(seconds: Int?): String {
        val s = seconds ?: 0
        return "%02d:%02d".format(s / 60, s % 60)
    }

    /** A real name, else the formatted phone — never a raw digit string. */
    fun displayName(name: String?, phoneOrId: String?): String =
        name?.trim()?.takeIf { it.isNotEmpty() } ?: formatPhone(phoneOrId).ifEmpty { "Unknown" }

    /** "KE" → "Kenya" (the platform's own region names). */
    fun countryName(iso: String?): String {
        val code = iso?.trim()?.uppercase() ?: return ""
        if (!Regex("^[A-Z]{2}$").matches(code)) return code
        return Locale("", code).getDisplayCountry(Locale.ENGLISH).ifEmpty { code }
    }

    /** "KE" → 🇰🇪 */
    fun flagEmoji(iso: String?): String {
        val code = iso?.trim()?.uppercase() ?: return ""
        if (!Regex("^[A-Z]{2}$").matches(code)) return ""
        return code.map { String(Character.toChars(0x1F1E6 + (it - 'A'))) }.joinToString("")
    }

    private val phoneRules: Map<String, (String, String) -> String> = mapOf(
        "1" to { cc, s -> if (s.length == 10) "+$cc (${s.substring(0, 3)}) ${s.substring(3, 6)}-${s.substring(6)}" else "+$cc $s" },
        "254" to { cc, s -> if (s.length == 9) "+$cc ${s.substring(0, 3)} ${s.substring(3, 6)} ${s.substring(6)}" else "+$cc $s" },
        "27" to { cc, s -> if (s.length == 9) "+$cc ${s.substring(0, 2)} ${s.substring(2, 5)} ${s.substring(5)}" else "+$cc $s" },
        "234" to { cc, s -> if (s.length == 10) "+$cc ${s.substring(0, 3)} ${s.substring(3, 6)} ${s.substring(6)}" else "+$cc $s" },
        "44" to { cc, s -> if (s.length == 10) "+$cc ${s.substring(0, 4)} ${s.substring(4)}" else "+$cc $s" },
        "49" to { cc, s -> if (s.length >= 9) "+$cc ${s.substring(0, 3)} ${s.substring(3, 7)}${if (s.length > 7) " " + s.substring(7) else ""}" else "+$cc $s" },
        "33" to { cc, s -> if (s.length == 9) "+$cc ${s.substring(0, 1)} ${s.substring(1, 3)} ${s.substring(3, 5)} ${s.substring(5, 7)} ${s.substring(7)}" else "+$cc $s" },
        "91" to { cc, s -> if (s.length == 10) "+$cc ${s.substring(0, 5)} ${s.substring(5)}" else "+$cc $s" },
        "971" to { cc, s -> if (s.length == 9) "+$cc ${s.substring(0, 2)} ${s.substring(2, 5)} ${s.substring(5)}" else "+$cc $s" },
        "255" to { cc, s -> if (s.length == 9) "+$cc ${s.substring(0, 3)} ${s.substring(3, 6)} ${s.substring(6)}" else "+$cc $s" },
        "256" to { cc, s -> if (s.length == 9) "+$cc ${s.substring(0, 3)} ${s.substring(3, 6)} ${s.substring(6)}" else "+$cc $s" },
        "251" to { cc, s -> if (s.length == 9) "+$cc ${s.substring(0, 2)} ${s.substring(2, 5)} ${s.substring(5)}" else "+$cc $s" },
        "233" to { cc, s -> if (s.length == 9) "+$cc ${s.substring(0, 2)} ${s.substring(2, 5)} ${s.substring(5)}" else "+$cc $s" },
        "250" to { cc, s -> if (s.length == 9) "+$cc ${s.substring(0, 3)} ${s.substring(3, 6)} ${s.substring(6)}" else "+$cc $s" },
        "61" to { cc, s -> if (s.length == 9) "+$cc ${s.substring(0, 1)} ${s.substring(1, 5)} ${s.substring(5)}" else "+$cc $s" },
    )

    /** "254712345678" → "+254 712 345 678"; Meta PSIDs (>15 digits) are shown as ids. */
    fun formatPhone(raw: String?): String {
        if (raw.isNullOrBlank()) return ""
        val cleaned = raw.trim()
        // Website chat visitors are keyed by a hash ("web_3f9a…"): never read it as a phone.
        if (cleaned.startsWith("web_")) return "Website visitor"
        val digits = cleaned.filter { it.isDigit() }
        if (digits.isEmpty()) return cleaned
        if (digits.length > 15) return "Messenger ID " + cleaned.removePrefix("+")
        for (len in listOf(3, 2, 1)) {
            if (digits.length <= len) continue
            val cc = digits.substring(0, len)
            phoneRules[cc]?.let { return it(cc, digits.substring(len)) }
        }
        return "+" + digits.replace(Regex("(\\d{3})(?=\\d)"), "$1 ")
    }
}

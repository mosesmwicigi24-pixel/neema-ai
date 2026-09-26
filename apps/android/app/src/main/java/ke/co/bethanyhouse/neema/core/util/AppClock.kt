package ke.co.bethanyhouse.neema.core.util

import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * The app's one source of "now". Production reads the system clock; tests
 * shift it to a pinned date (it still ticks, so timeouts and dedupe windows
 * behave) so rendered dates like "Joined 9 Mar 2026" never drift day to day.
 */
object AppClock {
    // Unit tests set -Dneema.clock.pin=<ISO instant> (see app/build.gradle.kts).
    @Volatile private var offsetMillis: Long =
        System.getProperty("neema.clock.pin")?.let { runCatching { Instant.parse(it).toEpochMilli() - System.currentTimeMillis() }.getOrNull() } ?: 0L

    fun now(): Long = System.currentTimeMillis() + offsetMillis
    fun instant(): Instant = Instant.ofEpochMilli(now())
    fun today(zone: ZoneId = ZoneId.systemDefault()): LocalDate = instant().atZone(zone).toLocalDate()
    fun localNow(zone: ZoneId = ZoneId.systemDefault()): LocalDateTime = instant().atZone(zone).toLocalDateTime()

    /** Tests only: make [now] read [pinned] at this moment (and advance from there). */
    fun pinTo(pinned: Instant) { offsetMillis = pinned.toEpochMilli() - System.currentTimeMillis() }
    fun reset() { offsetMillis = 0 }
}

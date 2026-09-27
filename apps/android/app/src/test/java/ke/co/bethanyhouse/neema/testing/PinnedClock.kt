package ke.co.bethanyhouse.neema.testing

import ke.co.bethanyhouse.neema.core.util.AppClock
import org.junit.rules.TestWatcher
import org.junit.runner.Description
import java.time.Instant

/**
 * Re-pins [AppClock] to the build's pinned instant at the start of each test.
 * The pin otherwise keeps running from JVM start, so a screen that prints a
 * clock time ("11:20", the Calls log and the thread's call pills) would read a
 * different minute depending on how long the suite had been running.
 */
class PinnedClock(private val at: Instant = Instant.parse(System.getProperty("neema.clock.pin") ?: "2026-09-25T09:00:00Z")) : TestWatcher() {
    override fun starting(description: Description) = AppClock.pinTo(at)
}

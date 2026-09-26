package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.isPhoneLike
import ke.co.bethanyhouse.neema.core.util.Fmt
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** lib/utils.ts, lib/permissions.ts and the api.ts mappers. */
class CoreLogicTest {
    @Test
    fun phoneLikeNamesGetAGlyphNotInitials() {
        // The bug: an unnamed contact's avatar read "+7" (initials of "+254 712 345 678").
        assertTrue(isPhoneLike(Fmt.displayName(null, "254712345678")))
        assertTrue(isPhoneLike("+1 (202) 555-1234"))
        assertTrue(isPhoneLike("254712345678"))
        assertTrue(isPhoneLike(Fmt.displayName("", "25898765432101234"))) // "Messenger ID …"
        assertFalse(isPhoneLike("Fr. Peter Kamau"))
        assertFalse(isPhoneLike("Room 101"))
        assertFalse(isPhoneLike("   "))
        assertFalse(isPhoneLike(null))
    }

    @Test
    fun initialsMatchTheWeb() {
        assertEquals("FP", Fmt.initials("Fr. Peter Kamau"))
        assertEquals("MM", Fmt.initials("moses mwicigi"))
        assertEquals("G", Fmt.initials("Grace"))
        assertEquals("?", Fmt.initials(null))
        assertEquals("?", Fmt.initials("  "))
    }

    @Test
    fun phonesFormatByCountryAsFormatPhoneDoes() {
        assertEquals("+254 712 345 678", Fmt.formatPhone("254712345678"))
        assertEquals("+254 712 345 678", Fmt.formatPhone("+254712345678"))
        assertEquals("+44 7911 123456", Fmt.formatPhone("447911123456"))
        assertEquals("+1 (202) 555-1234", Fmt.formatPhone("12025551234"))
        assertEquals("+33 6 12 34 56 78", Fmt.formatPhone("33612345678"))
        assertEquals("+49 301 2345 67", Fmt.formatPhone("49301234567"))
        assertEquals("+27 82 123 4567", Fmt.formatPhone("27821234567"))
        assertEquals("+91 98765 43210", Fmt.formatPhone("919876543210"))
        assertEquals("+255 754 333 222", Fmt.formatPhone("255754333222"))
        assertEquals("Messenger ID 25898765432101234", Fmt.formatPhone("25898765432101234"))
        assertEquals("", Fmt.formatPhone(null))
        assertEquals("Unknown", Fmt.displayName(" ", ""))
        assertEquals("Mary", Fmt.displayName(" Mary ", "254"))
    }

    @Test
    fun timeAgoMatchesTheWeb() {
        val now = 1_750_000_000_000L
        fun iso(msAgo: Long) = java.time.Instant.ofEpochMilli(now - msAgo).toString()
        assertEquals("—", Fmt.timeAgo(null, now))
        assertEquals("—", Fmt.timeAgo("garbage", now))
        assertEquals("just now", Fmt.timeAgo(iso(-5_000), now))
        assertEquals("42s ago", Fmt.timeAgo(iso(42_000), now))
        assertEquals("5m ago", Fmt.timeAgo(iso(5 * 60_000), now))
        assertEquals("3h ago", Fmt.timeAgo(iso(3 * 3_600_000), now))
        assertEquals("2d ago", Fmt.timeAgo(iso(49 * 3_600_000), now))
    }

    @Test
    fun permissionsResolveAsGetAgentPermissions() {
        assertEquals(Perms.ALL, Perms.effective("readonly", isSuperuser = true, permissions = listOf("view_orders")))
        assertEquals(listOf("view_orders"), Perms.effective("admin", false, listOf("view_orders")))
        assertEquals(Perms.ALL, Perms.effective("admin", false, emptyList()))
        assertEquals(11, Perms.effective("agent", false, null).size)
        assertEquals(6, Perms.effective("readonly", false, null).size)
        assertEquals(emptyList<String>(), Perms.effective("supervisor", false, null))
        assertEquals(21, Perms.ALL.size)
        // mapAgent(): custom_permissions ?? role_permissions
        val a = Agent("x", role = "agent", customPermissions = null, rolePermissions = listOf("view_reports"))
        assertEquals(listOf("view_reports"), Perms.of(a))
        assertEquals(listOf("add_notes"), Perms.of(a.copy(customPermissions = listOf("add_notes"))))
    }

    @Test
    fun mappersMatchApiTs() {
        // mapOrder(): an "open" cart shows as pending; the name falls back to the wa_id.
        val o = Order("o1", waId = "254700000000", rawStatus = "open", subtotal = 1200.0)
        assertEquals("pending", o.status)
        assertEquals("254700000000", o.customerName)
        assertEquals(1200.0, o.total, 0.0)
        assertEquals("delivered", o.copy(rawStatus = "delivered").status)
        // mapCatalogItem(): hub rows get a synthetic id and "General" category.
        val hub = CatalogItem(hubProductId = 501, sku = "CS-BLK")
        assertEquals("501", hub.id)
        assertEquals("General", hub.category)
        assertTrue(hub.isHub)
        assertEquals("CS-BLK", CatalogItem(sku = "CS-BLK").id)
        assertFalse(CatalogItem(rawId = "c1", sku = "x").isHub)
    }
}

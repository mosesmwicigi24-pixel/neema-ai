package ke.co.bethanyhouse.neema.orders

import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.orders.phoneLine
import ke.co.bethanyhouse.neema.testing.Fixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * GET /admin/orders carries no `contact_name`, so an order's name IS its
 * formatted phone; the card and the sheet must not print it twice.
 */
class OrderPhoneLineTest {
    private fun order(waId: String, name: String? = null): Order {
        val row = NeemaJson.decodeFromString(Order.serializer(), Fixtures.orderRow("o1", waId, "[]", "100.0", "pending", "whatsapp", 5))
        return row.copy(contactName = name)
    }

    @Test fun theApiShapeHasNoNameSoThePhoneLineIsHidden() {
        val o = order("254712345678")
        val name = Fmt.displayName(o.contactName, o.waId)
        assertEquals(Fmt.formatPhone("254712345678"), name)
        assertNull(phoneLine(o, name))
    }

    @Test fun aRealNameKeepsThePhoneUnderIt() {
        val o = order("254712345678", name = "Fr. Peter Kamau")
        assertEquals(Fmt.formatPhone("254712345678"), phoneLine(o, Fmt.displayName(o.contactName, o.waId)))
    }

    @Test fun aWebsiteVisitorIsNotRepeatedEither() {
        val o = order("web_3f9a0c")
        assertNull(phoneLine(o, Fmt.displayName(o.contactName, o.waId)))
    }

    @Test fun aBlankNameFallsBackToThePhoneAndHidesTheLine() {
        val o = order("255754333222", name = "   ")
        assertNull(phoneLine(o, Fmt.displayName(o.contactName, o.waId)))
    }
}

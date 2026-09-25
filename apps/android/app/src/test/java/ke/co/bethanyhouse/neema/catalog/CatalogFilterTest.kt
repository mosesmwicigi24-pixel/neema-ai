package ke.co.bethanyhouse.neema.catalog

import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.feature.catalog.catalogCategories
import ke.co.bethanyhouse.neema.feature.catalog.filterCatalog
import ke.co.bethanyhouse.neema.feature.catalog.plainNum
import ke.co.bethanyhouse.neema.feature.catalog.priceText
import ke.co.bethanyhouse.neema.feature.catalog.usd
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** CatalogView.tsx's category list, filter and search, and its number formats. */
class CatalogFilterTest {
    private val catalog: List<CatalogItem> = NeemaJson.decodeFromString(ReportsFixtures.catalog)

    private fun names(filter: String = "all", q: String = "") = filterCatalog(catalog, filter, q).map { it.sku }

    @Test fun categories_distinctNonEmpty_inCatalogueOrder() {
        assertEquals(
            listOf("Clergy Apparel", "Clergy Vestments", "Anointing Oil", "Communion Wafers", "Prefilled Cups", "Communion Trays"),
            catalogCategories(catalog),
        )
        // A local fallback row has category "" — no empty option; a null category reads "General".
        val odd: List<CatalogItem> = NeemaJson.decodeFromString("""[{"sku":"a","name":"A","category":""},{"sku":"b","name":"B"},{"sku":"c","name":"C","category":"Wine"},{"sku":"d","name":"D","category":"Wine"}]""")
        assertEquals(listOf("General", "Wine"), catalogCategories(odd))
    }

    @Test fun filter_all_and_byCategory() {
        assertEquals(6, names().size)
        assertEquals(listOf("CS-BLK"), names("Clergy Apparel"))
        assertEquals(emptyList<String>(), names("No Such Category"))
    }

    @Test fun search_matchesNameSkuOrAlias_caseInsensitive() {
        assertEquals(listOf("CS-BLK"), names(q = "CLERGY shirt"))
        assertEquals(listOf("WAF-500"), names(q = "waf-5"))
        assertEquals(listOf("WAF-500"), names(q = "Hosts"))
        assertEquals(listOf("OIL-50"), names(q = "holy"))
        // "communion" is in three names; the tray has no alias but matches by name.
        assertEquals(listOf("WAF-500", "CUP-PF", "TRAY-1"), names(q = "communion"))
        assertEquals(emptyList<String>(), names(q = "zzz"))
    }

    @Test fun search_andCategory_combine() {
        assertEquals(listOf("TRAY-1"), names("Communion Trays", "communion"))
        assertEquals(emptyList<String>(), names("Clergy Apparel", "communion"))
    }

    @Test fun search_isNotTrimmed_likeTheWeb() {
        assertEquals(emptyList<String>(), names(q = " clergy shirt "))
    }

    @Test fun hubRowsAreHub_localRowsAreNot() {
        assertTrue(catalog.first { it.sku == "CS-BLK" }.isHub)
        assertFalse(catalog.first { it.sku == "TRAY-1" }.isHub)
        assertEquals("501", catalog.first { it.sku == "CS-BLK" }.id)
        assertEquals("TRAY-1", catalog.first { it.sku == "TRAY-1" }.id)
    }

    @Test fun priceText_rangeWhenVariantsDiffer() {
        assertEquals("KES 3,500 – KES 4,200", priceText(catalog[0]))
        assertEquals("KES 12,500", priceText(catalog[1]))
    }

    @Test fun numberFormats() {
        assertEquals("$27", usd(27.0))
        assertEquals("$1,200", usd(1200.0))
        assertEquals("$276.92", usd(276.92))
        assertEquals("$0.08", usd(0.08))
        assertEquals("1200", plainNum(1200.0))
        assertEquals("129.5", plainNum(129.5))
    }
}

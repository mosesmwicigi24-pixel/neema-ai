package ke.co.bethanyhouse.neema.catalog

import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import androidx.compose.ui.unit.dp
import ke.co.bethanyhouse.neema.feature.catalog.catalogCategories
import ke.co.bethanyhouse.neema.feature.catalog.catalogColumns
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

    /** grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6. */
    @Test fun columns_followTheWebBreakpoints() {
        assertEquals(2, catalogColumns(380.dp))
        assertEquals(2, catalogColumns(639.dp))
        assertEquals(3, catalogColumns(640.dp))
        assertEquals(4, catalogColumns(768.dp))
        assertEquals(4, catalogColumns(1023.dp))
        assertEquals(6, catalogColumns(1024.dp))
    }

    /** Round 7: a large font drops columns until each card keeps ~118dp per 100% of font. */
    @Test fun columns_giveWayToALargeFont() {
        assertEquals(2, catalogColumns(328.dp, 1.3f))   // a 360dp phone at 130%: still two
        assertEquals(1, catalogColumns(361.dp, 2.0f))   // a Pixel 5 at 200%: one card a row
        assertEquals(4, catalogColumns(1232.dp, 2.0f))  // a landscape tablet at 200%: six → four
        assertEquals(6, catalogColumns(1232.dp, 1.0f))
        assertEquals(2, catalogColumns(380.dp, 0.85f))  // a small font never adds columns past the web's
    }

    /** A price range only wraps at the dash: "KES 3,500 –" / "KES 4,200", never "KES" / "4,200". */
    @Test fun priceRange_keepsEachAmountWhole() {
        val shirt = catalog.first { it.sku == "CS-BLK" }
        assertEquals("KES 3,500 – KES 4,200", ke.co.bethanyhouse.neema.feature.catalog.unbroken(priceText(shirt)))
    }

    @Test fun categories_distinctNonEmpty_inCatalogueOrder() {
        assertEquals(
            // The tray's hub category is "" (hub_client._map_product: name_en or ""), so it offers no option.
            listOf("Clergy Apparel", "Clergy Vestments", "Anointing Oil", "Communion Wafers", "Prefilled Cups"),
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
        assertEquals(listOf("WAF-500"), names("Communion Wafers", "communion"))
        assertEquals(emptyList<String>(), names("Clergy Apparel", "communion"))
    }

    @Test fun search_isNotTrimmed_likeTheWeb() {
        assertEquals(emptyList<String>(), names(q = " clergy shirt "))
    }

    /** Hub rows carry hub_product_id and no id; the local fallback (hub down) carries neither. */
    @Test fun hubRowsAreHub_localRowsAreNot() {
        assertTrue(catalog.first { it.sku == "CS-BLK" }.isHub)
        assertEquals("501", catalog.first { it.sku == "CS-BLK" }.id)
        val local: List<CatalogItem> = NeemaJson.decodeFromString(ReportsFixtures.localCatalog)
        assertFalse(local.first { it.sku == "TRAY-1" }.isHub)
        assertEquals("TRAY-1", local.first { it.sku == "TRAY-1" }.id)
        // str(category or "") — an empty category stays empty (the web's `?? "General"` only catches null).
        assertEquals("", local.first { it.sku == "TRAY-1" }.category)
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

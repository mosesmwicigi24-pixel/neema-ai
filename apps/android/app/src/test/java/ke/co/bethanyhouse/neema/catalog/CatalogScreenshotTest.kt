package ke.co.bethanyhouse.neema.catalog

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.BottomSheetDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.feature.catalog.CatalogScreen
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.catalog.ProductDetail
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.PageSlice
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/** The catalogue grid (images fall back to category glyphs), audit, filters, empty, product sheet; phone/tablet, light/dark. */
@OptIn(ExperimentalCoroutinesApi::class)
class CatalogScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    @Before fun setUp() { ReportsFixtures.pinTimeZone(); Dispatchers.setMain(UnconfinedTestDispatcher()) }
    @After fun tearDown() { Dispatchers.resetMain(); ReportsFixtures.restoreTimeZone() }

    private fun shot(
        dark: Boolean = false, auditOpen: Boolean = false, filter: String = "all", search: String = "",
        page: Int = 0,
        configure: (FakeNeema) -> Unit = {},
    ) {
        val f = FakeNeema.withFixtures().also(ReportsFixtures::install).also(configure)
        val dash = dashboard(paparazzi.context, f)
        val vm = CatalogViewModel(dash).apply {
            this.auditOpen.value = auditOpen; this.filter.value = filter; this.search.value = search
        }
        paparazzi.snapshot { AppFrame(dark) { PageSlice(page) { CatalogScreen(dash, vm) } } }
    }

    @Test fun grid() = shot()
    @Test fun gridPage2() = shot(page = 1)
    @Test fun gridDark() = shot(dark = true)
    @Test fun gridDarkPage2() = shot(dark = true, page = 1)
    @Test fun auditExpanded() = shot(auditOpen = true)
    @Test fun auditExpandedDark() = shot(dark = true, auditOpen = true)
    @Test fun categoryFilter() = shot(filter = "Clergy Vestments")
    @Test fun searchNoResults() = shot(search = "zzz")
    @Test fun emptyCatalog() = shot { ReportsFixtures.installEmpty(it) }
    @Test fun auditUnavailable() = shot { it.on("GET", "/admin/catalog/audit", code = 500, body = "{}") }

    @Test fun tablet() { paparazzi.unsafeUpdateConfig(DeviceConfig.PIXEL_C); shot() }
    @Test fun tabletDark() { paparazzi.unsafeUpdateConfig(DeviceConfig.PIXEL_C); shot(dark = true) }

    private val catalog: List<CatalogItem> = NeemaJson.decodeFromString(ReportsFixtures.catalog)

    /** The product sheet's body, framed as the bottom sheet draws it (a Popup can't be captured). */
    @OptIn(ExperimentalMaterial3Api::class)
    private fun sheet(item: CatalogItem, dark: Boolean = false) {
        paparazzi.unsafeUpdateConfig(DeviceConfig.PIXEL_6)
        paparazzi.snapshot {
            AppFrame(dark) {
                Box(Modifier.fillMaxSize().background(Color(0x66000000)), contentAlignment = Alignment.BottomCenter) {
                    Column(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp))
                            .background(Neema.colors.bg2),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        BottomSheetDefaults.DragHandle()
                        ProductDetail(item)
                    }
                }
            }
        }
    }

    @Test fun sheetVariants() = sheet(catalog.first { it.sku == "CS-BLK" })
    @Test fun sheetVariantsDark() = sheet(catalog.first { it.sku == "CS-BLK" }, dark = true)
    @Test fun sheetLongName() = sheet(catalog.first { it.sku == "CAS-PUR" })
    @Test fun sheetOutOfStock() = sheet(catalog.first { it.sku == "OIL-50" })
    /** A row from the local table the API serves while the hub is down (catalog_items() fallback). */
    @Test fun sheetLocalItem() = sheet(NeemaJson.decodeFromString<List<CatalogItem>>(ReportsFixtures.localCatalog).first { it.sku == "CS-BLK" })

    /** Hub down, no cached copy: GET /admin/catalog answers the local, in-stock-only table. */
    @Test fun hubDownLocalTable() = shot { it.on("GET", "/admin/catalog", body = ReportsFixtures.localCatalog) }
}

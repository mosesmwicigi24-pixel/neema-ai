import Foundation
import XCTest
@testable import NeemaCore

/// CatalogView.tsx's category list, filter and search, and its number formats (Android `CatalogFilterTest`).
final class CatalogRulesTests: XCTestCase {
    private let catalog: [CatalogItem] = try! NeemaJSON.decode([CatalogItem].self, from: ReportsFixtures.catalog)

    private func names(_ filter: String = "all", _ q: String = "") -> [String] { CatalogRules.filter(catalog, filter: filter, search: q).map { $0.sku } }

    /// grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6.
    func testColumnsFollowTheWebBreakpoints() {
        XCTAssertEqual(CatalogRules.columns(width: 380), 2)
        XCTAssertEqual(CatalogRules.columns(width: 639), 2)
        XCTAssertEqual(CatalogRules.columns(width: 640), 3)
        XCTAssertEqual(CatalogRules.columns(width: 768), 4)
        XCTAssertEqual(CatalogRules.columns(width: 1023), 4)
        XCTAssertEqual(CatalogRules.columns(width: 1024), 6)
    }

    /// A large font drops columns until each card keeps ~118pt per 100% of font.
    func testColumnsGiveWayToALargeFont() {
        XCTAssertEqual(CatalogRules.columns(width: 328, fontScale: 1.3), 2)   // a 360pt phone at 130%: still two
        XCTAssertEqual(CatalogRules.columns(width: 361, fontScale: 2.0), 1)   // a small phone at 200%: one card a row
        XCTAssertEqual(CatalogRules.columns(width: 1232, fontScale: 2.0), 4)  // a landscape tablet at 200%: six → four
        XCTAssertEqual(CatalogRules.columns(width: 1232, fontScale: 1.0), 6)
        XCTAssertEqual(CatalogRules.columns(width: 380, fontScale: 0.85), 2)  // a small font never adds columns past the web's
    }

    /// A price range only wraps at the dash: "KES 3,500 –" / "KES 4,200", never "KES" / "4,200".
    func testPriceRangeKeepsEachAmountWhole() {
        let shirt = catalog.first { $0.sku == "CS-BLK" }!
        XCTAssertEqual(CatalogRules.unbroken(CatalogRules.priceText(shirt)), "KES\u{00A0}3,500 – KES\u{00A0}4,200")
    }

    func testCategoriesDistinctNonEmptyInCatalogueOrder() {
        // The tray's hub category is "" (hub_client._map_product: name_en or ""), so it offers no option.
        XCTAssertEqual(CatalogRules.categories(catalog), ["Clergy Apparel", "Clergy Vestments", "Anointing Oil", "Communion Wafers", "Prefilled Cups"])
        // A local fallback row has category "" — no empty option; a null category reads "General".
        let odd = try! NeemaJSON.decode([CatalogItem].self, from: #"[{"sku":"a","name":"A","category":""},{"sku":"b","name":"B"},{"sku":"c","name":"C","category":"Wine"},{"sku":"d","name":"D","category":"Wine"}]"#)
        XCTAssertEqual(CatalogRules.categories(odd), ["General", "Wine"])
    }

    func testFilterAllAndByCategory() {
        XCTAssertEqual(names().count, 6)
        XCTAssertEqual(names("Clergy Apparel"), ["CS-BLK"])
        XCTAssertEqual(names("No Such Category"), [])
    }

    func testSearchMatchesNameSkuOrAliasCaseInsensitive() {
        XCTAssertEqual(names("all", "CLERGY shirt"), ["CS-BLK"])
        XCTAssertEqual(names("all", "waf-5"), ["WAF-500"])
        XCTAssertEqual(names("all", "Hosts"), ["WAF-500"])
        XCTAssertEqual(names("all", "holy"), ["OIL-50"])
        // "communion" is in three names; the tray has no alias but matches by name.
        XCTAssertEqual(names("all", "communion"), ["WAF-500", "CUP-PF", "TRAY-1"])
        XCTAssertEqual(names("all", "zzz"), [])
    }

    func testSearchAndCategoryCombine() {
        XCTAssertEqual(names("Communion Wafers", "communion"), ["WAF-500"])
        XCTAssertEqual(names("Clergy Apparel", "communion"), [])
    }

    func testSearchIsNotTrimmedLikeTheWeb() {
        XCTAssertEqual(names("all", " clergy shirt "), [])
    }

    /// The index answers exactly as the plain filter does, for every combination.
    func testTheIndexAgreesWithThePlainFilter() {
        let ix = CatalogIndex(catalog)
        for f in ["all", "Clergy Apparel", "Communion Wafers", "nope"] {
            for q in ["", "communion", "CLERGY shirt", "holy", "zzz", " clergy "] {
                XCTAssertEqual(ix.filter(f, q).map { $0.sku }, names(f, q), "\(f) / \(q)")
            }
        }
        XCTAssertEqual(ix.inStock, 5)
        XCTAssertEqual(ix.view(filter: "all", search: "").outStock, 1)
    }

    /// Hub rows carry hub_product_id and no id; the local fallback (hub down) carries neither.
    func testHubRowsAreHubLocalRowsAreNot() {
        XCTAssertTrue(catalog.first { $0.sku == "CS-BLK" }!.isHub)
        XCTAssertEqual(catalog.first { $0.sku == "CS-BLK" }!.id, "501")
        let local = try! NeemaJSON.decode([CatalogItem].self, from: ReportsFixtures.localCatalog)
        XCTAssertFalse(local.first { $0.sku == "TRAY-1" }!.isHub)
        XCTAssertEqual(local.first { $0.sku == "TRAY-1" }!.id, "TRAY-1")
        // str(category or "") — an empty category stays empty (the web's `?? "General"` only catches null).
        XCTAssertEqual(local.first { $0.sku == "TRAY-1" }!.category, "")
    }

    func testPriceTextRangeWhenVariantsDiffer() {
        XCTAssertEqual(CatalogRules.priceText(catalog[0]), "KES 3,500 – KES 4,200")
        XCTAssertEqual(CatalogRules.priceText(catalog[1]), "KES 12,500")
    }

    func testNumberFormats() {
        XCTAssertEqual(CatalogRules.usd(27.0), "$27")
        XCTAssertEqual(CatalogRules.usd(1200.0), "$1,200")
        XCTAssertEqual(CatalogRules.usd(276.92), "$276.92")
        XCTAssertEqual(CatalogRules.usd(0.08), "$0.08")
        XCTAssertEqual(CatalogRules.plainNum(1200.0), "1200")
        XCTAssertEqual(CatalogRules.plainNum(129.5), "129.5")
        XCTAssertEqual(CatalogRules.num(1500), "1,500")
        XCTAssertEqual(CatalogRules.stockText(catalog[0]), "1200 left")
        XCTAssertEqual(CatalogRules.stockText(catalog[2]), "OUT")
        XCTAssertEqual(CatalogRules.stockText(catalog[3]), "IN")
        XCTAssertEqual(CatalogRules.glyph("Clergy Apparel"), "👕")
        XCTAssertEqual(CatalogRules.glyph(nil), "📦")
    }

    func testGridRowsAndUniqueKeys() {
        let g = CatalogRules.gridRows(catalog, cols: 4)
        XCTAssertEqual(g.rows.map { $0.count }, [4, 2])
        XCTAssertEqual(g.keys.count, 2)
        XCTAssertEqual(CatalogRules.uniqueKeys(["a", "b", "a", "a"]), ["a", "b", "a#2", "a#3"])
        XCTAssertEqual(CatalogRules.gridRows([], cols: 0).rows.count, 0)
    }

    /// The snapshot round-trips the hub's rows, variants included.
    func testCatalogSnapshotRoundTrips() throws {
        let back = try NeemaJSON.decode([CatalogItem].self, from: NeemaJSON.encode(catalog))
        XCTAssertEqual(back, catalog)
    }
}

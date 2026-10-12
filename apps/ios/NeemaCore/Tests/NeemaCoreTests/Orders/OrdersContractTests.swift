import Foundation
import XCTest
@testable import NeemaCore

/// The Orders screen against the REAL shapes of admin.py `list_orders`,
/// `get_order` and `update_order` (Android `OrdersContractTest`). Every
/// request is asserted exactly; every response variant the server can
/// legitimately send must decode.
final class OrdersContractTests: OrdersTestCase {
    private var api: NeemaApi { host.api }

    // ── GET /admin/orders ───────────────────────────────────────────────────

    func testListIsAPlainGetWithNoQuery() async throws {
        let list = try await api.orders.list()
        let call = fake.callsTo("GET", "/admin/orders").last!
        XCTAssertNil(call.query, "the dashboard's list sends no filter")
        XCTAssertEqual(list.count, 6)
    }

    func testListFiltersUseTheServersParamNames() async throws {
        _ = try await api.orders.list(status: "confirmed", waId: "254712345678")
        XCTAssertEqual(fake.callsTo("GET", "/admin/orders").last?.query, "status=confirmed&wa_id=254712345678")
    }

    func testAFullOrmRowDecodesEveryFieldTheScreenReads() async throws {
        fake.on("GET", "/admin/orders", body: SalesFixtures.ordersJson([SalesFixtures.linkedOrder]))
        let o = try await api.orders.list()[0]
        XCTAssertEqual(o.id, "254712345678_1773480600000")
        XCTAssertEqual(o.subtotal, 9800.0) // Decimal → float via jsonable_encoder
        XCTAssertEqual(o.amount, 9800.0)
        XCTAssertEqual(o.currency, "KES")
        XCTAssertEqual(o.status, "confirmed")
        XCTAssertEqual(o.paymentStatus, "unpaid")
        XCTAssertEqual(o.fulfillmentStatus, "pending")
        XCTAssertEqual(o.hubOrderId, 1042)
        XCTAssertEqual(o.hubOrderNumber, "BH-1042")
        XCTAssertEqual(o.hubPushStatus, "pushed")
        XCTAssertEqual(o.hubStatus, "processing")
        XCTAssertEqual(o.hubPaymentStatus, "paid")
        XCTAssertEqual(o.hubPublicToken, "tok1042")
        XCTAssertEqual(o.hubPublicUrl, "https://hub.bethanyhouse.co.ke/order/tok1042")
        XCTAssertEqual(OrderUi.hubOrderHref(o), "https://hub.bethanyhouse.co.ke/handoff/orders/1042#v=tok1042")
        XCTAssertEqual(OrderUi.hubMeta(o)?.label, "Confirmed")
        // No contact_name on the wire (it isn't a column): the name falls back to the wa_id.
        XCTAssertNil(o.contactName)
        XCTAssertEqual(o.customerName, "254712345678")
        // "+00:00" with no fraction parses to the exact instant.
        XCTAssertEqual(Fmt.millis(o.createdAt), Fmt.millis("2026-03-14T09:30:00Z"))
        XCTAssertEqual(o.items.count, 3)
        XCTAssertEqual(o.items[0].lineTotal, 7000.0)
        XCTAssertEqual(o.items[0].effectiveUnit, 3500.0)
        XCTAssertEqual(o.replyText, "Asante Father! Your order BH-1042 is confirmed — we deliver to Nyeri on Friday.")
    }

    func testMicrosecondOffsetTimestampsParse() {
        let base = ISO8601DateFormatter().date(from: "2026-09-25T08:15:30Z")!.addingTimeInterval(0.123456)
        let iso = SalesFixtures.pyIso(base)
        XCTAssertEqual(iso, "2026-09-25T08:15:30.123456+00:00")
        XCTAssertEqual(Fmt.millis(iso), Fmt.millis("2026-09-25T08:15:30.123Z"))
        // Whole seconds print no fraction at all.
        XCTAssertEqual(SalesFixtures.pyIso(ISO8601DateFormatter().date(from: "2026-03-14T09:30:00Z")!), SalesFixtures.FIXED_AT)
    }

    func testAgentOrderLinesCarryUnitPriceOnlyAndNeverPrintAMadeUpZero() async throws {
        fake.on("GET", "/admin/orders", body: SalesFixtures.ordersJson([SalesFixtures.agentOrder]))
        let o = try await api.orders.list()[0]
        XCTAssertEqual(o.status, "pending")
        XCTAssertEqual(o.amount, 145000.0)
        let line = o.items[0]
        XCTAssertEqual(line.name, "Mitre — Gold embroidered")
        XCTAssertEqual(line.sku, "MIT-GLD")
        XCTAssertEqual(line.effectiveQty, 1.0)
        // The agent's cart lines carry only `unit_price` (agent/tools.py); the
        // decoder normalises it into `unit` and `total`, so the line is priced.
        XCTAssertTrue(line.priceKnown)
        XCTAssertEqual(line.unit, 85000.0)
        XCTAssertEqual(line.total, 85000.0)
        XCTAssertEqual(o.items.reduce(0) { $0 + $1.total }, 145000.0) // lines add up to the order
    }

    func testCartSnapshotWithNoLinesDecodes() async throws {
        let snap = SalesFixtures.orders.first { $0.contains("\"id\":\"o5\"") }!
        fake.on("GET", "/admin/orders", body: SalesFixtures.ordersJson([snap]))
        let o = try await api.orders.list()[0]
        XCTAssertEqual(o.status, "pending") // "open" is shown as pending
        XCTAssertTrue(o.items.isEmpty)
        XCTAssertEqual(o.eventType, "cart")
    }

    func testDecimalsAsStringsAndMissingColumnsStillDecode() async throws {
        // pydantic v2 serialises Decimal as a STRING; an older API had no hub columns at all.
        fake.on("GET", "/admin/orders", body: """
            [{"id":"254700000001_1","wa_id":"254700000001",
            "items":[{"name":"Alb","qty":"2","unit":"3500.00","total":"7000.00"}],
            "subtotal":"7000.00","currency":"KES","status":"open","channel":"whatsapp",
            "created_at":"2026-03-14T09:30:00","hub_total":"7000.00"}]
            """)
        let o = try await api.orders.list()[0]
        XCTAssertEqual(o.subtotal, 7000.0)
        XCTAssertEqual(o.items[0].qty, 2.0)
        XCTAssertEqual(o.items[0].effectiveUnit, 3500.0)
        XCTAssertNil(o.hubOrderId)
        XCTAssertNil(o.updatedAt)
        XCTAssertNil(o.hubPushStatus)
        // A naive timestamp is read as UTC, as the server wrote it.
        XCTAssertEqual(Fmt.millis(o.createdAt), Fmt.millis("2026-03-14T09:30:00Z"))
    }

    func testNullablesSentAsExplicitNullDecode() async throws {
        fake.on("GET", "/admin/orders", body: """
            [{"id":"x","wa_id":"254700000001","session_id":null,"event_type":null,
            "items":[{"name":"Alb","qty":1,"unit":100,"total":100,"sku":null}],"subtotal":100.0,"currency":"KES","status":"pending",
            "payment_status":"unpaid","fulfillment_status":"pending","reply_text":null,"channel":"whatsapp","state":{},
            "created_at":"2026-03-14T09:30:00+00:00","updated_at":"2026-03-14T09:30:00+00:00","hub_order_id":null,
            "hub_total":null,"hub_status":null,"hub_public_token":null}]
            """)
        let o = try await api.orders.list()[0]
        XCTAssertNil(o.items[0].sku)
        XCTAssertNil(OrderUi.hubOrderHref(o))
        XCTAssertNil(OrderUi.hubMeta(o))
    }

    // ── GET /admin/orders/{id} ──────────────────────────────────────────────

    func testGetOneAndItsNotFound() async throws {
        fake.on("GET", "/admin/orders/[^/]+", body: SalesFixtures.failedOrder)
        let o = try await api.orders.get(id: "254722000111_1773480600000")
        XCTAssertEqual(fake.calls.last?.path, "/admin/orders/254722000111_1773480600000")
        XCTAssertEqual(o.hubPushStatus, "failed")
        XCTAssertEqual(o.hubLastError, "Variant CAS-PUR-L is out of stock in the hub (0 available)")

        fake.on("GET", "/admin/orders/[^/]+", code: 404, body: #"{"detail":"Order not found"}"#)
        let e = await expectApi { try await self.api.orders.get(id: "nope") }
        XCTAssertEqual(e?.status, 404)
        XCTAssertEqual(e?.detail, "Order not found")
    }

    // ── PATCH /admin/orders/{id} ────────────────────────────────────────────

    func testPatchSendsOnlyAllowedKeysAndDecodesTheNaiveUpdatedAt() async throws {
        let o = try await api.orders.updateStatus(id: "o2", status: "confirmed")
        let call = fake.callsTo("PATCH", "/admin/orders/o2")
        XCTAssertEqual(call.count, 1)
        XCTAssertEqual(json(call[0].body ?? ""), ["status": .string("confirmed")])
        XCTAssertEqual(o.status, "confirmed")
        // update_order returns the row with updated_at from datetime.utcnow(): no offset.
        let updated = o.updatedAt!
        XCTAssertTrue(!updated.hasSuffix("Z") && !updated.contains("+"), "naive: \(updated)")
        XCTAssertNotNil(Fmt.millis(updated))

        _ = try await api.orders.updateStatus(id: "o3", status: "delivered", paymentStatus: "paid", fulfillmentStatus: "fulfilled")
        XCTAssertEqual(json(fake.callsTo("PATCH", "/admin/orders/o3")[0].body ?? ""),
                       ["status": .string("delivered"), "payment_status": .string("paid"), "fulfillment_status": .string("fulfilled")])
    }

    func testPatchingAHubLinkedOrderOnlyChangesOurFlag() async throws {
        // update_order never touches hub_*: the row comes back with the hub's own state intact.
        fake.on("PATCH", "/admin/orders/[^/]+", body: SalesFixtures.linkedOrder.replacingOccurrences(of: "\"status\":\"confirmed\"", with: "\"status\":\"delivered\""))
        let o = try await api.orders.updateStatus(id: "254712345678_1773480600000", status: "delivered")
        XCTAssertEqual(o.status, "delivered")
        XCTAssertEqual(o.hubStatus, "processing")
        XCTAssertEqual(OrderUi.hubMeta(o)?.label, "Confirmed") // the list keeps reading hub truth
    }

    func testPatchNotFoundAndUnprocessableToastTheWebsCopy() async {
        let vm = await vm()
        fake.on("PATCH", "/admin/orders/.*", code: 404, body: #"{"detail":"Order not found"}"#)
        vm.updateStatus(id: "gone", status: "confirmed")
        await drain()
        XCTAssertEqual(lastToast()?.message, "This order no longer exists — it may have been deleted")
        // FastAPI's 422 for a non-object body is a pydantic LIST detail.
        fake.on("PATCH", "/admin/orders/.*", code: 422,
                body: #"{"detail":[{"type":"dict_type","loc":["body"],"msg":"Input should be a valid dictionary","input":"x"}]}"#)
        vm.updateStatus(id: "o1", status: "confirmed")
        await drain()
        XCTAssertEqual(lastToast()?.message, "Failed to update order — input should be a valid dictionary")
        XCTAssertNil(vm.ui.updating)
    }

    func testZambianOrderKeepsItsCurrency() async throws {
        let zmw = SalesFixtures.orders.first { $0.contains("\"id\":\"o6\"") }!
        fake.on("GET", "/admin/orders", body: SalesFixtures.ordersJson([zmw]))
        let o = try await api.orders.list()[0]
        XCTAssertEqual(o.currency, "ZMW")
        XCTAssertEqual(Fmt.currency(o.amount, o.currency), "ZMW 1,450")
        XCTAssertEqual(OrderUi.money(o.amount, o.currency), "ZMW 1,450")
        XCTAssertEqual(OrderUi.hubMeta(o)?.label, "Shipped")
    }

    /// The snapshot round-trips: what the feed writes at sign-in decodes to the same orders.
    func testOrdersSnapshotRoundTrips() async throws {
        let list = try await api.orders.list()
        let text = try NeemaJSON.encode(list)
        let back = try NeemaJSON.decode([Order].self, from: text)
        XCTAssertEqual(back, list)
        XCTAssertEqual(host.snapshots.read(Fixtures.ME_ID, OrdersFeed.SNAPSHOT_KEY) as [Order]?, orders)
    }
}

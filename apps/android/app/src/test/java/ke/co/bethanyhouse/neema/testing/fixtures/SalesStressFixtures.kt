package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema

/**
 * Round 8: a busy shop, for the Orders / Leads / Deals / Calls stress tests —
 * a thousand orders, five hundred leads across every column, a queue of two
 * hundred planned actions and a thousand-call log. Every row is built by the
 * same wire-true builders as [SalesFixtures] / [CallsFixtures], so the shapes
 * are what the handlers send; the values cycle deterministically (no
 * randomness), so a failing assertion is reproducible.
 */
object SalesStressFixtures {
    private val names = listOf(
        "Fr. Peter Kamau", "Rev. Mary Achieng", "Sr. Lucy Njeri", "Deacon James Mwangi", "Bishop Samuel Kariuki",
        "Canon Joseph Kiprono", "Mrs. Faith Chebet", "Dr. Samuel Mutua", "Mama 🌸 Njeri", "Bro. Kevin Ouma",
    )
    private val statuses = listOf("pending", "confirmed", "delivered", "cancelled")
    private val channels = listOf("whatsapp", "messenger", "instagram", "facebook", "email", "sms")

    fun orderId(i: Int) = "0a0b0c0d-0000-4000-8000-%012d".format(i)
    fun waId(i: Int) = "2547%08d".format(10_000_000 + i * 37)

    /** [n] orders, newest first, statuses cycling pending → confirmed → delivered → cancelled. */
    fun orders(n: Int = 1_000): List<String> = (0 until n).map { i ->
        SalesFixtures.order(
            id = orderId(i), waId = waId(i), status = statuses[i % statuses.size],
            subtotal = 1_000.0 + (i % 50) * 250.0, channel = channels[i % channels.size],
            createdAt = SalesFixtures.ago(5L + i * 7),
            items = listOf(
                SalesFixtures.legacyLine("Clergy Shirt — Black, ${14 + i % 6} inch", 1 + i % 3, 1_000 + (i % 50) * 250, "CS-$i"),
            ),
        )
    }

    /** Pure Kotlin sums of [orders]' figures, to check the screen's arithmetic against. */
    fun orderSubtotal(i: Int) = 1_000.0 + (i % 50) * 250.0
    fun orderStatus(i: Int) = statuses[i % statuses.size]

    val leadStages = listOf("new", "contacted", "qualified", "proposal", "negotiation", "measuring", "won", "lost")

    fun leadId(i: Int) = "u%04d".format(i)

    /** [n] leads spread over every canonical column plus the custom "Measuring", score-descending as `list_leads` sorts. */
    fun leads(n: Int = 500): List<String> = (0 until n).map { i ->
        val orders = i % 5
        SalesFixtures.lead(
            id = leadId(i), waId = waId(i), name = if (i % 11 == 0) null else names[i % names.size] + " $i",
            stage = leadStages[i % leadStages.size], score = 100 - (i * 100 / n),
            spent = if (orders == 0) 0.0 else 2_500.0 * orders, orders = orders,
            channels = channels.take(1 + i % 3), tags = listOf("parish", "t$i").take(1 + i % 2),
            seen = SalesFixtures.ago(3L + i),
        )
    }

    fun actionId(i: Int) = "x%04d".format(i)

    /** One row of GET /admin/actions: every third needs approval, the rest are scheduled. */
    fun actionRow(i: Int): String {
        val needs = i % 3 == 0
        return """{"id":"${actionId(i)}","deal_id":"d$i","conversation_id":"c$i","due_at":"${if (needs) SalesFixtures.ago(5) else SalesFixtures.inHours(1L + i % 40)}",
          "kind":"${if (i % 2 == 0) "follow_up" else "customer_promise"}","reason":"Follow up #$i: confirm the delivery date for the parish order",
          "draft":${if (i % 4 == 0) "null" else "\"Hello ${names[i % names.size]} 🙏 — checking in on order #$i.\""},
          "status":"${if (needs) "needs_approval" else "planned"}","created_by":"ai"}"""
    }

    /** crm.py `list_actions`' envelope around [rows]. */
    fun actionsJson(rows: List<String>) = rows.joinToString(",", """{"actions":[""", "]}")

    /** GET /admin/actions with [n] rows. */
    fun actions(n: Int = 200): String = actionsJson((0 until n).map(::actionRow))

    /** GET /admin/deals with [n] open deals over the three columns (and a stray stage that lands under New). */
    fun deals(n: Int = 60): String = (0 until n).joinToString(",", """{"deals":[""", "]}") { i ->
        val stage = listOf("new", "qualified", "proposal", "negotiation")[i % 4]
        """{"id":"d$i","conversation_id":"c$i","customer":"${names[i % names.size]}","wa_id":"${waId(i)}","channel":"whatsapp",
          "title":"Order #$i — clergy shirts","items":[],"stage":"$stage","blocking":${if (i % 3 == 0) "\"Waiting on the measurements\"" else "null"},
          "next_action":null,"guidance":null,"status":"open","updated_at":"${SalesFixtures.ago(10L + i)}"}"""
    }

    /** A [n]-row call log (the API caps at 200 today; the screen must not care). */
    fun calls(n: Int = 1_000): String = (0 until n).joinToString(",", "[", "]") { i ->
        val st = listOf("answered", "missed", "declined", "callback", "ended")[i % 5]
        CallsFixtures.row(
            id = "9c1d2e3f-4a5b-4c6d-8e7f-%012d".format(i), callId = CallsFixtures.wacid("U1RS%04d".format(i)),
            waId = if (i % 13 == 0) null else waId(i % 150), name = if (i % 7 == 0) null else names[i % names.size],
            direction = if (i % 9 == 0) "outbound" else "inbound", status = st,
            duration = if (st == "answered" || st == "ended") 30 + i % 400 else null,
            agentName = if (i % 3 == 0) "Moses Mwicigi" else null, startedAt = CallsFixtures.pyIso(3L + i * 11),
            summary = if (i % 6 == 0) "Asked about delivery #$i." else null, transcriptStatus = if (i % 6 == 0) "done" else "none",
            hasRecording = i % 6 == 0,
        )
    }

    /** Every route of the four screens, with the stress data. */
    fun install(f: FakeNeema, orders: Int = 1_000, leads: Int = 500, actions: Int = 200, calls: Int = 1_000) {
        SalesFixtures.install(f, orders(orders))
        f.on("GET", "/admin/leads", body = SalesFixtures.leadsJson(leads(leads)))
        f.on("GET", "/admin/actions", body = actions(actions))
        f.on("GET", "/admin/deals") { r, _ ->
            200 to (if (r.url.queryParameter("status") == "won") SalesFixtures.wonDeals else deals())
        }
        CallsFixtures.install(f)
        f.on("GET", "/admin/calls", body = calls(calls))
    }
}

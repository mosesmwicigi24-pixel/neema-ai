package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures.agentLine
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures.ago
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures.lead
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures.legacyLine
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures.mirrored
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures.order
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures.pushed

/**
 * Round 7's stress data for the sales screens: six- and seven-digit KES
 * figures (so totals must line up in tabular figures), long product titles,
 * Swahili and emoji text, and enough rows to fill a page / a kanban column.
 */
object SalesPolishFixtures {
    /** A cathedral's order: seven-figure total, long Swahili/emoji line names, a note. */
    val bigOrder = order(
        "254711222333_1773480600000", "254711222333", "confirmed", 1_284_750.0,
        items = listOf(
            legacyLine("Mavazi ya Kwaya — Choir robes, burgundy with gold trim, sizes S–XXL 🎶", 48, 18_500, "CR-BUR-GLD"),
            legacyLine("Cope & Mitre set — Festal white, hand-embroidered (Nyeri Cathedral) ✝️", 1, 385_000, "CMS-FW-HE"),
            legacyLine("Stole — Green", 3, 4_750),
            legacyLine("Usafirishaji — Delivery Nairobi → Kisumu 🚚", 1, 1_750),
        ),
        createdAt = SalesFixtures.FIXED_AT,
        hub = pushed(104_217, 1_284_750.0) + mirrored("processing", "partially_paid", "unfulfilled"),
        replyText = "Asante sana Askofu 🙏 Oda yako BH-104217 imethibitishwa — tutawasilisha Kisumu Ijumaa ijayo.",
    )

    /** The list's stress page: amounts from 3 to 7 digits, every channel and state. */
    val orders get() = listOf(
        bigOrder,
        order("p2", "254722000111", "pending", 245_000.0, channel = "messenger", createdAt = ago(20),
            items = listOf(legacyLine("Mitre — Gold embroidered, custom crest for the Diocese of Mount Kenya West", 1, 245_000))),
        order("p3", "255754333222", "delivered", 950.0, createdAt = ago(60 * 3),
            items = listOf(legacyLine("Roman Collar Tab", 1, 950))),
        order("p4", "254700999888", "cancelled", 99_999.0, channel = "instagram", createdAt = ago(60 * 30),
            items = listOf(agentLine("Alb — White, M", 3, 33_333.0))),
        order("p5", "260977123456", "pending", 12_450.5, currency = "ZMW", channel = "sms", createdAt = ago(60 * 48),
            items = listOf(agentLine("Rozari — Rosary beads 📿", 10, 1_245.05)),
            hub = pushed(1_050, 12_450.5) + mapOf("hub_currency" to "ZMW") + mirrored("shipped")),
        order("p6", "254733444555", "open", 3_500.0, channel = "email", createdAt = ago(60 * 5),
            items = emptyList(), eventType = "cart",
            hub = mapOf("hub_push_status" to "failed", "hub_last_error" to "Variant out of stock in hub")),
    ) + (7..40).map { i ->
        val st = listOf("open", "confirmed", "delivered", "cancelled")[i % 4]
        order("p$i", "2547${(10_000_000 + i * 7_919).toString().take(8)}", st, 1_000.0 * i * i, createdAt = ago(i * 53L))
    }

    /** Leads with long names, emoji, 6-digit spend, and a column 40 deep. */
    val leads get() = listOf(
        lead("L1", "254711222333", "Askofu Mkuu Emmanuel Wabukala Onyango-Kipchumba 🙏", "proposal", 92, spent = 1_284_750.0, orders = 14,
            channels = listOf("whatsapp", "facebook", "email"), tags = listOf("vip", "kanisa-kuu", "wholesale", "nyeri"),
            notes = "Anapendelea uwasilishaji Ijumaa. Prefers Friday deliveries; invoice to the diocese office.",
            email = "askofu.mkuu@dayosisi-ya-mlima-kenya-magharibi.or.ke", location = "Nyeri — Mlima Kenya Magharibi"),
        lead("L2", "254722000111", "Rev. Mary Achieng", "qualified", 55, spent = 245_000.0, orders = 2, channels = listOf("messenger")),
        lead("L3", "255754333222", null, "new", 12),
        lead("L4", "17840000000000001", "Sr. Lucy Njeri ✨", "contacted", 38, channels = listOf("instagram"), tags = listOf("convent"), phone = null),
        lead("L5", "254799111222", "Bishop Samuel Kariuki", "won", 97, spent = 745_500.0, orders = 6, tags = listOf("vip")),
    ) + (6..45).map { i ->
        lead("L$i", "2547${(20_000_000 + i * 7_919).toString().take(8)}", "Parokia ya Mt. ${listOf("Yosefu", "Maria", "Petro", "Paulo")[i % 4]} #$i",
            "new", (i * 7) % 100, spent = 1_500.0 * i, orders = 1, seen = ago(i * 41L))
    }

    fun install(f: FakeNeema) {
        SalesFixtures.install(f, orders)
        f.on("GET", "/admin/leads", body = SalesFixtures.leadsJson(leads))
    }
}

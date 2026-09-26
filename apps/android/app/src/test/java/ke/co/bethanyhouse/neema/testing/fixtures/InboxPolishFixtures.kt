package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.Fixtures.ago
import ke.co.bethanyhouse.neema.testing.Fixtures.conv

/**
 * Round 7 (UX polish): the inbox at its most demanding — 44 rows with long
 * names, every channel, Swahili + emoji previews, 6-digit shillings — and a
 * thread whose bubbles carry long unbroken URLs, a very long word, Swahili
 * with emoji, a note and a translation. Shapes are the base [Fixtures.conv] /
 * admin.py thread rows.
 */
object InboxPolishFixtures {
    private val names = listOf(
        "Very Rev. Fr. Bartholomew Oluwaseun Mwakilema-Ndirangu", "Sr. Mary Immaculata Wanjiku wa Kamau", null,
        "Rt. Rev. Bishop Emmanuel Kiprotich arap Chelimo", "Mama Neema 🌸", "Deacon Josephat Otieno Owino",
        "St. Theresa's Parish — Kitengela Procurement Office", "Br. Anthony", "Rev. Canon Dr. Wilfred Kiplagat Ruto",
    )
    private val previews = listOf(
        "Habari za asubuhi! 🙏 Nataka kununua kanzu tatu nyeupe na stoles mbili za zambarau kwa ajili ya Pasaka 🌿✨",
        "Total ni KES 128,500 — nitalipa kupitia M-Pesa leo jioni 💸",
        "📷 Photo",
        "https://www.bethanyhouse.co.ke/products/clergy-shirts/black-tab-collar-long-sleeve?size=16&colour=black",
        "Asante sana! 😍😍😍",
        "Can you deliver 40 albs to Eldoret before the ordination on Saturday? The bishop needs them.",
    )
    private val channels = listOf("whatsapp", "messenger", "facebook", "instagram", "whatsapp", "whatsapp")
    private val modes = listOf("ai", "human", "ai", "paused", "ai", "human")
    private val stages = listOf("qualified", null, "negotiation", "won", "contacted", "lost", null)
    private val countries = listOf("KE", "TZ", "UG", "RW", "KE", "SS", "CD")

    /** 44 rows, newest first; the first is the long-content thread `lp1` (held by me). */
    val longList: List<String> get() = (0 until 44).map { i ->
        conv(
            id = "lp${i + 1}", name = names[i % names.size], waId = "2547${(10_000_000 + i * 7919).toString().padStart(8, '0')}",
            channel = channels[i % channels.size], mode = if (i == 0) "human" else modes[i % modes.size],
            preview = previews[i % previews.size], minutes = 1L + i * 37L,
            unread = if (i % 3 == 0) (i % 5) + 1 else 0, stage = stages[i % stages.size],
            orders = if (i % 4 == 0) 3 + i * 7 else 0, person = null,
            agent = if (i == 0) Fixtures.ME_ID else if (modes[i % modes.size] == "human") Fixtures.AGENT2_ID else null,
            iso = countries[i % countries.size],
        )
    }

    /** The long-content thread: unbroken URLs, a very long word, Swahili + emoji, big shillings. */
    val longThread get() = """[
      {"id":"l1","type":"message","direction":"inbound","sender":"user","text":"Habari za asubuhi Padre! 🙏🌿 Nataka kununua kanzu tatu nyeupe (size XL) na stoles mbili za zambarau kwa ajili ya Pasaka. Je, mnaweza kuzituma Kisumu kabla ya Ijumaa Kuu? ✨⛪","created_at":"${ago(90)}","translation":"Good morning Father! I want to buy three white cassocks (size XL) and two purple stoles for Easter. Can you send them to Kisumu before Good Friday?","translated_from":"sw"},
      {"id":"l2","type":"message","direction":"outbound","sender":"ai","text":"Karibu sana! 😊 Kanzu nyeupe ni KES 12,500 kila moja na stole ya zambarau ni KES 4,800. Jumla: KES 47,100. Tunatuma Kisumu kwa siku 2 🚚","created_at":"${ago(88)}"},
      {"id":"l3","type":"message","direction":"inbound","sender":"user","text":"https://www.bethanyhouse.co.ke/products/vestments/cassocks/white-polyester-cassock-with-cincture-and-matching-buttons?size=XL&colour=white&utm_source=whatsapp&utm_campaign=easter2026","created_at":"${ago(60)}"},
      {"id":"l4","type":"message","direction":"outbound","sender":"human_agent","agent_name":"Moses Mwicigi","text":"Order reference: BH-ORD-2026-000184-KISUMU-EASTER-VESTMENTS-PRIORITYDELIVERYCONFIRMEDANDPAIDINFULLVIAMPESA — total KES 128,500.00 for the whole parish 🙏","created_at":"${ago(40)}"},
      {"id":"l5","type":"message","direction":"outbound","sender":"human_agent","agent_name":"Moses Mwicigi","isNote":true,"text":"Parish procurement — invoice to St. Theresa's, Kitengela. Paybill 247247, acc 0712345678 😊","created_at":"${ago(30)}"},
      {"id":"l6","type":"message","direction":"inbound","sender":"user","text":"Sawa! 👍🏾👍🏾 Nimelipa sasa hivi.","created_at":"${ago(5)}","reply_to":{"id":"l4","text":"Order reference: BH-ORD-2026-000184-KISUMU-EASTER-VESTMENTS — total KES 128,500.00","sender":"human_agent"}},
      {"id":"l7","type":"message","direction":"inbound","sender":"user","text":"👍","created_at":"${ago(1)}"}
    ]"""

    fun install(f: FakeNeema) {
        val page = """{"items":[${longList.joinToString(",")}],"next_cursor":null}"""
        f.on("GET", "/admin/conversations") { r, _ ->
            200 to if (r.url.queryParameter("cursor") != null) """{"items":[],"next_cursor":null}""" else page
        }
        f.on("GET", "/admin/conversations/[^/]+") { r, _ ->
            val id = r.url.pathSegments.last()
            200 to (longList.firstOrNull { it.contains("\"id\":\"$id\"") } ?: longList.first())
        }
        f.on("GET", "/admin/conversations/summary", body = """{"unread":15,"human":14,"yours":1,"unread_messages":{"all":1284,"whatsapp":1200,"messenger":48,"facebook":20,"instagram":16},"tags":[]}""")
        f.on("GET", "/admin/conversations/[^/]+/messages", body = longThread)
    }
}

package ke.co.bethanyhouse.neema.calls

import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.feature.calls.avatarIndex
import ke.co.bethanyhouse.neema.feature.calls.initialsOf
import ke.co.bethanyhouse.neema.feature.calls.rowWho
import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The call log's avatar maths against values computed with the web's own
 * expressions in Node (CallsView.tsx `avatarColor`, the initials line, `who`).
 */
class CallsParityTest {
    @Test fun avatarColourIndexMatchesTheWeb() {
        // node: [...(s||"?")].reduce((a,c)=>a+c.charCodeAt(0),0) % 6
        assertEquals(5, avatarIndex("Fr. Peter Kamau"))
        assertEquals(1, avatarIndex("+254712345678"))
        assertEquals(2, avatarIndex("Unknown"))
        assertEquals("an emoji counts its first UTF-16 unit once", 0, avatarIndex("Mama 🌸 Njeri"))
        assertEquals("empty hashes as \"?\"", 3, avatarIndex(""))
    }

    @Test fun initialsMatchTheWeb() {
        assertEquals("FP", initialsOf("Fr. Peter Kamau"))
        assertEquals("a bare number: its first digit", "2", initialsOf("+254712345678"))
        assertEquals("only the first + goes", "AC", initialsOf("a+b c"))
        assertEquals("U", initialsOf("Unknown"))
        assertEquals("the whole emoji, not half of it", "M🌸", initialsOf("Mama 🌸 Njeri"))
        assertEquals("", initialsOf("  "))
    }

    @Test fun whoFallsBackLikeTheWeb() {
        fun call(name: String?, wa: String?) = Call(callId = "x", name = name, waId = wa)
        assertEquals("Fr. Peter Kamau", rowWho(call("Fr. Peter Kamau", "254712345678")))
        assertEquals("+254712345678", rowWho(call(null, "254712345678")))
        assertEquals("+254712345678", rowWho(call("", "254712345678")))
        assertEquals("Unknown", rowWho(call(null, null)))
        assertEquals("Unknown", rowWho(call(null, "")))
    }
}

# C. Findings by risk

Each finding names the rule IDs it rests on (see `A_RULE_INVENTORY.md`). "Checked" means the lead auditor re-read the code after the reader reported it. "Reported" means one reader established it by reading the code and it has not been re-read.

## Critical

| # | Finding | Example of what can reach a customer | Evidence | Confidence |
|---|---|---|---|---|
| C1 | **Messages Neema starts are not checked like her replies.** The reply gate runs only when the turn is not read-only; every follow-up, cart nudge, check-in, hub announcement, cross-channel answer and staff draft is composed read-only. They get two rules only (payment acknowledged, order status). No price, item, link or language rule. | A follow-up quoting a price the hub no longer has, or a wrong payment link. | `agent/runtime.py:2701`; `agent/review.py:974 initiated_issues`; `services/actions.py:525` | Checked |
| C2 | **"Team answer through Neema" sends model text with no check.** A colleague's note is rewritten by the model and sent at once: no gate, no opt-out check, no human-mode check, no guard against a double click. | Two different messages from one click; a figure the colleague never typed. | `routers/admin.py:1838-1899` | Checked |
| C3 | **A discount can be quoted without being granted.** The search hands the model the offer price before `apply_offer` runs, and that figure passes the price check. The grant is what puts the discount on the order. | Quoted the offer price, charged the list price. | `agent/tools.py:913-930, 1706` | Checked (mechanism); the customer-facing outcome is not reproduced |
| C4 | **Refund, remake, replacement and resolution promises have no check.** The complaint note even records "Neema has NOT promised any refund" without looking at what she said. | "We will refund you today." | NR rules under FIN-03; `agent/tools.py:2651` | Reported by three readers |
| C5 | **A discount in words passes.** Only money figures are read. | "I can take 10% off for you." | FIN-02 | Reported |
| C6 | **Payment numbers and account details in a reply are not read.** Prices and web links are verified; phone, till and account digits are not. This includes the official-numbers line added on 2026-11-20. | A transposed digit in a pay-to number. | FIN-05 | Reported by two readers |
| C7 | **An order can be created without a recorded yes.** `create_order` checks the cart, phone and unpriced pieces, not consent. Removing an item already needs the customer's quoted words; ordering does not. | An order pushed to the hub and the cart cleared on Neema's own reading. | ORD-01 | Reported by three readers |
| C8 | **A failed order can still be described as placed.** The failure text goes back to the model; nothing checks the reply. | "Your order is placed" after an error. | ORD-02 | Reported |
| C9 | **"Pay on delivery" has no check.** | Agreeing to deliver first. | FIN-04 | Reported by two readers |
| C10 | **A complaint alerts nobody.** `raise_complaint` writes one activity row: no bell, no tracked commitment, chat stays with Neema, who then says a colleague is on it. | A complaint nobody was told about. | ACT-02 | Reported by two readers |
| C11 | **A near-match product's price counts as verified.** A row marked "partial" is still remembered as a seen product, so its price passes the price check. | The wrong item priced with confidence. | PRD-02; `agent/tools.py:1099-1102` | Checked (the row is remembered); the gate effect is reported |

## High

| # | Finding | Evidence | Confidence |
|---|---|---|---|
| H1 | A second "stop" is not marked as silenced; the missed-reply sweep can then answer it, bypassing the opt-out and "speak to a person" doors. | `agent/runtime.py:3259`; `services/reply_sweeper.py:483` | Checked (first half) |
| H2 | Product cards and photos are sent inside the turn, before the reply is checked. They stay delivered when the reply is held. | `agent/tools.py:3094, 3170` | Reported |
| H3 | Automatic templates can go to a chat a colleague holds: the approval check returns before reading human mode. | `services/actions.py:238-245` | Reported |
| H4 | The rewrite note tells Neema to "say so plainly" when we lack an item; her instructions say never to say that. A correction can introduce the banned sentence. | `agent/review.py:1852` | Checked |
| H5 | Promises to act have no proof: "let me confirm with the team", "I'll check in on Friday", "I have raised it again", "I've sent you a private message" can be said with no tool call. | ACT-01, ACT-03 | Reported by three readers |
| H6 | Delivery dates and production times are judged only by the model reviewer. | FUL-01 | Reported |
| H7 | The repair rule of 2026-11-19 (our items only, 14 days, never "for life") has no code: no purchase or date look-up. | FUL-02 | Reported |
| H8 | A stale price passes: any figure already said in the chat counts as verified. | `agent/review.py transcript_figures` | Reported |
| H9 | The price check reads only numbers written with a currency; a bare "4,200", "free" and "KES 0" are not read. | FIN-01 | Reported |
| H10 | Neema can pause a complaint or open-order chat into two hours of silence; the pause lifts only on buying words. | SAL-03; `_pause_conversation` | Reported |
| H11 | A check-in can be scheduled on Neema's own initiative; the tool checks only the day and the reason. | ACT-03 | Reported |
| H12 | The unclaimed-chat answer runs a full turn with ordering tools in a chat a colleague owns. | `services/unclaimed.py:127` | Reported |
| H13 | Staff one-tap sends: approving a held draft sends the text the gate refused, with no double-send guard. | `services/conversation.py:780` | Reported |
| H14 | Bold and heading marks are stripped only on Messenger, Instagram, TikTok and public comments; not on WhatsApp or the website chat. | `services/meta_send.py:628` | Reported |
| H15 | The language check is one-directional and private-chat only. | `agent/review.py:1473` | Reported |
| H16 | Text typed by staff enters Neema's instructions unchecked: standing orders, approved learned rules, house voice, deal guidance. Any link typed there becomes sendable. | `services/app_settings.py`; `routers/crm.py:1455` | Reported |
| H17 | Outreach control defaults to "shadow": the daily cap and "customer replied" rules only log unless switched to enforce. The live value was not verified. | `core/config.py:214` | Reported |
| H18 | Seasonal outreach bypasses the dispatcher and its caps. | `jobs/seasonal_outreach.py:239` | Reported |

## Medium

- Measurements are stored as one list per person; a second wearer's sizes overwrite the first.
- The card cap is 6 in code against "2–3" in the instructions.
- The KES 350 delivery fee is spoken but is not a line on the order, so the spoken total and the link total differ.
- `status_without_source` is satisfied by the status tool having run, even when it returned nothing live.
- "I've removed it" with no cart change is soft: sent after one rewrite.
- Cart-recovery's "no discount, no links" wording exists only in the preview brief.
- Our own fixed lines break the tone rules (the fallback welcome says "so glad" with two emoji).
- Web chat and the ManyChat relay reply when the takeover state cannot be read; the live turn does not.

## Low

The 343 low-risk rules are style and phrasing preferences. They are counted by policy in `B_UNENFORCED_RULES.md`.

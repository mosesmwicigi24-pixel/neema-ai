# E. Conflict register

Recommended precedence when two rules pull apart: **truth → authorisation → company policy → what the customer asked → conversational quality.** Where the resolution is a company decision it is marked "decision" and repeated in `H_DECISIONS.md`.

| # | Conflict | Where | Recommended resolution | Kind |
|---|---|---|---|---|
| X1 | "Never say an item is unavailable" against "never invent availability" and the rewrite note "if we do not have the exact item, say so plainly". | `prompt.py:1849-1869` vs `review.py:1852`, `review.py:1714`, `runtime.py:142` | One wording everywhere: never claim we have it unconfirmed; never say "out of stock"; say what we can make or the nearest item, and that a colleague is confirming. Change the three correction texts to match. | Fix |
| X2 | "Never explain how ordering works" against "answer 'How can I order?' with how ordering works". | `prompt.py:1751-1755` vs `1661-1664` | An explicit ordering question is answered in one or two lines. The ban applies to unprompted explanations. | Fix |
| X3 | "Never repeat yourself" against a confirmed order summary and "a repeated 'how much?' means they felt unanswered". | `prompt.py:1756` vs `448`, `801` | The order summary before payment and a re-asked price are stated exceptions. | Fix |
| X4 | "No discount on her own authority" against the objection ladder and the held offer. | `prompt.py:978`, `1173` vs `1171-1196`; `tools.py:175-183` vs `922-926` | A discount is spoken only after the offer is granted and recorded. The two tool texts disagree on whether a quiet customer earns it. | Decision |
| X5 | "Keep replies short" against complex needs (multi-piece orders, parish orders in writing). | `prompt.py:1586` vs `1441`, `1533` | The length target is by kind of ask; an order for several people is allowed its length. | Fix |
| X6 | "Colours are never limited" against the reviewer failing "comes in any colour" and the rewrite text "say plainly we do not make it". | `prompt.py:1337-1340`, `747` vs `review.py:1746`, `501` | Sewn garments: any colour. Stock items: the hub's colours. Make the reviewer and rewrite text follow that split. | Fix |
| X7 | "Add up every piece of a set" against the price check, which accepts sums of two rows only. | `prompt.py:824-827` vs `review.py:330-334` | Let the check accept the sum of the rows named in the reply. | Fix |
| X8 | "Thank them for a shown payment" against the hard rule that holds "thank you for your payment". | `prompt.py:88-89` vs `review.paid_ack` | Thank them for sending the proof; confirm receipt only from the record. | Fix |
| X9 | "Never call it today's rate" against the gate's own rewrite text. | `prompt.py:359-360` vs `review.py:1889`, `1923` | Use "our rate" in the rewrite text. | Fix |
| X10 | Mukuru named only for some markets against the order step and the payment rewrite text, which always name it. | `prompt.py:408-414` vs `tools.py:1853`, `review.py:1533` | Follow the market rule in both texts. | Fix |
| X11 | "Frame distance as reach, never 'no branch'" against rewrite strings that say "no shop there". | `prompt.py:1015`, `475` vs `review.py:1460`, `1850`, `1892` | Change the rewrite strings. | Fix |
| X12 | "Say nothing when nothing is needed" against the turn putting words in an empty reply. | `prompt.py:1241-1245` vs `runtime.py:2640-2654` | Keep the stock line only when the customer asked something. | Fix |
| X13 | A second "I'll get back to you" gets one line against the closer gate, which silences it. | `prompt.py:1194-1196` vs `closer_gate` | Silence is the safer behaviour; change the instruction. | Decision |
| X14 | "Check in the day before their deadline" and "ask when they will next need supplies" against "check in only when they name a time" and "never ask when to remind them". | `prompt.py:1008`, `1156` vs `1100-1104` | A check-in needs a time the customer named. | Decision |
| X15 | "No exception after 14 days" against "never 'no', a colleague will confirm" and product text "alterations typically 1–3 days". | `prompt.py:1383-1385` vs `1372-1374`, `seeds.py:451` | The 14-day rule is said plainly; a fault on arrival is a complaint. | Decision |
| X16 | "One question per reply" against the instructions' own two-question examples. | `prompt.py:583-587` vs `851`, `865` | Fix the examples. | Fix |
| X17 | "2–3 matches" against "three to six lines" for a range. | `prompt.py:798-800` vs `913-927` | A named need: 2–3. A range asked for: up to six, cheapest first. | Fix |
| X18 | "Never ask which item" on a photo against "do not guess, ask". | `prompt.py:855` vs `892` | Ask only when the photo is not unmistakable. | Fix |
| X19 | "Do not suggest a substitute" against "offer the two closest". | `prompt.py:892-894` vs `699`, `809`, `960` | Offer the closest only after saying it is not the item asked for. | Fix |
| X20 | The offer is "applied by a person before payment" in the instructions; the code applies it at order time. | `prompt.py:317-321` vs `tools.py:1706` | Update the instruction. | Fix |
| X21 | The comment instructions say "say you have sent photos to their inbox"; no photo step exists on that path. | `runtime.py` comment addendum | Remove the sentence or build the step. | Fix |
| X22 | Our fixed lines break tone rules ("so glad", two emoji, re-welcome). | `runtime.py:2910-2932` vs `prompt.py:1643`, `1844`, `1678` | Rewrite the fixed lines to the rules. | Fix |

## Every conflict found, with sources

| ID | Source | Rule | Conflicts with | Risk |
|---|---|---|---|---|
| NR-0003 | `agent/prompt.py:82-87` | A Kenyan customer is offered only the M-Pesa link, our M-Pesa/Airtel lines and bank — never Western Union/MoneyGram/Mukuru. | apps/api/app/agent/review.py:1533-1538 | medium |
| NR-0005 | `agent/prompt.py:88-89` | On a shown payment to our line: thank, note the code, say the team will match it — without confirming receipt. | apps/api/app/agent/review.py:807-812,1487-1491 | high |
| NR-0011 | `agent/prompt.py:160-162` | When the country is unknown, never ask where the customer is; sell first. | apps/api/app/agent/prompt.py:475-481 (tells her to say 'Tell me your city') | medium |
| NR-0019 | `agent/prompt.py:179-180` | The city is asked once, only when delivery is being settled, never as an opener. | apps/api/app/agent/prompt.py:475-481 | low |
| NR-0020 | `agent/prompt.py:188-190` | Use the church calendar to advise season colour and ask once about an approaching season. | apps/api/app/agent/prompt.py:198-199 | low |
| NR-0024 | `agent/prompt.py:198-199` | Do not volunteer a season's colour unless asked for liturgical colour advice. | apps/api/app/agent/prompt.py:188-190 | low |
| NR-0031 | `agent/prompt.py:236-237` | After a failed create_order, tell the customer a colleague has the order and will confirm it. | apps/api/app/agent/tools.py:1578-1624 (next_step texts) | high |
| NR-0050 | `agent/prompt.py:317-321` | If the total looks like the old price, say the team is applying the offer before payment. | apps/api/app/agent/tools.py:1706-1708 | high |
| NR-0057 | `agent/prompt.py:357-359` | A converted figure is the exact arithmetic result to the whole unit, never tidied. | apps/api/app/agent/review.py:258-263 | low |
| NR-0058 | `agent/prompt.py:359-360` | Never describe the house conversion rate as today's rate or approximate. | apps/api/app/agent/review.py:1889-1890,1923; apps/api/app/services/fx.py:253-259 | medium |
| NR-0082 | `agent/prompt.py:421-423` | Name only the rails usable from the customer's country (Mukuru only in its send markets). | apps/api/app/agent/tools.py:1853-1857; apps/api/app/agent/review.py:1533-1538 | medium |
| NR-0092 | `agent/prompt.py:459-463` | A Kenyan asking where we are gets the shop address and hours plainly, with no worldwide pitch and no city question. | apps/api/app/agent/review.py:1460-1463,1850-1851,1892-1893 | medium |
| NR-0097 | `agent/prompt.py:475-481` | When asked about a local shop, lead with warmth and reach, not with the absence of a branch, then invite their city. | apps/api/app/agent/review.py:1462-1463,1850-1851,1892-1893; apps/api/app/agent/prompt.py:160-162,179-180 | low |
| NR-0114 | `agent/prompt.py:532-535` | A new conversation opens with the greeting matching Nairobi's time of day. | apps/api/app/agent/runtime.py:170 (comment channel: "never 'Good morning' under a comment") | low |
| NR-0120 | `agent/prompt.py:546-550` | An opener that names an item gets greeting, affirmation, thanks, the hub price, then the first open detail. | apps/api/app/agent/prompt.py:551-552 (example omits the price the rule requires) | low |
| NR-0132 | `agent/prompt.py:583-587` | At most one question per reply; no either/or tail. | apps/api/app/agent/prompt.py:851-852; apps/api/app/agent/prompt.py:865-866 | medium |
| NR-0133 | `agent/prompt.py:587-591` | One ask per reply; further details wait for the next turn. | apps/api/app/agent/prompt.py:851-852 | low |
| NR-0141 | `agent/prompt.py:614-615` | No quote without a hub row; ambiguity is resolved by one question before quoting. | apps/api/app/agent/prompt.py:662-666 (ambiguity: quote BOTH, do not ask) | high |
| NR-0150 | `agent/prompt.py:650-651` | A product photo is answered with that item's price first. | apps/api/app/agent/runtime.py:2758-2767 (live photo check: a referred photo is never priced) | medium |
| NR-0152 | `agent/prompt.py:653-655` | One add-on suggestion, only after the piece is settled. | apps/api/app/agent/runtime.py:2768-2787 (cassock ladder adds two sets right after the first price) | low |
| NR-0155 | `agent/prompt.py:662-666` | Two honest readings are both quoted with prices. | apps/api/app/agent/prompt.py:614-615; apps/api/app/agent/prompt.py:892-894 | medium |
| NR-0169 | `agent/prompt.py:699-700` | An unplaceable word gets a clarifying question or the two closest hub items. | apps/api/app/agent/prompt.py:892-894 (don't suggest a substitute — ask) | low |
| NR-0178 | `agent/prompt.py:727-728` | Uncertainty is resolved by one focused question. | apps/api/app/agent/prompt.py:662-666; apps/api/app/agent/prompt.py:875-878 (quote BOTH instead of asking) | low |
| NR-0180 | `agent/prompt.py:730` | Neema never says an item is unavailable. | apps/api/app/agent/review.py:442-450 (a 'we don't have' phrase passes the item rule) | medium |
| NR-0186 | `agent/prompt.py:747-748` | Any colour may be promised for a sewn garment. | apps/api/app/agent/review.py:1746-1749 | medium |
| NR-0206 | `agent/prompt.py:798-800` | At most 2–3 matches; never a whole category with prices. | apps/api/app/agent/prompt.py:913-927 | medium |
| NR-0211 | `agent/prompt.py:809-810` | With nothing confirmed, no single quote: two closest with prices, or a question. | apps/api/app/agent/prompt.py:892-894 (don't suggest a substitute — ask) | medium |
| NR-0215 | `agent/prompt.py:824-827` | With no set row, every piece is searched and totalled by the model. | apps/api/app/agent/review.py:330-334 | high |
| NR-0222 | `agent/prompt.py:845-850` | 'Do you make this for…?' is answered yes first. | apps/api/app/agent/review.py:1746-1749 | low |
| NR-0224 | `agent/prompt.py:855-856` | A photo with 'how much?' is never answered with 'which item?'. | apps/api/app/agent/prompt.py:892-894; apps/api/app/agent/runtime.py:2758-2767 | medium |
| NR-0227 | `agent/prompt.py:861-866` | A second item plainly in the photo is priced and offered as the add-on. | apps/api/app/agent/prompt.py:583-587 | low |
| NR-0230 | `agent/prompt.py:875-878` | When the photo could be two products, both are quoted. | apps/api/app/agent/prompt.py:892-894 | medium |
| NR-0235 | `agent/prompt.py:892-894` | Unclear image or word: no guess, no substitute — ask. | apps/api/app/agent/prompt.py:809-810; apps/api/app/agent/prompt.py:960-962; apps/api/app/agent/prompt.py:855-856 | medium |
| NR-0246 | `agent/prompt.py:927-928` | Range answers are three to six lines. | apps/api/app/agent/prompt.py:798-800 | low |
| NR-0248 | `agent/prompt.py:930-931` | Every communion tray is sold as including 40 free plastic cups. | apps/api/app/agent/prompt.py:710-713 | high |
| NR-0256 | `agent/prompt.py:952-954` | The silver tray is described as more elegant, durable and easier to maintain. | apps/api/app/agent/prompt.py:732-734 | low |
| NR-0260 | `agent/prompt.py:960-962` | An unopenable link: ask the name once and offer the two closest items. | apps/api/app/agent/prompt.py:892-894 | medium |
| NR-0263 | `agent/prompt.py:969-971` | Hurried customers get one line, no upsell, price in text first. | apps/api/app/agent/runtime.py:2768-2787 (cassock ladder appends two sets after a cassock price regardless of pace) | medium |
| NR-0268 | `agent/prompt.py:983-986` | A complaint is never answered with a product, a price, an emoji or scripture. | apps/api/app/agent/runtime.py:1628-1638 (hold lines contain an emoji) | high |
| NR-0272 | `agent/prompt.py:996-998` | Nothing extra is offered until the stated want is settled. | apps/api/app/agent/runtime.py:2768-2787 | low |
| NR-0277 | `agent/prompt.py:1006-1007` | On a deadline the order and payment must be asked for in the same reply. | apps/api/app/agent/prompt.py:1036-1037 (never pressure) — tension, not a direct contradiction | medium |
| NR-0278 | `agent/prompt.py:1008` | Neema books a check-in for the day before the customer's deadline on her own initiative. | apps/api/app/agent/prompt.py:1100-1105 ('A check-in is booked ONLY when THEY name a time') | medium |
| NR-0281 | `agent/prompt.py:1015-1019` | A reply about the customer's city/country must not lead with the absence of a branch/shop there. | apps/api/app/agent/review.py:1460-1463, 1850-1851, 1892 | medium |
| NR-0292 | `agent/prompt.py:1038-1041` | An unopenable attachment gets a reply: say it can't be opened and ask for words or a photo. | apps/api/app/agent/cooling.py:541-543 (is_silent_ack '[sticker]'); services/inbound_kinds.py _NO_WAKE_KINDS | low |
| NR-0311 | `agent/prompt.py:1100-1103` | Neema never asks the customer when to follow up or whether to remind them. | apps/api/app/agent/prompt.py:1156-1158 (SCHEDULE THE NEXT NEED asks 'a week? two?') | medium |
| NR-0316 | `agent/prompt.py:1113-1117` | A firm decline gets one line: no question, no alternative offer, no check-back date. | apps/api/app/services/declines.py:6-9 docstring ('gets Neema's in-turn answer (a cheaper option, paying little by little)') vs prompt 'no alternative offered' | high |
| NR-0323 | `agent/prompt.py:1128-1131` | The 'all sizes/colours same price' claim is never sent. | apps/api/app/seeds.py:448 seed description 'Same price across sizes' (if hub descriptions carry it, GROUNDED DETAILS tells Neema to quote it) | high |
| NR-0330 | `agent/prompt.py:1156-1157` | Neema asks the customer when they will next need supplies. | apps/api/app/agent/prompt.py:1100-1102 ('NEVER ask when to remind them') | medium |
| NR-0348 | `agent/prompt.py:1194-1196` | A bare or second deferral gets exactly one acknowledging line. | apps/api/app/agent/runtime.py:698-707; apps/api/app/agent/prompt.py:1190-1192 | low |
| NR-0365 | `agent/prompt.py:1241-1245` | Neema may return an empty reply when nothing is needed and nothing is pending. | apps/api/app/agent/runtime.py:2640-2654 | medium |
| NR-0376 | `agent/prompt.py:1284-1289` | A repeated appeal gets one brief line, then no further replies to that request. | apps/api/app/services/buyer_intent.py FIRST_NOTE ('Do not call pause_conversation'); apps/api/app/agent/prompt.py:1293-1294 | medium |
| NR-0391 | `agent/prompt.py:1330-1333` | Discovery runs colour → gender → base → single/set → quantities; never open with 'how many?'. | apps/api/app/agent/review.py:1909-1910 (mild) | low |
| NR-0392 | `agent/prompt.py:1337-1340` | Neema never says a colour is unavailable and may say any colour is possible. | apps/api/app/agent/review.py:1746-1749, 498-502, 1896-1897 | high |
| NR-0405 | `agent/prompt.py:1372` | No binding admission of liability. | apps/api/app/agent/prompt.py:1352-1353 (mild tension) | medium |
| NR-0406 | `agent/prompt.py:1372-1374` | Refund/discount/remake asks are deferred to a colleague, neither refused nor promised. | apps/api/app/agent/review.py:1895 (rewrite_block), 1182-1192 (promise_only, soft) | medium |
| NR-0407 | `agent/prompt.py:1375-1376` | No selling during a complaint. | apps/api/app/services/cassock_ladder.py:applies/follow_up | medium |
| NR-0410 | `agent/prompt.py:1383-1385` | After 14 days no repair is accepted and no exception or colleague review is suggested. | apps/api/app/agent/prompt.py:1372-1374; apps/api/app/seeds.py:451 | high |
| NR-0445 | `agent/prompt.py:1470-1475` | After a contact is given, reply with thanks, a colleague-will-call line and both official numbers exactly. | apps/api/app/agent/prompt.py:1629-1635 (a promise such as 'a colleague will reach out' is named as the failure that caused takeovers) | high |
| NR-0453 | `agent/prompt.py:1499-1500` | No more than 2–3 cards at once. | apps/api/app/agent/tools.py:_send_product_cards cap of 6 | low |
| NR-0473 | `agent/prompt.py:1549` | Never state unavailability. | apps/api/app/agent/review.py:1714,1852; apps/api/app/agent/runtime.py:142 | medium |
| NR-0493 | `agent/prompt.py:1603-1606` | Use 'Thank you', not 'Thanks!'; state facts without celebration. | apps/api/app/routers/web_chat.py:250 | low |
| NR-0498 | `agent/prompt.py:1614-1615` | No markdown; one *bold* allowed on WhatsApp only. | apps/api/app/agent/prompt.py:1846-1848 (also allows _italics_ on WhatsApp); apps/api/app/agent/tools.py:3413 prepare_quotation emits two *bold* runs on WhatsApp | medium |
| NR-0507 | `agent/prompt.py:1643-1645` | No gushing adjectives and no exclamation marks. | apps/api/app/agent/prompt.py:1674; apps/api/app/agent/runtime.py:2932 | medium |
| NR-0513 | `agent/prompt.py:1658-1660` | Never ask 'how may I help' after an ask; never say 'we don't have it'. | apps/api/app/agent/review.py:1714,1852 | medium |
| NR-0515 | `agent/prompt.py:1662-1664` | An ordering question is answered with how ordering works for them. | apps/api/app/agent/prompt.py:1751-1755 (NEVER EXPLAIN HOW ORDERING WORKS … gets the first question, not the manual) | medium |
| NR-0516 | `agent/prompt.py:1667-1671` | First-ever contact gets the welcome shape. | apps/api/app/agent/prompt.py:1598-1606, 1645 (no hype, no exclamation marks) | medium |
| NR-0517 | `agent/prompt.py:1678-1680` | Never re-welcome a returning customer. | apps/api/app/agent/runtime.py:2914-2957 | medium |
| NR-0536 | `agent/prompt.py:1743-1747` | Apply corrections in one sentence without asking permission. | apps/api/app/agent/prompt.py:1458-1459 (read the whole order back before offering to place it) — different moment, but both are absolute | low |
| NR-0538 | `agent/prompt.py:1751-1755` | Never explain the ordering process. | apps/api/app/agent/prompt.py:1661-1664; apps/api/app/agent/prompt.py:1672-1677 (owner's exemplar explains ordering) | medium |
| NR-0544 | `agent/prompt.py:1768-1771` | No Swahili words inside an English reply. | apps/api/app/agent/memory.py:318-320 | medium |
| NR-0555 | `agent/prompt.py:1794-1800` | Use the fixed official Swahili phrases for shipping, made-to-order, location, availability, private message and close. | apps/api/app/agent/review.py:1031-1035 (_PROMISE_RE flags the prescribed availability phrase in some turns) | low |
| NR-0563 | `agent/prompt.py:1820-1826` | A colleague's price/product overrides the tools; the cart is corrected to match. | apps/api/app/agent/tools.py:5,1440 | high |
| NR-0571 | `agent/prompt.py:1844` | At most one emoji, only if the customer used one first. | apps/api/app/agent/runtime.py:1212,2932,2956; apps/api/app/routers/web_chat.py:257 | low |
| NR-0572 | `agent/prompt.py:1845` | No emoji in complaint/delay/refund threads. | apps/api/app/agent/runtime.py:1212-1215,1628-1639 | medium |
| NR-0574 | `agent/prompt.py:1847-1848` | Only WhatsApp may carry one *bold* / _italics_. | apps/api/app/agent/prompt.py:1614-1615 (says the only exception is a single *bold*) | low |
| NR-0575 | `agent/prompt.py:1849-1850` | Never mention stock status or counts. | apps/api/app/agent/review.py:1852 | medium |
| NR-0576 | `agent/prompt.py:1850-1852` | Answer availability of catalogue goods with yes. | apps/api/app/agent/prompt.py:1864-1869; apps/api/app/agent/review.py:1060-1083 | medium |
| NR-0579 | `agent/prompt.py:1864-1869` | Never say we do not have an item. | apps/api/app/agent/review.py:440-445,1714,1852,1888; apps/api/app/agent/runtime.py:142 | high |
| NR-0580 | `agent/prompt.py:1870-1871` | For an unconfirmable item, ask for time without naming a lack. | apps/api/app/agent/review.py:1182-1192 | low |
| NR-0582 | `agent/prompt.py:1873-1874` | Do not hand off for a stock question. | apps/api/app/agent/prompt.py:1562-1564 (says a refund ALWAYS goes through raise_complaint, not handoff) | medium |
| NR-0615 | `agent/runtime.py:142-143` | Under a comment, say plainly when the exact item is not sold and offer the nearest. | apps/api/app/agent/tools.py:360-366; apps/api/app/agent/runtime.py:452-455 | medium |
| NR-0617 | `agent/runtime.py:148-151` | Claim to the model that any failed check (figure, item, unanswered question) blocks posting. | apps/api/app/agent/runtime.py:1498-1516 | low |
| NR-0621 | `agent/runtime.py:158-162` | Tell the commenter a private message was sent. | apps/api/app/agent/runtime.py:6772-6793 | high |
| NR-0630 | `agent/runtime.py:200-207` | Answer 'do you make this for X' with yes, then the post's item and price. | apps/api/app/agent/review.py:1510-1515 | medium |
| NR-0636 | `agent/runtime.py:240-245` | On a public request, list 2–3 items with prices and state that photos were sent to the inbox. | apps/api/app/agent/runtime.py:70-76; apps/api/app/agent/review.py:1551 | high |
| NR-0647 | `agent/runtime.py:313-319` | A Swahili comment is quoted in KES. | apps/api/app/agent/tools.py:56-63,167-168 | low |
| NR-0657 | `agent/runtime.py:377-385` | Host replies avoid a banned corporate-phrase list and use at most one emoji. | apps/api/app/agent/runtime.py:1212-1213 (_REVIEW_HOLD_DM itself says 'One of our team') | low |
| NR-0666 | `agent/runtime.py:433-437` | Other currencies are converted only with the rate supplied this turn. | apps/api/app/services/fx.py:265-272 (hub_only_line says give NO figure in that currency when fx_public_feed is off — the addendum still says 'convert … at today's rate') | low |
| NR-0669 | `agent/runtime.py:452-455` | Never state an item is not sold; call check_availability instead. | apps/api/app/agent/runtime.py:142-143 | medium |
| NR-0684 | `agent/runtime.py:546-547` | Give the WhatsApp number as digits on TikTok. | apps/api/app/agent/runtime.py:51-61 (tool list includes whatsapp_checkout_link) | low |
| NR-0701 | `agent/runtime.py:2321-2322` | Ask for a description when the photo fails to load. | apps/api/app/agent/review.py:1009-1019 (_NO_PHOTOS_RE is about sending, not receiving — no real conflict) | low |
| NR-0708 | `agent/runtime.py:2654` | Hard-coded stall line sent when the model returns no words twice. | apps/api/app/agent/runtime.py:2641-2650 | medium |
| NR-0710 | `agent/runtime.py:4307-4318` | In a campaign DM never apologise, hold, or imply the person was chosen. | apps/api/app/agent/runtime.py:1620-1625 | high |
| NR-0713 | `agent/runtime.py:4330-4333` | Hard-coded campaign terms: one recipient, free, recipient pays shipping. |  | medium |
| NR-0734 | `agent/tools.py:175-183` | The offer is played only on a discount ask, a price objection or a big/repeat order — never because the customer is quiet. | apps/api/app/agent/tools.py:922-926 | high |
| NR-0747 | `agent/tools.py:363-366` | Never say an item is unavailable; ask the team. | apps/api/app/agent/runtime.py:142-143 | medium |
| NR-0749 | `agent/tools.py:395-400` | Ask a name at most once and only when unknown. | apps/api/app/agent/runtime.py:442-445,460-464 | low |
| NR-0800 | `jobs/cart_recovery.py:171-175` | Cart nudge: no pressure, discount or links, two sentences. | apps/api/app/services/actions.py:440-448 | medium |
| NR-0812 | `services/buyer_intent.py:355` | No pause on the first boundary. | apps/api/app/agent/tools.py:414-425 | low |
| NR-0819 | `services/fx.py:269-272` | No figure in a currency the hub does not price. | apps/api/app/agent/runtime.py:433-437 (_meta_addendum still says convert at today's rate) | low |

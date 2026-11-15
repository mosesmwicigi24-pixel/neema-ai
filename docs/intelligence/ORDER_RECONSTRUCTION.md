# Order Reconstruction (slice 21)

Owner's directive, 2026-11-15, after the Melchizkek WhatsApp thread. Status: **on the branch, tested; not merged, not deployed.**

## 1. What happened in the real thread

A customer abroad asked for three garments for two people, each chosen by sending a photo: two for himself (black with red, white with red) and one for his spiritual father (purple, with the stole and the cross, "all as in the picture"). The conversation ended as two standard Cassock Sets, a cross and a stole (USD 630). One garment was dropped and the style he chose was replaced by a listed product.

The customer had given every fact needed. Neema lost them.

## 2. Causes found in the code

| # | Cause | Where |
|---|---|---|
| 1 | Photos sent together reached the turn as ONE picture | `wa_native._drain` kept one image per burst |
| 2 | A past photo read as the bare words "[the customer sent a photo]" | `runtime._history` |
| 3 | WhatsApp's album notice told Neema "we cannot see what it says", though each photo arrives as its own message | `inbound_kinds.describe` |
| 4 | "These two", "this one is his" arrived with no picture to point at | no photo went with a text turn |
| 5 | A cart line was a product and a number: nowhere for who it is for, which photo, what colour, "as pictured" | `agent/cart.py`, `update_cart` |
| 6 | The cart was shown to the model only when it asked | no per-turn record |
| 7 | `remove` and `clear` ran on the model's own reading | `tools._update_cart` |
| 8 | An item with no hub price had nowhere to live, so the nearest priced product took its place. Asking the team about it could also be short-circuited: a near-named catalogue row answered "available" | `tools._check_availability` |

## 3. Changes

**Photos**

- Every photo of a burst reaches the turn, in order, each under its number (cap: `turn_photos_max`, 4).
- Each photo a customer sends gets a number that stays with it ("photo 2"). The same picture sent again keeps its number. Stored on the message itself (`raw_meta.photo`); no new table.
- History shows "[the customer sent photo 2 — our own photo of the Red Apostolic Cassock]" when the existing photo check has a reading for it.
- A message that points at photos ("these two are mine", "all as in the picture"), or a few bare words right after photos, gets the recent photos put back in front of the model (`photo_reference_minutes`, 180).
- The album notice no longer wakes the agent and no longer says the photos cannot be seen.
- The photo check now runs on every photo of a burst, not only the first.
- A conversation with no photo does no extra database read.

**The order record**

- A cart line can carry `details`, one per piece: who it is for, colour, photo, as pictured, a note, confirmed or tentative. One product is still one line; prices are still the hub's.
- `update_cart hold`: an item with no hub price is kept on the order as "awaiting a colleague's price" and a colleague is asked (inbox note "💰 PRICE NEEDED", an open team check). Nothing takes its place. It is not in the total and the tool result says so.
- The order so far is put in front of the model on every turn (lines, pieces, what awaits a price, the total of the priced lines).
- The per-piece facts are written onto the order note for the workshop.

**Guards (code, not instructions)**

- Removing a line, clearing the cart, or lowering a quantity needs `customer_said`: the customer's own words, quoted. The quote is checked against the stored messages of the customer and of any human colleague. Not found: the cart does not change. Undoing one's own addition in the same turn is exempt.
- No order while a piece awaits a colleague's price, or while a piece is recorded as not yet confirmed.
- A reply that says the order was changed in a turn whose cart did not change is sent back for a rewrite (gate rule `cart_claim`, soft).
- An offer to start or place the order that the record cannot back is sent back for a rewrite (gate rule `order_unready`, soft). The ordinary single-item sale is untouched.

**Rules (prompt, short)** — one block of five points: pieces go on the order with details; an unpriced piece is held, never substituted; a correction changes one piece; ask only the one unclear thing, once; no offer to place or total the order while a piece is missing or unconfirmed.

**Read-only access key** — `GET /api/ops/read/…` (conversations, messages, order). Off unless the server has `OPS_READ_KEY` of 32+ characters; header `X-Ops-Key`; constant-time compare; GET only; numbers masked; every read logged; closes after 10 wrong keys in 10 minutes. Media files are not served.

No migration. Three new settings, all with defaults: `turn_photos_max`, `photo_reference_minutes`, `ops_read_key`.

## 4. Decisions taken that the owner may want to change

| Decision | Why | The alternative |
|---|---|---|
| An unpriced piece is handed to a colleague as a team check; Neema stays in the chat for the rest | The existing "ask the team" path keeps the customer served and holds sales nudges while the check is open | Full hand-over of the whole chat to a person (`handoff_to_human`) |
| No order at all while a piece awaits a price | A partial order is how a garment gets lost | Let the priced pieces be ordered first |
| The colleague completes the order for a held piece | There is no hub product for Neema to add | A hub entry for the item, then Neema can add it |

## 5. Verification

**Without the model.** `tests/test_order_reconstruction.py` (23) and `tests/test_order_reconstruction_db.py` (3, real Postgres, in the Migrations job). The full suite ran locally before the last commits: 3,778 passed, 2 failed; both failures were fixed (a loop variable that shared a name with a later local import in `run_turn`; one pinned string).

**With the model.** `app.jobs.eval_order_thread`: five customer turns, three drawn photos, the real turn. The order record is checked after every turn. Two runs on the owner's word ("Start it"), on the branch, 15 Nov 2026.

| Turn | Run 1 (43711949562, commit ca60064) | Run 2 (43713060582, commit 52f7b52) |
|---|---|---|
| 1. Two photos, "these two for me" | Photos read and searched | Both priced by name (USD 130 each). Ended "Which would you like to order?" though he had already said |
| 2. Third photo, "for my spiritual father … all as in the picture" | Photos read and searched | Team asked to confirm the piping and cross as pictured. Asked "Is this a third piece?" |
| 3. "How much for everything?" | **Failed.** USD 455 quoted with nothing on the order; the father's stole and cross priced from listed items; "shall I start your two cassocks?" | Two cassocks on the order (USD 260); the purple one held for a colleague's price and said so; no offer to start. Marked failed by a check that read only the "for" field; the piece was held with the father named in its description. Check corrected. |
| 4. "Make the cross silver" | Three cassocks on the order, stole and silver cross held; nothing lost | Nothing lost. **Defect:** the correction held the purple cassock a second time instead of changing the first |
| 5. "Send me the total" | Said USD 390 excludes the held pieces, then "Shall I place it now?" | "The full total isn't ready yet"; no offer to place |

Changes made between and after the runs:

- After run 1: gate rule `order_unready` (a total for several pieces over an empty order with an offer to start; an offer to place while a piece awaits its price); the order note says so too. Run 2 shows neither offer.
- After run 2: a held piece described again (same person, most of the same words) changes that piece instead of adding a second (`order_sheet.same_held_item`). **Tested without the model only; not re-run with it.**

Set against the real thread: no garment was dropped in either run, the correction did not remove or swap a piece, and the piece with no price went to a colleague instead of being replaced by a listed product.

The re-ask on turn 1 of run 2 ("Which would you like to order?") is now a gate rule on the owner's word ("fix the re-ask"): `asked_again`, soft — when the customer's message has already chosen by pointing ("these two", "this one", "both"), a reply that asks what they want is sent back for a rewrite. "I want a cassock" still leaves "which one?" a fair question. **Tested without the model only.** The confirming question on turn 2 ("Is this a third piece?") is left as it is.

Cost: run 2 recorded 696,722 cached input tokens read, 49,222 written, 3,777 output and 38 uncached input (the writer's calls). At the list price assumed for the configured writer model (USD 3 per million input, 0.30 cached read, 3.75 cache write, 15 output) that is about USD 0.45. The reviewer's calls are not in that count. Run 1 printed no token count; it is the same shape. A first dispatch (run 43711828629) stopped before any model call: the runner could not write the media folder.

Two runs of five turns are evidence, not a measurement.

## 6. Not verified, and remaining risks

- **The two gate rules are soft**: one rewrite, then the reply goes. They read English phrasing and a little Swahili.
- **The model test's pictures are drawings**, not the customer's photos, and its wording is a reconstruction. It tests the order logic with photos in the turn, not recognition of real garments.
- **Photo numbers start when this ships.** Photos already in a conversation are numbered the first time that conversation has a turn.
- **The quote check is exact-substring** (case, punctuation and spacing aside). A model that paraphrases the customer's words will be refused and must quote again; it costs a tool call, not an order.
- **A voice note's words** count as the customer's words only if they are stored as message text.
- **"Points at a photo" is read by pattern** (English and a little Swahili). A pointing message in another language gets no photos back unless it is four words or fewer and close in time.
- **Cost:** a turn with photos put back costs more (each photo is roughly 1,000–1,600 input tokens). The per-turn order note is small.
- **Meta channels** (Messenger, Instagram): the burst change is WhatsApp's; numbering, history and re-attachment apply on every channel, but several images in one Messenger message were not examined.
- **The read key** is one shared secret with no per-reader identity. Rotate it by changing the server's value.

## 7. Rollback

Revert the slice's commit. Data written: `raw_meta.photo` on image messages, `units` on cart lines, `pending` in a cart. All are ignored by the previous code.

# G. Verification report — Phase 1

## 1. Independent validation of the critical findings

Before building, the lead auditor re-read the code for each critical finding of `C_RISK_FINDINGS.md`.

| Finding | Result | What was read |
|---|---|---|
| C1 Messages Neema starts are not checked like replies | Confirmed | `runtime.py:2701` (gate only when not read-only); `review.initiated_issues` |
| C2 Team answer sent with no check | Confirmed | `routers/admin.py` `answer_through_neema` |
| C3 Discount quotable without the grant | Mechanism confirmed; not reproduced with the model | `tools.py:913-930`, `1706` |
| C4 Refund promises unchecked | Confirmed: no refund, remake or replacement rule among the gate's rules | `review.py` `rule_findings` |
| C5 Discount in words unchecked | Confirmed: no percentage or discount-wording rule | same |
| C6 Payment numbers unchecked | Confirmed: no rule reads phone digits in a reply | same |
| C7 Order needs no recorded yes | Confirmed | `tools.py` `_create_order` |
| C8 Failed order described as placed | Confirmed: no "placed" rule | `review.py` |
| C9 Pay on delivery unchecked | Confirmed | `review.py` |
| C10 Complaint alerts nobody | Confirmed (now rings the team) | `tools.py` `_raise_complaint` |
| C11 Near-match price counts as verified | The row is remembered as seen: confirmed. Its effect on the price check: reported, not re-read | `tools.py:1099-1102` |

## 2. Coverage after Phase 1

**Routes.** The trace found 40 routes. 15 of them send text the model wrote.

| | Routes |
|---|---|
| Model-written routes now read by the policy layer | 13 of 15 |
| Not yet read | One-tap approval of a draft the gate held; reply-box translation of a colleague's text |
| Fixed-text and template routes (25) | Not read by the layer. Their text is written in code; the audit lists the three where a figure is inserted |

The 13: live WhatsApp; live Messenger, Instagram and TikTok; web chat; the ManyChat relay; the missed-reply sweep; the unclaimed-chat answer; public comment answers; comment-to-private message; model-composed follow-ups; hub announcements; the cross-channel bridge; approved planned actions; team answer through Neema.

**Critical findings.**

| Finding | After Phase 1 |
|---|---|
| C2, C4, C5, C6, C8, C9 | Detected and recorded on every model-written route above; held once the policy is switched on |
| C7 | Detected and recorded at the order step; refused once switched on |
| C10 | The team is rung. A tracked case with an owner is Phase 3 |
| C1 | The company policies now run on messages Neema starts. Price, item, link and language rules on those messages are Phase 3 |
| C3 | A discount spoken in words or as a percentage is detected. A bare offer price quoted without the grant is not; Phase 3 |
| C11 | Not addressed; Phase 3 |

**Rules.** Counted from `rule_inventory.jsonl` by canonical policy:

| Risk | Rules | Under a policy the layer now evaluates or acts on | Not yet |
|---|---|---|---|
| Critical | 27 | 21 | 6: four on which item a price belongs to, one on prices from the hub, one on the gate for messages Neema starts |
| High | 161 | 57 | 104, mostly "the price belongs to the item asked for" (24) and "every price comes from the hub" (22), which the existing reply gate covers in part |

All of this is record-only today, except the complaint bell. The count of hard-enforced rules is unchanged at 62 until a policy is switched on.

## 3. False-alarm measurement

The layer was run over text that is known to be acceptable.

| Corpus | Texts | Findings | Reading |
|---|---|---|---|
| Neema's fixed lines (every reply pool and both fallback welcomes) | 99 | 0 | No false alarm |
| Quoted strings in her instructions (example replies mixed with instruction fragments) | 485 | 5 | See below |

The 5:
- 3 are "a colleague will reach out" or "let me confirm with the team" with no step that tells the team. In a real turn the step would be in the record; alone they are correctly findings.
- 1 is the instructions' own example of a discount ("Harvest Offer running, 10% off"), correct only after the offer is granted.
- 1 is the instructions' deliberate bad example ("I'll knock something off").

Found and fixed during measurement: shipping times the instructions state as fact ("1–2 days", "3–7 days") were flagged; "the final price is" was read as a discount; "the order is placed once you confirm" was read as a claim; the gate's own hold line was read as an unkept promise.

**What this does not show.** These are written examples, not live conversations. The real false-alarm rate is what the record shows after Phase 1 has run on live traffic, which is why nothing is enforced yet.

## 4. Tests

`apps/api/tests/test_policy_layer.py`: for each policy, the direct violation, paraphrases (English and Swahili), the legitimate sentence that must not be flagged, and the record that makes the claim true (a granted offer, a successful order step, a colleague's words, the customer's own number or date). Also: shadow holds nothing; enforce holds only listed policies; the stored record never holds a whole phone number; every route is wired; the defaults are record-only.

**Full API suite, run locally with the database on the Phase 1 code:** 3902 passed, 1 xpassed, 2 warnings in 762.37s (0:12:42).

**CI on the pull request (commit b6902f0):** API tests, database tests (fresh-database replay), lint, import check, web build and image build all passed.

CI on the first Phase 1 commit failed two existing order tests: the consent check added a read on the order step's own database session, which shifted those tests' scripted answers. The check now reads in a separate session; both tests pass unchanged.

## 5. Not tested, and limits

- **Not run with the model.** No conversation was generated to see how often real replies trip a policy.
- **Not tested end to end from message receipt to dispatch.** The route wiring is asserted by reading the source and by the existing route tests still passing, not by new end-to-end cases per policy.
- **Concurrent messages, partial tool failures and long histories** are covered only by the existing suite, not by new policy cases. Partial tool failure is covered for the offer and order steps (a failed step does not authorise the claim).
- **The customer's yes (ORD-01)** is read from wording in the last three messages. A yes phrased another way, or given four messages back, is recorded as missing. This is why it is record-only.
- **Phone numbers (FIN-05)** are recognised by shape. A number written in an unusual format may be missed.
- **Dates (FUL-01)** accept a day the customer named anywhere in their recent words, which is permissive.

## 6. Switch-on (#388, main 5e13d15)

- Full local suite on dd583ae: 3934 passed, 1 xpassed. CI green (API tests, migrations, lint ratchet, import smoke, web build).
- Older tests run with the new switches off (autouse fixture in `tests/conftest.py`); each switch is tested on in `tests/test_safeguards_on.py` (15 tests).
- Model check of the wording changes, 7 cases (run 45152831211): all behaved as decided. In that run the model wrote the official-numbers line in 1 of 7 first replies, which is why the line is now written by code.
- NOT YET MEASURED: false alarms of the six enforced policies on live traffic; the one-minute wait's effect on reply counts.

# Customer geography with provenance — slice 13 (2026-11-09)

The first implementation slice of the owner's directive "Unified Customer
Intelligence, Geographic Discovery & Commercial Profiling" (2026-11-09),
following the Phase 1 audit (`CUSTOMER_INTELLIGENCE_AUDIT.md` §8, item 1).
Merged as d402c0a (PR #350) and live on the box at 11:35 UTC on 9 Nov; the
suite, CI and production rows are in `REGRESSION_SAFETY_REPORT.md`. No evaluation run was dispatched (the owner's
standing stop). No migration: the record is JSONB on `persons.state`.

## 1. What the owner saw, and what it means now

A customer with a +973 number shows **Country: Bahrain** and **Location:
Kenya**. The audit established that both are legitimate: the first is the
telephone country, the second what the customer said. The cost was that the
WhatsApp market read the number alone, so this customer was quoted in dollars,
offered DHL and the international close, never M-Pesa, although they are in
Kenya.

After this slice the two facts are two attributes with their own provenance,
and the one decision every reader shares prefers what the customer said:

| | Before | After |
|---|---|---|
| Telephone country | `users.country` from the `+973` prefix, no source recorded | `geo.telephone_country = {BH, by: phone, confirmed, "+973"}` — kept, shown with a ☎ when it differs from the decision |
| Where they said they are | `users.location = "Nairobi"`, free text, not read for the market | `geo.probable_country = {KE, by: stated, high, "Nairobi"}`, `geo.city = Nairobi` |
| Market on WhatsApp | USD (the prefix) | **KES** (the decision: confirmed residence → probable country → telephone country) |
| The turn they said it | the location saved; the currency unchanged until… never (WhatsApp never read it) | the same turn switches to KES and tells the writer to re-run the catalogue in KES, as Messenger already did |
| Profile | Country Bahrain, Location Kenya, no source | Country **Kenya** (hover: "Kenya — what the customer said · High confidence"), beside it "☎ Bahrain" (hover: "Bahrain — the telephone number · Confirmed"); the Profile tab adds a "Number from" row only when the two differ |
| Operator edit | `country` by name left `country_iso` unset; nothing recorded | confirms the residence (`geo.confirmed_residence`, by operator, confirmed), derives the ISO and flag from the name, outranks the customer's words |
| Activity | nothing | "Placed the customer — Placed in Kenya (what the customer said); was Bahrain" on the conversation, only when the decision moved |
| Shared dialling codes | `+1 212…` labelled Canada, `+7 495…` Kazakhstan | the phone-numbers library decides: US, RU (the prefix table remains the fallback) |

Nothing was removed. `users.country / country_iso / flag_url` keep working
and are written from the same decision, so the inbox flag, the country tag and
the leads list see the country Neema treats the customer as being in.

## 2. The record

`persons.state["geo"]` (`app/services/geography.py`):

```
telephone_country    the number's country          by phone      confidence confirmed
probable_country     where they probably are now   by stated / ip / locale   high / probable / possible
confirmed_residence  a residence someone confirmed by operator   confidence confirmed
shipping_country     where a parcel went           by order      confidence probable
city                 the town they named           by stated / operator
history              [{attr, value, by, confidence, at, previous?, kept?}]  (last 12)
```

Each reading is `{value, by, confidence, at, detail?}`. Confidence is the
directive's five-level scale — confirmed, high, probable, possible, unknown —
and nothing else; no numeric score is invented. A reading replaces an earlier
one of the same attribute only when it is at least as confident; the earlier
reading goes to the history. A weaker, conflicting reading is recorded in the
history only (`kept: previous`), so the conflict is visible without moving the
decision. The same value from a weaker source changes nothing.

`decide(state)` is the one decision: confirmed residence, then a probable
country of at least "probable" confidence, then the telephone country, then
the caller's fallback (the number read directly). A "possible" reading (a
Facebook profile locale) never decides, exactly as the locale never decided
before. Shipping and city never decide the market.

`view(state, handle, language)` is what the profile returns under `geo`: every
attribute with a plain-words source and confidence label, the decision, a
`discrepancy` flag (telephone ≠ decision), the preferred language (read from
`contact_preferences.language`, written by the scribe as before), the history.
A profile from before this slice gets its telephone country derived from the
handle for display, and written on the next inbound message.

## 3. Writers and readers

| Path | Writes | Reads |
|---|---|---|
| WhatsApp upsert (`messaging.provision_user`) | `telephone_country` once, via the phone-numbers library; `users.country*` when empty, as before | — |
| `capture_customer` (WhatsApp) | `probable_country` (stated, high), `city`; mirrors the decision on the user row; switches this turn's currency when the decision names a hub-priced market; an activity event when the decision moved | — |
| `capture_contact` (Messenger / Instagram) | the same readings beside the legacy `persons.state.location/country*`; a shared phone adds `telephone_country` | — |
| Operator `PATCH /customers/{key}` | `confirmed_residence` (operator, confirmed), `city`; ISO and flag from a typed country name; the event | — |
| `create_order` | `shipping_country` (order, probable) when the delivery notes name a country or a Kenyan town; never decides the market | — |
| Meta profile locale | `probable_country` (locale, **possible**) beside the legacy empty-fill | — |
| Web chat IP | `probable_country` (ip, probable) when the visitor is already a known person | — |
| Merge | carries every attribute (stronger wins, history kept); also carries an opt-out and the language, and the customer state when the primary has none — the audit's §3 fault | — |
| WhatsApp turn (`runtime.run_turn`) | — | `market.placement_for_handle` → the decision, the number as fallback; `market_locked` on the decided country |
| `market.customer_market` (shared catalogue link, public comments, panel) | — | the same decision for a number; the Meta evidence chain reads the record first (step 0), then the legacy stores |
| Profile (`crm._country_fields`, `geo`) | — | the decision first; the stores as fallback for a person without a record |

Any failure reading the record falls back to the number, with a warning: a
quote is never lost to a geography read.

## 4. Behaviour changes a person should know about

- A WhatsApp customer who names a town or country in a hub-priced market
  (Kenya, Zambia) is now quoted in that market's money from that turn, even
  when their number is foreign. This is the owner's 2026-09-05 rule ("their own
  words — a captured location, or a panel edit" is evidence) applied to
  WhatsApp as it already was to Messenger. The reverse holds too: a +254
  number who says they are in Dubai is quoted USD.
- An operator's country or location edit now outranks everything, including
  the customer's words, and is recorded as confirmed.
- The profile's "Country" now shows the decided country; the telephone
  country stays visible beside it only when the two differ. Neither is marked
  wrong (the owner: "Do not assume either is incorrect").
- A Facebook locale still decides nothing.

## 5. Tests

- `tests/test_geography.py` (27): shared dialling codes through the library;
  words → country and city; the observe rules (replace, keep, history, cap,
  purity); the decision order and the "possible" exclusion; the view and the
  discrepancy; operator readings; the merge carry; the event line; the market
  on fakes (the Bahrain number in Kenya → KES; a broken read → the number);
  the Meta chain reading the record first; the profile fields; the capture
  tool placing, switching the turn, mirroring the row, and writing no event
  when the decision did not move.
- `tests/test_geography_db.py` (4, CI database job): the Bahrain case end to
  end on Postgres — upsert, capture, market, profile fields, view, the
  activity row on the conversation, the same words again writing no second
  event, the operator's confirmation (ISO derived from the name) outranking
  the words, a later IP guess not moving the decision; an older profile
  gaining its telephone country on the next message; `+1 212` → US; a merge
  carrying geography, the opt-out and the customer state.
- Existing suites unchanged in behaviour: market evidence (one test renamed to
  say the record is read first), currencies, the currency gate, merge, Meta
  Kenyan market, web geo, phone shapes — 126 passed before the new files.
- Web: `tsc --noEmit` clean.

Not measured with the model (the owner's stop): whether the writer re-runs the
catalogue in KES after the switch note (the note is the same one
`capture_contact` has used since September).

## 6. What this slice does not do (the next slices, in order)

Insights from evidence (paid vs unpaid, one scorer, no stage from a prefix,
next best action); Activity as a levelled timeline; the fuller Profile UX
(verify / correct controls, aging); segmentation by country and language;
the directive's validation list. Each is its own slice with tests
(`CUSTOMER_INTELLIGENCE_AUDIT.md` §8).

## 7. Risks and rollback

- A stated "delivery location" for someone else ("send it to my mother in
  Nairobi") would place a foreign customer in Kenya. The capture tool's
  schema calls the field a delivery location; the decision treats it as the
  customer's own words, as Messenger has since September. Watch for it in the
  Activity events ("Placed the customer"); an operator's edit corrects it in
  one step and outranks it thereafter.
- `users.country` changes meaning slightly: it was the telephone country, it
  is now the decided country. The telephone country is preserved on the
  record and shown when it differs.
- Rollback: `git revert` of the squash commit. The `geo` key on
  `persons.state` is ignored by the previous code; nothing to unwind.

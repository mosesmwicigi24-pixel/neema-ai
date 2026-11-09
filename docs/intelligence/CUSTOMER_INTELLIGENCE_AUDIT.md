# Customer Intelligence — Phase 1 forensic audit (2026-11-09)

The owner's directive "Unified Customer Intelligence, Geographic Discovery &
Commercial Profiling" (2026-11-09) requires a deep audit before any code is
written. This is that audit, read from main at 50f37e8 under `apps/api/app/`
and `apps/web/src/`. Every finding carries its file and line; two tracing
passes were made over the code and the key claims were re-read by hand.
Nothing here was changed; section 8 is the implementation order that follows
from it. No evaluation run was dispatched (the owner's standing stop).

## 1. What exists, and how a message becomes a profile

**WhatsApp.** The inbound payload's `contacts[].profile.name` becomes
`users.name` only when the row has no name and no one confirmed one
(`services/messaging.py:91-93`). The country, ISO and flag come from the
dialling prefix on the first message, only when `users.country` is empty
(`:95-100`); `users.phone` is the handle itself for a plausible phone
(`:87`). An identity and a person are made with that name
(`:117-125`). `users.location` is never written by an inbound message: it is
written only by the agent's `capture_customer` tool (what the customer said)
or by an operator in the panel.

**Messenger / Instagram.** One Profile API call per contact per 30 days gives
name, picture and locale (`services/meta_send.py:284-326`,
`routers/meta_webhook.py:325-340`). The locale is not stored; it sets the
person's country only when the person has none (`meta_webhook.py:359-372`),
and never touches a user row. No `users` row exists for a Meta contact until
the CRM resolves them, when a placeholder is made once (`routers/crm.py:470-487`).
A comment stores the commenter's name and the post (`meta_webhook.py:810-817`).

**TikTok, ManyChat, web.** Name and username only; web chat adds the IP
country without a flag (`routers/web_chat.py:159-180`). Calls create `User`
rows directly, without country or person (`services/call_transcribe.py:396`).

**Then, per turn.** The capture tools write what the customer volunteers;
the scribe writes facts, language, contact preferences and customer state on
the person; `refresh_lead_signals` (WhatsApp only) advances the stage and
tags the country (`services/lead_signals.py:47-90`, `agent/runtime.py:2611`).

**Then, on display.** `GET /customers/{id}` (`routers/crm.py:492`) assembles
the profile from users, identities, persons.state, order_events, the hub's
customer summary and the parish (`:524-612`), recomputes the lead score, and
returns it to `CustomerSidebar.tsx` (`apps/web/src/components/ui/`), whose
three tabs render it (`:1680`, `:2398`, `:2594`).

## 2. The Bahrain / Kenya screenshot, verified

Both values are legitimate and mean different things:

- **Country: Bahrain** is `users.country`, written once from the `+973` prefix
  on the first message (`messaging.py:95-100`). It is the telephone country.
- **Location: Kenya** is `users.location`, written by `capture_customer` when
  the customer said where they are, or typed by an operator. It is a stated
  location.

What the system does with them today:

- The profile shows both, with the flag from the phone (`crm.py:401-420`,
  user fields first).
- **The market stays Bahrain's: USD.** On WhatsApp the currency comes from
  the phone prefix alone (`runtime.py:1801-1808`; `services/market.py:123-129`),
  and `users.location` is never read for currency. This customer is quoted in
  dollars, offered DHL and the international two-step close, never M-Pesa,
  although they live in Kenya. The Meta path behaves differently: there the
  person's own words come first in the evidence chain (`market.py:53-113`).
- `capture_contact` (which WhatsApp also has, `runtime.py:2367`) does switch
  the current turn to KES when a location resolves to Kenya (`tools.py:1994-1998`),
  but it writes `persons.state.location`, which the next WhatsApp turn ignores,
  so the switch lasts one turn and bypasses `market_locked`.
- The lead stage reads this customer as "qualified" because a name plus a
  country exists (`lead_signals.py:36-45`), where the country is the prefix.

Conclusion: the screenshot is not a bug in either value. It is the absence of
the distinction the directive asks for (telephone country vs probable or
confirmed residence vs shipping destination), and that absence costs this
customer the right money and the right payment route.

## 3. Geography: the resolvers and their faults

| Finding | Evidence | Verified |
|---|---|---|
| 241 dialling codes, longest-prefix match | `core/countries.py:258`, `resolve_country` | yes |
| Shared codes take the first table entry: a New York number (+1 212) is labelled Canada, a Moscow number (+7 495) Kazakhstan | `resolve_country("12125550123")` → Canada; the phone-numbers library already in the codebase (`core/phone.region_of`, `phonenumbers 8.13.45`) returns US and KZ correctly | yes, run |
| Country from words knows every country name and 60 Kenyan towns; no town outside Kenya | `countries.iso_from_text:304-325` | yes |
| The Meta locale is parsed (`iso_from_locale`) but is not in the evidence chain and not stored | `countries.py:338`; `market.py:53-113`; `meta_webhook.py:359-372` | yes |
| Country is stored in three places with different writers: `users.country*` (prefix at upsert; web IP without flag; operator PATCH of `country` alone leaves `country_iso` unset, `crm.py:775-786`), `persons.state.country*` (words via `capture_contact`, locale), tags (`lead_signals.py:59-64`) | as cited | yes |
| No record of how a country was decided, no confidence, no history on conflict; the evidence name is only logged | `market.py` returns `evidence` to a log line only | yes |
| A merge carries location, lead source, cart, measurements and memory from the secondary person, but not country fields, contact preferences (opt-out, language) or customer state | `services/merge.py:89-153` | yes |
| Language: `guess_language` knows hi, ar, am, sw, pt, fr, en; stored only as `persons.state.contact_preferences.language`, overwritten each turn; no Indonesian; Swahili-means-Kenya lives in a redis key, not the profile | `customer_state.py:275-325, 437-442`; `runtime.py:1061-1088` | yes |

## 4. Profile tab

Fields shown: name with a confirmed tick, role, ministry (organization),
email, phone, country, location, parish (read-only), age; lead source and ad
reference; the stage stepper; tags; notes; cross-channel identities and
merge suggestions (`CustomerSidebar.tsx:1680-2396`). Edits go through
`PATCH /customers/{key}` (`crm.py:748`).

Faults: location has two stores (`users.location` from `capture_customer`
and the operator; `persons.state.location` from `capture_contact`) and the
display picks the first non-empty (`crm.py:352`). The name has four stores
(user, person, identity, comment profile) with three different rules
(`capture_customer` overwrites the user only; `capture_contact` applies
fuller-wins to all; inbound and enrichment fill empties). `customer_history`
(the hub's view: last status, open order, counts) is loaded on every profile
read and never used (`crm.py:553-557`, `_build_profile`). `suggested_lead_stage`
is returned and not rendered. Nothing on the profile says which source a
value came from or when it was last confirmed.

## 5. Insights tab and lead scoring

Shown: purchase summary (orders, spend, average order value, first and last
order), buying rhythm, top products (aggregated in the browser from the order
list), and the lead-score breakdown (`CustomerSidebar.tsx:2398-2592`).

**The scorer** (`crm.py:108-148`), one definition, 120 points capped at 100:
active cart 25, orders 10 each up to 25, recent contact 15/7, spend 15/8,
phone verified 10, multi-channel 10, name known 5, location known 5 (on
`users.location`), clergy role 10.

Faults the directive asked about:

- **Paid and unpaid are the same.** Every `order_events` row counts as an
  order and its subtotal as spend; `payment_status` / `hub_payment_status`
  (`models/order_event.py:23,58`) are not read. An unpaid order raises the
  score and the "Spent" figure exactly like a paid one. When the hub answers,
  its summary replaces the local figures (`crm.py:254-274`), so the panel and
  the Leads list can disagree.
- **Two computations.** The panel scores with hub orders, person-wide
  matching and identity-aware phone verification; `GET /leads` scores with
  local orders by `wa_id` only, conversations by `wa_id` only (missing
  Messenger and Instagram) and a user-only phone check (`crm.py:1637-1663`).
  The same customer ranks differently in the two places.
- **Stage from a prefix.** "Qualified" needs a name and an email or a
  country; the country is the dialling prefix (`lead_signals.py:36-45`).
- **Nothing from conversation evidence.** No product interest, no customer
  state (needs time, consulting, ready, paid claim), no open commitment, no
  quotation, no demand signal enters the score; the directive's "sales
  psychology" layer has no data path to Insights today, although the
  deterministic floor and the deal record already hold most of it
  (`services/customer_state.py`, `services/deals.py`).
- The score is never stored; recomputed on every read. Fine for consistency,
  nothing for history.

## 6. Activity

**The panel's Activity tab is not an activity log.** It shows the first five
orders and the per-channel conversation counts (`CustomerSidebar.tsx:2594-2711`).
The real event trail is a separate collapsible "Activity log" column in the
conversation view (`ConversationsView.tsx:4807-4943`), fed by
`GET /conversations/{id}/activity` (`routers/admin.py:1415`), which gathers
intercepts (40), planned actions (40), deals, order events (20), agent
activities (60) and calls (20), sorts by time and cuts at 80. No filtering,
grouping or deduplication on either side; the kind only colours the dot.

The only writer of `agent_activities` is the tool trail, one row per tool
call (`services/activity_trail.py:107-138`), with labels for 18 tools and a
raw "Agent step: {tool}" for the rest. This is why the screenshots show
repeated "Searched the catalogue" and "quote follow-up vetoed" rows: they are
honest technical events shown at customer-timeline level. Rows written with a
null conversation are never shown (`activity_trail.py:117-122`). The
`approve_draft` intercept has no label (`admin.py:1449`). Handoff events are
hidden from the chat and shown only in the log (`ConversationsView.tsx:3592`).

What is not written as an event at all: a profile fact captured or corrected,
a geographic discovery, a lead-stage change, a commitment opened, escalated
or closed (slice 12's records live on the deal, not in the trail), a payment
confirmation from the hub, a delivery update.

## 7. Segmentation, analytics, duplicates

No endpoint or page aggregates customers by country or language; channel
counts exist in `GET /stats` and the overview. The conversation list
resolves a country per row and never aggregates it (`admin.py:963-980`).
Tier (prospect to VIP) is per customer only (`crm.py:221-237`). Language
appears only as a reply-quality metric and on call transcripts.

Duplicates and conflicts, consolidated: four name stores with three rules;
two location stores; three country stores with a prefix that can overwrite an
operator's text; two lead-score computations; two lead-stage writers; two
activity concepts; memory split between user and person stores and unioned on
read but not fully carried by a merge; `lead_source` written by four paths
with different first-touch rules; `customer_history` loaded and unused;
`demand_signals.sourcing_gap` defined and never written.

## 8. What follows (implementation order, each a slice with tests)

1. **Geography with provenance (foundation).** One place on the person for
   `geo`: telephone country (from the number, via the phone-numbers library
   for shared codes), probable current country, confirmed residence,
   shipping destination, city/region, preferred language, each with
   `{value, by, at, confidence}` on the directive's five-level scale and a
   short history on conflict. Writers: upsert (telephone), capture tools
   (stated → probable; an explicit "I live in" → confirmed), orders
   (shipping), operator PATCH (confirmed), locale (possible). The market
   decision reads confirmed → probable → telephone, so the Bahrain customer
   in Kenya is quoted KES. `users.country*` stays for compatibility and is
   written from the same decision. Activity records each discovery.
2. **Insights from evidence.** The commercial snapshot (stage, last interest,
   open order or quotation, confirmed spend from paid orders only, next best
   action) read from the deal, the customer state, order_events with payment
   status, the hub summary and slice 12's commitments; one scorer shared by
   the panel and the list, paid and unpaid separated, no stage from a prefix.
3. **Activity as a timeline.** A `level` on each event (customer / technical),
   grouping of repeated tool steps, new events for profile and geographic
   discoveries, stage changes and commitments; the panel's Activity tab shows
   the customer level with the technical level behind a toggle.
4. **Profile UX.** Telephone country and residence shown distinctly, source
   and confidence on hover, a clarification mark only on a real discrepancy,
   verify/correct controls; no new permanent elements.
5. **Segmentation.** Country, language and channel aggregates on the existing
   Reports, with inferred and confirmed geography kept apart.
6. **Validation.** The directive's test list, model-free where possible; the
   model-dependent cases wait for the owner to lift the evaluation stop.

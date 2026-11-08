# Knowing the customer: location, names and intelligent information gathering

Repository copy of the report written for the owner on 2026-11-08 (the
editable document lives in Claude Docs; this copy is the durable checkpoint).
Read from the code on main at c04dda8. Nothing here is implemented beyond
what section 1–5 describe; section 7 is a proposal awaiting the owner's word.

## 1. Summary

Neema places a customer by evidence, never by asking: a WhatsApp number's
international code decides the country in one lookup, a website visitor is
placed by their connection, and a Messenger or Instagram contact is placed
only when something on their record proves it (their own words, a linked
WhatsApp number, a phone they gave with its code). Their own words can move a
placement; a model tool argument cannot. Names come from the channel profile
first and from what the customer says second, and the fuller name wins.
Everything volunteered is captured in the turn it appears; nothing is asked
twice.

The system is sound on the first message and on the home market. Its weak
spots are what happens over time and across channels: no confidence level on
a placement, no record of why a country was decided when two signals
disagree, a profile name that can be a church or a nickname, and gathering
that stops at the four fields the capture tools know.

| Signal | Decides | Strength | Where it lives |
|---|---|---|---|
| WhatsApp number code (+254, +260, +27 …) | country, market currency, payment route | strongest; locks the market | `core/countries.py`, `core/phone.py` |
| Website visitor's connection (IP) | country, currency on the web chat | strong when present; private addresses ignored | `routers/web_chat.py` |
| What they say (town, church, country, slang, currency words) | country; moves a placed customer | strong when a place is named | `core/countries.iso_from_text`, the capture tools |
| Language (Swahili) | Kenya, only when nothing else places them | medium; remembered 30 days | `runtime._kes_for_swahili` |
| Meta profile (name, picture, locale) | name; country from the locale when valid | weak alone | `services/identity.py`, `services/meta_enrich.py` |
| A linked WhatsApp number or a phone they gave with its code | country for a Messenger or Instagram contact | strong | `services/market.evidence_for_person` |

## 2. Location from the phone number

A WhatsApp contact is placed the moment their first message arrives, from the
international dialling code at the front of their number, on our own server.
`core/countries.py` holds 241 dialling codes and matches the longest code
first (`1684` before `1`; `254` is Kenya). That decides the market currency
(`market_currency`: KES for Kenya, ZMW for Zambia, USD everywhere else because
the hub prices only those), the payment route and selling script (M-Pesa and
local delivery for Kenya; the international two-step close and DHL otherwise),
and the lock (`market_locked`: a `search_catalog` currency argument cannot
move a placed customer — the 2026-10-29 misses; only their own words can).
`core/phone.py` reads numbers the customer types: local forms against their
own country, WhatsApp's legacy Mexican/Brazilian forms, and marks a number
whose country we only assumed as `region_assumed` so it is never evidence.

Limits: shared codes (`+1`, `+7`, `+44`) pick the first country in sort
order (the market is USD for all of them, the flag may be wrong); a number is
where the SIM was issued, not where the person is; Messenger, Instagram,
TikTok and web carry no number; non-geographic codes resolve to nothing.

## 3. Location from what they say

A customer is never asked where they are (owner rule). `iso_from_text` reads a
country name (longest first, so "South Sudan" never reads as "Sudan") and 60
Kenyan towns as whole words; a town alone is Kenya; towns elsewhere are not
known. The writer calls `capture_customer` (WhatsApp) or `capture_contact`
(Meta) in the turn a place is named; the country is derived, written on the
person with its flag, and if it is Kenya or Zambia the same turn switches
market. The evidence chain for a contact with no number
(`services/market.evidence_for_person`), first hit wins: their own words; a
country already on a user row (IP, prefix, panel edit); a phone on a profile
or a merged WhatsApp identity; a phone identifier given with its code (never
an assumed one). A Swahili message on an unplaced thread is KES by
construction, remembered 30 days, unless another country is named. Cues the
prompt names ("eish", "po", a currency word) are read by the model only.

## 4. Names and identity

| Source | Stored where | Rule |
|---|---|---|
| WhatsApp profile name on an inbound message | `users.name` | never overwrites a name the customer or an operator set (`name_confirmed`) |
| Meta profile (name, picture, locale) | `identities.display_name`, `identities.raw_profile`, `persons.display_name` | enriches an empty name, never replaces one |
| What the customer says | identity, person and user row at once | the fuller name wins; sets `name_confirmed` |
| An operator's edit | the same | wins, confirmed |

Titles stay with the first name ("Pastor Moses"), used once per reply at
most; role and church go to `persons.state.profile`. One person has many
handles (`Identity`), many identifiers with `source` and `confidence`
(`Identifier`), and an audited, undoable merge (`PersonMerge`). The parish is
found or created by a normalised name and attached to the person. The writer
is told "You are speaking with {name}" and "They appear to be in {country}"
plus facts, sizes, past orders and the parish. Thin spot: a profile name is
trusted as a person's name even when it is a church, a shop or symbols.

## 5. How information is gathered today

Sell first, never ask the country; slot check before any question; one ask
per reply; capture what is volunteered in that turn; measure once; receive a
contact as trust; remember facts, language and preferences on the person; the
parish and past orders travel with the person across channels. A first
WhatsApp message already yields country, market, profile name, language, the
item of interest, the Nairobi time and whether they have written before.
Nothing infers religion, ethnicity or income; tags never carry the country.

## 6. Gaps and risks

| # | Gap | Cost |
|---|---|---|
| G1 | No confidence or provenance on a placement (the evidence name is only logged) | conflicts invisible; no view of customers placed on a guess |
| G2 | Words move a placement only into Kenya or Zambia; only Kenyan towns are known | "Kitwe", "Lusaka", "Kampala", "Lagos" alone read as nothing |
| G3 | Shared dialling codes pick one country | wrong flag and greeting country; market unaffected |
| G4 | A profile name is trusted as a person's name | a church or nickname greeted as a person |
| G5 | A placement never ages | a relocated customer stays placed |
| G6 | The locale is read but not used as a cue | `sw_KE`, `en_ZA` profiles stay USD |
| G7 | Two user rows after a merge | stale name or location in reports |
| G8 | Gathering stops at four fields | recipient, wearer, occasion, contact hours asked again |
| G9 | Cues the prompt names are model-only | missed market switches, unmeasured |
| G10 | No consent note on volunteered personal data | fine for fulfilment; marketing use would lack a basis |

## 7. Smarter gathering: recommendations (proposal)

| # | Change | Builds on | Closes | Days |
|---|---|---|---|---|
| R1 | Record the placement with its evidence and confidence; keep the previous reading on conflict; show "placed on a guess" in the inbox and health | `evidence_for_person`, `persons.state` | G1, G5, G7 | 1.5 |
| R2 | Teach `iso_from_text` the region's towns (Zambia, Tanzania, Uganda, South Africa, Nigeria, Ghana, Rwanda, South Sudan, Malawi, Botswana, Namibia); let a resolved country move a placed market whenever the hub prices it | `iso_from_text`, the capture path | G2, G9 | 1 |
| R3 | Use the Meta locale as a weak cue (step 5 of the chain) | `iso_from_locale` | G6 | 0.5 |
| R4 | Resolve shared codes by the national number via the phone-numbers library | `core/phone.region_of` | G3 | 0.5 |
| R5 | Check a profile name "looks like a person" before greeting by it; a church-looking name goes to the parish capture | `messaging` upsert, `customer_context`, `services/parish` | G4 | 1 |
| R6 | Widen the capture schema: delivery recipient, wearer, occasion and date, contact hours, preferred channel; store under `profile`, show in memory | the capture tools, `_save_profile_fields`, `build_memory_context` | G8 | 1.5 |
| R7 | Let a weak placement age (90 days) and be re-read against new cues; a number never ages | R1 | G5 | 0.5 |

Not to do: ask a location question "to confirm"; infer a country from a name
or a language beyond the Swahili rule; add a third-party people database.
Measure with R1's health number and the market-evidence case suite.

## 8. Evidence

`app/core/countries.py`, `app/core/phone.py`, `app/services/market.py`,
`app/agent/runtime.py` (`run_turn`, `_meta_market`, `_kes_for_swahili`),
`app/routers/web_chat.py` (`_country_from_ip`), `app/agent/tools.py`
(`_capture_customer`, `_capture_contact`, `_save_profile_fields`),
`app/services/messaging.py`, `app/services/identity.py`,
`app/services/meta_enrich.py`, `app/models/person.py`, `app/services/merge.py`,
`app/services/parish.py`, `app/agent/memory.py`, `app/agent/prompt.py`,
`app/services/customer_state.py`. Tests: `test_market_currencies`,
`test_market_evidence`, `test_market_lock_and_stock_checks`,
`test_meta_kenyan_market`, `test_identity_spine`, `test_identity_and_history`,
`test_merge`, `test_ask_only_the_open_details`, `test_intelligence_floors`.
Not measured: how often a Meta contact is still unplaced after three turns;
how often a profile name is not a person's name (needs the admin credential).

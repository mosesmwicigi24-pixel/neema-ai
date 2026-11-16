# Rands (and pounds) from the hub's rates

Owner's word, 2026-11-16: "Yes, quote rands from the hub rates." Status: **on the branch, tested without the model; not merged.**

## What was happening

The hub's Currencies page sets a customer price per currency: KES 6.50 = 1 ZAR, KES 149.99 = 1 GBP, KES 7.14 = 1 ZMW, KES 100 = 1 USD. Neema quoted a South African customer in dollars and, when asked for rands, converted the dollar figure at the day's market rate from a public feed. A KES 13,000 cassock was R 2,000 on the hub and about R 2,130 from Neema, moving daily.

## What the hub sends (read 2026-11-16, `GET /api/v1/products`, 40 products)

| Currency | Products with a hub price row | Rate read from the rows |
|---|---|---|
| KES | 40 | — |
| USD | 40 | — |
| ZMW | 40 | KES 7.14 |
| GBP | 17 | KES 150 |
| ZAR | 8 | KES 6.50 |

The hub has no endpoint for the rates themselves (five likely paths answered 404). The rates are visible in the product prices it writes from them.

## The change

- `services/fx.hub_kes_per_unit`: the hub's KES-per-unit for each currency, read from the catalogue's own price rows (the middle value across products; a currency on fewer than three products is left out; prices under KES 500 are ignored because whole-unit rounding blurs them).
- When a customer asks for a currency the hub prices in, the turn uses that rate and tells the writer it is **our own rate**, rounded to the whole unit, never "today's rate" or "approximately". The gate verifies figures against the same rate.
- A currency the hub does not price in (naira, cedis, …) still uses the public daily rate, as before.
- Change a rate on the hub and Neema follows within the catalogue cache (10 minutes), once the hub has rewritten its product prices.

No setting, no migration. USD stays KES/100.

## Not changed, and decisions left to the owner

- **South African customers are still quoted in dollars first**, with rands when they ask. Quoting rands from the start is a market-currency change (it also decides what currency the order and payment link carry) and was not part of this instruction.
- **Kwacha fallback:** a product with no hub kwacha row falls back to KES 5 = 1 ZMW (`zmw_kes_rate`), the figure the owner gave earlier; the hub now says 7.14. All 40 products read today have a kwacha row, so the fallback is not in use.
- **GBP reads as KES 150, the hub page says 149.99**: the hub's whole-pound rounding hides the last cent of the rate. On a KES 15,000 cassock both give £100.

## Not verified

- Not run with the model: the writer's wording with the new line has not been seen.
- Only 8 products carry a rand row. If the hub stops writing them, or fewer than three remain, Neema falls back to the public rate without saying so to anyone but the log.

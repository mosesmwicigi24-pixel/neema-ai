# Hub integration scripts

One-off, auditable operations run against the Bethany House hub
(`bethany_laravel` container) in support of Neema's hub integration.

## `backfill_aliases.php`

Backfills product `aliases` in the hub from Neema's original catalogue
(`apps/api/db/seed.sql`). Matches hub products by SKU (exact) → English name
(exact) → normalised name → hub-name-equals-a-Neema-alias, and writes aliases
**only where currently empty** (idempotent, non-destructive).

```bash
# from the repo, produce the mapping, then run in the container:
docker cp neema_aliases.json bethany_laravel:/tmp/neema_aliases.json
docker cp scripts/hub/backfill_aliases.php bethany_laravel:/tmp/
docker exec bethany_laravel php /tmp/backfill_aliases.php            # dry-run
docker exec bethany_laravel php /tmp/backfill_aliases.php --commit   # apply
```

First run (2026-07-07): 16 of 50 hub products aliased; the rest are new/renamed
products with no Neema equivalent. Aliases feed the AI's order-line resolution
and the operator catalogue search.

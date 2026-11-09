# Customers in aggregate — slice 16 (2026-11-09)

The fourth implementation slice of the owner's directive "Unified Customer
Intelligence, Geographic Discovery & Commercial Profiling" (Phase 4,
"geographic / market aggregation"), following the audit
(`CUSTOMER_INTELLIGENCE_AUDIT.md` §7, §8 item 5) and slices 13–15. No model
call, no migration, nothing stored; counts only.

## 1. What the audit found, and what changed

| Audit finding (§7) | Before | After |
|---|---|---|
| No endpoint or page aggregates customers by country or language | channel counts in `/stats` only; the conversation list resolved a country per row and never aggregated it | `GET /admin/reports/segments` (`services/segments.py`) and a **Customers** tab on Reports: by market, by language, by channel |
| Inferred and confirmed geography indistinguishable | — | each customer's market is the geography decision (slice 13); a placement a person said or confirmed (`stated`, `operator`) counts as **confirmed**, one from the number, the connection or a profile locale as **inferred**, and nothing-places-them as **unknown**; the table keeps the two apart per country, with totals |

## 2. What the report reads

Live users (merged-away rows and tombstoned persons excluded), their persons'
state and their conversations, in three bulk queries. Market: `geography.decide`
with the telephone country from the handle as the fallback, then
`users.country_iso` (the web visitor's connection) when the person has no
record. Language: `contact_preferences.language` as the scribe writes it
("Unknown" when none). Channel: a customer counts once per channel they have
written on. The response carries a `basis` block saying exactly this, and the
panel shows it on hover.

No handle, name or message text leaves the service.

## 3. Tests

- `tests/test_segments.py` (5): the per-customer placement and its basis
  (words over the number, an operator's confirmation, the number alone, the
  IP, the web row's country, a Meta id with nothing); the summary's markets
  (Bahrain and South Africa absent when the words say Kenya and Zambia),
  languages and channels; an empty set; the report on a scripted database
  excluding a tombstoned person and counting a customer once per channel; the
  endpoint delegating to the service.
- Web: `tsc --noEmit` clean; the build result is in the regression report.

## 4. Not done

Aggregation by shipping destination or city (the records exist on the
person; a column each when the operators ask); a period filter (the report
is "as of now"); no export. The directive's remaining items — the fuller
Profile UX (verify / correct controls, aging) and the model-dependent
validation — are listed in `UNFINISHED_REGISTER.md`.

## 5. Rollback

`git revert` of the squash commit. Nothing stored.

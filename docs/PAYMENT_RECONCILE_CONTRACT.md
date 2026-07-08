# Payment → person reconciliation — hub ⇄ neema contract

The deterministic identity bridge (lever 2 of `MULTICHANNEL_IDENTITY_PLAN.md`).
When the Bethany House hub confirms an M-Pesa payment it knows the **payer MSISDN
+ registered name**. Relaying that to neema binds the payer into the phone-anchored
person world — the only signal precise enough to auto-link across identity worlds.

**neema receiver (built, live on `epic/multichannel-identity`):**

```
POST /api/n8n/payment
Header:  X-N8N-Secret: <n8n_api_secret>        # same secret as the other bridge calls
Body (JSON):
  {
    "payer_msisdn": "254712345678",   // REQUIRED. Any format — 0712…, +254…, 254… — canonicalized to E.164.
    "payer_name":   "Jane Wanjiru",   // optional. M-Pesa registered name.
    "mpesa_ref":    "QGH1XYZ789",     // optional. M-Pesa transaction code (stored as a portable token).
    "hub_order_id": 4211,             // optional. Hub order id — stamps the matching local order_event with the person.
    "order_number": "BH-1042",        // optional. Human order number (stored as a portable token).
    "region":       "KE"              // optional, default KE. Default region for a *local* (no country code) number.
  }
```

**Response:**

```jsonc
// resolved
{ "resolved": true,
  "person_id": "…uuid…",
  "matched_via": "whatsapp_phone" | "phone_identifier" | "phone_merge" | "new_person",
  "e164": "+254712345678",
  "order_events_stamped": 0 | 1 }
// unparseable MSISDN (never an error — a payment webhook must not break)
{ "resolved": false, "reason": "unparseable_msisdn", "msisdn": "…" }
```

**Semantics** (`apps/api/app/services/reconcile.py`): the payer is resolved to a
person by **exact, country-safe E.164** — (1) an existing WhatsApp identity for
the same number (same human), else (2) an existing `phone` identifier, else (3) a
new phone-only person. If both a WhatsApp person and a separate phone-only person
exist for the number, they are **auto-merged** (deterministic Tier-1; WhatsApp kept
primary, reversible). The phone (+ any ref/order number) is stored as an
`identifier`, and the matching local `order_event` is stamped with the person.

**Idempotent** — re-posting the same payment re-resolves to the same person and
re-attaches the same tokens without creating duplicates.

**Hub TODO (bethany-house `feat/customer-country-e164`):** on M-Pesa
confirmation, POST the payload above to neema. Send the payer MSISDN exactly as
Daraja provides it (do not strip the country code) — neema canonicalizes. Fire it
best-effort/async so a neema hiccup never blocks the hub's own payment flow.

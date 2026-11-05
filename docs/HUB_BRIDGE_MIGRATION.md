# Hub bridge — repointing the hub plugin to `/api/hub`

The Bethany House hub (WordPress plugin) pushes payments, order events and
customer-history snapshots into Neema. The plugin is still configured with the
older base path `/api/n8n` and header `X-N8N-Secret`; the canonical names are
`/api/hub` and `X-Hub-Secret`. Both are served by the same router today, so
nothing is broken — this is the two-line change that moves the hub onto the
clean names, after which the older alias can be dropped from Neema.

## What changes on the hub (WordPress plugin) side

| | Current plugin config (works today) | Clean names (work today too) |
|---|---|---|
| Base path | `https://neema.bethanyhouse.co.ke/api/n8n` | `https://neema.bethanyhouse.co.ke/api/hub` |
| Auth header | `X-N8N-Secret: <secret>` | `X-Hub-Secret: <secret>` |
| Secret value | *(unchanged — same value)* | *(unchanged — same value)* |

The three pushes keep their route names and bodies exactly:

- `POST /api/hub/payment` — captured M-Pesa payment (see
  `PAYMENT_RECONCILE_CONTRACT.md` for the body)
- `POST /api/hub/order-event` — order event
- `POST /api/hub/customer-history` — customer-history snapshot

Both base paths and both headers are live **simultaneously** — the hub can
switch one push at a time with zero downtime, in any order, whenever
convenient. Nothing needs to be coordinated with a Neema deploy.

## The secret on the Neema box

The API reads the shared secret from `HUB_BRIDGE_SECRET`, and still accepts
the older env name `N8N_API_SECRET`, so an existing box `.env` needs no edit.
When convenient, rename the key in the box `.env` (same value) and restart the
API.

## Verifying a switched push

A correct call returns the same responses as before. A quick smoke from the
hub server (expects `403 Forbidden` — proves the route is reachable and
guarded; a `404` means the path is wrong):

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  -H "Content-Type: application/json" -d '{}' \
  https://neema.bethanyhouse.co.ke/api/hub/payment      # → 403 without the header
```

## Afterwards (Neema side) — evidence-gated removal

Every authenticated push that still uses the older surface (old prefix or old
header) bumps a daily counter, and the **08:00 standup** reports it:

> 🌉 Hub bridge: N push(es) yesterday still used the older /api/n8n alias …

Switch the plugin, then watch the standup. When that line has been absent for
about a week, the alias is provably quiet — then delete in
`apps/api/app/main.py` the alias mount line (marked with a comment) and the
`x_n8n_secret` parameter in `hub_bridge.verify_hub_secret`, and drop the
`N8N_API_SECRET` alias from `hub_bridge_secret` in `app/core/config.py`.
`tests/test_hub_bridge_contract.py` pins today's dual-mount state; update it in
that same change.

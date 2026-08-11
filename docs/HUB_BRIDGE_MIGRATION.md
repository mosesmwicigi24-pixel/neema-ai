# Hub bridge migration — off the n8n-era paths

n8n is retired; the only reason `/api/n8n/*` still exists is that the hub's
plugin posts there. This is the two-line change that moves the hub onto the
clean names, so the legacy surface can be dropped entirely.

## What changes on the hub (WordPress plugin) side

| | Old (works today) | New (works today too) |
|---|---|---|
| Base path | `https://neema.bethanyhouse.co.ke/api/n8n` | `https://neema.bethanyhouse.co.ke/api/hub` |
| Auth header | `X-N8N-Secret: <secret>` | `X-Hub-Secret: <secret>` |
| Secret value | *(unchanged — same value)* | *(unchanged — same value)* |

The three pushes keep their route names and bodies exactly:

- `POST /api/hub/payment` — captured M-Pesa payment (see
  `PAYMENT_RECONCILE_CONTRACT.md` for the body)
- `POST /api/hub/order-event` — order event
- `POST /api/hub/customer-history` — customer-history snapshot

Both the old and new base path + header are live **simultaneously** — the hub
can switch one push at a time with zero downtime, in any order, whenever
convenient. Nothing needs to be coordinated with a Neema deploy.

## Verifying a switched push

A correct call returns the same responses as before. A quick smoke from the
hub server (expects `403 Forbidden` — proves the route is reachable and
guarded; a `404` means the path is wrong):

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
  -H "Content-Type: application/json" -d '{}' \
  https://neema.bethanyhouse.co.ke/api/hub/payment      # → 403 without the header
```

## Afterwards (Neema side)

Once the hub posts only on `/api/hub/*` with `X-Hub-Secret`, delete in
`apps/api/app/main.py` the legacy mount line (marked with a comment) and the
`x_n8n_secret` parameter in `hub_bridge.verify_hub_secret` — and, if desired,
rename the `N8N_API_SECRET` env var to a clean name in the same change as the
box `.env` edit. `tests/test_n8n_retirement.py` pins today's dual-mount state;
update it in that same change.

# Web storefront chat endpoint (`POST /web/chat`)

Lets the **bethanyhouse.co.ke** storefront's chat widget call **this agent**
instead of running its own model — as a new **`web`** channel. Same brain as
WhatsApp / Messenger / Instagram: `route_model` (Sonnet‑5 main / Haiku light),
the tool loop, prompt caching, cross‑conversation memory, and hub grounding.

The one difference from the messaging channels: **the cart and payment live on
the storefront**, not here. So on `web` the agent never calls `update_cart` /
`create_order` / `whatsapp_checkout_link`. Instead it returns **product cards**
(with the same hub **slug** the storefront/POS use) and one‑tap **actions** the
site renders against its own cart + M‑Pesa/Card checkout. A human handoff comes
back as a **`wa.me` link** (the widget can't send WhatsApp itself).

---

## Endpoint

`POST /web/chat` — served by the FastAPI app (`apps/api`, port `8000`), mounted at
`/web`.

Reachable in two ways (see [Networking](#networking)):

| From | URL |
|------|-----|
| Storefront **server**, same VPS (recommended, no nginx hop) | `http://127.0.0.1:8000/web/chat` |
| Storefront **server**, same docker network | `http://api:8000/web/chat` |
| Public (via host nginx `location /web/`) | `https://neema.bethanyhouse.co.ke/web/chat` |

## Auth (server‑to‑server)

Every request must carry the shared secret in a header:

```
X-Storefront-Key: <token>
```

- Set the **same value** in the API env (`STOREFRONT_KEY`) and in the storefront
  env. The browser never sees it — the storefront's **server** adds the header.
- Missing/wrong key → **401**. `STOREFRONT_KEY` unset on the API → **503**
  (channel is off until configured).

Generate a token with `openssl rand -base64 48` (mirrors the other secrets in
`.env.example`).

## Request body

```jsonc
{
  "session_id": "stable-per-browser id",          // required — memory/conversation key
  "message": "the customer's latest text",         // required unless `image` is sent
  "history": [                                       // optional — the storefront owns the transcript
    {"role": "user",      "content": "…"},
    {"role": "assistant", "content": "…"}
  ],
  "page_context": {                                  // optional — grounds the reply on the current page
    "path": "/product/x", "product_slug": "x", "category": "y"
  },
  "locale": "en-KE",                                 // optional — sets the KES/USD quote gate
  "phone":  "2547…",                                 // optional — if present, unifies memory with WhatsApp
  "image":  "data:image/jpeg;base64,…"               // optional — for vision / measurement
}
```

Notes:
- **`session_id`** is the memory + conversation key. Keep it stable per browser
  (e.g. a first‑party cookie / localStorage id). Reusing it across visits gives
  the shopper continuity.
- **`history`** is authoritative — the widget owns the visible transcript, so
  send the running turns each call (last ~24 are used). The server keys memory on
  `session_id`, not on this list.
- **`phone`** (when the shopper shares one) links this web session to the matching
  WhatsApp customer, so both share **one** memory + order history.
- **`locale`** / `phone` decide whether chat quotes are in **KES** (Kenya) or
  **USD** (everyone else). Card prices are rendered by the storefront in the
  shopper's own currency regardless.

## Response body

Only `reply` is guaranteed; the rest are present when relevant (arrays may be
empty, `handoff.required` defaults to `false`).

```jsonc
{
  "reply": "the assistant's message",
  "products": [                                      // hub slugs — render matching cards
    {"slug": "<hub product slug>", "reason": "why it fits"}
  ],
  "actions": [                                       // one-tap actions for the storefront
    {"type": "view_product",  "label": "View White Cassock",   "value": "white-cassock"},
    {"type": "add_to_cart",   "label": "Add White Cassock to cart", "value": "white-cassock"},
    {"type": "request_quote", "label": "Request a quote — Cope","value": "purple-cope"},
    {"type": "whatsapp",      "label": "Continue on WhatsApp",  "value": "https://wa.me/2547…"}
  ],
  "quick_replies": [
    {"id": "show-colours", "label": "Show colours"}
  ],
  "handoff": {"required": false, "url": "https://wa.me/2547…"}
}
```

- **`products[].slug`** is the hub product slug — identical to what the storefront
  and POS use, so the site can render matching cards. Slugs are resolved
  **server‑side** against the live hub catalogue, so an invented name never
  surfaces a card (grounding is preserved).
- **`actions[].value`** is the hub slug for `view_product` / `add_to_cart` /
  `request_quote`, and a `wa.me` URL for `whatsapp`. The storefront runs its own
  cart + checkout — the agent never takes payment here.
- **`handoff.url`** is always the storefront's WhatsApp fallback link (when a
  handoff number is configured); `required` is `true` when the agent explicitly
  escalated (refund, complaint, bespoke request, "talk to a person").

## Web‑channel rules (enforced)

- **No payment/cart here.** The `web` tool set excludes `update_cart` /
  `create_order` / `whatsapp_checkout_link`. The agent uses `recommend_products`
  → the site renders cards + `view_product` / `add_to_cart` actions.
- **Human handoff = `wa.me` link.** `handoff_to_human` on `web` returns
  `handoff.url` + a `whatsapp` action; the widget can't message WhatsApp itself.
- **Grounding unchanged.** Products/prices come from `search_catalog` (the hub) —
  never invented, exactly as on WhatsApp/Meta.

---

## Networking

On the VPS, `api` is published on `127.0.0.1:8000` (see
`docker-compose.vps.yml`). The storefront runs on the **same box**, so its server
can call the agent **directly** with no nginx hop:

```
POST http://127.0.0.1:8000/web/chat
```

To also expose it publicly at `neema.bethanyhouse.co.ke/web/chat`, add a
`location /web/` block to the **host** nginx (the bundled `nginx/nginx.conf`
already has it for standalone installs):

```nginx
location /web/ {
    proxy_pass         http://127.0.0.1:8000;   # the api container
    proxy_http_version 1.1;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
}
```

Reload nginx after adding it (`nginx -t && systemctl reload nginx`).

## Config

| Env var | Purpose |
|---------|---------|
| `STOREFRONT_KEY` | Shared secret for the `X-Storefront-Key` header. Unset → `/web/chat` is `503`. |
| `WHATSAPP_HANDOFF_NUMBER` | The number the `wa.me` handoff/fallback link points to (already used by other channels). |

The web channel reuses everything else already configured for the agent
(`ANTHROPIC_API_KEY`, `TIER2_*`, `HUB_*`, `USD_KES_RATE`, …).

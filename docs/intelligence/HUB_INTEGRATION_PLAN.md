# The hub as the one source of truth — inventory and plan

Owner's directive, 2026-11-16: "The hub is the center … every aspect of this app should get its first-hand information, the truth from the hub." Status: **investigation and proposal. Nothing in this document is built.**

The hub cannot be seen or edited from this repository. Everything below about the hub is what Neema's code calls and what its public API returned.

## 1. Where each fact comes from today

| Fact | Today | Source of truth today |
|---|---|---|
| Products, variants, images, made-to-order flag, measurement spec | Read from the hub, cached 10 minutes | **Hub** |
| Prices in KES, USD, ZMW (and ZAR, GBP rows) | Read from the hub | **Hub** |
| Order creation, order status, payment status, payment link | Created in and read from the hub | **Hub** |
| Order events (paid, shipped, delivered, delayed, refund) | Pushed by the hub | **Hub** |
| A customer's order history and lifetime spend | Hub, but only in the staff customer panel | **Hub (staff only)** |
| What the AI remembers of a customer's past orders | Neema's own mirror of orders | Neema |
| Orders screen, its badge, "pending orders" | Neema's own mirror and its own triage flag | Neema |
| Revenue and performance figures | Computed by Neema from its mirror | Neema |
| Customer tier (VIP, loyal, at risk) | Computed by Neema from hub figures | Neema |
| Customer name, parish, measurements, notes | Neema's tables; only name and phone reach the hub, at order time | Neema |
| Offers and campaigns | Set in Neema's dashboard, sent to the hub as a line discount | Neema |
| Carts in progress, quotations | Neema only; a quotation is not stored anywhere | Neema |
| Currency rules (USD = KES/100, kwacha fallback 5, which countries get which currency) | Neema settings and code | Neema |
| Payment lines (M-Pesa and Airtel numbers), which countries can use Mukuru | Neema settings and instructions | Neema |
| Shop address, opening hours, phone numbers | Neema's instructions | Neema |
| Delivery fee (KES 350), courier (DHL), transit times, pickup, "no other branch" | Neema's instructions | Neema |
| Production lead times (shirts 24 h, cassocks 5 days, copes 4 days) | Neema setting | Neema |
| Product knowledge (what a set contains, 40 cups per tray, which items go together, other names for an item) | Neema's instructions and code tables | Neema |
| Example prices inside Neema's instructions | Written by hand, about 40 figures | Neema (some already stale) |
| A second, local product table that the dashboard can still edit | Neema | Neema |
| Staff accounts and roles | Neema's own logins; no shared login with the hub | Neema |
| Conversations, messages, calls | Neema | Neema (by nature) |

Two examples of the cost of the "Neema" rows: the instructions still say "Our Cassock Set is $210" where the hub says $195, and the Orders badge counts Neema's own triage flag, not the hub's order state.

## 2. Proposed principle

The hub owns every **business fact**: what is sold, at what price, to whom, what was ordered and paid, where the shop is, how delivery works, what offer is running, who the staff are. Neema owns **conversation**: messages, calls, what the AI is doing in a chat, and how it speaks. Neema keeps no second copy of a business fact that can drift; where it must keep a copy to answer quickly, the copy is a cache with the hub's timestamp, refreshed by a hub event.

## 3. Plan

### Stage A — Neema only, no hub change (can start now)

| # | Change | Why |
|---|---|---|
| A1 | The AI's memory of a customer's past orders reads the hub's customer record (the endpoint staff already use) | The AI and the staff see the same history |
| A2 | Orders screen, badge and revenue figures are driven by the hub's order and payment state; Neema's own triage flag becomes a note beside it | One answer to "how many orders are waiting" |
| A3 | Hand-written prices leave Neema's instructions; examples are filled from the live catalogue when the instructions are built, and a test fails if a price is typed in | A price can no longer go stale in the instructions |
| A4 | The local product table becomes read-only in the dashboard and is used only when the hub is unreachable | No second catalogue to edit |
| A5 | The kwacha fallback uses the hub's rate (as PR #377 does for rands) | Removes the 5 vs 7.14 mismatch |
| A6 | A "sources" check in `/api/health`: for each fact above, where it came from and how old the copy is | The owner can see drift without reading code |

### Stage B — needs the hub to expose something (hub-side work)

| # | The hub provides | Neema then |
|---|---|---|
| B1 | **Business profile**: address, hours, phone lines, payment lines, delivery fees and couriers, lead times, branches | Reads it; the same facts leave Neema's settings and instructions |
| B2 | **Currencies**: the customer-price rates and which country is quoted in which currency | Reads it directly (replaces reading rates out of product prices) |
| B3 | **Offers**: the running promotions | Reads them; the offer editor in Neema's dashboard is retired |
| B4 | **Customer write-back**: accept name, parish, role, measurements for a customer; a "customer changed" event | Sends what it learns in chat; reads the hub's customer as the master |
| B5 | **Product knowledge fields**: set contents, what an item comes with, companion items, other names | Reads them; the code tables shrink to language handling only |
| B6 | **Draft orders / quotations**: accept a cart or quotation as a draft | A cart and a quotation become hub records staff can see |
| B7 | **Events** for catalogue and price changes, confirmed as sent | Refreshes at once instead of within 10 minutes |
| B8 | **Reports**: sales and revenue figures | Shows the hub's numbers, not its own arithmetic |
| B9 | **Staff sign-in**: one login for the hub and Neema | Staff and roles are managed in one place |

### Stage C — stays in Neema

Conversations, messages, calls and recordings; the AI's behaviour rules and tone; safety gates; outreach timing. These are not business records. The hub can be given a view of them (it already pulls a message summary).

## 4. What is not known

- Who maintains the hub and whether Stage B can be built there.
- Which events the hub sends today, and whether it sends a catalogue-changed event.
- Whether the hub already has profile, offers, currency or reports endpoints that Neema simply does not call. Five guessed currency paths answered 404; the rest were not probed.
- The live server's settings (`BUSINESS_INFO`, outlet id, event secret).
- What the Orders badge figure (303) counts in production; the code counts Neema's own "pending" flag.

## 5. Risks

- **Availability.** The more Neema reads live from the hub, the more a hub outage stops a sale. Each read keeps a last-good copy with its age, and the AI hands to a person when a copy is too old to quote from.
- **Speed.** A reply should not wait on several hub calls; facts are cached and refreshed by events.
- **Order of work.** Stage A changes what staff see on the Orders screen; it should be shown to the owner before it replaces the current one.

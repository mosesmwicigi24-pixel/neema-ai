"""The hub bridge — what the Bethany House hub posts into Neema.

Three pushes: a captured M-Pesa payment (identity reconciliation), an order
event, and a customer-history snapshot. Canonical prefix: `/api/hub/*` with the
`X-Hub-Secret` header. The same router is ALSO mounted at the older
`/api/n8n/*` prefix, accepting the older `X-N8N-Secret` header, because that is
the URL and header the hub's plugin is configured with today. Nothing behind
either prefix depends on anything but this API; the alias is only the hub
plugin's current address and stays until the hub side is repointed (see
docs/HUB_BRIDGE_MIGRATION.md). Both headers carry the SAME secret value
(`HUB_BRIDGE_SECRET` in the box .env; the older `N8N_API_SECRET` name is still
read).
"""
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.core.config import settings
from app.services import messaging as svc
from app.schemas.bridge import OrderEventDto, CustomerHistoryDto, PaymentDto

router = APIRouter()


async def verify_hub_secret(request: Request,
                            x_hub_secret: str | None = Header(None),
                            x_n8n_secret: str | None = Header(None)):
    """One shared secret, two accepted header names (clean + the older one the
    hub plugin still sends).

    Fails CLOSED: an unconfigured secret rejects everything — the old check
    compared equal empty strings, which would have waved through a request
    carrying an empty legacy header on a box with no secret set."""
    supplied = x_hub_secret or x_n8n_secret
    if not settings.hub_bridge_secret or supplied != settings.hub_bridge_secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    # Migration telemetry: count authenticated pushes still arriving on the
    # older surface (old prefix or old header). The 08:00 standup reads the
    # daily counter — a week of silence after the hub plugin is repointed is
    # the evidence that makes dropping the alias mount safe. Best-effort.
    if (not x_hub_secret) or request.url.path.startswith("/api/n8n/"):
        try:
            from datetime import datetime, timezone
            redis = request.app.state.redis
            key = f"bridge:legacy:{datetime.now(timezone.utc).strftime('%Y%m%d')}"
            await redis.incr(key)
            await redis.expire(key, 14 * 24 * 3600)
        except Exception:
            pass


# ── Orders (hub → Neema) ──────────────────────────────────
@router.post("/order-event", dependencies=[Depends(verify_hub_secret)])
async def upsert_order_event(body: OrderEventDto, request: Request, db: AsyncSession = Depends(get_db)):
    return await svc.upsert_order_event(db, body, request.app.state.redis)


# ── Customer History (hub → Neema) ────────────────────────
@router.post("/customer-history", dependencies=[Depends(verify_hub_secret)])
async def upsert_customer_history(body: CustomerHistoryDto, db: AsyncSession = Depends(get_db)):
    return await svc.upsert_customer_history(db, body)


# ── Payment → person reconciliation (the deterministic identity bridge) ──────
@router.post("/payment", dependencies=[Depends(verify_hub_secret)])
async def reconcile_payment(body: PaymentDto, db: AsyncSession = Depends(get_db)):
    """The hub relays a captured M-Pesa payment here (payer MSISDN + name +
    order refs). We bind the payer to a person deterministically by phone —
    the load-bearing bridge that pulls no-phone social leads into World A. See
    app/services/reconcile.py and docs/PAYMENT_RECONCILE_CONTRACT.md."""
    from app.services.reconcile import reconcile_payment as _reconcile
    result = await _reconcile(
        db,
        payer_msisdn=body.payer_msisdn,
        payer_name=body.payer_name,
        mpesa_ref=body.mpesa_ref,
        hub_order_id=body.hub_order_id,
        order_number=body.order_number,
        region=body.region,
    )
    await db.commit()

    # Event agency (Phase A): a matched direct M-Pesa payment gets the same
    # instant thank-you as a hub order.paid — one guard prevents doubles when
    # the hub also reports it. Best-effort; reconciliation already succeeded.
    if result.get("resolved") and settings.hub_events_secret:
        try:
            import asyncio as _aio
            _redis = None
            try:
                from app.main import app as _app                 # runtime state
                _redis = getattr(_app.state, "redis", None)
            except Exception:
                pass
            event = {"id": f"mpesa:{body.mpesa_ref or body.payer_msisdn}",
                     "type": "order.paid",
                     "order_number": body.order_number,
                     "customer_phone": body.payer_msisdn}
            _aio.create_task(_run_paid_event(event, _redis))
        except Exception:
            pass
    return result


async def _run_paid_event(event: dict, redis) -> None:
    from app.database import AsyncSessionLocal
    from app.services import hub_events as _events
    try:
        async with AsyncSessionLocal() as db:
            await _events.handle_event(db, redis, event)
    except Exception:
        pass

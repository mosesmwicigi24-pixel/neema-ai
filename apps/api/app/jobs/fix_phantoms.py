"""One-shot repair: remove the phantom "WhatsApp" contacts minted from Meta ids.

Opening a Messenger/Facebook contact's CRM panel used to leak the 16-17 digit
Meta id into WhatsApp-space: a (whatsapp, <psid>) Identity, a User whose phone
displayed the PSID, and a message-less whatsapp Conversation. The mint paths are
now guarded (is_plausible_phone); this cleans up what already exists.

Dry-run by default — prints what it WOULD do. Pass --apply to execute:

    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.fix_phantoms            # preview
    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.fix_phantoms --apply    # fix
"""
from __future__ import annotations

import argparse
import asyncio

# Full model registry so mappers configure standalone.
import app.models.agent      # noqa: F401
import app.models.catalog    # noqa: F401
import app.models.conversation  # noqa: F401
import app.models.intercept  # noqa: F401
import app.models.message    # noqa: F401
import app.models.order_event  # noqa: F401
import app.models.person     # noqa: F401
import app.models.user       # noqa: F401

from sqlalchemy import select, func, delete

from app.core.phone import is_plausible_phone
from app.database import AsyncSessionLocal
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.person import Identity
from app.models.user import User


async def run(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN (nothing changed — pass --apply to fix)"
    print(f"── phantom-WhatsApp repair · {mode} ──")
    async with AsyncSessionLocal() as db:
        # 1. Phantom (whatsapp, <meta-id>) identities.
        idents = (await db.execute(
            select(Identity).where(Identity.channel == "whatsapp")
        )).scalars().all()
        phantoms = [i for i in idents if not is_plausible_phone(i.external_id)]
        for i in phantoms:
            others = (await db.execute(
                select(func.count(Identity.id)).where(
                    Identity.person_id == i.person_id, Identity.id != i.id)
            )).scalar_one()
            print(f"identity (whatsapp, {i.external_id}) — person has "
                  f"{others} other identit{'y' if others == 1 else 'ies'} → DELETE")
            if apply:
                await db.execute(delete(Identity).where(Identity.id == i.id))

        # 2. Users displaying a Meta id as their phone.
        users = (await db.execute(select(User))).scalars().all()
        bad_users = [u for u in users
                     if not is_plausible_phone(u.wa_id) and (u.phone or "") == (u.wa_id or "")]
        for u in bad_users:
            print(f"user {u.wa_id} — phone shows the Meta id → phone=NULL")
            if apply:
                u.phone = None

        # 3. Message-less whatsapp conversations keyed on a Meta id.
        convs = (await db.execute(
            select(Conversation).where(Conversation.channel == "whatsapp")
        )).scalars().all()
        bad_convs = []
        for c in convs:
            if is_plausible_phone(c.wa_id or c.external_id):
                continue
            n = (await db.execute(
                select(func.count(Message.id)).where(Message.conversation_id == c.id)
            )).scalar_one()
            if n == 0:
                bad_convs.append(c)
                print(f"conversation whatsapp/{c.wa_id or c.external_id} — 0 messages → DELETE")
        if apply:
            for c in bad_convs:
                await db.execute(delete(Conversation).where(Conversation.id == c.id))

        if apply:
            await db.commit()
    print(f"── {'fixed' if apply else 'found'}: {len(phantoms)} phantom identit"
          f"{'y' if len(phantoms) == 1 else 'ies'} · {len(bad_users)} PSID-as-phone user(s) · "
          f"{len(bad_convs)} empty phantom conversation(s) ──")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Repair phantom WhatsApp contacts minted from Meta ids.")
    ap.add_argument("--apply", action="store_true", help="execute (default: dry-run preview)")
    asyncio.run(run(apply=ap.parse_args().apply))

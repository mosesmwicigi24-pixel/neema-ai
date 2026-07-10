"""One-shot backfill: scan past Messenger/IG/Facebook conversations for phone
numbers customers shared in chat (before capture_contact existed / was fixed),
normalize them against THEIR country, and save — the Vusumzi case, retroactively.

For each Meta contact without a phone: scan their inbound texts for a number,
resolve their country from the captured location (person.state.location or the
profile), normalize via to_e164 (0799… + South Africa → +27799…), then attach
the phone identifier, set it on the profile, and auto-link to an existing
WhatsApp identity for that number when one exists.

Dry-run by default:
    docker compose -f docker-compose.yml -f docker-compose.vps.yml \\
        exec -T api python -m app.jobs.backfill_contacts            # preview
    docker compose ... exec -T api python -m app.jobs.backfill_contacts --apply
"""
from __future__ import annotations

import argparse
import asyncio
import re

import app.models.agent      # noqa: F401
import app.models.catalog    # noqa: F401
import app.models.conversation  # noqa: F401
import app.models.intercept  # noqa: F401
import app.models.message    # noqa: F401
import app.models.order_event  # noqa: F401
import app.models.person     # noqa: F401
import app.models.user       # noqa: F401

from sqlalchemy import select

from app.core.countries import iso_from_text
from app.core.phone import to_e164, is_plausible_phone
from app.database import AsyncSessionLocal
from app.models.message import Message, MsgDirection
from app.models.person import Person, Identity, Identifier
from app.models.user import User

META = ("messenger", "instagram", "facebook")
# 9-18 chars of digits/spaces/dashes, optional leading + — then validated hard.
_PHONE_RE = re.compile(r"\+?\d[\d\s\-]{7,16}\d")


def _candidates(text: str) -> list[str]:
    return [re.sub(r"[\s\-]", "", m.group(0)) for m in _PHONE_RE.finditer(text or "")]


async def run(apply: bool) -> None:
    mode = "APPLY" if apply else "DRY RUN (pass --apply to save)"
    print(f"── contact backfill · {mode} ──")
    found = linked = 0
    async with AsyncSessionLocal() as db:
        idents = (await db.execute(select(Identity).where(
            Identity.channel.in_(META)))).scalars().all()
        for ident in idents:
            person = await db.get(Person, ident.person_id)
            user = (await db.execute(select(User).where(
                User.person_id == ident.person_id))).scalar_one_or_none()
            location = ((person.state or {}).get("location") if person else None) \
                or (user.location if user else None)
            region = iso_from_text(location) or "KE"

            # Already has a phone? Verify its country matches the known location —
            # early captures defaulted to Kenya (+254799… for a South African).
            existing = (await db.execute(select(Identifier).where(
                Identifier.person_id == ident.person_id,
                Identifier.type == "phone"))).scalars().all()
            if existing:
                from app.core.countries import resolve_country
                for idf in existing:
                    cur_iso = (resolve_country(idf.value) or {}).get("country_iso")
                    if not location or not region or cur_iso == region:
                        continue
                    # Re-normalize from the ORIGINAL chat candidates against the
                    # right country (safer than surgery on the stored value).
                    fixed = None
                    msgs0 = (await db.execute(select(Message.text).where(
                        Message.channel == ident.channel,
                        Message.external_id == ident.external_id,
                        Message.direction == MsgDirection.inbound))).scalars().all()
                    for t in msgs0:
                        for cand in _candidates(t or ""):
                            if is_plausible_phone(cand):
                                got = to_e164(cand, region)
                                if got and got != idf.value:
                                    fixed = got
                                    break
                        if fixed:
                            break
                    if fixed:
                        found += 1
                        who = (person.display_name if person else None) or ident.external_id
                        print(f"{ident.channel}/{who}: REGION FIX {idf.value} → {fixed} "
                              f"(location '{location}')")
                        if apply:
                            idf.value = fixed
                            idf.confidence = "self_reported"
                            if user is not None and user.phone in (None, "", idf.value):
                                user.phone = fixed
                continue
            has_wa = (await db.execute(select(Identity.id).where(
                Identity.person_id == ident.person_id,
                Identity.channel == "whatsapp").limit(1))).scalar_one_or_none()
            if has_wa:
                continue

            msgs = (await db.execute(select(Message.text).where(
                Message.channel == ident.channel,
                Message.external_id == ident.external_id,
                Message.direction == MsgDirection.inbound))).scalars().all()

            e164 = None
            for text in msgs:
                for cand in _candidates(text or ""):
                    if not is_plausible_phone(cand):
                        continue
                    got = to_e164(cand, region)
                    if got:
                        e164 = got
                        break
                if e164:
                    break
            if not e164:
                continue

            found += 1
            wa_match = (await db.execute(select(Identity).where(
                Identity.channel == "whatsapp",
                Identity.external_id == e164.lstrip("+")))).scalar_one_or_none()
            action = "phone saved" + (" + LINK to existing WhatsApp person" if wa_match else "")
            who = (person.display_name if person else None) or ident.external_id
            print(f"{ident.channel}/{who}: found {e164} (region {region}, "
                  f"location '{location or '-'}') → {action}")

            if not apply:
                continue
            from app.services.reconcile import attach_identifier
            await attach_identifier(db, ident.person_id, "phone", e164,
                                    source=f"{ident.channel}_chat_backfill",
                                    confidence="self_reported")
            if user is not None and not user.phone:
                user.phone = e164
            if wa_match is not None and wa_match.person_id != ident.person_id:
                from app.services.merge import merge_persons
                try:
                    await merge_persons(db, primary_person_id=wa_match.person_id,
                                        secondary_person_id=ident.person_id,
                                        primary_wa_id=e164.lstrip("+"))
                    linked += 1
                except Exception as exc:
                    print(f"  link failed: {exc}")
        if apply:
            await db.commit()
    print(f"── {'saved' if apply else 'found'}: {found} phone(s), {linked} cross-channel link(s) ──")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backfill phones shared in past Meta chats.")
    ap.add_argument("--apply", action="store_true", help="save (default: dry-run preview)")
    asyncio.run(run(apply=ap.parse_args().apply))

"""Parish accounts — group the people of one church into one customer.

Rev Grace, the parish secretary and the choir master are three contacts but ONE
buyer: their parish. This service is the single place that resolves a spoken
church name to a parish row, attaches people to it, and rolls a parish's members
up into institution-level numbers.
"""
from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.parish import Parish
from app.models.person import Person

_log = logging.getLogger("neema.parish")


def normalise(name: str | None) -> str:
    """One dedup key per church: lowercase, punctuation stripped, whitespace
    collapsed, 'saint' → 'st' — so "St. Mary's Nakuru", "st marys nakuru" and
    "Saint Marys Nakuru" are the SAME parish."""
    s = re.sub(r"[^\w\s]", "", (name or "").lower())
    s = re.sub(r"\bsaint\b", "st", s)
    return re.sub(r"\s+", " ", s).strip()[:200]


def is_plausible_parish(name: str | None) -> bool:
    """A real church name, not a stray word — at least two words or a known
    church-word ('cathedral', 'chapel', 'parish', …)."""
    n = normalise(name)
    if not n or len(n) < 4:
        return False
    church_words = {"parish", "cathedral", "chapel", "church", "basilica",
                    "ministries", "ministry", "diocese", "assembly", "temple"}
    return len(n.split()) >= 2 or any(w in n.split() for w in church_words)


async def find_or_create(db: AsyncSession, name: str,
                         location: str | None = None) -> Parish | None:
    """The parish row for a spoken name — existing when the normalised name is
    known, freshly created otherwise. None for noise."""
    if not is_plausible_parish(name):
        return None
    norm = normalise(name)
    existing = (await db.execute(
        select(Parish).where(Parish.norm == norm))).scalar_one_or_none()
    if existing is not None:
        if location and not existing.location:
            existing.location = location[:200]
        return existing
    p = Parish(name=" ".join((name or "").split())[:200], norm=norm,
               location=(location or None))
    db.add(p)
    await db.flush()
    return p


async def attach_person(db: AsyncSession, person_id, name: str,
                        location: str | None = None) -> Parish | None:
    """Put a person under their parish (creating it if new). Never OVERWRITES an
    existing affiliation with a different one silently — a person naming a second
    church keeps the first until a human decides; same church is idempotent."""
    if person_id is None:
        return None
    parish = await find_or_create(db, name, location)
    if parish is None:
        return None
    person = await db.get(Person, person_id)
    if person is None:
        return None
    if person.parish_id is None or person.parish_id == parish.id:
        person.parish_id = parish.id
        await db.commit()
        return parish
    _log.info("person %s already in another parish — not reassigning to %s",
              person_id, parish.name)
    return None


async def parish_of_person(db: AsyncSession, person_id) -> Parish | None:
    if person_id is None:
        return None
    person = await db.get(Person, person_id)
    if person is None or person.parish_id is None:
        return None
    return await db.get(Parish, person.parish_id)


async def members(db: AsyncSession, parish_id) -> list[Person]:
    return list((await db.execute(
        select(Person).where(Person.parish_id == parish_id,
                             Person.merged_into_id.is_(None)))).scalars().all())

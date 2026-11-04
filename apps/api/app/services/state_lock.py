"""Taking a row before rewriting its JSONB `state`.

users.state and persons.state are one document with many owners (crm_notes,
call_note_ids, agent_memory, the cart, measurements, tags…), and writers copy
the whole of it and write it back. A writer must therefore hold the row from
its read to its commit, or whatever lands in between is overwritten.
"""
from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_for_write(db: AsyncSession, row):
    """`row` locked and re-read, ready for its `state` to be rewritten. Call it
    immediately before reading the state you will write back, and commit soon
    after: never hold it across a model call or any other slow wait. Every path
    out must commit, or the lock outlives the write.

    Re-read as well as lock: sessions run expire_on_commit=False, so a row this
    session already holds — an agent turn keeps `user` for the whole model loop
    — would otherwise keep its old state, lock or no lock. The session's
    autoflush puts the caller's pending edits on the row first, so they survive
    the re-read.

    FOR NO KEY UPDATE (key_share): what an UPDATE of `state` takes anyway. It
    excludes other writers without blocking the foreign-key checks of rows being
    inserted against this one; FOR UPDATE would, and two sessions that each hold
    such a check and want the lock would deadlock.

    None stays None, and so does a row deleted meanwhile. A row not in the
    database yet has nothing to lock and is returned as it is."""
    insp = inspect(row, raiseerr=False)
    if insp is None or not insp.persistent:
        return row
    return await db.get(type(row), row.id, with_for_update={"key_share": True},
                        populate_existing=True)

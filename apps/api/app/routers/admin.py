from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, delete, or_
from app.core import money
from app.database import get_db
from app.models.conversation import Conversation, InterceptMode
from app.models.message import Message
from app.models.agent import Agent
from app.models.user import User
from app.models.person import Person, Identity
from app.models.call import Call  # noqa: F401 — register the mapper at boot
from app.models.parish import Parish  # noqa: F401 — Person.parish_id FK needs the table registered
from app.models.demand_signal import DemandSignal  # noqa: F401 — register at boot
from app.models.intercept import Intercept, InterceptAction
from app.schemas.conversation import ConversationListItem, InterceptRequest
from app.services.conversation import (
    intercept_conversation, release_conversation,
    transfer_conversation, send_agent_reply, approve_draft, send_agent_media,
)
from app.services import translate as translate_svc
import jwt
import logging
from app.core.security import decode_token
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

router = APIRouter()
_log = logging.getLogger("neema.admin")

# Most recent messages returned when a chat is opened. The inbox renders every
# message into the DOM (no virtualisation), and the thread query was unbounded,
# so one long-running customer could freeze the tab. 500 is far above a normal
# sales conversation — an agent never notices the ceiling, but the pathological
# case can no longer hang the page.
THREAD_LIMIT = 500


def _parse_before(before: str | None):
    """ISO timestamp → aware datetime, or None on anything unparseable — a bad
    cursor must degrade to 'first page', never to a 500."""
    if not before:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(before).replace("Z", "+00:00"))
    except Exception:
        return None


def _shape_messages_into(thread: list, msgs, agent_name_map: dict) -> None:
    """One message row → one thread item (shared by page one and older pages).
    Quoted messages resolve within the same fetched page — an older page's
    quote of a still-older message falls back to its cached text, no join."""
    _by_id = {str(m.id): m for m in msgs}
    for m in msgs:
        _q = _by_id.get(str(m.reply_to_id)) if getattr(m, "reply_to_id", None) else None
        thread.append({
            "id":            str(m.id),
            "type":          "message",
            "direction":     m.direction,
            "sender":        m.sender,
            "text":          m.text,
            "translation":     translate_svc.translation_for(m),
            "translated_from": getattr(m, "translated_from", None),
            "isNote":        m.media_type == "note",
            "agent_name":    agent_name_map.get(str(m.agent_id)) if m.agent_id else None,
            "created_at":    m.created_at.isoformat() if m.created_at else None,
            "media_type":    m.media_type if m.media_type != "note" else None,
            "media_id":      m.media_id,
            "media_url":     m.media_url,
            "media_caption": m.media_caption,
            "mime_type":     m.mime_type,
            "filename":      m.filename,
            "comment_context": m.comment_context,
            "reply_to": ({"id": str(m.reply_to_id), "text": m.reply_to_text,
                          "sender": m.reply_to_sender,
                          "media_type": (_q.media_type if _q and _q.media_type != "note" else None),
                          "media_url": (_q.media_url if _q and _q.media_type != "note" else None)}
                         if getattr(m, "reply_to_id", None) else None),
        })
bearer = HTTPBearer()


async def get_current_agent(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    # Only an access token opens the API. A refresh token lives 30 days and
    # exists to mint access tokens at /auth/refresh — accepted here, a leaked
    # one would be a month-long pass.
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token")

    result = await db.execute(select(Agent).where(Agent.id == payload["sub"]))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


# ── Conversations ─────────────────────────────────────────

@router.get("/conversations/resolve")
async def resolve_conversation(
    key: str = "",
    ref: str = "",
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Resolve a hub deep link to ONE conversation.

    The hub links to a chat by the customer's PHONE — the only key it has.
    That matches WhatsApp threads directly, but a Meta customer's thread is
    keyed by PSID and their phone may exist nowhere in identities (it was
    captured during ordering and lives on the order record). So resolution
    walks the strongest chain available:

      1. conversations.wa_id / external_id == the digits         (WhatsApp)
      2. ref (hub order number) -> order_events.person_id -> that person's
         identities -> their conversations                        (Meta orders)
      3. order_events.wa_id == digits -> person -> conversations  (phone-keyed
         order but PSID-keyed thread)
      4. identities.external_id == digits -> person -> conversations

    Preference within a person's threads: WhatsApp first, then most recent.
    Returns {"conversation_id": <id>|null} — the caller toasts on null.
    """
    from app.models.order_event import OrderEvent
    from app.models.person import Identity

    digits = "".join(ch for ch in (key or "") if ch.isdigit())

    async def by_external(ids: list[str]):
        if not ids:
            return None
        q = (select(Conversation)
             .where(or_(Conversation.wa_id.in_(ids), Conversation.external_id.in_(ids))))
        convs = (await db.execute(q)).scalars().all()
        if not convs:
            return None
        convs.sort(key=lambda c: (c.channel != "whatsapp",
                                  -(c.last_message_at.timestamp() if c.last_message_at else 0)))
        return convs[0]

    # 1. direct thread key
    if digits:
        conv = await by_external([digits])
        if conv:
            return {"conversation_id": conv.id}

    async def person_conversation(person_id):
        if not person_id:
            return None
        idents = (await db.execute(
            select(Identity.external_id).where(Identity.person_id == person_id)
        )).scalars().all()
        return await by_external(list({*idents}))

    # 2 + 3. the order knows the person even when identities don't know the phone
    clauses = []
    if ref:
        clauses.append(OrderEvent.hub_order_number == ref)
    if digits:
        clauses.append(OrderEvent.wa_id == digits)
    if clauses:
        events = (await db.execute(
            select(OrderEvent.person_id, OrderEvent.wa_id)
            .where(or_(*clauses))
            .order_by(OrderEvent.created_at.desc())
            .limit(5)
        )).all()
        for person_id, ev_wa in events:
            conv = await person_conversation(person_id) or await by_external([ev_wa] if ev_wa else [])
            if conv:
                return {"conversation_id": conv.id}

    # 4. the phone as a known identity
    if digits:
        pid = (await db.execute(
            select(Identity.person_id).where(Identity.external_id == digits).limit(1)
        )).scalar_one_or_none()
        conv = await person_conversation(pid)
        if conv:
            return {"conversation_id": conv.id}

    # 5. the phone as an IDENTIFIER — the designed home for captured phones
    # (capture_contact stores '+<digits>' with source=messenger_capture). This
    # is what makes the PLAIN phone link find a Meta customer with no order
    # ref: identifier -> person -> PSID identities -> thread. Stored values
    # carry a leading '+'; links send bare digits — match both spellings.
    if digits:
        from app.models.person import Identifier
        pid = (await db.execute(
            select(Identifier.person_id).where(
                Identifier.type == "phone",
                Identifier.value.in_([digits, f"+{digits}"]),
            ).limit(1)
        )).scalar_one_or_none()
        conv = await person_conversation(pid)
        if conv:
            return {"conversation_id": conv.id}

    return {"conversation_id": None}


@router.get("/conversations")
async def list_conversations(
    mode: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    tab: str | None = None,
    channel: str | None = None,
    tag: str | None = None,
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """The inbox, one page of PEOPLE at a time.

    With `limit`: {"items": [...conversation rows...], "next_cursor": str|null}.
    Items are every thread of the people on the page, so the per-person
    collapse is complete; pass next_cursor back to continue.

    Without `limit`: the legacy full array, kept for Reports (which aggregates
    over a date range and still needs every row) and for any browser holding a
    cached older bundle. The inbox itself no longer asks for it.
    """
    if limit is None:
        return await _conversation_rows(db, mode=mode)
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="limit must be 1-200")

    conditions = _inbox_conditions(
        agent_id=agent.id if agent else None,
        tab=tab, channel=channel, mode=mode, tag=tag, q=q,
    )
    keys, nxt = await _inbox_page(db, limit=limit, cursor=cursor, conditions=conditions)
    ids = await _conversations_for_rows(db, keys)
    return {"items": await _conversation_rows(db, conv_ids=ids), "next_cursor": nxt}


@router.get("/conversations/summary")
async def conversations_summary(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Every inbox badge, counted by the database over ALL conversations.

    These were counted in the browser over the list it held. Once the list is
    paged, that is a count of one page — so they come from here instead, in
    the same units as before:

      unread              conversations with an unread message (Unread tab)
      human / yours       human-held; human-held by me (Human, Yours, "N live")
      unread_messages     unread MESSAGE totals, overall and per channel —
                          the channel chips have always summed messages, not
                          conversations, and still do
      tags                every tag in use, not just those on loaded rows
    """
    from sqlalchemy import or_
    from app.models.conversation import InterceptMode
    from app.models.user import User

    unread_ids = _unread_conv_ids().subquery()
    unread_n = (await db.execute(select(func.count()).select_from(unread_ids))).scalar() or 0

    human_n, yours_n = (await db.execute(select(
        func.count().filter(Conversation.intercept_mode == InterceptMode.human),
        func.count().filter(
            (Conversation.intercept_mode == InterceptMode.human)
            & (Conversation.assigned_agent_id == (agent.id if agent else None))
        ),
    ))).one()

    # Unread message totals per channel, same definition as the row's `unread`.
    last_out = (
        select(Message.conversation_id.label("cid"), func.max(Message.created_at).label("last_out"))
        .where(Message.direction == "outbound")
        .where(or_(Message.media_type.is_(None), Message.media_type != "note"))
        .group_by(Message.conversation_id)
        .subquery()
    )
    per_channel = (await db.execute(
        select(Conversation.channel, func.count(Message.id))
        .select_from(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .outerjoin(last_out, last_out.c.cid == Message.conversation_id)
        .where(Message.direction == "inbound")
        .where(or_(last_out.c.last_out.is_(None), Message.created_at > last_out.c.last_out))
        .group_by(Conversation.channel)
    )).all()
    by_channel = {ch: int(n) for ch, n in per_channel if ch}

    # Only customers who HAVE a conversation: the filter narrows conversations,
    # so a tag worn only by someone who never messaged would offer an empty list.
    tag_rows = (await db.execute(
        select(func.jsonb_array_elements_text(User.state["tags"]).label("t"))
        .where(func.jsonb_typeof(User.state["tags"]) == "array")
        .where(User.wa_id.in_(select(Conversation.wa_id).where(Conversation.wa_id.isnot(None))))
        .distinct()
    )).scalars().all()

    return {
        "unread":          int(unread_n),
        "human":           int(human_n),
        "yours":           int(yours_n),
        "unread_messages": {"all": sum(by_channel.values()), **by_channel},
        "tags":            sorted({t for t in tag_rows if t}, key=str.lower),
    }


@router.get("/conversations/{conv_id}")
async def get_conversation(
    conv_id: UUID,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """ONE conversation, in exactly the shape the list returns.

    The hub's chat deep link resolves to a conversation id, and the inbox then
    has to render it. It could not: the client paints from a snapshot capped at
    600 rows, and the thread pane reads `conversations.find(c => c.id === ...)`,
    so a link to anything older than the 600 most recent threads selected an id
    that was not in the list and showed "Select a conversation" — the exact
    complaint. The full list is 13,000+ rows and 13 MB, so waiting for it is
    not an answer either.

    Declared after /conversations/resolve so that literal path still wins.
    """
    rows = await _conversation_rows(db, conv_id=conv_id)
    if not rows:
        raise HTTPException(status_code=404, detail="conversation not found")
    return rows[0]


# ── Inbox paging ──────────────────────────────────────────────────────────────
# The list used to return EVERY conversation — 14,000 rows, 13 MB, rebuilt and
# re-sent on a 60-second poll, with a 30-second client timeout it could lose to.
# Paging keys on inbox ROWS, not conversations: the inbox shows one row per
# PERSON (their WhatsApp, Messenger and Facebook threads collapse together), so
# a page holds whole people. Paging raw conversations would put someone's
# WhatsApp thread on page 1 and their Messenger thread on page 7 as a second,
# duplicate row.
#
# Order is the TRUE latest message, computed from messages through the
# (conversation_id, created_at) index — not conversations.last_message_at,
# which has drifted on ~2,300 threads because roughly eight write paths add a
# message without touching it. ~80 ms for a page at today's volume; if message
# volume grows ~10x, maintain the column instead and order by it.

_NEG_INF = "-infinity"


def _encode_cursor(sort_ts, row_key: str) -> str:
    import base64
    import json as _json
    ts = sort_ts.isoformat() if hasattr(sort_ts, "isoformat") else _NEG_INF
    raw = _json.dumps([ts, row_key]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str):
    """-> (sort_ts datetime | '-infinity', row_key) or None for a bad cursor."""
    import base64
    import json as _json
    from datetime import datetime as _dt
    try:
        pad = "=" * (-len(cursor) % 4)
        ts, key = _json.loads(base64.urlsafe_b64decode(cursor + pad))
        if not isinstance(key, str) or not key:
            return None
        return (ts if ts == _NEG_INF else _dt.fromisoformat(ts)), key
    except Exception:
        return None


def _row_key_expr():
    """One inbox row per person; a conversation with no person is its own row."""
    from sqlalchemy import String, cast, func, literal
    return func.coalesce(
        cast(Conversation.person_id, String),
        literal("c:") + cast(Conversation.id, String),
    )


def _latest_message_subq():
    """Each conversation's true latest message, staff notes excluded — the same
    definition the row builder uses for its preview and sort."""
    from sqlalchemy import func, or_
    return (
        select(
            Message.conversation_id.label("cid"),
            func.max(Message.created_at).label("last_at"),
        )
        .where(or_(Message.media_type.is_(None), Message.media_type != "note"))
        .group_by(Message.conversation_id)
        .subquery()
    )


async def _inbox_page(db: AsyncSession, *, limit: int, cursor: str | None, conditions: list):
    """One page of inbox rows -> (row_keys in order, next_cursor | None).

    `conditions` filter which CONVERSATIONS count toward a row; a person
    appears if any of their conversations qualifies, ordered by the latest of
    those.
    """
    from sqlalchemy import DateTime, func, literal, literal_column, tuple_

    latest = _latest_message_subq()
    neg_inf = literal_column("'-infinity'::timestamptz")
    per_conv = (
        select(_row_key_expr().label("row_key"), latest.c.last_at)
        .select_from(Conversation)
        .outerjoin(latest, latest.c.cid == Conversation.id)
        .where(*conditions)
        .subquery()
    )
    rows = (
        select(
            per_conv.c.row_key,
            func.coalesce(func.max(per_conv.c.last_at), neg_inf).label("sort_ts"),
        )
        .group_by(per_conv.c.row_key)
        .subquery()
    )
    q = select(rows.c.row_key, rows.c.sort_ts)
    if cursor:
        dec = _decode_cursor(cursor)
        if dec is None:
            raise HTTPException(status_code=400, detail="bad cursor")
        ts, key = dec
        ts_val = neg_inf if ts == _NEG_INF else literal(ts, type_=DateTime(timezone=True))
        q = q.where(tuple_(rows.c.sort_ts, rows.c.row_key) < tuple_(ts_val, key))
    q = q.order_by(rows.c.sort_ts.desc(), rows.c.row_key.desc()).limit(limit + 1)

    got = (await db.execute(q)).all()
    more = len(got) > limit
    got = got[:limit]
    nxt = _encode_cursor(got[-1][1], got[-1][0]) if (more and got) else None
    return [r[0] for r in got], nxt


def _unread_conv_ids():
    """Conversations with an inbound message after our last reply (staff notes
    don't count as a reply) — the row builder's own definition of unread, so a
    count, a filter and a row can never disagree."""
    from sqlalchemy import or_
    last_out = (
        select(
            Message.conversation_id.label("cid"),
            func.max(Message.created_at).label("last_out"),
        )
        .where(Message.direction == "outbound")
        .where(or_(Message.media_type.is_(None), Message.media_type != "note"))
        .group_by(Message.conversation_id)
        .subquery()
    )
    return (
        select(Message.conversation_id)
        .outerjoin(last_out, last_out.c.cid == Message.conversation_id)
        # 8 inbound messages carry no conversation; grouped, they formed one
        # phantom "unread conversation" the inbox could never show.
        .where(Message.conversation_id.isnot(None))
        .where(Message.direction == "inbound")
        .where(or_(last_out.c.last_out.is_(None), Message.created_at > last_out.c.last_out))
        .group_by(Message.conversation_id)
    )


_TABS = ("all", "unread", "read", "human", "yours")


def _inbox_conditions(*, agent_id, tab=None, channel=None, mode=None, tag=None, q=None) -> list:
    """The inbox filters, evaluated per CONVERSATION. A person's row appears
    when any of their threads qualifies — the client then shows the qualifying
    siblings, exactly as it filtered the full list before."""
    from sqlalchemy import or_
    from app.models.conversation import InterceptMode
    from app.models.person import Person
    from app.models.user import User

    conds = []
    tab = (tab or "all").lower()
    if tab not in _TABS:
        raise HTTPException(status_code=400, detail=f"tab must be one of {', '.join(_TABS)}")
    if tab == "unread":
        conds.append(Conversation.id.in_(_unread_conv_ids()))
    elif tab == "read":
        conds.append(Conversation.id.notin_(_unread_conv_ids()))
    elif tab == "human":
        conds.append(Conversation.intercept_mode == InterceptMode.human)
    elif tab == "yours":
        conds.append(Conversation.intercept_mode == InterceptMode.human)
        conds.append(Conversation.assigned_agent_id == agent_id)

    if channel and channel != "all":
        conds.append(Conversation.channel == channel)
    if mode and mode != "all":
        try:
            conds.append(Conversation.intercept_mode == InterceptMode(mode))
        except ValueError:
            raise HTTPException(status_code=400, detail="unknown mode")
    if tag:
        # Tags live on the WhatsApp user's state, keyed by wa_id — the same
        # place the row reads them from.
        tagged = select(User.wa_id).where(User.state["tags"].contains([tag]))
        conds.append(Conversation.wa_id.in_(tagged))

    term = (q or "").strip()
    if term:
        # Server-side now, so it searches EVERY conversation, not the page the
        # browser holds. Name, phone/handle, and what was said — the old
        # client search matched only the name and the latest preview, so a
        # phone number found nothing.
        like = f"%{term}%"
        conds.append(or_(
            Conversation.wa_id.ilike(like),
            Conversation.external_id.ilike(like),
            Conversation.wa_id.in_(select(User.wa_id).where(User.name.ilike(like))),
            Conversation.person_id.in_(select(Person.id).where(Person.display_name.ilike(like))),
            Conversation.id.in_(
                select(Message.conversation_id).where(Message.text.ilike(like)).distinct()
            ),
        ))
    return conds


async def _conversations_for_rows(db: AsyncSession, row_keys: list[str]) -> list:
    """Every conversation behind these inbox rows — ALL of a person's threads,
    so the client's per-person collapse is complete within the page."""
    from sqlalchemy import or_
    people = [k for k in row_keys if not k.startswith("c:")]
    solos  = [k[2:] for k in row_keys if k.startswith("c:")]
    clauses = []
    if people:
        clauses.append(Conversation.person_id.in_(people))
    if solos:
        clauses.append(Conversation.id.in_(solos))
    if not clauses:
        return []
    return list((await db.execute(select(Conversation.id).where(or_(*clauses)))).scalars().all())


async def _conversation_rows(
    db: AsyncSession,
    mode: str | None = None,
    conv_id=None,
    conv_ids: list | None = None,
) -> list[dict]:
    """The inbox row shape. One code path, so a single conversation fetched by
    id — or one page of them — can never drift from the same conversation
    inside the full list."""
    from sqlalchemy import and_, case, literal

    q = select(Conversation)
    if conv_id is not None:
        q = q.where(Conversation.id == conv_id)
    if conv_ids is not None:
        if not conv_ids:
            return []
        q = q.where(Conversation.id.in_(conv_ids))
    if mode:
        q = q.where(Conversation.intercept_mode == mode)
    result = await db.execute(q)
    conversations = result.scalars().all()

    if not conversations:
        return []

    conv_ids = [c.id for c in conversations]
    wa_ids   = [c.wa_id for c in conversations]

    # ── Batch-load User names / metadata ─────────────────────────────────────
    user_map: dict[str, User] = {}
    u_res = await db.execute(select(User).where(User.wa_id.in_(wa_ids)))
    for u in u_res.scalars().all():
        user_map[u.wa_id] = u

    # ── Batch-load person display_names (names for phone-less Meta contacts) ──
    # WhatsApp names come from User (keyed on wa_id); Messenger/IG/Facebook have
    # no wa_id, so their name lives on the resolved person (enriched from the FB
    # comment name or the Messenger profile API). Without this they read "Unknown".
    person_ids = [c.person_id for c in conversations if getattr(c, "person_id", None)]
    person_map: dict = {}
    if person_ids:
        p_res = await db.execute(select(Person).where(Person.id.in_(person_ids)))
        for p in p_res.scalars().all():
            person_map[p.id] = p

    # ── Profile photos (Messenger/IG avatars) keyed by person ────────────────
    # Stored on the identity's raw_profile by the DM enrichment. Meta pic URLs can
    # expire, so the frontend falls back to the initial if the image 404s.
    avatar_map: dict = {}
    if person_ids:
        id_res = await db.execute(select(Identity).where(Identity.person_id.in_(person_ids)))
        for idn in id_res.scalars().all():
            pic = (idn.raw_profile or {}).get("profile_pic")
            if pic and idn.person_id not in avatar_map:
                avatar_map[idn.person_id] = pic

    def _pstate(c: Conversation) -> dict:
        p = person_map.get(getattr(c, "person_id", None))
        return (getattr(p, "state", None) or {}) if p else {}

    def _list_country(c: Conversation) -> tuple:
        """(country_iso, flag_url) for the row: stored User → person.state → the
        contact's own phone prefix (external_id/wa_id). The phone fallback fills
        the flag for a Meta contact whose number is their key, with no backfill."""
        from app.core.countries import resolve_country
        from app.core.phone import is_plausible_phone
        u = user_map.get(c.wa_id)
        ps = _pstate(c)
        iso = (u.country_iso if u else None) or ps.get("country_iso")
        flag = (u.flag_url if u else None) or ps.get("flag_url")
        if not iso:
            handle = (u.phone if u and u.phone else None) or c.wa_id or getattr(c, "external_id", None)
            if handle and is_plausible_phone(handle):
                loc = resolve_country(handle)
                iso, flag = loc.get("country_iso"), loc.get("flag_url")
        return iso, flag

    def _name_for(c: Conversation):
        u = user_map.get(c.wa_id)
        if u and u.name:
            return u.name
        p = person_map.get(getattr(c, "person_id", None))
        return p.display_name if p else None

    def _stage_for(c: Conversation):
        """The lead-pipeline stage for the row chip (user state, person fallback)."""
        u = user_map.get(c.wa_id)
        st = ((u.state or {}).get("lead_stage") if u else None) or _pstate(c).get("lead_stage")
        if not st:
            return None
        from app.services.lead_signals import normalise_stage
        return normalise_stage(st)

    # ── Batch-load assigned agent names ──────────────────────────────────────
    agent_ids = [c.assigned_agent_id for c in conversations if c.assigned_agent_id]
    agent_map: dict[str, str] = {}
    if agent_ids:
        a_res = await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
        for a in a_res.scalars().all():
            agent_map[str(a.id)] = a.name or ""

    # ── Batch-load latest message per conversation for preview + true sort ───
    latest_sub = (
        select(
            Message.conversation_id,
            func.max(Message.created_at).label("max_at"),
        )
        .where(Message.conversation_id.in_(conv_ids))
        .where(Message.media_type.is_(None) | (Message.media_type != "note"))
        .group_by(Message.conversation_id)
        .subquery()
    )
    latest_q = select(Message).join(
        latest_sub,
        (Message.conversation_id == latest_sub.c.conversation_id)
        & (Message.created_at == latest_sub.c.max_at),
    )
    preview_map: dict[str, tuple[str, str]] = {}
    for m in (await db.execute(latest_q)).scalars().all():
        cid = str(m.conversation_id)
        ts  = m.created_at.isoformat() if m.created_at else None
        preview_map[cid] = (m.text or "", ts)

    # ── Compute unread per conversation ───────────────────────────────────────
    last_outbound_sub = (
        select(
            Message.conversation_id,
            func.max(Message.created_at).label("last_out_at"),
        )
        .where(Message.conversation_id.in_(conv_ids))
        .where(Message.direction == "outbound")
        .where(Message.media_type.is_(None) | (Message.media_type != "note"))
        .group_by(Message.conversation_id)
        .subquery()
    )

    unread_q = (
        select(
            Message.conversation_id,
            func.count().label("unread"),
        )
        .outerjoin(
            last_outbound_sub,
            Message.conversation_id == last_outbound_sub.c.conversation_id,
        )
        .where(Message.conversation_id.in_(conv_ids))
        .where(Message.direction == "inbound")
        .where(
            last_outbound_sub.c.last_out_at.is_(None)
            | (Message.created_at > last_outbound_sub.c.last_out_at)
        )
        .group_by(Message.conversation_id)
    )
    unread_map: dict[str, int] = {}
    for row in (await db.execute(unread_q)).all():
        unread_map[str(row.conversation_id)] = row.unread

    # ── Completed (paid) orders per customer — the repeat-buyer badge ─────────
    # Counted the same dual way memory reads history: by person when the row
    # has one (survives a Messenger↔WhatsApp merge), by wa_id otherwise. The
    # row takes max() of the two views — they see overlapping rows, never
    # disjoint halves, so max never double-counts. Grouped queries, never
    # per-row. Only hub-linked orders whose money landed count.
    from app.jobs.payment_followup import PAID_STATES
    from app.models.order_event import OrderEvent
    _paid = (OrderEvent.hub_order_id.isnot(None),
             func.lower(OrderEvent.payment_status).in_(tuple(PAID_STATES)))
    person_orders: dict = {}
    if person_ids:
        for pid, n in (await db.execute(
            select(OrderEvent.person_id, func.count())
            .where(OrderEvent.person_id.in_(person_ids), *_paid)
            .group_by(OrderEvent.person_id))).all():
            person_orders[pid] = n
    wa_orders: dict[str, int] = {}
    _real_wa = [w for w in wa_ids if w]
    if _real_wa:
        for wid, n in (await db.execute(
            select(OrderEvent.wa_id, func.count())
            .where(OrderEvent.wa_id.in_(_real_wa), *_paid)
            .group_by(OrderEvent.wa_id))).all():
            wa_orders[wid] = n

    # Resolve each row's country ONCE. This used to be called twice per row
    # (country_iso and flag_url), and on a row with no stored country it parses
    # the phone number each time — double the work for every conversation, on
    # every poll.
    country_map = {str(c.id): _list_country(c) for c in conversations}

    # ── Build response, sorted by true latest-message timestamp desc ──────────
    def sort_key(c: Conversation):
        entry = preview_map.get(str(c.id))
        if entry and entry[1]:
            return entry[1]
        if c.last_message_at:
            return c.last_message_at.isoformat()
        return c.created_at.isoformat() if c.created_at else ""

    conversations.sort(key=sort_key, reverse=True)

    return [
        {
            "id":                   str(c.id),
            "wa_id":                c.wa_id,
            # The resolved human. Conversations sharing a person_id are the SAME
            # customer across channels (Doctors West on Facebook + Messenger +
            # WhatsApp) — the inbox collapses them into one row with channel chips.
            "person_id":            str(c.person_id) if getattr(c, "person_id", None) else None,
            # Channel-native handle (wa_id | PSID | IGSID). == wa_id for WhatsApp,
            # but the ONLY customer key for Messenger/IG/FB (whose wa_id is null),
            # so the panel can load + save their profile.
            "external_id":          getattr(c, "external_id", None),
            "intercept_mode":       c.intercept_mode,
            "assigned_agent_id":    str(c.assigned_agent_id) if c.assigned_agent_id else None,
            "assigned_agent_name":  agent_map.get(str(c.assigned_agent_id), "") if c.assigned_agent_id else None,
            "intercept_since":      c.intercept_since.isoformat() if c.intercept_since else None,
            "last_message_at":      preview_map[str(c.id)][1] if str(c.id) in preview_map else (
                                        c.last_message_at.isoformat() if c.last_message_at else None
                                    ),
            "last_message":         preview_map.get(str(c.id), (c.last_message_preview or "", None))[0],
            "last_message_preview": preview_map.get(str(c.id), (c.last_message_preview or "", None))[0],
            "status":               c.status,
            "created_at":           c.created_at.isoformat() if c.created_at else None,
            "updated_at":           c.updated_at.isoformat() if c.updated_at else None,
            "name":                 _name_for(c),
            "avatar_url":           avatar_map.get(getattr(c, "person_id", None)),
            "country_iso":          country_map[str(c.id)][0],
            "flag_url":             country_map[str(c.id)][1],
            "channel":              getattr(c, "channel", "whatsapp") or "whatsapp",
            "unread":               unread_map.get(str(c.id), 0),
            "orders_count":         max(person_orders.get(getattr(c, "person_id", None), 0),
                                        wa_orders.get(c.wa_id, 0) if c.wa_id else 0),
            "lead_stage":           _stage_for(c),
            "tags":                 (user_map[c.wa_id].state or {}).get("tags", []) if c.wa_id in user_map else [],
        }
        for c in conversations
    ]


@router.get("/conversations/{conv_id}/messages")
async def get_thread(
    conv_id: str,
    request: Request,
    before: str | None = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """
    Return the full conversation timeline: regular chat messages interleaved
    with system-event items (escalations, intercepts, releases, transfers).

    Every item in the returned list has a `type` field:
      - "message"      → normal chat bubble
      - "system_event" → inline timeline divider with event_kind + event_reason

    Bounded to the most recent THREAD_LIMIT messages. The inbox renders every
    message it is given into the DOM (no virtualisation), so an unbounded
    thread meant a long-running customer could freeze the tab on click — the
    browser building thousands of nodes in one synchronous pass. The cap is far
    above a normal sales conversation, so nothing an agent works with is lost.
    """
    # ── 1. Fetch ONE PAGE of messages (newest `limit`, returned oldest-first).
    # Owner's rule (2026-08-19): open with the latest 50 and fetch the next 50
    # only when the reader scrolls past them — the app stays light instead of
    # painting a long customer's whole history into the DOM in one pass.
    # `before` (ISO timestamp) pages older; THREAD_LIMIT stays the hard cap.
    page = max(1, min(int(limit or 50), THREAD_LIMIT))
    before_dt = _parse_before(before)
    q = select(Message).where(Message.conversation_id == conv_id)
    if before_dt is not None:
        q = q.where(Message.created_at < before_dt)
    msg_result = await db.execute(
        q.order_by(Message.created_at.desc()).limit(page)
    )
    msgs = list(reversed(msg_result.scalars().all()))

    # Batch-load agent names referenced by messages to avoid N+1
    msg_agent_ids = [m.agent_id for m in msgs if m.agent_id]
    agent_name_map: dict[str, str] = {}
    if msg_agent_ids:
        a_res = await db.execute(select(Agent).where(Agent.id.in_(msg_agent_ids)))
        for a in a_res.scalars().all():
            agent_name_map[str(a.id)] = a.name

    # ── 2. Fetch intercept events (activity log rows) — FIRST page only.
    # An older page (`before` set) adds messages alone: the full event timeline
    # already arrived with page one, and re-sending it would duplicate pills.
    # We surface escalated, flag, intercept, release, and transfer actions.
    # approve_draft is skipped — it's implicit from the AI message that follows.
    if before_dt is not None:
        thread: list[dict] = []
        _shape_messages_into(thread, msgs, agent_name_map)
        thread.sort(key=lambda x: x["created_at"] or "")
        try:
            _cand = [str(m.id) for m in msgs if translate_svc.is_candidate(m)]
            if _cand:
                translate_svc.schedule_thread_translation(
                    request.app.state.redis, conv_id, _cand)
        except Exception:
            pass
        return thread

    SURFACED_ACTIONS = {
        InterceptAction.escalated,
        InterceptAction.flag,
        InterceptAction.intercept,
        InterceptAction.release,
        InterceptAction.transfer,
        InterceptAction.pause,
    }

    evt_result = await db.execute(
        select(Intercept)
        .where(Intercept.conversation_id == conv_id)
        .where(Intercept.action.in_(SURFACED_ACTIONS))
        .order_by(Intercept.created_at.asc())
    )
    events = evt_result.scalars().all()

    # Batch-load agent names referenced by events
    evt_agent_ids = [e.agent_id for e in events if e.agent_id]
    all_agent_ids = list(set(msg_agent_ids + evt_agent_ids))
    if evt_agent_ids:
        extra_agents = [aid for aid in evt_agent_ids if str(aid) not in agent_name_map]
        if extra_agents:
            ea_res = await db.execute(select(Agent).where(Agent.id.in_(extra_agents)))
            for a in ea_res.scalars().all():
                agent_name_map[str(a.id)] = a.name

    # ── 3. Shape messages into thread items ───────────────────────────────────
    thread: list[dict] = []
    _shape_messages_into(thread, msgs, agent_name_map)

    # ── 4. Shape intercept events into system_event thread items ──────────────
    # Human-readable labels for each action shown in the timeline pill
    ACTION_LABEL: dict[InterceptAction, str] = {
        InterceptAction.escalated: "Escalated — needs human",
        InterceptAction.flag:      "Flagged: Needs Attention",
        InterceptAction.intercept: "Picked up by agent",
        InterceptAction.release:   "Released to AI",
        InterceptAction.transfer:  "Transferred",
        InterceptAction.pause:     "Paused — replies held",
    }

    # Build a quick lookup: messages that arrived before each event timestamp
    # so we can auto-detect the escalation cause for agentless intercepts.
    msg_list = sorted(msgs, key=lambda m: m.created_at or "")

    for e in events:
        agent_name = agent_name_map.get(str(e.agent_id)) if e.agent_id else None

        label = ACTION_LABEL.get(e.action, e.action)
        if e.action == InterceptAction.intercept and agent_name:
            label = f"Picked up by {agent_name}"
        elif e.action == InterceptAction.release and agent_name:
            label = f"Released to AI by {agent_name}"
        elif e.action == InterceptAction.transfer and e.note:
            label = f"Transferred — {e.note}"

        # ── Auto-derive reason for agentless intercepts (media escalations) ──
        # When no agent triggered the intercept it was auto-escalated by the
        # system because of inbound media or a media request.  Look at messages
        # that arrived just before this event to identify which case it is.
        auto_reason: str | None = None
        if e.action == InterceptAction.intercept and not e.agent_id:
            evt_ts = e.created_at
            preceding = [
                m for m in msg_list
                if m.created_at and evt_ts and m.created_at <= evt_ts
            ]
            has_inbound_media = any(
                m.direction == "inbound" and m.media_type and m.media_type != "note"
                for m in preceding[-10:]  # check last 10 messages before event
            )
            if has_inbound_media:
                auto_reason = (
                    "Customer sent a media file (image, document, or audio) "
                    "that the AI cannot process. An agent needs to review and respond."
                )
            else:
                auto_reason = (
                    "Customer requested media or files that the AI cannot send. "
                    "An agent needs to take over to fulfil this request."
                )

        thread.append({
            "id":           f"evt-{e.id}",
            "type":         "system_event",
            "direction":    "outbound",
            "sender":       "ai",
            "text":         label,
            "created_at":   e.created_at.isoformat() if e.created_at else None,
            # ── Timeline-specific fields ──────────────────────────────────
            "event_kind":   e.action.value,
            # For escalated rows: use note. For agentless intercepts: use auto_reason.
            "event_reason": (
                e.note if e.action == InterceptAction.escalated
                else auto_reason
            ),
            "agent_name":   agent_name,
        })

    # ── 4b. Calls with this customer, inline where they happened ──────────────
    # A call is part of the conversation: the agent coming back from one (or
    # a colleague picking the thread up later) sees it — outcome, length, who
    # took it and the brief — without leaving the chat. WhatsApp threads match
    # on the number; Messenger / Instagram threads on the linked person.
    try:
        thread.extend(await _call_thread_items(db, conv_id))
    except Exception as exc:
        _log.warning("thread call items failed for %s: %s", conv_id, exc)

    # ── 5. Sort merged timeline by created_at ascending ───────────────────────
    thread.sort(key=lambda x: x["created_at"] or "")

    # ── 6. Lazily fill the missing gray English lines ─────────────────────────
    # Background so the open stays instant; results arrive over the same ws
    # channel new messages ride and are cached on the rows forever after.
    try:
        _cand = [str(m.id) for m in msgs if translate_svc.is_candidate(m)]
        if _cand:
            translate_svc.schedule_thread_translation(
                request.app.state.redis, conv_id, _cand)
    except Exception:
        pass

    return thread


async def _call_thread_items(db: AsyncSession, conv_id: str) -> list[dict]:
    """The customer's calls as `system_event` thread items (event_kind "call")."""
    from app.services import call_log
    conv = (await db.execute(select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if conv is None:
        return []
    wa = conv.external_id if conv.channel == "whatsapp" else None
    conds = []
    if wa:
        conds.append(Call.wa_id == wa)
    if getattr(conv, "person_id", None):
        conds.append(Call.person_id == conv.person_id)
    if not conds:
        return []
    rows = (await db.execute(
        select(Call).where(or_(*conds)).order_by(Call.started_at.desc()).limit(50))).scalars().all()
    items = []
    for r in await call_log.serialize_rows(db, list(rows)):
        items.append({
            "id": f"call-{r['id']}",
            "type": "system_event",
            "direction": "outbound" if r["direction"] == "outbound" else "inbound",
            "sender": "human_agent",
            "text": _call_label(r),
            "created_at": r["started_at"],
            "event_kind": "call",
            "event_reason": r.get("summary"),
            "agent_name": r.get("agent_name"),
            "call": r,
        })
    return items


def _call_label(r: dict) -> str:
    """The thread pill's words — the same the Calls view uses."""
    d = r.get("duration")
    dur = f" · {d // 60}:{d % 60:02d}" if d else ""
    out = r.get("direction") == "outbound"
    return {
        "ringing": "Calling…" if out else "Incoming call",
        "answered": "Call in progress",
        "completed": ("Outgoing call" if out else "Incoming call") + dur,
        "missed": "Missed call",
        "declined": "Declined call",
        "callback": "Missed call · call back",
        "no_answer": "Outgoing call · no answer",
        "cancelled": "Outgoing call · cancelled",
        "failed": "Outgoing call · failed",
    }.get(r.get("status") or "", "Call")


@router.get("/conversations/{conv_id}/activity")
async def get_conversation_activity(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """The customer's journey, person-scoped — everything the system did and
    observed for this human across channels: pickups/escalations, the check-ins
    Neema planned and sent, deals and detected promises, orders, and calls.
    The in-thread system_event dividers show a slice of this; this endpoint is
    the full ledger the Activity Log panel renders."""
    from app.models.agent_action import AgentAction
    from app.models.deal import Deal
    from app.models.order_event import OrderEvent

    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    person_id = getattr(conv, "person_id", None)
    wa_id = conv.wa_id

    # Sibling conversations of the same person — their intercepts and actions
    # belong to this journey too (the cross-channel "one human" principle).
    conv_ids = [conv.id]
    if person_id:
        sib = await db.execute(select(Conversation.id).where(
            Conversation.person_id == person_id))
        conv_ids = list({*conv_ids, *[r[0] for r in sib.all()]})

    events: list[dict] = []

    # ── Pickups / escalations / releases ──────────────────────────────────────
    ACTION_LABEL = {
        InterceptAction.escalated: "Escalated — needs human",
        InterceptAction.flag:      "Flagged: needs attention",
        InterceptAction.intercept: "Picked up by agent",
        InterceptAction.release:   "Released to AI",
        InterceptAction.transfer:  "Transferred",
        InterceptAction.pause:     "Paused — replies held",
    }
    icpts = (await db.execute(
        select(Intercept).where(Intercept.conversation_id.in_(conv_ids))
        .order_by(Intercept.created_at.desc()).limit(40))).scalars().all()
    agent_ids = [e.agent_id for e in icpts if e.agent_id]
    name_map: dict[str, str] = {}
    if agent_ids:
        a_res = await db.execute(select(Agent).where(Agent.id.in_(agent_ids)))
        name_map = {str(a.id): a.name for a in a_res.scalars().all()}
    for e in icpts:
        who = name_map.get(str(e.agent_id)) if e.agent_id else None
        label = ACTION_LABEL.get(e.action, str(e.action))
        if e.action == InterceptAction.intercept and who:
            label = f"Picked up by {who}"
        elif e.action == InterceptAction.release and who:
            label = f"Released to AI by {who}"
        events.append({
            "id": f"icpt-{e.id}", "kind": e.action.value, "label": label,
            "detail": e.note, "at": e.created_at.isoformat() if e.created_at else None,
        })

    # ── Check-ins Neema planned / sent (the initiative engine) ────────────────
    acts = (await db.execute(
        select(AgentAction).where(AgentAction.conversation_id.in_(conv_ids))
        .order_by(AgentAction.created_at.desc()).limit(40))).scalars().all()
    ACT_LABEL = {"planned": "Check-in planned", "sent": "Check-in sent",
                 "vetoed": "Check-in vetoed", "needs_approval": "Check-in awaiting approval",
                 "failed": "Check-in failed"}
    for a in acts:
        due = a.due_at.strftime("%a %d %b, %H:%M") if a.due_at else None
        events.append({
            "id": f"act-{a.id}",
            "kind": f"checkin_{a.status}",
            "label": ACT_LABEL.get(a.status, f"Check-in {a.status}")
                     + (f" — {a.kind.replace('_', ' ')}" if a.kind and a.kind != "follow_up" else ""),
            "detail": (a.reason or "") + (f" (due {due} UTC)" if due and a.status == "planned" else ""),
            "at": (a.updated_at or a.created_at).isoformat() if (a.updated_at or a.created_at) else None,
        })

    # ── Deals ─────────────────────────────────────────────────────────────────
    deal_q = select(Deal).where(Deal.conversation_id.in_(conv_ids))
    if person_id:
        deal_q = select(Deal).where(
            (Deal.conversation_id.in_(conv_ids)) | (Deal.person_id == person_id))
    deals = (await db.execute(deal_q.order_by(Deal.created_at.desc()).limit(20))
             ).scalars().all()
    for d in deals:
        nxt = d.next_action or {}
        events.append({
            "id": f"deal-{d.id}", "kind": "deal",
            "label": f"Deal {d.status}" + (f" — {d.title}" if d.title else ""),
            "detail": (f"stage {d.stage}" if d.stage else None),
            "at": d.created_at.isoformat() if d.created_at else None,
        })
        if isinstance(nxt, dict) and nxt.get("note"):
            kind_label = ("Customer promised" if nxt.get("kind") == "customer_promise"
                          else "Neema owes a reply")
            events.append({
                "id": f"deal-next-{d.id}", "kind": "promise",
                "label": kind_label,
                "detail": nxt.get("note"),
                "at": (d.updated_at or d.created_at).isoformat()
                      if (d.updated_at or d.created_at) else None,
            })

    # ── Orders ────────────────────────────────────────────────────────────────
    if person_id or wa_id:
        o_q = select(OrderEvent)
        o_q = o_q.where((OrderEvent.person_id == person_id) if person_id
                        else (OrderEvent.wa_id == wa_id))
        orders = (await db.execute(o_q.order_by(OrderEvent.created_at.desc())
                                   .limit(20))).scalars().all()
        for o in orders:
            n_items = len(o.items or [])
            events.append({
                "id": f"ord-{o.id}", "kind": "order",
                "label": f"Order {o.status}"
                         + (f" · {o.payment_status}" if o.payment_status else ""),
                "detail": f"{n_items} item{'s' if n_items != 1 else ''} — "
                          f"{o.currency} {money.num(o.subtotal or 0)}",
                "at": o.created_at.isoformat() if o.created_at else None,
            })

    # ── The agent's own steps — every tool call of every turn ─────────────────
    # (owner's rule, 2026-08-19: the log must capture every activity of the
    # interaction, not just the system's milestones around it.)
    try:
        from app.models.agent_activity import AgentActivity
        acts_rows = (await db.execute(
            select(AgentActivity).where(AgentActivity.conversation_id.in_(conv_ids))
            .order_by(AgentActivity.created_at.desc()).limit(60))).scalars().all()
        for t in acts_rows:
            events.append({
                "id": f"tool-{t.id}", "kind": "tool",
                "label": t.summary,
                "detail": t.detail,
                "at": t.created_at.isoformat() if t.created_at else None,
            })
    except Exception:
        pass          # a missing table (pre-migration box) must not break the ledger

    # ── Calls ─────────────────────────────────────────────────────────────────
    if person_id or wa_id:
        c_q = select(Call)
        c_q = c_q.where((Call.person_id == person_id) if person_id
                        else (Call.wa_id == wa_id))
        calls = (await db.execute(c_q.order_by(Call.started_at.desc())
                                  .limit(20))).scalars().all()
        from app.services import call_log as _call_log
        for c in calls:
            secs = getattr(c, "duration", None)
            if secs is None and c.answered_at and c.ended_at:
                secs = int((c.ended_at - c.answered_at).total_seconds())
            events.append({
                "id": f"call-{c.id}", "kind": "call",
                "label": _call_label({"status": _call_log.normalize_status(c.status),
                                      "direction": getattr(c, "direction", None), "duration": secs}),
                "detail": name_map.get(str(c.agent_id)) if c.agent_id else None,
                "at": c.started_at.isoformat() if c.started_at else None,
            })

    events.sort(key=lambda x: x["at"] or "", reverse=True)
    return {"events": events[:80]}


@router.get("/conversations/{conv_id}/latest-draft")
async def get_latest_draft(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Return the most recent held AI draft for this conversation, if any."""
    result = await db.execute(
        select(Intercept)
        .where(Intercept.conversation_id == conv_id)
        .where(Intercept.ai_reply_held.isnot(None))
        .order_by(Intercept.created_at.desc())
        .limit(1)
    )
    intercept = result.scalar_one_or_none()
    return {"draft": intercept.ai_reply_held if intercept else None}


@router.post("/conversations/{conv_id}/generate-draft")
async def generate_draft(
    conv_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Generate a fresh AI draft reply for the human agent — the SAME Neema brain a
    live reply uses. It reads the conversation, SEES the post / product images
    (vision), and looks up real catalogue prices, then composes a suggestion in
    Neema's voice. Runs READ-ONLY (never creates an order, edits the cart, or sends
    anything) and routes the model per-turn to keep cost down (the light model for
    simple turns, the full model when the turn is complex)."""
    from app.agent import runtime

    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    recent = list(reversed((await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc())
        .limit(10))).scalars().all()))
    if not recent:
        raise HTTPException(status_code=422, detail="No messages to draft from")

    # Draft a reply to the customer's latest message (the last inbound one). If it
    # carried a photo, hand it to the vision model so the draft is informed by it.
    last_in = next((m for m in reversed(recent) if m.direction == "inbound"), None)
    user_text = ((last_in.text if last_in else None) or recent[-1].text or "").strip()
    media = None
    if last_in and last_in.media_type == "image" and last_in.media_url:
        media = {"type": "image", "url": last_in.media_url,
                 "caption": last_in.media_caption or ""}

    channel = conv.channel or "whatsapp"
    is_comment = channel == "facebook" or bool(last_in and getattr(last_in, "comment_context", None))

    try:
        llm = runtime.build_llm(model=runtime.route_model(user_text), purpose="admin")
        draft = await runtime.run_turn(
            db, request.app.state.redis,
            wa_id=conv.wa_id or (conv.external_id or ""),
            user_text=user_text or "(compose the next reply)",
            llm=llm, media=media,
            channel=channel, external_id=conv.external_id,
            public_comment=is_comment, read_only=True,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Draft generation failed: {str(e)}")

    return {"draft": (draft or "").strip()}


@router.post("/conversations/{conv_id}/note")
async def add_note(
    conv_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Save an internal agent note against the conversation thread."""
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")

    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msg = Message(
        wa_id=conv.wa_id,
        conversation_id=conv.id,
        direction="outbound",
        sender="human_agent",
        text=text,
        media_type="note",
        agent_id=agent.id,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(msg)

    return {
        "id": str(msg.id),
        "type": "message",
        "direction": "outbound",
        "sender": "human_agent",
        "text": text,
        "isNote": True,
        "created_at": msg.created_at.isoformat() if msg.created_at else None,
    }


@router.post("/conversations/{conv_id}/intercept")
async def intercept(conv_id: str, request: Request, db: AsyncSession = Depends(get_db),
                    agent: Agent = Depends(get_current_agent)):
    out = await intercept_conversation(db, conv_id, agent, request.app.state.redis)
    # Copilot C1: brief the human who just took over (background, best-effort).
    # Only on a REAL takeover — an idempotent re-click (out.already) must not
    # write another briefing note (five stacked up in one thread, 2026-08-19,
    # each a full model turn).
    try:
        if not out.get("already"):
            from app.services import copilot
            copilot.schedule_briefing(request.app.state.redis, conv_id)
    except Exception:
        pass
    return out


@router.post("/conversations/{conv_id}/ask")
async def ask_neema(conv_id: str, request: Request, body: dict,
                    db: AsyncSession = Depends(get_db),
                    agent: Agent = Depends(get_current_agent)):
    """Ask-Neema (plan C5): the human asks about THIS customer — 'what were his
    sizes?', 'what did he order last Easter?' — answered from the conversation,
    calls, measurements and orders. Read-only; never customer-facing."""
    from app.agent import runtime
    question = (body.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="question is required")
    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    key = conv.wa_id if conv.channel == "whatsapp" else conv.external_id
    answer = (await runtime.run_turn(
        db, request.app.state.redis, wa_id=key,
        user_text=("[OPERATOR QUESTION — a human colleague asks about this "
                   "customer. Answer THEM, briefly and factually, from the "
                   "conversation, phone calls, sizes on file, cart and orders. "
                   f"This is never sent to the customer.] {question[:400]}"),
        llm=runtime.build_llm(purpose="admin"), channel=conv.channel,
        external_id=(None if conv.channel == "whatsapp" else conv.external_id),
        read_only=True)).strip()
    return {"answer": answer or "I couldn't find that in what we have on file."}


@router.post("/conversations/{conv_id}/answer")
async def answer_through_neema(conv_id: str, request: Request, body: dict,
                               db: AsyncSession = Depends(get_db),
                               agent: Agent = Depends(get_current_agent)):
    """Deliver the team's answer THROUGH Neema.

    When she said "let me confirm with the team and come right back" (a
    check_availability flag) or a complaint was raised, the confirmation used
    to die in the Activity feed — nobody carried it back. Here the human gives
    the FACTS ("yes, we make it — KES 3,500, about 5 days") and Neema wraps
    them in her own voice, in the thread's language, and keeps the sale moving
    — the thread stays in AI mode and the promise is actually kept.

    Refused outside the messaging window (409) — send a template or reply as
    yourself when they next write."""
    from app.agent import runtime
    from app.services.hub_events import _within_window
    facts = (body.get("facts") or body.get("text") or "").strip()
    if not facts:
        raise HTTPException(status_code=422,
                            detail="facts is required — what the team confirmed")
    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conv_id))).scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not await _within_window(db, conv):
        raise HTTPException(status_code=409,
                            detail="outside the messaging window — send it as a "
                                   "template, or reply yourself when they next write")
    key = conv.wa_id if conv.channel == "whatsapp" else conv.external_id
    text = (await runtime.run_turn(
        db, request.app.state.redis, wa_id=key,
        user_text=("[TEAM ANSWER — not a customer message. A colleague has "
                   "confirmed what this customer was waiting on: "
                   f'"{facts[:400]}". Compose the ONE short, warm message '
                   "delivering this answer now, in the conversation's language, "
                   "picking up exactly where the thread left off. If it confirms "
                   "availability or a price, invite the next step of the order "
                   "in the same breath. Never mention the checking process or "
                   "the team's internals.]"),
        llm=runtime.build_llm(purpose="admin"), channel=conv.channel,
        external_id=(None if conv.channel == "whatsapp" else conv.external_id),
        read_only=True)).strip()
    if not text:
        raise HTTPException(status_code=502, detail="Neema could not compose the answer")
    from app.services import n8n_bridge as svc
    if conv.channel == "whatsapp":
        wamid = await svc._send_waba(key, text)
        await svc.save_outbound_message(db, request.app.state.redis, key, text,
                                        waba_msg_id=wamid)
    else:
        from app.services.meta_send import send_to_channel
        await send_to_channel(conv.channel, key, text)
        await svc.save_outbound_channel_message(db, request.app.state.redis,
                                                conv.channel, key, text)
    # Audit trail: who answered, with what facts — an internal note, never sent.
    db.add(Message(wa_id=conv.wa_id, conversation_id=conv.id, direction="outbound",
                   sender="human_agent", media_type="note", agent_id=agent.id,
                   text=f"📣 Team answer delivered via Neema: {facts[:300]}"))
    await db.commit()
    return {"ok": True, "sent": text}


@router.post("/posts/{post_id}/product")
async def set_post_product(post_id: str, request: Request, body: dict,
                           db: AsyncSession = Depends(get_db),
                           agent: Agent = Depends(get_current_agent)):
    """The team's ten-second correction: "this post is actually X".

    Resolves the given product (slug, name, or alias) against the live
    catalogue and stores it as the post's identity — from that moment every
    comment and DM funnelled from the post prices THAT product. The safety
    valve behind the deterministic ladder (caption slug/alias → image
    fingerprint): even a rare miss is a one-call fix, not a support thread."""
    from app.agent.runtime import _remember_post_product
    from app.services import n8n_bridge as svc
    from app.services.post_catalog import product_from_caption
    q = (body.get("product") or "").strip()
    channel = (body.get("channel") or "facebook").strip()
    if not q:
        raise HTTPException(status_code=422, detail="product is required — a slug, name or alias")
    catalog = await svc.catalog_items(db, request.app.state.redis)
    hit = next((p for p in catalog if (p.get("slug") or "").lower() == q.lower()), None) \
        or product_from_caption(q, catalog)
    if hit is None:
        raise HTTPException(status_code=404, detail=f"no catalogue product matches '{q}'")
    # The team's word is the strongest rung there is: source "team", 1.0 —
    # the one identity a canned reply may always price.
    from app.services.post_catalog import with_provenance
    await _remember_post_product(request.app.state.redis, channel, post_id,
                                 with_provenance(hit, "team"))
    return {"ok": True, "post_id": post_id, "channel": channel,
            "product": hit.get("name"), "slug": hit.get("slug")}


@router.post("/conversations/{conv_id}/reply")
async def reply(conv_id: str, request: Request, body: dict, db: AsyncSession = Depends(get_db),
                agent: Agent = Depends(get_current_agent)):
    text = body.get("text", "")
    if not text:
        raise HTTPException(status_code=422, detail="text is required")
    # Reply-box translate toggle: `text` is what the CUSTOMER receives (their
    # language); original_text is the English the human actually typed, stored
    # on the row so the thread shows the gray English line under the sent
    # bubble — the reading glass working in reverse.
    return await send_agent_reply(db, conv_id, agent, text, request.app.state.redis,
                                  reply_to_id=body.get("reply_to"),
                                  original_text=body.get("original_text"),
                                  original_lang=body.get("original_lang"),
                                  client_msg_id=body.get("client_msg_id"))


@router.post("/conversations/{conv_id}/translate-reply")
async def translate_reply(conv_id: str, request: Request, body: dict,
                          db: AsyncSession = Depends(get_db),
                          agent: Agent = Depends(get_current_agent)):
    """The reply box's outbound direction: the human types English, the
    customer reads their own language (the 'Samsung keyboard' toggle). Target
    language comes from the thread's cached detections — free — or the newest
    foreign inbound as a sample. Fails open to the original text: the
    translator must never block a reply."""
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")
    return await translate_svc.translate_reply(db, request.app.state.redis,
                                               conv_id, text)


@router.get("/conversations/{conv_id}/window")
async def messaging_window_state(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Whether a free-form reply can go out on this conversation right now, so
    the composer can say so BEFORE the agent types one Meta will refuse."""
    from app.services.conversation import messaging_window
    conv = (await db.execute(select(Conversation).where(
        Conversation.id == conv_id))).scalar_one_or_none()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await messaging_window(db, conv)


@router.post("/conversations/{conv_id}/approve-draft")
async def approve(conv_id: str, request: Request, db: AsyncSession = Depends(get_db),
                  agent: Agent = Depends(get_current_agent)):
    try:
        body = await request.json()
    except Exception:
        body = {}
    return await approve_draft(db, conv_id, agent, body.get("text") if isinstance(body, dict) else None, request.app.state.redis)


@router.post("/conversations/{conv_id}/release")
async def release(conv_id: str, request: Request, db: AsyncSession = Depends(get_db),
                  agent: Agent = Depends(get_current_agent)):
    return await release_conversation(db, conv_id, agent, request.app.state.redis)


@router.post("/conversations/{conv_id}/pause")
async def pause(conv_id: str, request: Request, db: AsyncSession = Depends(get_db),
                agent: Agent = Depends(get_current_agent)):
    """Hold ALL replies until someone resumes. The Pause button used to call
    /release — the opposite of pausing — because this endpoint didn't exist."""
    from app.services.conversation import pause_conversation
    return await pause_conversation(db, conv_id, agent, request.app.state.redis)


@router.post("/conversations/{conv_id}/close")
async def close_conv(conv_id: str, db: AsyncSession = Depends(get_db),
                     agent: Agent = Depends(get_current_agent)):
    from app.models.conversation import ConvStatus
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conv.status = ConvStatus.closed
    await db.commit()
    return {"ok": True, "status": "closed"}


@router.post("/conversations/{conv_id}/transfer")
async def transfer(conv_id: str, request: Request, body: dict, db: AsyncSession = Depends(get_db),
                   agent: Agent = Depends(get_current_agent)):
    agent_id = body.get("agentId") or body.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=422, detail="agentId or agent_id required")
    return await transfer_conversation(db, conv_id, agent, agent_id, request.app.state.redis)


# ── Media upload + send ───────────────────────────────────────────────────────

@router.post("/conversations/{conv_id}/upload-media")
async def upload_media(
    conv_id: str,
    request: Request,
    file: UploadFile = File(...),
    caption: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    import aiofiles, os, uuid, mimetypes
    from app.core.config import settings

    ALLOWED_MIME = {
        "image/jpeg", "image/png", "image/webp", "image/gif",
        "application/pdf", "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "video/mp4", "video/3gpp", "video/quicktime", "video/hevc", "video/x-m4v",
        "audio/ogg", "audio/aac", "audio/mpeg",
    }

    ct = file.content_type or mimetypes.guess_type(file.filename or "")[0] or ""
    # iPhone .mov/.hevc files often arrive as octet-stream — trust the extension.
    if ct in ("", "application/octet-stream"):
        _ext = os.path.splitext(file.filename or "")[1].lower() if file.filename else ""
        ct = {".mov": "video/quicktime", ".hevc": "video/hevc",
              ".mp4": "video/mp4", ".m4v": "video/x-m4v"}.get(_ext, ct)
    if ct not in ALLOWED_MIME:
        raise HTTPException(status_code=415, detail=f"Unsupported media type: {ct}")

    if ct.startswith("image/"):
        waba_type = "image"
    elif ct.startswith("video/"):
        waba_type = "video"
    elif ct.startswith("audio/"):
        waba_type = "audio"
    else:
        waba_type = "document"

    # Per-type ACCEPTANCE ceilings. Videos are accepted up to 150 MB — like
    # WhatsApp itself, we take the raw phone clip and transcode it down to the
    # Cloud API's 16 MB H.264 MP4 before sending (services/video_convert.py).
    # The other types match WhatsApp's hard limits directly.
    MB = 1024 * 1024
    MAX_BYTES = {"image": 5 * MB, "video": 150 * MB, "audio": 16 * MB, "document": 18 * MB}
    MAX_LABEL = {"image": "5 MB", "video": "150 MB", "audio": "16 MB", "document": "18 MB"}

    from app.routers.media import MEDIA_DIR
    media_dir = MEDIA_DIR
    os.makedirs(media_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "file")[1] or (mimetypes.guess_extension(ct) or "")
    saved_name = f"{uuid.uuid4().hex}{ext}"
    file_path  = os.path.join(media_dir, saved_name)

    content = await file.read()
    limit = MAX_BYTES[waba_type]
    if len(content) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{waba_type.capitalize()} too large — max {MAX_LABEL[waba_type]}.",
        )
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    # Videos: normalise to a WhatsApp-ready H.264 MP4 (≤16 MB). A compliant
    # file passes through untouched; a 150 MB iPhone .mov gets re-encoded.
    if waba_type == "video":
        from app.services.video_convert import to_whatsapp_video
        converted = await to_whatsapp_video(file_path)
        if converted is None:
            try:
                os.remove(file_path)
            except OSError:
                pass
            raise HTTPException(
                status_code=422,
                detail="Couldn't convert this video for WhatsApp — try a shorter "
                       "clip or export it as MP4 (H.264).")
        if converted != file_path:
            try:
                os.remove(file_path)
            except OSError:
                pass
            file_path = converted
            saved_name = os.path.basename(converted)

    public_base = getattr(settings, "media_public_url", "").rstrip("/")
    if not public_base:
        raise HTTPException(
            status_code=500,
            detail="MEDIA_PUBLIC_URL is not configured. Set it in your .env file.",
        )
    public_url = f"{public_base}/api/admin/media/{saved_name}"

    return await send_agent_media(
        db=db,
        conv_id=conv_id,
        agent=agent,
        media_url=public_url,
        media_type=waba_type,
        caption=caption,
        filename=file.filename,
        redis=request.app.state.redis,
    )


@router.get("/post-video/{post_id}")
async def post_video(
    post_id: str,
    request: Request,
    channel: str = "facebook",
    agent: Agent = Depends(get_current_agent),
):
    """A fresh direct video URL for one of our page's reels/video posts, so the
    inbox can play the commented-on reel INLINE (no leaving to Facebook). Source
    URLs are short-lived, so we cache only ~30 min and re-fetch after. `channel`
    picks the right read — an IG media exposes media_url, a FB post attachments."""
    channel = "instagram" if channel == "instagram" else "facebook"
    redis = getattr(request.app.state, "redis", None)
    key = f"meta:postvid:{channel}:{post_id}"
    if redis is not None:
        try:
            cached = await redis.get(key)
            if cached:
                return {"video_url": cached}
        except Exception:
            pass
    from app.services.meta_send import fetch_post_video_url
    url = await fetch_post_video_url(post_id, channel=channel)
    if not url:
        raise HTTPException(status_code=404, detail="No playable video for this post")
    if redis is not None:
        try:
            await redis.set(key, url, ex=1800)
        except Exception:
            pass
    return {"video_url": url}


@router.post("/conversations/{conv_id}/reply-media")
async def reply_media(
    conv_id: str,
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    media_url  = body.get("media_url")
    media_type = body.get("media_type", "image")
    if not media_url:
        raise HTTPException(status_code=422, detail="media_url is required")

    return await send_agent_media(
        db=db,
        conv_id=conv_id,
        agent=agent,
        media_url=media_url,
        media_type=media_type,
        caption=body.get("caption"),
        filename=body.get("filename"),
        redis=request.app.state.redis,
    )


@router.post("/messages/{message_id}/recover-media")
async def recover_message_media(
    message_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Fetch a lost Meta photo/video back from the source.

    Meta serves inbound attachments as signed CDN links that expire, so an old
    thread can end up showing an empty bubble where a customer's photo was.
    This asks Meta for the attachment again and re-hosts it permanently."""
    from app.services import meta_media
    try:
        msg = (await db.execute(select(Message).where(
            Message.id == message_id))).scalar_one_or_none()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid message id")
    if msg is None:
        raise HTTPException(status_code=404, detail="Message not found")
    url = await meta_media.recover_one(db, msg)
    if not url:
        raise HTTPException(
            status_code=404,
            detail="Meta no longer has this attachment — it can't be recovered.")
    return {"ok": True, "media_url": url, "media_type": msg.media_type}


@router.delete("/conversations/{conv_id}/messages")
async def clear_chat_history(
    conv_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    if agent.role != "admin" and not agent.is_superuser:
        raise HTTPException(status_code=403, detail="Only admins can clear chat history")

    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Delete all messages AND all activity-log rows so both the thread
    # and the activity log are completely clean after a clear.
    await db.execute(delete(Message).where(Message.conversation_id == conv_id))
    await db.execute(delete(Intercept).where(Intercept.conversation_id == conv_id))

    conv.last_message_preview = None
    conv.last_message_at      = None
    # Return conversation to AI mode so it is ready for a fresh start.
    conv.intercept_mode    = InterceptMode.ai
    conv.assigned_agent_id = None
    conv.intercept_since   = None

    await db.commit()

    redis = request.app.state.redis
    import json, logging as _logging
    _redis_log = _logging.getLogger("neema.redis")

    # Cache invalidation — non-fatal: if Redis is a read replica or temporarily
    # unavailable the cache will expire on its own (TTL=1h).
    try:
        await redis.delete(f"context:{conv.wa_id}")
    except Exception as exc:
        _redis_log.warning("Redis delete failed (context:%s): %s", conv.wa_id, exc)

    # Broadcast — non-fatal: agents will see the cleared state on next refresh.
    try:
        await redis.publish(
            f"ws:channel:{conv_id}",
            json.dumps({
                "type":           "history_cleared",
                "conversationId": conv_id,
                "clearedBy":      agent.name,
            })
        )
    except Exception as exc:
        _redis_log.warning("Redis publish failed (channel:%s): %s", conv_id, exc)

    return {"ok": True, "cleared": True, "conversation_id": conv_id}


# ── Agents ────────────────────────────────────────────────

@router.get("/agents")
async def list_agents(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from sqlalchemy import text
    rows = await db.execute(text("""
        SELECT
            a.id,
            a.name,
            a.email,
            a.role,
            a.is_available,
            a.is_superuser,
            a.avatar_url,
            a.created_at,
            a.last_seen_at,
            COALESCE(a.active_convs, 0)  AS active_convs,
            a.custom_role_id,
            a.custom_permissions,
            r.name        AS role_name,
            r.color       AS role_color,
            r.permissions AS role_permissions
        FROM agents a
        LEFT JOIN custom_roles r ON r.id = a.custom_role_id
        ORDER BY a.name
    """))
    keys = rows.keys()
    return [dict(zip(keys, row)) for row in rows.fetchall()]


@router.patch("/agents/{agent_id}/role")
async def assign_agent_role(
    agent_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current: Agent = Depends(get_current_agent),
):
    from sqlalchemy import text
    import json
    from app.core.permissions import ALL_PERMISSIONS, require_permission

    await require_permission(db, current, "manage_agents",
                             "Only someone who manages agents can assign roles")

    custom_role_id = body.get("custom_role_id")
    if not custom_role_id:
        raise HTTPException(status_code=422, detail="custom_role_id is required")

    role_row = await db.execute(
        text("SELECT id FROM custom_roles WHERE id = :id"),
        {"id": custom_role_id},
    )
    if not role_row.fetchone():
        raise HTTPException(status_code=404, detail="Role not found")

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if agent.is_superuser and not current.is_superuser:
        raise HTTPException(status_code=403,
                            detail="Only a superuser can change a superuser's role")

    custom_permissions = body.get("custom_permissions")
    if custom_permissions is not None:
        if (not isinstance(custom_permissions, list)
                or any(not isinstance(p, str) for p in custom_permissions)):
            raise HTTPException(status_code=422,
                                detail="custom_permissions must be a list of permission names")
        unknown = sorted(set(custom_permissions) - set(ALL_PERMISSIONS))
        if unknown:
            raise HTTPException(status_code=422,
                                detail=f"Unknown permissions: {', '.join(unknown)}")
    perms_json = json.dumps(custom_permissions) if custom_permissions is not None else None

    await db.execute(
        text("""
            UPDATE agents
            SET custom_role_id     = :role_id,
                custom_permissions = CAST(:perms AS jsonb)
            WHERE id = :agent_id
        """),
        {"role_id": custom_role_id, "perms": perms_json, "agent_id": agent_id},
    )
    await db.commit()

    row = await db.execute(
        text("""
            SELECT a.id, a.name, a.email, a.role, a.is_available,
                   a.custom_role_id, a.custom_permissions,
                   r.name  AS role_name,
                   r.color AS role_color
            FROM agents a
            LEFT JOIN custom_roles r ON r.id = a.custom_role_id
            WHERE a.id = :id
        """),
        {"id": agent_id},
    )
    keys = row.keys()
    data = row.fetchone()
    return dict(zip(keys, data))


@router.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, body: dict,
                       db: AsyncSession = Depends(get_db),
                       current: Agent = Depends(get_current_agent)):
    """Edit an agent. Anyone may change their own name, email, password and
    availability (as on their Profile); everything else — another agent's
    account, or any legacy role — needs manage_agents, and only a superuser
    touches a superuser's account."""
    from app.core.security import hash_password
    from app.core.permissions import permissions_of
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    is_self = str(agent.id) == str(current.id)
    manages = "manage_agents" in await permissions_of(db, current)
    wants_role = bool(body.get("role"))
    account_change = any(body.get(k) for k in ("name", "email", "role", "password"))
    if not is_self and not manages:
        raise HTTPException(status_code=403,
                            detail="Only someone who manages agents can change another agent")
    if wants_role and not manages:
        raise HTTPException(status_code=403,
                            detail="Only someone who manages agents can change a role")
    if agent.is_superuser and not current.is_superuser and not is_self and account_change:
        raise HTTPException(status_code=403,
                            detail="Only a superuser can change a superuser's account")

    if "name" in body and body["name"]:
        agent.name = str(body["name"]).strip()[:100] or agent.name
    if "email" in body and body["email"]:
        email = _clean_email(body["email"])
        if await _email_taken(db, email, exclude_id=agent.id):
            raise HTTPException(status_code=409, detail="Another agent already uses that email")
        agent.email = email
    if wants_role:
        new_role = _valid_role(body["role"])
        if (_role_str(agent.role) == "admin" and new_role != "admin"
                and not agent.is_superuser and not await _other_admins_exist(db, agent.id)):
            raise HTTPException(status_code=409,
                                detail="This is the last admin — make someone else an admin first")
        agent.role = new_role
    if "is_available" in body:
        agent.is_available = bool(body["is_available"])
    if "password" in body and body["password"]:
        agent.password_hash = hash_password(_valid_password(body["password"]))
    await db.commit()
    return {"ok": True}


# ── Agent-account helpers ──────────────────────────────────────────────────────

def _role_str(role) -> str:
    return getattr(role, "value", role) or ""


def _valid_role(role) -> str:
    from app.models.agent import AgentRole
    value = str(role).strip().lower()
    if value not in {r.value for r in AgentRole}:
        raise HTTPException(status_code=422,
                            detail="role must be one of: admin, agent, readonly")
    return value


def _valid_password(password) -> str:
    password = str(password)
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")
    return password


def _clean_email(email) -> str:
    email = str(email).strip()
    if "@" not in email or len(email) > 200:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return email


async def _email_taken(db: AsyncSession, email: str, exclude_id=None) -> bool:
    """Case-insensitive: two accounts that differ only in capitals are one
    person's typo, and sign-in would pick whichever matched exactly."""
    from sqlalchemy import func
    q = select(Agent.id).where(func.lower(Agent.email) == email.lower())
    if exclude_id is not None:
        q = q.where(Agent.id != exclude_id)
    return (await db.execute(q.limit(1))).first() is not None


async def _other_admins_exist(db: AsyncSession, excluding_id) -> bool:
    """Is there still someone who can run the team without this agent?"""
    from app.models.agent import AgentRole
    q = select(Agent.id).where(
        Agent.id != excluding_id,
        (Agent.role == AgentRole.admin) | (Agent.is_superuser.is_(True)),
    ).limit(1)
    return (await db.execute(q)).first() is not None


# ── Orders ────────────────────────────────────────────────────────────────────

@router.get("/orders")
async def list_orders(
    status: str | None = None,
    wa_id: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.order_event import OrderEvent
    q = select(OrderEvent).order_by(OrderEvent.created_at.desc())
    if status:
        q = q.where(OrderEvent.status == status)
    if wa_id:
        q = q.where(OrderEvent.wa_id == wa_id)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/orders/{order_id}")
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.order_event import OrderEvent
    result = await db.execute(
        select(OrderEvent).where(OrderEvent.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.patch("/orders/{order_id}")
async def update_order(
    order_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.order_event import OrderEvent
    result = await db.execute(
        select(OrderEvent).where(OrderEvent.id == order_id)
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    allowed = {"status", "payment_status", "fulfillment_status", "reply_text"}
    for k, v in body.items():
        if k in allowed:
            setattr(order, k, v)
    await db.commit()
    return order


# ── Catalog ───────────────────────────────────────────────────────────────────

@router.get("/catalog/audit")
async def catalog_price_audit(
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Where the hub's prices disagree with themselves.

    Two kinds of finding, both hub-data problems Neema can only repeat: a USD
    row that is not KES / rate (a hand-set dollar column with a $10 floor put
    a KES 10 cup at $10 and a KES 36,000 tray set at $600), and a pack good
    priced per single piece with no quantity in its name. Nothing here changes
    a price — it says which rows to fix in the hub.
    """
    from app.core.config import settings
    from app.services import n8n_bridge as svc
    from app.services.price_audit import audit
    items = await svc.catalog_items(db, request.app.state.redis)
    return audit(items, settings.usd_kes_rate or 100)


@router.get("/catalog")
async def list_catalog(
    request: Request,
    category: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Operator catalogue view.

    Reads the SAME source the AI sells from — the Bethany House hub when
    `catalog_source=hub` (live prices + stock), falling back to Neema's local
    table if the hub is unreachable. Read-only here: products are maintained in
    the hub, so operators see exactly what the agent quotes.
    """
    from app.services import n8n_bridge as svc
    items = await svc.catalog_items(db, request.app.state.redis)
    if category:
        items = [i for i in items if (i.get("category") or "") == category]
    if search:
        needle = search.lower()
        items = [
            i for i in items
            if needle in (i.get("name") or "").lower()
            or needle in (i.get("sku") or "").lower()
            or any(needle in str(a).lower() for a in (i.get("aliases") or []))
        ]
    return items


@router.post("/catalog")
async def create_catalog_item(
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.catalog import Catalog
    from decimal import Decimal, InvalidOperation
    if not body.get("name"):
        raise HTTPException(status_code=422, detail="name is required")
    try:
        price = Decimal(str(body["price"])) if "price" in body else Decimal("0")
    except (InvalidOperation, KeyError):
        raise HTTPException(status_code=422, detail="price must be a valid number")
    item = Catalog(
        sku=body.get("sku", ""),
        name=body["name"],
        price=price,
        unit=body.get("unit"),
        category=body.get("category"),
        description=body.get("description"),
        aliases=body.get("aliases", []),
        in_stock=body.get("in_stock", True),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.patch("/catalog/{item_id}")
async def update_catalog_item(
    item_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.catalog import Catalog
    from decimal import Decimal, InvalidOperation
    result = await db.execute(
        select(Catalog).where(Catalog.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    allowed = {"name", "price", "unit", "category", "description", "aliases", "in_stock", "sku"}
    for k, v in body.items():
        if k in allowed:
            if k == "price":
                try:
                    setattr(item, k, Decimal(str(v)))
                except (InvalidOperation, ValueError):
                    raise HTTPException(status_code=422, detail="price must be a valid number")
            else:
                setattr(item, k, v)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/catalog/{item_id}")
async def delete_catalog_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.models.catalog import Catalog
    result = await db.execute(
        select(Catalog).where(Catalog.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    await db.delete(item)
    await db.commit()
    return {"ok": True}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def overview_stats(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Headline counts, counted by the DATABASE.

    This used to load every conversation, agent, order and catalogue row as a
    Python object and count them in a loop — 14,000 conversations per call. It
    is also what the inbox's totals must now come from: once the list is
    paginated, a count taken over the rows the browser happens to hold is a
    count of one page.

    Every field keeps its exact previous meaning, NULLs included: an order
    whose status is NULL was "not cancelled" to the Python and still is.

    channel_breakdown used to walk a hard-coded list — whatsapp, messenger,
    instagram, tiktok, email, sms — with no "facebook". Facebook comment
    threads are 55% of all conversations, so the server-side breakdown dropped
    more than half the inbox. It now groups by whatever channels exist.
    """
    from app.models.order_event import OrderEvent
    from app.models.catalog import Catalog
    from app.models.conversation import ConvStatus, InterceptMode
    from sqlalchemy import func, or_

    open_c, human_c, ai_c = (await db.execute(select(
        func.count().filter(Conversation.status == ConvStatus.open),
        func.count().filter(Conversation.intercept_mode == InterceptMode.human),
        func.count().filter(Conversation.intercept_mode == InterceptMode.ai),
    ))).one()

    active_a, total_a = (await db.execute(select(
        func.count().filter(Agent.is_available.is_(True)),
        func.count(),
    ).select_from(Agent))).one()

    not_cancelled = or_(OrderEvent.status.is_(None), OrderEvent.status != "cancelled")
    (revenue, total_o, pending_o, delivered_o, confirmed_o, cancelled_o) = (await db.execute(select(
        func.coalesce(func.sum(OrderEvent.subtotal).filter(not_cancelled), 0),
        func.count(),
        func.count().filter(OrderEvent.status.in_(("open", "pending"))),
        func.count().filter(OrderEvent.status == "delivered"),
        func.count().filter(OrderEvent.status == "confirmed"),
        func.count().filter(OrderEvent.status == "cancelled"),
    ).select_from(OrderEvent))).one()

    in_stock, total_items = (await db.execute(select(
        func.count().filter(Catalog.in_stock.is_(True)),
        func.count(),
    ).select_from(Catalog))).one()

    by_channel = (await db.execute(
        select(
            Conversation.channel,
            func.count(),
            func.count().filter(Conversation.status == ConvStatus.open),
        ).group_by(Conversation.channel)
    )).all()
    # Known channels keep their familiar order; anything new follows by name.
    order = ("whatsapp", "messenger", "facebook", "instagram", "tiktok", "email", "sms", "web")
    by_channel = sorted(
        by_channel,
        key=lambda r: (order.index(r[0]) if r[0] in order else len(order), r[0] or ""),
    )

    return {
        "open_conversations":   int(open_c),
        "human_conversations":  int(human_c),
        "ai_conversations":     int(ai_c),
        "active_agents":        int(active_a),
        "total_agents":         int(total_a),
        "total_revenue":        float(revenue or 0),
        "total_orders":         int(total_o),
        "pending_orders":       int(pending_o),
        "delivered_orders":     int(delivered_o),
        "confirmed_orders":     int(confirmed_o),
        "cancelled_orders":     int(cancelled_o),
        "in_stock_items":       int(in_stock),
        "total_items":          int(total_items),
        "channel_breakdown":    [
            {"channel": ch, "count": int(cnt), "open": int(opn)}
            for ch, cnt, opn in by_channel
            if cnt > 0
        ],
    }


# ── Me (current agent profile) ────────────────────────────────────────────────

@router.get("/me")
async def get_me(agent: Agent = Depends(get_current_agent)):
    from app.core.permissions import agent_public
    return agent_public(agent)


@router.patch("/me")
async def update_me(
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.core.security import hash_password
    from app.core.permissions import agent_public
    if "name" in body:
        name = str(body["name"] or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Name can't be empty")
        agent.name = name[:100]
    if "email" in body:
        email = _clean_email(body["email"] or "")
        if await _email_taken(db, email, exclude_id=agent.id):
            raise HTTPException(status_code=409, detail="Another agent already uses that email")
        agent.email = email
    if "password" in body:
        agent.password_hash = hash_password(_valid_password(body["password"] or ""))
    await db.commit()
    await db.refresh(agent)
    return agent_public(agent)


# ── Agents CRUD ───────────────────────────────────────────────────────────────

@router.post("/agents")
async def create_agent(
    body: dict,
    db: AsyncSession = Depends(get_db),
    current: Agent = Depends(get_current_agent),
):
    from sqlalchemy.exc import IntegrityError
    from app.core.security import hash_password
    from app.core.permissions import agent_public, require_permission
    await require_permission(db, current, "manage_agents",
                             "Only someone who manages agents can add one")
    missing = [f for f in ("name", "email", "password") if not body.get(f)]
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required fields: {', '.join(missing)}")
    email = _clean_email(body["email"])
    if await _email_taken(db, email):
        raise HTTPException(status_code=409, detail="An agent with that email already exists")
    agent = Agent(
        name=str(body["name"]).strip()[:100],
        email=email,
        password_hash=hash_password(_valid_password(body["password"])),
        role=_valid_role(body.get("role") or "agent"),
        is_available=True,
    )
    db.add(agent)
    try:
        await db.commit()
    except IntegrityError:
        # Two adds racing past the check above: the unique index decides.
        await db.rollback()
        raise HTTPException(status_code=409, detail="An agent with that email already exists")
    await db.refresh(agent)
    return agent_public(agent)


@router.delete("/agents/{agent_id}")
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current: Agent = Depends(get_current_agent),
):
    from app.core.permissions import require_permission
    await require_permission(db, current, "manage_agents",
                             "Only someone who manages agents can remove one")
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if str(agent.id) == str(current.id):
        raise HTTPException(status_code=409, detail="You can't remove your own account")
    if agent.is_superuser and not current.is_superuser:
        raise HTTPException(status_code=403, detail="Only a superuser can remove a superuser")
    if ((_role_str(agent.role) == "admin" or agent.is_superuser)
            and not await _other_admins_exist(db, agent.id)):
        raise HTTPException(status_code=409,
                            detail="This is the last admin — make someone else an admin first")
    await db.delete(agent)
    await db.commit()
    return {"ok": True}

# ── Meta profile backfill ─────────────────────────────────────────────────────
# Retro-enrich "Unknown" Messenger/Instagram/Facebook contacts now that the Meta
# app is approved for the Profile API. Operator-triggered (safe, bounded); a
# gated pass also runs on startup (see main.py) so the backlog drains on its own.
@router.post("/meta/backfill-profiles")
async def backfill_meta_profiles(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    from app.services.meta_enrich import backfill_unknown_profiles
    return await backfill_unknown_profiles(db, limit=min(max(limit, 1), 200))


@router.post("/whatsapp-invite")
async def whatsapp_invite(
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Open a WhatsApp thread with a customer who reached us on Messenger/Facebook,
    by sending the approved `whatsapp_invite` template to their number. Meta
    requires a template to message first (no open session). Records the outbound
    invite on the WhatsApp conversation so it shows in the inbox; their reply lands
    via the WABA webhook and continues the thread. Returns {ok, wa_id}."""
    from app.core.phone import is_plausible_phone
    from app.services.identity import resolve_or_create_person
    from app.services.channel import get_or_create_conversation
    from app.services import n8n_bridge as bridge
    from app.models.message import Message, MsgDirection, MsgSender
    from app.core.config import settings

    phone = str(body.get("phone") or "").strip()
    name = str(body.get("name") or "").strip()
    wa_id = phone.lstrip("+").strip()
    if not is_plausible_phone(wa_id):
        raise HTTPException(status_code=400, detail="A valid phone number is required to invite to WhatsApp.")
    if not settings.waba_token or not settings.waba_phone_number_id:
        raise HTTPException(status_code=503, detail="WhatsApp sending is not configured.")

    first = (name.split()[0] if name else "there")
    # The FULL message the customer receives — recorded verbatim so the Neema chat
    # view shows the whole invite, not a truncated placeholder. Mirrors the
    # approved `whatsapp_invite` template body (keep in sync if the template edits).
    full_body = (
        f"Hello {first}, this is Bethany House. We saw your message on "
        "Facebook/Messenger. May we continue here on WhatsApp to finalise your "
        "order? Reply and we'll help right away."
    )
    try:
        await bridge.send_wa_template(
            wa_id, settings.wa_invite_template, settings.wa_invite_lang,
            body_params=[first],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"WhatsApp invite failed: {exc}")

    # Record it so the WhatsApp thread appears with the full invite already sent,
    # and TAG the customer `whatsapp-invited` so the inbox tag filter can show
    # everyone we've invited (the "[WhatsApp invite sent]" marker becomes a
    # filterable label instead of inline text).
    try:
        ident = await resolve_or_create_person(db, "whatsapp", wa_id,
                                               display_name=name or None,
                                               source="whatsapp_invite")
        conv = await get_or_create_conversation(db, "whatsapp", wa_id,
                                                person_id=ident.person_id, wa_id=wa_id)
        db.add(Message(
            channel="whatsapp", external_id=wa_id, wa_id=wa_id,
            person_id=ident.person_id, conversation_id=conv.id,
            direction=MsgDirection.outbound, sender=MsgSender.human_agent,
            text=full_body,
        ))
        # Tag on the WhatsApp User row (the inbox tag filter reads user.state.tags).
        from sqlalchemy.orm.attributes import flag_modified
        u = (await db.execute(select(User).where(User.wa_id == wa_id))).scalar_one_or_none()
        if u is None:
            u = User(wa_id=wa_id, phone=wa_id, name=name or None, person_id=ident.person_id)
            db.add(u)
        st = dict(u.state or {})
        tags = list(st.get("tags") or [])
        if "whatsapp-invited" not in tags:
            tags.append("whatsapp-invited")
        st["tags"] = tags
        u.state = st
        flag_modified(u, "state")
        await db.commit()
    except Exception:
        await db.rollback()   # the template already went out; recording is best-effort

    return {"ok": True, "wa_id": wa_id}


# ── WhatsApp voice calling — the softphone's backend ─────────────────────────
# services/call_log.py owns the statuses and the live events; these routes are
# the agent's side of each transition. Every change reaches every agent at once
# (ws:channel:calls), so two phones never disagree about a call.

def _redis(request: Request):
    return getattr(request.app.state, "redis", None)


def _answered_by(value) -> str | None:
    """The redis answer-lock holds "<agent id>|<agent name>" (older: the id)."""
    if not value:
        return None
    v = value.decode() if isinstance(value, bytes) else str(value)
    return v.split("|", 1)[1] if "|" in v else None


@router.get("/calls/ice-config")
async def calls_ice_config(agent: Agent = Depends(get_current_agent)):
    """ICE servers (coturn + STUN) for the softphone's RTCPeerConnection, plus
    whether the softphone should record the call (server-side kill switch) and
    whether recordings get transcribed (so the UI never promises a summary the
    server won't write)."""
    from app.services.wa_calling import ice_servers
    from app.core.config import settings
    return {"ice_servers": ice_servers(), "record": settings.call_recording_enabled,
            "transcribe": bool(settings.whisper_enabled),
            "auto_transcribe": bool(settings.whisper_enabled and settings.whisper_auto)}


@router.get("/calls/permission")
async def calls_permission(
    wa_id: str,
    request: Request,
    agent: Agent = Depends(get_current_agent),
):
    """Whether this customer allowed business calls: granted | denied |
    requested | unknown (never asked — a call may still go through)."""
    from app.services import call_log
    return await call_log.permission(_redis(request), wa_id.lstrip("+").strip())


@router.get("/calls/{call_id}/offer")
async def calls_get_offer(
    call_id: str,
    request: Request,
    agent: Agent = Depends(get_current_agent),
):
    """The caller's SDP offer, stashed by the webhook on `connect`. The softphone
    sets this as its remote description before building an answer."""
    redis = _redis(request)
    if redis is None:
        raise HTTPException(status_code=503, detail="calling unavailable")
    raw = await redis.get(f"wa:call:offer:{call_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="call offer expired or not found")
    import json
    data = json.loads(raw)
    return {"call_id": call_id, "sdp": data.get("sdp"), "from": data.get("from")}


@router.post("/calls/{call_id}/answer")
async def calls_answer(
    call_id: str,
    body: dict,
    request: Request,
    agent: Agent = Depends(get_current_agent),
):
    """Accept the call with the softphone's SDP answer. One agent wins a call via
    a redis lock so two phones can't both answer; the loser's 409 names the
    winner, and every other phone stops ringing on the `call_answered` event."""
    sdp = (body or {}).get("sdp")
    if not sdp:
        raise HTTPException(status_code=400, detail="sdp answer is required")
    from app.services import wa_calling, call_log
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        st = (await db.execute(select(Call.status).where(Call.call_id == call_id))).scalar_one_or_none()
    if st is not None and st not in call_log.LIVE:
        # Over already (the caller gave up, a colleague declined it): say so
        # instead of asking Meta to accept a call that no longer exists.
        raise HTTPException(status_code=410, detail="This call has already ended.")
    redis = _redis(request)
    lock = f"wa:call:answered:{call_id}"
    if redis is not None:
        won = await redis.set(lock, f"{agent.id}|{agent.name or ''}", nx=True, ex=3600)
        if not won:
            who = _answered_by(await redis.get(lock))
            raise HTTPException(status_code=409,
                                detail=f"call already answered by {who}" if who else "call already answered")
    try:
        # accept directly with the SDP answer. (pre_accept+accept back-to-back
        # raced and 502'd — accept alone establishes media fine.)
        await wa_calling.accept(call_id, sdp)
    except Exception as exc:
        if redis is not None:
            await redis.delete(lock)   # let another try
        raise HTTPException(status_code=502, detail=f"accept failed: {exc}")
    moved = await call_log.mark_answered(call_id, agent.id)
    await call_log.publish(redis, {
        "type": "call_answered", "call_id": call_id,
        "agent_id": str(agent.id), "agent_name": agent.name,
        "direction": (moved or {}).get("direction") or "inbound",
    })
    return {"ok": True, "call_id": call_id}


@router.post("/calls/request-permission")
async def calls_request_permission(
    body: dict,
    request: Request,
    agent: Agent = Depends(get_current_agent),
):
    """Ask a customer for permission to call them (interactive
    call_permission_request). Needed before a business-initiated call to someone
    who hasn't allowed calls. Their answer arrives as `call_permission`."""
    from app.core.phone import is_plausible_phone
    from app.services import wa_calling, call_log
    to = str((body or {}).get("to") or "").lstrip("+").strip()
    if not is_plausible_phone(to):
        raise HTTPException(status_code=400, detail="A valid phone number is required.")
    try:
        await wa_calling.request_call_permission(to)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"permission request failed: {exc}")
    perm = await call_log.set_permission(_redis(request), to, "requested")
    await call_log.publish(_redis(request), {"type": "call_permission", **perm})
    return {"ok": True, "permission": perm}


@router.post("/calls/connect")
async def calls_connect(
    body: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Business-initiated call: the softphone hands us its SDP offer; we ask Meta
    to place the call. Returns {call_id}. The customer's SDP answer arrives on the
    calls webhook and is relayed to the phone. Records an outbound Call row so
    it shows in the Calls log."""
    from app.core.phone import is_plausible_phone
    from app.services import call_log
    to = str((body or {}).get("to") or "").lstrip("+").strip()
    sdp = (body or {}).get("sdp")
    name = str((body or {}).get("name") or "").strip() or None
    if not is_plausible_phone(to):
        raise HTTPException(status_code=400, detail="A valid phone number is required.")
    if not sdp:
        raise HTTPException(status_code=400, detail="sdp offer is required")
    from app.services import wa_calling
    try:
        resp = await wa_calling.connect(to, sdp)
    except Exception as exc:
        msg = str(exc)
        if "138006" in msg:
            # Meta's "no call permission": whatever we had on file is stale.
            perm = await call_log.permission(_redis(request), to)
            if perm.get("status") == "granted":
                await call_log.set_permission(_redis(request), to, "unknown")
            raise HTTPException(status_code=409,
                detail="This customer hasn't allowed calls yet. Send them a call "
                       "request — you can call as soon as they tap Allow.")
        raise HTTPException(status_code=502, detail=f"call failed: {wa_calling.friendly_error(msg)}")
    call_id = ((resp.get("calls") or [{}])[0]).get("id")
    if not call_id:
        raise HTTPException(status_code=502, detail="Meta did not return a call id")
    redis = _redis(request)
    if redis is not None:
        # We own it: nobody else can "answer" our outbound call.
        await redis.set(f"wa:call:answered:{call_id}", f"{agent.id}|{agent.name or ''}", ex=3600)
    try:
        from app.services.identity import resolve_person_id_for_wa_id
        pid = await resolve_person_id_for_wa_id(db, to, source="whatsapp_call")
        db.add(Call(call_id=call_id, wa_id=to, caller_name=name, direction="outbound",
                    status="ringing", person_id=pid, agent_id=agent.id))
        await db.commit()
    except Exception:
        await db.rollback()
    await call_log.publish_update(redis, call_id)
    return {"ok": True, "call_id": call_id}


@router.get("/calls")
async def list_calls(
    request: Request,
    limit: int = 50,
    wa_id: str | None = None,
    view: str | None = None,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Recent WhatsApp calls (newest first) for the Calls view — like a phone's
    recents. `wa_id` narrows to one customer; `view=follow_up` to the missed and
    callback calls nobody has returned yet."""
    from app.services import call_log
    await call_log.sweep_stale(db, _redis(request))
    q = select(Call)
    if wa_id:
        q = q.where(Call.wa_id == wa_id.lstrip("+").strip())
    if view == "follow_up":
        q = q.where(Call.status.in_(call_log.FOLLOW_UP), Call.follow_up_done_at.is_(None))
    rows = (await db.execute(
        q.order_by(Call.started_at.desc()).limit(min(max(limit, 1), 200))
    )).scalars().all()
    out = await call_log.serialize_rows(db, rows)
    if view == "follow_up":
        out = [r for r in out if r["follow_up_open"]]
    return out


@router.get("/calls/{call_id}")
async def get_call(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """One call's current row — what a phone that lost its connection reads to
    learn how the call on its screen really ended."""
    from app.services import call_log
    r = await call_log.row(db, call_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return r


@router.post("/calls/{call_id}/terminate")
async def calls_terminate(
    call_id: str,
    request: Request,
    body: dict | None = None,
    agent: Agent = Depends(get_current_agent),
):
    """Hang up, decline or cancel. What it meant is decided by where the call is:
    a ringing inbound call is declined (for the whole team — the caller hears it
    end), our ringing outbound call is cancelled (or failed, with
    `{"reason": "failed"}` when our side couldn't connect), a live call is
    completed."""
    from app.services import wa_calling, call_log
    from app.database import AsyncSessionLocal
    try:
        await wa_calling.terminate(call_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"terminate failed: {exc}")
    async with AsyncSessionLocal() as db:
        c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
        status, direction = (c.status, c.direction) if c else (None, None)
    reason = str((body or {}).get("reason") or "")
    info = None
    if status == "ringing" and direction == "outbound" and reason == "failed":
        # Our side couldn't connect the media before they answered.
        info = await call_log.mark_failed(call_id)
    elif status == "ringing" and direction == "outbound":
        info = await call_log.mark_cancelled(call_id, agent.id)
    elif status == "ringing":
        info = await call_log.mark_declined(call_id, agent.id)
    elif status == "answered":
        info = await call_log.mark_ended(call_id)
    if info is not None:
        info.pop("wa_id", None)
        await call_log.publish(_redis(request), {"type": "call_ended", **info})
    return {"ok": True, "call_id": call_id, "outcome": (info or {}).get("outcome")}


@router.post("/calls/{call_id}/callback")
async def calls_callback(
    call_id: str,
    request: Request,
    agent: Agent = Depends(get_current_agent),
):
    """Decline now, but flag the customer for a call-back — ends the ringing call
    and marks it `callback` so it surfaces in the Calls view as a follow-up."""
    from app.services import wa_calling, call_log
    try:
        await wa_calling.terminate(call_id)
    except Exception:
        pass   # may already be gone; still record the intent
    info = await call_log.mark_callback(call_id, agent.id)
    if info is None:
        # Already over (the caller gave up first): still owe them the call.
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
            if c is not None and c.status == "missed":
                c.status = "callback"
                c.agent_id = agent.id
                await db.commit()
        await call_log.publish_update(_redis(request), call_id)
    else:
        info.pop("wa_id", None)
        await call_log.publish(_redis(request), {"type": "call_ended", **info})
    return {"ok": True, "call_id": call_id}


@router.post("/calls/{call_id}/follow-up-done")
async def calls_follow_up_done(
    call_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Clear a missed / callback call from the follow-up list (handled in chat,
    or not worth a call)."""
    from app.services import call_log
    if not await call_log.mark_follow_up_done(db, call_id):
        raise HTTPException(status_code=404, detail="Call not found")
    await call_log.publish_update(_redis(request), call_id)
    return {"ok": True, "call_id": call_id}


@router.post("/calls/{call_id}/recording")
async def calls_upload_recording(
    call_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """The softphone uploads the recorded call audio (both sides mixed) on hangup.
    Saved to disk; then (if whisper_auto) transcription is scheduled immediately,
    otherwise it waits for an on-demand /transcribe. Gated by call_recording_enabled."""
    import aiofiles, os, uuid
    from app.core.config import settings
    from app.models.call import Call
    from app.routers.media import MEDIA_DIR

    if not settings.call_recording_enabled:
        raise HTTPException(status_code=403, detail="Call recording is disabled.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty recording.")
    MB = 1024 * 1024
    if len(content) > 60 * MB:
        raise HTTPException(status_code=413, detail="Recording too large — max 60 MB.")

    os.makedirs(MEDIA_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".webm"
    saved_name = f"call_{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(MEDIA_DIR, saved_name)
    async with aiofiles.open(file_path, "wb") as f:
        await f.write(content)

    public_base = getattr(settings, "media_public_url", "").rstrip("/")
    recording_url = f"{public_base}/api/admin/media/{saved_name}" if public_base else saved_name

    auto = bool(settings.whisper_enabled and settings.whisper_auto)
    c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
    if c is None:
        # A recording implies the call happened; keep a row so it can be transcribed.
        c = Call(call_id=call_id, status="completed")
        db.add(c)
    c.recording_url = recording_url
    c.transcript_status = "pending" if auto else "recorded"
    await db.commit()

    if auto:
        from app.services.call_transcribe import schedule_transcription
        schedule_transcription(call_id)
    from app.services import call_log
    await call_log.publish_update(getattr(request.app.state, "redis", None), call_id)
    return {"ok": True, "call_id": call_id, "will_transcribe": auto}


@router.get("/calls/{call_id}/transcript")
async def calls_get_transcript(
    call_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """The transcript + AI summary + insights + status for a call."""
    c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Call not found")
    return {
        "call_id": c.call_id,
        "status": c.transcript_status,
        "transcript": c.transcript,
        "summary": c.summary,
        "insights": c.insights,
        "language": c.transcript_lang,
        "has_recording": bool(c.recording_url),
        "recording_url": c.recording_url,
    }


@router.post("/calls/{call_id}/transcribe")
async def calls_transcribe(
    call_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Transcribe + summarise a recorded call on demand — the free path: spend the
    box's CPU only on the calls you care about. Needs a recording and Whisper on."""
    from app.core.config import settings
    from app.services import call_log
    if not settings.whisper_enabled:
        raise HTTPException(
            status_code=409,
            detail="Transcription isn't enabled yet. Set WHISPER_ENABLED=1 (self-hosted "
                   "faster-whisper) on the server to turn it on.")
    c = (await db.execute(select(Call).where(Call.call_id == call_id))).scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Call not found")
    if not c.recording_url:
        raise HTTPException(status_code=409, detail="No recording was captured for this call.")
    if c.transcript_status in ("pending", "processing"):
        return {"ok": True, "call_id": call_id, "status": c.transcript_status}
    c.transcript_status = "pending"
    await db.commit()
    from app.services.call_transcribe import schedule_transcription
    schedule_transcription(call_id)
    await call_log.publish_update(getattr(request.app.state, "redis", None), call_id)
    return {"ok": True, "call_id": call_id, "status": "pending"}

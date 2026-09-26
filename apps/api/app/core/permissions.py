"""Server-side permissions — the same rules the dashboard applies.

Until now the API only checked that a caller was signed in: the web and the
app hid the Team and Roles controls from agents without the permission, but
any agent could call the endpoints directly and, say, reset the admin's
password or make themselves an admin. These helpers resolve an agent's
effective permissions exactly as apps/web/src/lib/permissions.ts does
(`getAgentPermissions` over `mapAgent`), so the server now refuses what the
dashboard would never offer.

Resolution (web parity):
  1. is_superuser                                  → every permission
  2. custom_permissions ?? the custom role's list  → that list, if non-empty
  3. otherwise the legacy role's defaults (admin / agent / readonly)
"""
from __future__ import annotations

import json

from fastapi import Depends, HTTPException
from sqlalchemy import text

# Keys must match custom_roles.permissions and the web's PERMS.
ALL_PERMISSIONS: tuple[str, ...] = (
    "view_conversations", "reply_conversations", "intercept_release",
    "close_conversations", "transfer_conversations", "add_notes",
    "view_orders", "manage_orders",
    "view_catalog", "manage_catalog",
    "view_leads", "manage_leads", "view_crm", "edit_crm",
    "view_analytics", "view_reports", "export_reports",
    "manage_agents", "manage_roles", "manage_settings", "clear_chat_history",
)

LEGACY_FALLBACK: dict[str, tuple[str, ...]] = {
    "admin": ALL_PERMISSIONS,
    "agent": (
        "view_conversations", "reply_conversations", "intercept_release",
        "close_conversations", "transfer_conversations", "add_notes",
        "view_orders", "manage_orders", "view_catalog", "view_crm", "view_leads",
    ),
    "readonly": (
        "view_conversations", "view_orders", "view_catalog", "view_crm",
        "view_leads", "view_analytics",
    ),
}


def _as_list(value) -> list[str] | None:
    """A JSONB list as the driver hands it back (list, JSON text or NULL)."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, (list, tuple)):
        return [str(p) for p in value]
    return None


def role_value(role) -> str:
    return getattr(role, "value", role) or ""


def effective_permissions(*, role, is_superuser: bool,
                          custom_permissions=None, role_permissions=None) -> set[str]:
    if is_superuser:
        return set(ALL_PERMISSIONS)
    custom = _as_list(custom_permissions)
    listed = custom if custom is not None else _as_list(role_permissions)
    if listed:
        return set(listed)
    return set(LEGACY_FALLBACK.get(role_value(role), ()))


async def permissions_of(db, agent) -> set[str]:
    """The signed-in agent's effective permissions, read fresh from the DB
    (custom_role_id / custom_permissions are not on the ORM model)."""
    if getattr(agent, "is_superuser", False):
        return set(ALL_PERMISSIONS)
    row = (await db.execute(text(
        "SELECT a.custom_permissions, r.permissions AS role_permissions "
        "FROM agents a LEFT JOIN custom_roles r ON r.id = a.custom_role_id "
        "WHERE a.id = :id"), {"id": str(agent.id)})).fetchone()
    return effective_permissions(
        role=agent.role, is_superuser=False,
        custom_permissions=row[0] if row else None,
        role_permissions=row[1] if row else None,
    )


async def require_permission(db, agent, perm: str,
                             detail: str = "Your role doesn't allow that") -> None:
    if perm not in await permissions_of(db, agent):
        raise HTTPException(status_code=403, detail=detail)


def requires(perm: str, detail: str = "Your role doesn't allow that"):
    """Route dependency: the signed-in agent must hold [perm]."""
    from app.database import get_db
    from app.routers.admin import get_current_agent

    async def _check(db=Depends(get_db), agent=Depends(get_current_agent)):
        await require_permission(db, agent, perm, detail)
        return agent
    return _check


def agent_public(agent) -> dict:
    """An agent as the API may show it — never the password hash."""
    def _iso(v):
        return v.isoformat() if v is not None else None
    return {
        "id": str(agent.id),
        "name": agent.name,
        "email": agent.email,
        "role": role_value(agent.role),
        "is_available": agent.is_available,
        "is_superuser": agent.is_superuser,
        "active_convs": agent.active_convs,
        "avatar_url": agent.avatar_url,
        "created_at": _iso(getattr(agent, "created_at", None)),
        "last_seen_at": _iso(getattr(agent, "last_seen_at", None)),
    }

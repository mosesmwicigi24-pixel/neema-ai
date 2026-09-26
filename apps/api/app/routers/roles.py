# app/routers/roles.py
# Custom roles CRUD + agent role assignment.
# Schema (custom_roles table, agents columns) is created at startup in main.py.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db
from app.models.agent import Agent
from app.routers.admin import get_current_agent
from app.core.permissions import ALL_PERMISSIONS, requires
import re, uuid, json

router = APIRouter()


# ── Roles CRUD ────────────────────────────────────────────────────────────────
# Reading the roles is open to every agent (the dashboard resolves permissions
# from them); writing needs manage_roles, as the Roles tab does on the web.

_ROLE_WRITER = requires("manage_roles", "Only someone who manages roles can change them")
_ROLE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _clean_permissions(perms) -> list[str]:
    if not isinstance(perms, list) or any(not isinstance(p, str) for p in perms):
        raise HTTPException(status_code=422, detail="permissions must be a list of permission names")
    unknown = sorted(set(perms) - set(ALL_PERMISSIONS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown permissions: {', '.join(unknown)}")
    return perms


@router.get("/roles")
async def list_roles(
    db:    AsyncSession = Depends(get_db),
    agent: Agent        = Depends(get_current_agent),
):
    rows = await db.execute(
        text("SELECT id, name, description, color, permissions, protected, created_at "
             "FROM custom_roles ORDER BY protected DESC, name")
    )
    keys = rows.keys()
    return [dict(zip(keys, row)) for row in rows.fetchall()]


@router.post("/roles")
async def create_role(
    body:  dict,
    db:    AsyncSession = Depends(get_db),
    agent: Agent        = Depends(_ROLE_WRITER),
):
    """Create a role. Never an upsert: a POST naming an existing id used to
    rewrite that role in place — protected ones (Super Admin) included."""
    if not body.get("name"):
        raise HTTPException(status_code=422, detail="name is required")

    role_id = body.get("id") or f"role_{uuid.uuid4().hex[:8]}"
    if not isinstance(role_id, str) or not _ROLE_ID.match(role_id):
        raise HTTPException(status_code=422, detail="Invalid role id")
    perms   = json.dumps(_clean_permissions(body.get("permissions", [])))

    result = await db.execute(text("""
        INSERT INTO custom_roles (id, name, description, color, permissions, protected)
        VALUES (:id, :name, :desc, :color, CAST(:perms AS jsonb), FALSE)
        ON CONFLICT (id) DO NOTHING
        RETURNING id
    """), {
        "id":    role_id,
        "name":  body["name"],
        "desc":  body.get("description", ""),
        "color": body.get("color", "#589b31"),
        "perms": perms,
    })
    if result.fetchone() is None:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A role with that id already exists")
    await db.commit()

    row = await db.execute(
        text("SELECT id, name, description, color, permissions, protected, created_at "
             "FROM custom_roles WHERE id = :id"),
        {"id": role_id},
    )
    keys = row.keys()
    return dict(zip(keys, row.fetchone()))


@router.patch("/roles/{role_id}")
async def update_role(
    role_id: str,
    body:    dict,
    db:      AsyncSession = Depends(get_db),
    agent:   Agent        = Depends(_ROLE_WRITER),
):
    row = await db.execute(
        text("SELECT protected FROM custom_roles WHERE id = :id"),
        {"id": role_id},
    )
    existing = row.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Role not found")
    if existing[0]:
        raise HTTPException(status_code=403, detail="Cannot modify a protected role")

    sets, params = [], {"id": role_id}
    if "name"        in body: sets.append("name = :name");                params["name"]  = body["name"]
    if "description" in body: sets.append("description = :desc");          params["desc"]  = body["description"]
    if "color"       in body: sets.append("color = :color");               params["color"] = body["color"]
    if "permissions" in body: sets.append("permissions = CAST(:perms AS jsonb)");  params["perms"] = json.dumps(_clean_permissions(body["permissions"]))

    if sets:
        await db.execute(
            text(f"UPDATE custom_roles SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        await db.commit()

    row = await db.execute(
        text("SELECT id, name, description, color, permissions, protected, created_at "
             "FROM custom_roles WHERE id = :id"),
        {"id": role_id},
    )
    keys = row.keys()
    return dict(zip(keys, row.fetchone()))


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: str,
    db:      AsyncSession = Depends(get_db),
    agent:   Agent        = Depends(_ROLE_WRITER),
):
    row = await db.execute(
        text("SELECT protected FROM custom_roles WHERE id = :id"),
        {"id": role_id},
    )
    existing = row.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Role not found")
    if existing[0]:
        raise HTTPException(status_code=403, detail="Cannot delete a protected role")

    await db.execute(
        text("UPDATE agents SET custom_role_id = NULL, custom_permissions = NULL "
             "WHERE custom_role_id = :id"),
        {"id": role_id},
    )
    await db.execute(
        text("DELETE FROM custom_roles WHERE id = :id"),
        {"id": role_id},
    )
    await db.commit()
    return {"ok": True}


# Note: PATCH /agents/{agent_id}/role is defined in admin.py
# (it must appear before the catch-all PATCH /agents/{agent_id} route)
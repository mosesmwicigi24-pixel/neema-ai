# app/routers/roles.py
# Custom roles CRUD + agent role assignment.
# Schema (custom_roles table, agents columns) is created at startup in main.py.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db
from app.models.agent import Agent
from app.routers.admin import get_current_agent
import uuid, json

router = APIRouter()


# ── Roles CRUD ────────────────────────────────────────────────────────────────

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
    agent: Agent        = Depends(get_current_agent),
):
    if not body.get("name"):
        raise HTTPException(status_code=422, detail="name is required")

    role_id = body.get("id") or f"role_{uuid.uuid4().hex[:8]}"
    perms   = json.dumps(body.get("permissions", []))

    await db.execute(text("""
        INSERT INTO custom_roles (id, name, description, color, permissions, protected)
        VALUES (:id, :name, :desc, :color, :perms::jsonb, FALSE)
        ON CONFLICT (id) DO UPDATE
            SET name        = EXCLUDED.name,
                description = EXCLUDED.description,
                color       = EXCLUDED.color,
                permissions = EXCLUDED.permissions
    """), {
        "id":    role_id,
        "name":  body["name"],
        "desc":  body.get("description", ""),
        "color": body.get("color", "#589b31"),
        "perms": perms,
    })
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
    agent:   Agent        = Depends(get_current_agent),
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
    if "permissions" in body: sets.append("permissions = :perms::jsonb");  params["perms"] = json.dumps(body["permissions"])

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
    agent:   Agent        = Depends(get_current_agent),
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


# ── Assign role to agent ──────────────────────────────────────────────────────

@router.patch("/agents/{agent_id}/role")
async def assign_agent_role(
    agent_id: str,
    body:     dict,
    db:       AsyncSession = Depends(get_db),
    current:  Agent        = Depends(get_current_agent),
):
    """Assign a custom role and snapshot its permissions onto the agent."""
    role_id = body.get("custom_role_id")
    if not role_id:
        raise HTTPException(status_code=422, detail="custom_role_id is required")

    row = await db.execute(
        text("SELECT permissions FROM custom_roles WHERE id = :id"),
        {"id": role_id},
    )
    role_row = row.fetchone()
    if not role_row:
        raise HTTPException(status_code=404, detail="Role not found")

    permissions = role_row[0]   # list from JSONB

    await db.execute(
        text("UPDATE agents "
             "SET custom_role_id = :role_id, custom_permissions = :perms::jsonb "
             "WHERE id = :agent_id"),
        {"role_id": role_id, "perms": json.dumps(permissions), "agent_id": agent_id},
    )
    await db.commit()
    return {"ok": True, "custom_role_id": role_id, "permissions": permissions}
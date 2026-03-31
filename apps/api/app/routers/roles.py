# app/routers/roles.py
# Custom roles system.
# Roles are stored in a `custom_roles` table (created lazily on first request).
# Agents get a `custom_role_id` (text) and `permissions` (JSONB array) column,
# both added with ADD COLUMN IF NOT EXISTS — no Alembic migration needed.

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.database import get_db
from app.models.agent import Agent
from app.routers.admin import get_current_agent
import uuid, json

router = APIRouter()

# ── Lazy schema bootstrap ─────────────────────────────────────────────────────

BOOTSTRAP_SQL = """
CREATE TABLE IF NOT EXISTS custom_roles (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT '#589b31',
    permissions JSONB NOT NULL DEFAULT '[]',
    protected   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE agents ADD COLUMN IF NOT EXISTS custom_role_id TEXT;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS custom_permissions JSONB;

INSERT INTO custom_roles (id, name, description, color, permissions, protected)
VALUES
  ('super_admin', 'Super Admin',
   'Full platform access — cannot be modified',
   '#7c3aed',
   '["view_conversations","reply_conversations","intercept_release","close_conversations",
     "transfer_conversations","add_notes","view_orders","manage_orders","view_catalog",
     "manage_catalog","view_leads","manage_leads","view_crm","edit_crm","view_analytics",
     "view_reports","export_reports","manage_agents","manage_roles","manage_settings"]',
   TRUE),
  ('agent', 'Agent',
   'Handle conversations and orders',
   '#589b31',
   '["view_conversations","reply_conversations","intercept_release","close_conversations",
     "transfer_conversations","add_notes","view_orders","manage_orders","view_catalog",
     "view_crm","view_leads"]',
   FALSE),
  ('viewer', 'Viewer',
   'Read-only access',
   '#699a32',
   '["view_conversations","view_orders","view_catalog","view_crm","view_leads","view_analytics"]',
   FALSE)
ON CONFLICT (id) DO NOTHING;
"""

_bootstrapped = False

async def ensure_schema(db: AsyncSession):
    global _bootstrapped
    if _bootstrapped:
        return
    await db.execute(text(BOOTSTRAP_SQL))
    await db.commit()
    _bootstrapped = True


# ── Roles CRUD ────────────────────────────────────────────────────────────────

@router.get("/roles")
async def list_roles(
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    await ensure_schema(db)
    rows = await db.execute(text("SELECT * FROM custom_roles ORDER BY protected DESC, name"))
    cols = rows.keys()
    return [dict(zip(cols, row)) for row in rows.fetchall()]


@router.post("/roles")
async def create_role(
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    await ensure_schema(db)
    if not body.get("name"):
        raise HTTPException(status_code=422, detail="name is required")
    role_id = body.get("id") or f"role_{uuid.uuid4().hex[:8]}"
    perms = json.dumps(body.get("permissions", []))
    await db.execute(text("""
        INSERT INTO custom_roles (id, name, description, color, permissions, protected)
        VALUES (:id, :name, :desc, :color, :perms::jsonb, FALSE)
        ON CONFLICT (id) DO UPDATE
          SET name=EXCLUDED.name, description=EXCLUDED.description,
              color=EXCLUDED.color, permissions=EXCLUDED.permissions
    """), {"id": role_id, "name": body["name"],
           "desc": body.get("description", ""),
           "color": body.get("color", "#589b31"),
           "perms": perms})
    await db.commit()
    row = await db.execute(text("SELECT * FROM custom_roles WHERE id=:id"), {"id": role_id})
    cols = row.keys()
    return dict(zip(cols, row.fetchone()))


@router.patch("/roles/{role_id}")
async def update_role(
    role_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    await ensure_schema(db)
    row = await db.execute(text("SELECT * FROM custom_roles WHERE id=:id"), {"id": role_id})
    existing = row.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Role not found")
    if existing[5]:  # protected flag
        raise HTTPException(status_code=403, detail="Cannot modify a protected role")

    updates = {}
    if "name"        in body: updates["name"]        = body["name"]
    if "description" in body: updates["description"] = body["description"]
    if "color"       in body: updates["color"]        = body["color"]
    if "permissions" in body: updates["permissions"]  = json.dumps(body["permissions"])

    if updates:
        set_clause = ", ".join(
            f"{k}=:{k}" + ("::jsonb" if k == "permissions" else "")
            for k in updates
        )
        await db.execute(
            text(f"UPDATE custom_roles SET {set_clause} WHERE id=:id"),
            {**updates, "id": role_id}
        )
        await db.commit()

    row = await db.execute(text("SELECT * FROM custom_roles WHERE id=:id"), {"id": role_id})
    cols = row.keys()
    return dict(zip(cols, row.fetchone()))


@router.delete("/roles/{role_id}")
async def delete_role(
    role_id: str,
    db: AsyncSession = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    await ensure_schema(db)
    row = await db.execute(text("SELECT protected FROM custom_roles WHERE id=:id"), {"id": role_id})
    existing = row.fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Role not found")
    if existing[0]:
        raise HTTPException(status_code=403, detail="Cannot delete a protected role")
    # Unassign agents from this role
    await db.execute(
        text("UPDATE agents SET custom_role_id=NULL WHERE custom_role_id=:id"),
        {"id": role_id}
    )
    await db.execute(text("DELETE FROM custom_roles WHERE id=:id"), {"id": role_id})
    await db.commit()
    return {"ok": True}


# ── Assign role to agent ──────────────────────────────────────────────────────

@router.patch("/agents/{agent_id}/role")
async def assign_agent_role(
    agent_id: str,
    body: dict,
    db: AsyncSession = Depends(get_db),
    current: Agent = Depends(get_current_agent),
):
    """Assign a custom role to an agent, storing role_id + permissions snapshot."""
    await ensure_schema(db)

    role_id = body.get("custom_role_id")
    if not role_id:
        raise HTTPException(status_code=422, detail="custom_role_id is required")

    # Look up the role to get its current permissions
    row = await db.execute(
        text("SELECT permissions FROM custom_roles WHERE id=:id"), {"id": role_id}
    )
    role_row = row.fetchone()
    if not role_row:
        raise HTTPException(status_code=404, detail="Role not found")

    permissions = role_row[0]  # already a list from JSONB

    await db.execute(text("""
        UPDATE agents
        SET custom_role_id=:role_id, custom_permissions=:perms::jsonb
        WHERE id=:agent_id
    """), {"role_id": role_id, "perms": json.dumps(permissions), "agent_id": agent_id})
    await db.commit()
    return {"ok": True, "custom_role_id": role_id, "permissions": permissions}
from uuid import UUID

from fastapi import HTTPException, Request

from .auth import Principal
from .supabase_store import SupabaseStore


async def workspace_for_request(request: Request, principal: Principal, store: SupabaseStore) -> UUID:
    """Resolve and authorize the workspace for a request.

    Reads the X-Workspace-ID header, confirms the authenticated principal is a
    member of that workspace, and returns the confirmed UUID.
    """
    if not store.enabled:
        raise HTTPException(status_code=503, detail="Database service is not configured")
    workspace_raw = request.headers.get("X-Workspace-ID")
    if not workspace_raw:
        raise HTTPException(status_code=400, detail="X-Workspace-ID header is required")
    try:
        workspace_id = UUID(workspace_raw)
    except ValueError:
        raise HTTPException(status_code=422, detail="Workspace ID is invalid") from None
    memberships = await store.select(
        "workspace_members",
        {"workspace_id": f"eq.{workspace_id}", "user_id": f"eq.{principal.user_id}", "select": "role"},
    )
    if not memberships:
        raise HTTPException(status_code=403, detail="You are not authorized for this workspace")
    return workspace_id


async def role_for_request(
    request: Request,
    principal: Principal,
    store: SupabaseStore,
    allowed_roles: set[str] | None = None,
) -> tuple[UUID, str]:
    """Like workspace_for_request but also returns the role and enforces role constraints."""
    workspace_id = await workspace_for_request(request, principal, store)
    memberships = await store.select(
        "workspace_members",
        {"workspace_id": f"eq.{workspace_id}", "user_id": f"eq.{principal.user_id}", "select": "role"},
    )
    role = memberships[0]["role"]
    if allowed_roles and role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Your workspace role cannot perform this action")
    return workspace_id, role

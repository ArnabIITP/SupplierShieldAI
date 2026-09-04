from dataclasses import dataclass
from functools import lru_cache
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException, Request

from .config import get_settings


@dataclass(frozen=True)
class Principal:
    user_id: UUID


@lru_cache(maxsize=1)
def _settings():
    return get_settings()


async def current_principal(request: Request) -> Principal:
    settings = _settings()
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication is required")
    token = authorization.removeprefix("Bearer ")
    secret = settings.supabase_service_role_key or settings.supabase_secret_key
    if not settings.supabase_url or not secret:
        raise HTTPException(status_code=503, detail="Authentication service is not configured")
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={"apikey": secret, "Authorization": f"Bearer {token}"},
        )
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token")
    try:
        return Principal(user_id=UUID(response.json()["id"]))
    except (KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid authentication identity") from None


AuthenticatedPrincipal = Depends(current_principal)

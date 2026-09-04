import logging
import httpx

from .config import get_settings


class SupabaseStore:
    """Server-side Data API adapter. The secret key is never sent to the browser."""
    def __init__(self) -> None:
        settings = get_settings()
        self.url = settings.supabase_url
        self.key = settings.supabase_service_role_key or settings.supabase_secret_key

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.key)

    def _headers(self) -> dict[str, str]:
        if not self.enabled:
            raise RuntimeError("Supabase persistence is not configured")
        return {"apikey": self.key or "", "Authorization": f"Bearer {self.key}", "Content-Type": "application/json", "Prefer": "return=representation"}

    async def select(self, table: str, query: dict[str, str]) -> list[dict]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self.url}/rest/v1/{table}", params=query, headers=self._headers())
        response.raise_for_status()
        return response.json()

    async def insert(self, table: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(f"{self.url}/rest/v1/{table}", json=payload, headers=self._headers())
        response.raise_for_status()
        return response.json()[0]

    async def update(self, table: str, query: dict[str, str], payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.patch(f"{self.url}/rest/v1/{table}", params=query, json=payload, headers=self._headers())
        response.raise_for_status()
        return response.json()[0]

    async def delete(self, table: str, query: dict[str, str]) -> None:
        if not self.enabled:
            return
        headers = {**self._headers(), "Prefer": "return=minimal"}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.delete(
                f"{self.url}/rest/v1/{table}",
                params=query,
                headers=headers,
            )
        if response.status_code >= 400:
            logging.error(f"Supabase delete failed on {table}: {response.text}")
            raise Exception(f"Delete failed on {table}: {response.text}")

    async def upload(self, bucket: str, path: str, content: bytes, mime_type: str) -> str:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{self.url}/storage/v1/object/{bucket}/{path}", content=content, headers={**self._headers(), "Content-Type": mime_type, "x-upsert": "false"})
        response.raise_for_status()
        return path

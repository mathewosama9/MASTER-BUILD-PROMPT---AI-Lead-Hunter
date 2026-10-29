"""Thin client for the shared FastAPI backend. The bot has no database of its own."""
from typing import Any

import httpx

from bot.config import get_settings


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class BackendClient:
    def __init__(self, base_url: str | None = None, service_token: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        s = get_settings()
        self.base_url = (base_url or s.api_base_url).rstrip("/")
        self.service_token = service_token or s.telegram_service_token
        self._client = httpx.AsyncClient(timeout=30.0, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self, tg_user_id: int | None) -> dict[str, str]:
        h = {"x-service-token": self.service_token}
        if tg_user_id is not None:
            h["x-telegram-user-id"] = str(tg_user_id)
        return h

    async def request(self, method: str, path: str, tg_user_id: int | None, **kw: Any) -> httpx.Response:
        resp = await self._client.request(method, f"{self.base_url}{path}", headers=self._headers(tg_user_id), **kw)
        if resp.status_code >= 400:
            try:
                msg = resp.json().get("error", {}).get("message") or resp.text
            except ValueError:
                msg = resp.text
            raise ApiError(resp.status_code, str(msg)[:300])
        return resp

    async def json(self, method: str, path: str, tg_user_id: int | None, **kw: Any) -> Any:
        return (await self.request(method, path, tg_user_id, **kw)).json()

    # Convenience wrappers --------------------------------------------------------------------------

    async def whoami(self, uid: int) -> dict:
        return await self.json("GET", "/telegram/whoami", uid)

    async def link(self, code: str, uid: int, chat_id: int, username: str | None, locale: str) -> dict:
        return await self.json("POST", "/telegram/link", None, json={
            "code": code, "telegram_user_id": uid, "chat_id": chat_id, "username": username, "locale": locale})

    async def set_locale(self, uid: int, locale: str) -> dict:
        return await self.json("POST", "/telegram/locale", uid, json={"locale": locale})

    async def meta(self) -> dict:
        return await self.json("GET", "/meta", None)

    async def providers(self, uid: int) -> list[dict]:
        return await self.json("GET", "/providers", uid)

    async def create_campaign(self, uid: int, body: dict) -> dict:
        return await self.json("POST", "/campaigns", uid, json=body)

    async def campaigns(self, uid: int, page_size: int = 8) -> dict:
        return await self.json("GET", "/campaigns", uid, params={"page_size": page_size})

    async def campaign(self, uid: int, cid: str) -> dict:
        return await self.json("GET", f"/campaigns/{cid}", uid)

    async def action(self, uid: int, cid: str, action: str) -> dict:
        return await self.json("POST", f"/campaigns/{cid}/{action}", uid)

    async def leads(self, uid: int, **params: Any) -> dict:
        return await self.json("GET", "/leads", uid, params={k: v for k, v in params.items() if v is not None})

    async def campaign_csv(self, uid: int, cid: str) -> bytes:
        return (await self.request("GET", f"/exports/campaigns/{cid}", uid, params={"format": "csv"})).content

    async def leads_csv(self, uid: int) -> bytes:
        return (await self.request("GET", "/exports/leads", uid, params={"format": "csv", "qualified_only": True})).content

    async def stats(self, uid: int) -> dict:
        return await self.json("GET", "/dashboard/stats", uid)

"""Thin client for the shared FastAPI backend. The bot has no database of its own."""
import time
from typing import Any

import httpx

from bot.config import get_settings

META_SECONDS = 600


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


class BackendClient:
    def __init__(self, base_url: str | None = None, service_token: str | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        s = get_settings()
        self.base_url = (base_url or s.api_base_url).rstrip("/")
        self.service_token = service_token or s.telegram_service_token
        if transport is None and s.api_socket:
            transport = httpx.AsyncHTTPTransport(uds=s.api_socket)
        self._client = httpx.AsyncClient(timeout=30.0, transport=transport)
        self._meta: tuple[float, dict] | None = None

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self, tg_user_id: int | None) -> dict[str, str]:
        h = {"x-service-token": self.service_token}
        if tg_user_id is not None:
            h["x-telegram-user-id"] = str(tg_user_id)
        return h

    async def request(self, method: str, path: str, tg_user_id: int | None, **kw: Any) -> httpx.Response:
        try:
            resp = await self._client.request(method, f"{self.base_url}{path}", headers=self._headers(tg_user_id),
                                              **kw)
        except httpx.HTTPError as exc:
            raise ApiError(503, "backend unavailable", "unavailable") from exc
        if resp.status_code >= 400:
            code = None
            try:
                err = resp.json().get("error", {})
                msg, code = err.get("message") or resp.text, err.get("code")
            except (ValueError, AttributeError):
                msg = resp.text
            raise ApiError(resp.status_code, str(msg)[:300], code)
        return resp

    async def json(self, method: str, path: str, tg_user_id: int | None, **kw: Any) -> Any:
        return (await self.request(method, path, tg_user_id, **kw)).json()

    # Account ---------------------------------------------------------------------------------------

    async def whoami(self, uid: int) -> dict:
        return await self.json("GET", "/telegram/whoami", uid)

    async def link_status(self, uid: int) -> str:
        return (await self.json("POST", "/telegram/status", None, params={"telegram_user_id": uid}))["status"]

    async def link(self, code: str, uid: int, chat_id: int, username: str | None, locale: str) -> dict:
        return await self.json("POST", "/telegram/link", None, json={
            "code": code, "telegram_user_id": uid, "chat_id": chat_id, "username": username, "locale": locale})

    async def set_locale(self, uid: int, locale: str) -> dict:
        return await self.json("POST", "/telegram/locale", uid, json={"locale": locale})

    async def meta(self) -> dict:
        """Reference data (countries, industries); cached because every wizard step needs it."""
        if self._meta and self._meta[0] > time.monotonic():
            return self._meta[1]
        data = await self.json("GET", "/meta", None)
        self._meta = (time.monotonic() + META_SECONDS, data)
        return data

    # Campaigns -------------------------------------------------------------------------------------

    async def providers(self, uid: int) -> list[dict]:
        return await self.json("GET", "/providers", uid)

    async def parse_spec(self, uid: int, text: str) -> dict:
        return await self.json("POST", "/campaigns/parse-spec", uid, json={"text": text})

    async def estimate(self, uid: int, body: dict) -> dict:
        return await self.json("POST", "/campaigns/estimate", uid, json=body)

    async def create_campaign(self, uid: int, body: dict) -> dict:
        return await self.json("POST", "/campaigns", uid, json=body)

    async def campaigns(self, uid: int, page: int = 1, page_size: int = 6) -> dict:
        return await self.json("GET", "/campaigns", uid, params={"page": page, "page_size": page_size})

    async def campaign(self, uid: int, cid: str) -> dict:
        return await self.json("GET", f"/campaigns/{cid}", uid)

    async def action(self, uid: int, cid: str, action: str) -> dict:
        return await self.json("POST", f"/campaigns/{cid}/{action}", uid)

    async def campaign_csv(self, uid: int, cid: str) -> bytes:
        return (await self.request("GET", f"/exports/campaigns/{cid}", uid, params={"format": "csv"})).content

    # Leads -----------------------------------------------------------------------------------------

    async def leads(self, uid: int, **params: Any) -> dict:
        return await self.json("GET", "/leads", uid, params={k: v for k, v in params.items() if v is not None})

    async def lead(self, uid: int, lead_id: str) -> dict:
        return await self.json("GET", f"/leads/{lead_id}", uid)

    async def update_lead(self, uid: int, lead_id: str, **changes: Any) -> dict:
        return await self.json("PATCH", f"/leads/{lead_id}", uid, json=changes)

    async def add_note(self, uid: int, lead_id: str, body: str) -> dict:
        return await self.json("POST", f"/leads/{lead_id}/notes", uid, json={"body": body})

    async def leads_csv(self, uid: int) -> bytes:
        return (await self.request("GET", "/exports/leads", uid, params={"format": "csv", "qualified_only": True})).content

    # Credits ---------------------------------------------------------------------------------------

    async def billing_summary(self, uid: int) -> dict:
        return await self.json("GET", "/billing/summary", uid)

    async def packages(self, uid: int) -> list[dict]:
        return await self.json("GET", "/billing/packages", uid)

    async def create_topup(self, uid: int, body: dict) -> dict:
        return await self.json("POST", "/billing/topups", uid, json=body)

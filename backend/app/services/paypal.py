"""PayPal Checkout (Orders v2 REST API, called with httpx; no SDK).

The platform admin connects the store's PayPal account once (Admin → Payments): the REST app's client id and secret
are checked, a webhook is registered automatically, and everything is stored encrypted as the platform-wide
"paypal" provider configuration. Clients then buy credit packages: an order is created here, the client approves it
on PayPal, and the capture (on return, or the webhook as a backup) grants the credits exactly once.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import TopUpRequest
from app.models.enums import CreditKind, TopUpStatus
from app.services import credits as credit_svc
from app.services import providers as provider_svc

log = logging.getLogger(__name__)
KEY = "paypal"
API = {"live": "https://api-m.paypal.com", "sandbox": "https://api-m.sandbox.paypal.com"}
WEBHOOK_EVENTS = ("PAYMENT.CAPTURE.COMPLETED", "CHECKOUT.ORDER.APPROVED")
TIMEOUT = httpx.Timeout(20.0)


class PayPalError(AppError):
    status_code = 502

    def __init__(self, message: str, code: str = "paypal_error") -> None:
        super().__init__(message, code=code)


class PayPalNotConnected(AppError):
    status_code = 503

    def __init__(self) -> None:
        super().__init__("Online payment is not available right now", code="payments_unavailable")


def webhook_url() -> str:
    return f"{get_settings().frontend_url.rstrip('/')}/api/v1/payments/paypal/webhook"


async def credentials(db: AsyncSession) -> dict[str, str]:
    creds, _ = await provider_svc.credentials_for(db, None, KEY)
    return creds if creds.get("client_id") and creds.get("client_secret") else {}


async def require_credentials(db: AsyncSession) -> dict[str, str]:
    creds = await credentials(db)
    if not creds:
        raise PayPalNotConnected
    return creds


def _base(creds: dict[str, str]) -> str:
    return API.get(creds.get("mode", "live"), API["live"])


async def _token(client: httpx.AsyncClient, creds: dict[str, str]) -> str:
    r = await client.post(
        f"{_base(creds)}/v1/oauth2/token",
        auth=(creds["client_id"], creds["client_secret"]),
        data={"grant_type": "client_credentials"},
    )
    if r.status_code in (401, 403):
        raise PayPalError("PayPal rejected the client ID or secret", code="paypal_bad_credentials")
    r.raise_for_status()
    return r.json()["access_token"]


async def _call(
    creds: dict[str, str], method: str, path: str, headers: dict[str, str] | None = None, **kw  # noqa: ANN003
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            token = await _token(client, creds)
            return await client.request(
                method, f"{_base(creds)}{path}", headers={**(headers or {}), "Authorization": f"Bearer {token}"}, **kw
            )
        except httpx.HTTPError as exc:
            log.warning("paypal request failed", extra={"path": path, "error": str(exc)})
            raise PayPalError("Could not reach PayPal; please try again") from exc


async def connect(client_id: str, client_secret: str, mode: str) -> dict[str, str]:
    """Check the credentials and register the webhook. Returns the credentials to store.

    A webhook needs a public https URL; on a local server it is skipped and payments are captured on return."""
    creds = {"client_id": client_id.strip(), "client_secret": client_secret.strip(), "mode": mode}
    url = webhook_url()
    if not url.startswith("https://"):
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            try:
                await _token(client, creds)
            except httpx.HTTPError as exc:
                raise PayPalError("Could not reach PayPal; please try again") from exc
        return creds
    r = await _call(creds, "GET", "/v1/notifications/webhooks")
    r.raise_for_status()
    existing = next((w for w in r.json().get("webhooks", []) if w.get("url") == url), None)
    if existing:
        creds["webhook_id"] = existing["id"]
        return creds
    r = await _call(
        creds,
        "POST",
        "/v1/notifications/webhooks",
        json={"url": url, "event_types": [{"name": e} for e in WEBHOOK_EVENTS]},
    )
    if r.status_code >= 400:
        log.warning("paypal webhook registration failed", extra={"body": r.text[:500]})
    else:
        creds["webhook_id"] = r.json()["id"]
    return creds


async def create_order(
    creds: dict[str, str], *, amount: Decimal, currency: str, reference: str, description: str, locale: str
) -> tuple[str, str]:
    """Returns (order id, approve URL)."""
    base = get_settings().frontend_url.rstrip("/")
    r = await _call(
        creds,
        "POST",
        "/v2/checkout/orders",
        json={
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference,
                    "custom_id": reference,
                    "description": description[:127],
                    "amount": {"currency_code": currency, "value": f"{amount:.2f}"},
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "brand_name": "Rasd",
                        "locale": "ar-EG" if locale == "ar" else "en-US",
                        "shipping_preference": "NO_SHIPPING",
                        "user_action": "PAY_NOW",
                        "return_url": f"{base}/app/billing?paypal=return",
                        "cancel_url": f"{base}/app/billing?paypal=cancel",
                    }
                }
            },
        },
        headers={"PayPal-Request-Id": reference},  # idempotent if retried
    )
    if r.status_code >= 400:
        log.warning("paypal create order failed", extra={"body": r.text[:500]})
        raise PayPalError("PayPal could not start the payment")
    data = r.json()
    approve = next((x["href"] for x in data.get("links", []) if x.get("rel") in ("payer-action", "approve")), None)
    if not approve:
        raise PayPalError("PayPal did not return a payment link")
    return data["id"], approve


async def capture_order(creds: dict[str, str], order_id: str) -> dict:
    """Capture an approved order. An order captured before (return + webhook racing) is read back instead."""
    r = await _call(creds, "POST", f"/v2/checkout/orders/{order_id}/capture", json={})
    if r.status_code == 422 and "ORDER_ALREADY_CAPTURED" in r.text:
        r = await _call(creds, "GET", f"/v2/checkout/orders/{order_id}")
    if r.status_code >= 400:
        log.warning("paypal capture failed", extra={"order_id": order_id, "body": r.text[:500]})
        raise PayPalError("The PayPal payment was not completed", code="paypal_not_completed")
    return r.json()


def completed_capture(order: dict) -> dict | None:
    """The completed capture of an order ({id, amount: {currency_code, value}}), if any."""
    for unit in order.get("purchase_units", []):
        for cap in (unit.get("payments") or {}).get("captures", []):
            if cap.get("status") == "COMPLETED":
                return cap
    return None


async def verify_webhook(creds: dict[str, str], headers: dict[str, str], event: dict) -> bool:
    if not creds.get("webhook_id"):
        return False
    r = await _call(
        creds,
        "POST",
        "/v1/notifications/verify-webhook-signature",
        json={
            "auth_algo": headers.get("paypal-auth-algo"),
            "cert_url": headers.get("paypal-cert-url"),
            "transmission_id": headers.get("paypal-transmission-id"),
            "transmission_sig": headers.get("paypal-transmission-sig"),
            "transmission_time": headers.get("paypal-transmission-time"),
            "webhook_id": creds["webhook_id"],
            "webhook_event": event,
        },
    )
    return r.status_code == 200 and r.json().get("verification_status") == "SUCCESS"


async def settle(db: AsyncSession, order_id: str, order: dict) -> tuple[TopUpRequest, bool]:
    """Grant the credits of a captured order exactly once (row lock: the return page and the webhook may race).

    Returns (top-up, whether credits were granted now). The caller commits."""
    topup = await db.scalar(
        select(TopUpRequest).where(TopUpRequest.provider_order_id == order_id).with_for_update()
    )
    if topup is None:
        raise PayPalError("Unknown PayPal order", code="paypal_unknown_order")
    if topup.status == TopUpStatus.APPROVED:
        return topup, False
    capture = completed_capture(order)
    if capture is None:
        raise PayPalError("The PayPal payment was not completed", code="paypal_not_completed")
    amount = capture.get("amount") or {}
    if amount.get("currency_code") != topup.currency or Decimal(amount.get("value", "0")) != topup.amount:
        log.error("paypal amount mismatch", extra={"order_id": order_id, "amount": amount})
        raise PayPalError("The paid amount does not match the package", code="paypal_amount_mismatch")
    tx = await credit_svc.grant(
        db,
        topup.workspace_id,
        topup.credits,
        CreditKind.PURCHASE,
        note=f"PayPal {topup.amount} {topup.currency} (order {order_id})",
        created_by=topup.created_by,
    )
    topup.status = TopUpStatus.APPROVED
    topup.reviewed_at = datetime.now(UTC)
    topup.provider_capture_id = capture.get("id")
    topup.transaction_id = tx.id
    return topup, True

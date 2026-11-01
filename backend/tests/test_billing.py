"""The client billing API: summary, ledger, packages and manual top-up requests with receipts."""

import base64
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import CreditPackage, Workspace
from app.models.enums import CreditKind, Role
from app.services import credits as credit_svc
from tests.conftest import login, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.7\n%test\n"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


@pytest.fixture
async def metered(app, db):
    user, ws = await make_user(db, billing_exempt=False)
    client = await login(app, user.email)
    yield client, ws
    await client.aclose()


@pytest.fixture
async def package(db):
    pkg = CreditPackage(name_ar="باقة 500", name_en="500 pack", credits=500, price=Decimal("750.00"), currency="EGP")
    hidden = CreditPackage(name_ar="قديمة", name_en="Old", credits=50, price=Decimal("1"), active=False)
    db.add_all([pkg, hidden])
    await db.commit()
    yield pkg
    await db.delete(pkg)
    await db.delete(hidden)
    await db.commit()


def topup(pkg, **over) -> dict:
    return {
        "package_id": str(pkg.id),
        "method": "instapay",
        "reference": "IPN-778899",
        "receipt_filename": "receipt.png",
        "receipt_base64": b64(PNG),
        **over,
    }


async def test_summary_for_trial_and_exempt_workspaces(metered, client, db):
    mc, ws = metered
    w = await db.get(Workspace, ws.id)
    w.trial_ends_at = datetime.now(UTC) + timedelta(days=12, hours=3)
    await db.commit()
    await credit_svc.grant(db, ws.id, 8, CreditKind.TRIAL_GRANT)
    await db.commit()
    s = (await mc.get("/api/v1/billing/summary")).json()
    assert s["balance"] == 8 and s["on_trial"] and s["trial_days_left"] == 13 and not s["trial_expired"]
    assert s["low_balance"] and not s["billing_exempt"] and s["credits_per_contact"] == 1

    exempt = (await client.get("/api/v1/billing/summary")).json()
    assert exempt["billing_exempt"] and not exempt["low_balance"] and not exempt["on_trial"]


async def test_ledger_is_newest_first_and_paged(metered, db):
    mc, ws = metered
    for n in (5, 3, 2):
        await credit_svc.grant(db, ws.id, n, CreditKind.PURCHASE)
        await db.commit()
    page = (await mc.get("/api/v1/billing/transactions", params={"page_size": 2})).json()
    assert page["total"] == 3 and [x["balance_after"] for x in page["items"]] == [10, 8]
    page2 = (await mc.get("/api/v1/billing/transactions", params={"page": 2, "page_size": 2})).json()
    assert [x["delta"] for x in page2["items"]] == [5]


async def test_only_active_packages_are_offered(metered, package):
    mc, _ = metered
    names = [x["name_en"] for x in (await mc.get("/api/v1/billing/packages")).json()]
    assert "500 pack" in names and "Old" not in names


async def test_topup_request_with_receipt(app, metered, package, db):
    mc, ws = metered
    r = await mc.post("/api/v1/billing/topups", json=topup(package))
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "pending" and t["credits"] == 500 and t["amount"] == "750.00" and t["method"] == "instapay"
    assert "receipt_base64" not in t and "receipt_data" not in t
    assert [x["id"] for x in (await mc.get("/api/v1/billing/topups")).json()] == [t["id"]]
    assert (await mc.get("/api/v1/billing/summary")).json()["pending_topups"] == 1
    assert (await mc.get("/api/v1/billing/summary")).json()["balance"] == 0  # nothing granted until approved

    rec = await mc.get(f"/api/v1/billing/topups/{t['id']}/receipt")
    assert rec.status_code == 200 and rec.content == PNG and rec.headers["content-type"] == "image/png"
    assert "sandbox" in rec.headers["content-security-policy"] and rec.headers["x-content-type-options"] == "nosniff"

    # Another tenant cannot see it.
    other_user, _ = await make_user(db, billing_exempt=False)
    other = await login(app, other_user.email)
    assert (await other.get(f"/api/v1/billing/topups/{t['id']}/receipt")).status_code == 404
    assert (await other.get("/api/v1/billing/topups")).json() == []
    await other.aclose()


async def test_pdf_receipts_download_instead_of_rendering(metered, package):
    mc, _ = metered
    t = (await mc.post("/api/v1/billing/topups", json=topup(package, receipt_base64=b64(PDF)))).json()
    rec = await mc.get(f"/api/v1/billing/topups/{t['id']}/receipt")
    assert rec.headers["content-type"] == "application/pdf"
    assert rec.headers["content-disposition"].startswith("attachment")


@pytest.mark.parametrize(
    ("receipt", "code"),
    [
        (b64(b"<html><script>alert(1)</script></html>"), "unsupported_receipt"),
        (b64(b"\x89PNG\r\n\x1a\n" + b"\x00" * (5 * 1024 * 1024)), "receipt_too_large"),
        ("not base64!!", "bad_request"),
    ],
)
async def test_bad_receipts_are_rejected(metered, package, receipt, code):
    mc, _ = metered
    r = await mc.post("/api/v1/billing/topups", json=topup(package, receipt_base64=receipt))
    assert r.status_code == 400
    if code != "bad_request":
        assert r.json()["error"]["code"] == code


async def test_topup_rules(app, metered, package, db):
    mc, ws = metered
    hidden_id = await db.scalar(select(CreditPackage.id).where(CreditPackage.active.is_(False)))
    assert (await mc.post("/api/v1/billing/topups", json=topup(package, package_id=str(hidden_id)))).status_code == 404
    assert (await mc.post("/api/v1/billing/topups", json=topup(package, method="cash"))).status_code == 422

    analyst, _ = await make_user(db, role=Role.ANALYST, workspace=ws)
    ac = await login(app, analyst.email)
    assert (await ac.post("/api/v1/billing/topups", json=topup(package))).status_code == 403
    assert (await ac.get("/api/v1/billing/summary")).status_code == 200  # everyone can see the balance
    await ac.aclose()

    for _ in range(3):
        assert (await mc.post("/api/v1/billing/topups", json=topup(package))).status_code == 201
    r = await mc.post("/api/v1/billing/topups", json=topup(package))
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_many_pending"

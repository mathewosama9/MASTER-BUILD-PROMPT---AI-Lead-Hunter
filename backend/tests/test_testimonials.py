"""Testimonials: the public list, users' own reviews (consent + approval) and admin management."""

import httpx
import pytest
from sqlalchemy import delete, select

from app.models import marketing
from tests.conftest import login, make_user


@pytest.fixture(autouse=True)
async def clean(db):
    await db.execute(delete(marketing.Testimonial))
    await db.commit()
    yield
    await db.execute(delete(marketing.Testimonial))
    await db.commit()


@pytest.fixture
async def admin(app, db):
    user, ws = await make_user(db)
    user.is_superuser = True
    await db.commit()
    c = await login(app, user.email)
    yield c
    await c.aclose()


@pytest.fixture
async def member(app, db):
    user, ws = await make_user(db)
    user.locale = "ar"
    await db.commit()
    c = await login(app, user.email)
    yield c, user
    await c.aclose()


def row(**kw):
    base = dict(author_name="Sara", rating=5, body_ar="ممتاز", body_en="Great", source="manual", status="approved")
    return marketing.Testimonial(**{**base, **kw})


async def test_public_list_shows_only_approved_featured_first(app, db):
    db.add_all(
        [
            row(author_name="Approved", sort=1),
            row(author_name="Featured", is_featured=True, sort=5),
            row(author_name="Pending", status="pending"),
            row(author_name="Hidden", status="hidden"),
        ]
    )
    await db.commit()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/public/testimonials")
    assert r.status_code == 200
    names = [x["author_name"] for x in r.json()]
    assert names == ["Featured", "Approved"]
    assert "source" not in r.json()[0] and "status" not in r.json()[0]


async def test_user_review_is_pending_and_replaced_on_resubmit(member, db):
    c, user = member
    assert (await c.get("/api/v1/reviews/mine")).json() is None
    r = await c.post("/api/v1/reviews", json={"rating": 4, "body": "خدمة رائعة ساعدتني كثيراً", "consent_publish": True})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending"
    r = await c.post("/api/v1/reviews", json={"rating": 5, "body": "أفضل من أي أداة جربتها", "consent_publish": True})
    assert r.status_code == 201
    rows = (await db.scalars(select(marketing.Testimonial))).all()
    assert len(rows) == 1
    mine = (await c.get("/api/v1/reviews/mine")).json()
    assert mine["rating"] == 5 and mine["status"] == "pending"


async def test_admin_cannot_publish_without_consent(admin, member, db):
    c, user = member
    await c.post("/api/v1/reviews", json={"rating": 5, "body": "مفيد جداً لفريق المبيعات", "consent_publish": False})
    items = (await admin.get("/api/v1/admin/testimonials")).json()
    rid = items[0]["id"]
    assert items[0]["source"] == "in_app" and items[0]["body_ar"]
    r = await admin.patch(f"/api/v1/admin/testimonials/{rid}", json={"status": "approved"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "no_consent"


async def test_admin_crud_and_access_control(admin, member):
    c, _ = member
    assert (await c.get("/api/v1/admin/testimonials")).status_code == 403
    r = await admin.post(
        "/api/v1/admin/testimonials",
        json={"author_name": "Omar", "rating": 5, "body_en": "Found clients we never knew existed.", "city": "Doha"},
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert r.json()["source"] == "manual" and r.json()["status"] == "approved"
    r = await admin.patch(f"/api/v1/admin/testimonials/{tid}", json={"status": "hidden", "is_featured": True})
    assert r.json()["status"] == "hidden" and r.json()["is_featured"] is True
    assert (await admin.post("/api/v1/admin/testimonials", json={"author_name": "X Y"})).status_code == 422
    assert (await admin.delete(f"/api/v1/admin/testimonials/{tid}")).status_code == 200
    assert (await admin.get("/api/v1/admin/testimonials")).json() == []


async def test_admin_overview_and_usage(admin, member, db):
    c, _ = member
    db.add(row(author_name="Placeholder", source="sample"))
    await db.commit()
    assert (await c.get("/api/v1/admin/overview")).status_code == 403
    assert (await c.get("/api/v1/admin/usage")).status_code == 403
    o = (await admin.get("/api/v1/admin/overview")).json()
    assert o["attention"]["sample_reviews"] == 1
    assert len(o["daily"]) == 30 and o["users"]["total"] >= 2
    assert set(o["funnel"]) == {"signed_up", "verified", "first_search", "paid"}
    r = await admin.get("/api/v1/admin/usage")
    assert r.status_code == 200 and isinstance(r.json(), list)

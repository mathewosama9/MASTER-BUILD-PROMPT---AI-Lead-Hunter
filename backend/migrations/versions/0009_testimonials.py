"""testimonials for the public site, seeded with sample reviews flagged `source = 'sample'`

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-01 12:00:00.000000
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Placeholder reviews requested by the owner until real ones exist. They carry no invented figures, and the admin
# dashboard warns while any of them is still published.
SAMPLES = [
    (
        "سارة م.",
        "مؤسِّسة وكالة تسويق رقمي",
        "الرياض",
        "SA",
        5,
        True,
        "كنت أقضي أياماً أبحث عن مطاعم وعيادات أتواصل معها. الآن أكتب نوع العميل والمدينة، وتصلني قائمة فيها "
        "الأرقام وسبب التواصل مع كل واحد.",
        "I used to spend days looking for restaurants and clinics to contact. Now I type the kind of client and the "
        "city, and I get a list with their numbers and a reason to reach out to each one.",
    ),
    (
        "أحمد ع.",
        "مدير مبيعات، شركة برمجيات",
        "القاهرة",
        "EG",
        5,
        True,
        "أكثر ما أعجبني أن كل عميل يأتي معه سبب واضح لحاجته لنا. صارت رسالتنا الأولى شخصية بدل رسالة عامة للجميع.",
        "What I like most is that every lead comes with a clear reason it needs us. Our first message is now personal "
        "instead of the same text for everyone.",
    ),
    (
        "نورة س.",
        "صاحبة مكتب محاسبة",
        "جدة",
        "SA",
        5,
        False,
        "الدفع مقابل العميل الذي له رقم فقط جعل التجربة مريحة. لا أدفع على أسماء بلا فائدة.",
        "Paying only for clients that come with a number makes it easy. I don't pay for names I can't use.",
    ),
    (
        "خالد ر.",
        "مورّد مستلزمات طبية",
        "دبي",
        "AE",
        4,
        False,
        "ساعدنا في الوصول إلى عيادات جديدة داخل مناطق التوصيل لدينا، والترتيب حسب الأولوية وفّر على فريق المبيعات "
        "وقتاً كبيراً.",
        "It helped us reach new clinics inside our delivery areas, and the priority order saves our sales team a lot "
        "of time.",
    ),
    (
        "يوسف ح.",
        "مصمم هوية بصرية مستقل",
        "عمّان",
        "JO",
        5,
        False,
        "كمستقل لم يكن لدي وقت للبحث عن عملاء. رصد يعطيني أنشطة تحتاج هوية بصرية فعلاً، ومعها رسالة أبدأ بها.",
        "As a freelancer I had no time to look for clients. Rasd gives me businesses that really need a brand "
        "identity, with a message to start with.",
    ),
    (
        "مريم ك.",
        "مديرة شركة صيانة",
        "الكويت",
        "KW",
        4,
        False,
        "الواجهة بالعربي وسهلة، والتنبيهات على تليجرام تجعلني أتابع وأنا خارج المكتب.",
        "The interface is in Arabic and easy to use, and the Telegram alerts let me follow up when I'm out of the "
        "office.",
    ),
]


def upgrade() -> None:
    table = op.create_table(
        "testimonials",
        sa.Column("author_name", sa.String(length=120), nullable=False),
        sa.Column("author_role", sa.String(length=120), nullable=True),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("body_ar", sa.Text(), server_default="", nullable=False),
        sa.Column("body_en", sa.Text(), server_default="", nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("is_featured", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consent_publish", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name=op.f("ck_testimonials_rating_range")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_testimonials_workspace_id_workspaces"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_testimonials_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_testimonials")),
    )
    op.create_index(op.f("ix_testimonials_status"), "testimonials", ["status"])
    op.create_index(op.f("ix_testimonials_user_id"), "testimonials", ["user_id"])
    op.create_index("ix_testimonials_public", "testimonials", ["status", "is_featured", "sort"])
    op.bulk_insert(
        table,
        [
            {
                "id": uuid.uuid4(),
                "author_name": name,
                "author_role": role,
                "city": city,
                "country": country,
                "rating": rating,
                "is_featured": featured,
                "body_ar": body_ar,
                "body_en": body_en,
                "source": "sample",
                "status": "approved",
                "sort": i,
                "consent_publish": False,
            }
            for i, (name, role, city, country, rating, featured, body_ar, body_en) in enumerate(SAMPLES)
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_testimonials_public", table_name="testimonials")
    op.drop_index(op.f("ix_testimonials_user_id"), table_name="testimonials")
    op.drop_index(op.f("ix_testimonials_status"), table_name="testimonials")
    op.drop_table("testimonials")

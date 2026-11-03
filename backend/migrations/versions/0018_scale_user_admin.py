"""scale the user admin: stored duplicate counts, indexes for sign-in, listing, searching and sign-in history

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-03 02:00:00.000000

Safe on a large live database:
- the two columns have constant defaults, so adding them is a catalog-only change (no table rewrite);
- every index is built CONCURRENTLY outside the migration transaction, so sign-ins and writes keep working;
- the counts are filled afterwards in batches by `python -m app.cli refresh-dup-counts`, not inside the migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = ("ix_audit_logs_user_created", "ix_users_created_at", "ix_users_dup_matches", "ix_users_email_lower")
TRGM = (("users", "email"), ("users", "full_name"), ("users", "phone"), ("workspaces", "name"))


def upgrade() -> None:
    op.add_column("users", sa.Column("dup_matches", sa.Integer(), server_default="0", nullable=False))
    op.add_column("users", sa.Column("dup_strong", sa.Integer(), server_default="0", nullable=False))
    with op.get_context().autocommit_block():
        # Sign-in, signup and password reset look users up by lower(email); the plain unique index can't serve that.
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_users_email_lower ON users (lower(email))")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_users_dup_matches ON users (dup_matches) WHERE dup_matches > 0"
        )
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_users_created_at ON users (created_at)")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_logs_user_created ON audit_logs (user_id, created_at)"
        )
        # Substring search (ILIKE '%x%'): trigram indexes, where the database lets us use the extension.
        op.execute(
            """
            DO $$ BEGIN
                CREATE EXTENSION IF NOT EXISTS pg_trgm;
            EXCEPTION WHEN insufficient_privilege OR undefined_file THEN
                RAISE NOTICE 'pg_trgm unavailable; admin search runs without trigram indexes';
            END $$;
            """
        )
        has_trgm = op.get_bind().scalar(sa.text("SELECT count(*) FROM pg_extension WHERE extname = 'pg_trgm'"))
        if has_trgm:
            for table, col in TRGM:
                op.execute(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_{table}_{col}_trgm "
                    f"ON {table} USING gin ({col} gin_trgm_ops)"
                )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for table, col in TRGM:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS ix_{table}_{col}_trgm")
        for name in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    op.drop_column("users", "dup_strong")
    op.drop_column("users", "dup_matches")

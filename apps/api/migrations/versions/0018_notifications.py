"""notifications.

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("resource", sa.String(length=300), nullable=False),
        sa.Column("href", sa.String(length=500), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=300), nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_notifications_organization_id", "notifications", ["organization_id"], unique=False)
    op.create_index("ix_notifications_owner_id", "notifications", ["owner_id"], unique=False)
    op.create_index("ix_notifications_owner_read_created", "notifications", ["owner_id", "read_at", "created_at"], unique=False)
    op.create_index("ix_notifications_org_created", "notifications", ["organization_id", "created_at"], unique=False)


def downgrade():
    op.drop_index("ix_notifications_org_created", table_name="notifications")
    op.drop_index("ix_notifications_owner_read_created", table_name="notifications")
    op.drop_index("ix_notifications_owner_id", table_name="notifications")
    op.drop_index("ix_notifications_organization_id", table_name="notifications")
    op.drop_table("notifications")

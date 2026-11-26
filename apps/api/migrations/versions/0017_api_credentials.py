"""api_credentials.

Revision ID: 0017
Revises: 0016
"""
from alembic import op
import sqlalchemy as sa


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("scopes_json", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("secret_hash"),
    )
    op.create_index("ix_api_credentials_organization_id", "api_credentials", ["organization_id"], unique=False)
    op.create_index("ix_api_credentials_owner_id", "api_credentials", ["owner_id"], unique=False)
    op.create_index("ix_api_credentials_org_created", "api_credentials", ["organization_id", "created_at"], unique=False)


def downgrade():
    op.drop_index("ix_api_credentials_org_created", table_name="api_credentials")
    op.drop_index("ix_api_credentials_owner_id", table_name="api_credentials")
    op.drop_index("ix_api_credentials_organization_id", table_name="api_credentials")
    op.drop_table("api_credentials")

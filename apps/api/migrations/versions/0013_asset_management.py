"""asset_management.

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "asset_assignments",
        sa.Column("asset_id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("assignee_id", sa.String(), nullable=True),
        sa.Column("team", sa.String(length=120), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("asset_id"),
    )
    op.create_index("ix_asset_assignments_organization_id", "asset_assignments", ["organization_id"], unique=False)
    op.create_table(
        "asset_history",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("asset_id", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("before_json", sa.Text(), nullable=False),
        sa.Column("after_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_history_asset_created", "asset_history", ["asset_id", "created_at"], unique=False)
    op.create_index("ix_asset_history_organization_id", "asset_history", ["organization_id"], unique=False)
    op.create_index("ix_asset_history_asset_id", "asset_history", ["asset_id"], unique=False)
    op.create_table(
        "asset_vulnerabilities",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("asset_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("cve", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("remediation", sa.Text(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_asset_vulnerabilities_asset_status", "asset_vulnerabilities", ["asset_id", "status"], unique=False)
    op.create_index("ix_asset_vulnerabilities_organization_id", "asset_vulnerabilities", ["organization_id"], unique=False)
    op.create_index("ix_asset_vulnerabilities_asset_id", "asset_vulnerabilities", ["asset_id"], unique=False)


def downgrade():
    op.drop_index("ix_asset_vulnerabilities_asset_id", table_name="asset_vulnerabilities")
    op.drop_index("ix_asset_vulnerabilities_organization_id", table_name="asset_vulnerabilities")
    op.drop_index("ix_asset_vulnerabilities_asset_status", table_name="asset_vulnerabilities")
    op.drop_table("asset_vulnerabilities")
    op.drop_index("ix_asset_history_asset_id", table_name="asset_history")
    op.drop_index("ix_asset_history_organization_id", table_name="asset_history")
    op.drop_index("ix_asset_history_asset_created", table_name="asset_history")
    op.drop_table("asset_history")
    op.drop_index("ix_asset_assignments_organization_id", table_name="asset_assignments")
    op.drop_table("asset_assignments")

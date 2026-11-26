"""report_center.

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "report_records",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("source_module", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=True),
        sa.Column("source_refs_json", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("review_status", sa.String(length=20), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("integrity_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_records_organization_id", "report_records", ["organization_id"], unique=False)
    op.create_index("ix_report_records_owner_id", "report_records", ["owner_id"], unique=False)
    op.create_index("ix_report_records_org_created", "report_records", ["organization_id", "created_at"], unique=False)
    op.create_index("ix_report_records_org_category", "report_records", ["organization_id", "category"], unique=False)


def downgrade():
    op.drop_index("ix_report_records_org_category", table_name="report_records")
    op.drop_index("ix_report_records_org_created", table_name="report_records")
    op.drop_index("ix_report_records_owner_id", table_name="report_records")
    op.drop_index("ix_report_records_organization_id", table_name="report_records")
    op.drop_table("report_records")

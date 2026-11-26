"""threat_indicators.

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "threat_indicators",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("organization_id", sa.String(), nullable=False),
        sa.Column("indicator_type", sa.String(length=20), nullable=False),
        sa.Column("value", sa.String(length=300), nullable=False),
        sa.Column("classification", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("provenance", sa.String(length=300), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "indicator_type", "value", name="uq_threat_indicator"),
    )
    op.create_index("ix_threat_indicators_organization_id", "threat_indicators", ["organization_id"], unique=False)
    op.create_index("ix_threat_indicators_org_status", "threat_indicators", ["organization_id", "status"], unique=False)


def downgrade():
    op.drop_index("ix_threat_indicators_org_status", table_name="threat_indicators")
    op.drop_index("ix_threat_indicators_organization_id", table_name="threat_indicators")
    op.drop_table("threat_indicators")

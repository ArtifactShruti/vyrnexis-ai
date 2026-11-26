"""organization_configuration.

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organizations", sa.Column("timezone", sa.String(length=80), nullable=False, server_default="UTC"))
    op.add_column("organizations", sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"))
    op.add_column("organizations", sa.Column("industry", sa.String(length=100), nullable=False, server_default=""))
    op.add_column("organizations", sa.Column("branding_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("organizations", sa.Column("settings_json", sa.Text(), nullable=False, server_default="{}"))
    op.add_column("organizations", sa.Column("onboarding_json", sa.Text(), nullable=False, server_default="{}"))


def downgrade():
    op.drop_column("organizations", "onboarding_json")
    op.drop_column("organizations", "settings_json")
    op.drop_column("organizations", "branding_json")
    op.drop_column("organizations", "industry")
    op.drop_column("organizations", "currency")
    op.drop_column("organizations", "timezone")

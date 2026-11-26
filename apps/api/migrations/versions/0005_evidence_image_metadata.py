"""Store derived image metadata without rewriting evidence or custody rows."""
from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evidence_image_metadata",
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence.id"), primary_key=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("fields_json", sa.Text(), nullable=False),
        sa.Column("inspected_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("evidence_image_metadata")

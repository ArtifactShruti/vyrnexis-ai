"""incident_assignment.

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.add_column(sa.Column("assignee_id", sa.String(),
                                      sa.ForeignKey("users.id", name="fk_incidents_assignee_id_users"), nullable=True))
        batch_op.add_column(sa.Column("team", sa.String(length=120), nullable=False, server_default=""))
        batch_op.create_index("ix_incidents_assignee_id", ["assignee_id"], unique=False)


def downgrade():
    with op.batch_alter_table("incidents") as batch_op:
        batch_op.drop_index("ix_incidents_assignee_id")
        batch_op.drop_column("team")
        batch_op.drop_column("assignee_id")

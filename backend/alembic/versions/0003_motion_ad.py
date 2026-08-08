"""motion_ad: persist the AIVDO job id

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column("aivdo_job_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("content_items", "aivdo_job_id")

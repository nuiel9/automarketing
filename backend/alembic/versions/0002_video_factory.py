"""video factory: scenario + render_error

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_items", sa.Column("scenario", sa.String(length=80), nullable=True))
    op.add_column("content_items", sa.Column("render_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("content_items", "render_error")
    op.drop_column("content_items", "scenario")

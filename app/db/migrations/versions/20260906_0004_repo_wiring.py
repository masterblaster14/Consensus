"""per-project webhook secret and hook id

Revision ID: 0004_repo_wiring
Revises: 0003_frontend_queue
Create Date: 2026-09-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_repo_wiring"
down_revision = "0003_frontend_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("webhook_secret", sa.Text()))
    op.add_column("projects", sa.Column("webhook_id", sa.Integer()))


def downgrade() -> None:
    op.drop_column("projects", "webhook_id")
    op.drop_column("projects", "webhook_secret")

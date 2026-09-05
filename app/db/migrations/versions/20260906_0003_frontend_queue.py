"""events table, project archive, membership status, task status and assignee

Revision ID: 0003_frontend_queue
Revises: 0002_auth_orgs
Create Date: 2026-09-06
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_frontend_queue"
down_revision = "0002_auth_orgs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_events_project_created", "events", ["project_id", "created_at"])

    op.add_column("projects", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("memberships", sa.Column("status", sa.Text(), nullable=False, server_default="active"))
    op.add_column("tasks", sa.Column("status", sa.Text(), nullable=False, server_default="open"))
    op.add_column("tasks", sa.Column("assignee_agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id")))
    op.add_column("tasks", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))


def downgrade() -> None:
    op.drop_column("tasks", "created_at")
    op.drop_column("tasks", "assignee_agent_id")
    op.drop_column("tasks", "status")
    op.drop_column("memberships", "status")
    op.drop_column("projects", "archived_at")
    op.drop_index("ix_events_project_created", table_name="events")
    op.drop_table("events")

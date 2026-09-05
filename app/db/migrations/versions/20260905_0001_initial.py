"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

DIM = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("repo_full_name", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("developer_name", sa.Text(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_agents_project_name", "agents", ["project_id", "name"], unique=True)

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("external_ref", sa.Text()),
        sa.Column("notion_page_id", sa.Text()),
        sa.Column("title", sa.Text(), nullable=False),
    )

    op.create_table(
        "claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("intent_text", sa.Text(), nullable=False),
        sa.Column("stance", postgresql.JSONB(), nullable=False),
        sa.Column("concepts", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("embedding", Vector(DIM)),
        sa.Column("branch", sa.Text()),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_claims_project_status", "claims", ["project_id", "status"])
    op.execute(
        "CREATE INDEX ix_claims_embedding ON claims USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "memory_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("concepts", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("axis", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(DIM)),
        sa.Column("source_agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("related_claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_memory_project_type", "memory_entries", ["project_id", "type"])
    op.execute(
        "CREATE INDEX ix_memory_embedding ON memory_entries USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "clashes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("claim_a_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("claim_b_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id"), nullable=False),
        sa.Column("axis", sa.Text(), nullable=False),
        sa.Column("shared_concepts", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_clashes_project_status", "clashes", ["project_id", "status"])

    op.create_table(
        "token_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_token_events_project_kind", "token_events", ["project_id", "kind"])

    op.create_table(
        "verdict_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("claims.id"), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("verdict_logs")
    op.drop_table("token_events")
    op.drop_table("clashes")
    op.drop_table("memory_entries")
    op.drop_table("claims")
    op.drop_table("tasks")
    op.drop_table("agents")
    op.drop_table("projects")

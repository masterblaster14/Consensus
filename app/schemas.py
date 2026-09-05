"""Shared response/request contracts.

The same models back the MCP tool outputs, the REST API and the WebSocket
event payloads, so a frontend sees one shape per entity everywhere.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["proceed", "proceed_with_context", "wait"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# -- entities ---------------------------------------------------------------


class ProjectOut(ORM):
    id: uuid.UUID
    org_id: uuid.UUID | None = None
    name: str
    repo_full_name: str | None = None
    created_at: datetime | None = None


class ProjectCreate(BaseModel):
    name: str
    repo_full_name: str | None = None
    org_id: uuid.UUID | None = None  # required unless the caller belongs to exactly one org
    id: uuid.UUID | None = None


class AgentOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    developer_name: str
    user_id: uuid.UUID | None = None
    last_seen: datetime | None = None


class TaskOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    external_ref: str | None = None
    notion_page_id: str | None = None
    title: str


class StanceOut(BaseModel):
    concepts: list[str] = Field(default_factory=list)
    error_handling: str | None = None
    auth_check: str | None = None
    data_access: str | None = None
    api_shape: str | None = None
    summary: str = ""


class ClaimOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str | None = None
    developer_name: str | None = None
    task_id: uuid.UUID | None = None
    task_ref: str | None = None
    intent_text: str
    stance: StanceOut
    concepts: list[str]
    branch: str | None = None
    pr_number: int | None = None
    status: str
    created_at: datetime | None = None
    resolved_at: datetime | None = None

    @classmethod
    def from_claim(cls, c) -> "ClaimOut":
        return cls(
            id=c.id,
            project_id=c.project_id,
            agent_id=c.agent_id,
            agent_name=c.agent.name if c.agent else None,
            developer_name=c.agent.developer_name if c.agent else None,
            task_id=c.task_id,
            task_ref=c.task.external_ref if c.task else None,
            intent_text=c.intent_text,
            stance=StanceOut(**(c.stance or {})),
            concepts=list(c.concepts or []),
            branch=c.branch,
            pr_number=c.pr_number,
            status=c.status,
            created_at=c.created_at,
            resolved_at=c.resolved_at,
        )


class MemoryEntryOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    type: str
    content: str
    concepts: list[str]
    axis: str | None = None
    source_agent_id: uuid.UUID | None = None
    source_agent: str | None = None
    related_claim_id: uuid.UUID | None = None
    created_at: datetime | None = None

    @classmethod
    def from_entry(cls, e) -> "MemoryEntryOut":
        return cls(
            id=e.id,
            project_id=e.project_id,
            type=e.type,
            content=e.content,
            concepts=list(e.concepts or []),
            axis=e.axis,
            source_agent_id=e.source_agent_id,
            source_agent=e.source_agent.name if e.source_agent else None,
            related_claim_id=e.related_claim_id,
            created_at=e.created_at,
        )


class ClashOut(ORM):
    id: uuid.UUID
    project_id: uuid.UUID
    claim_a_id: uuid.UUID
    claim_b_id: uuid.UUID
    agent_a: str | None = None
    agent_b: str | None = None
    intent_a: str | None = None
    intent_b: str | None = None
    position_a: str | None = None
    position_b: str | None = None
    axis: str
    shared_concepts: list[str]
    severity: str
    status: str
    resolution: str | None = None
    resolution_note: str | None = None
    resolved_by: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_clash(cls, x) -> "ClashOut":
        a, b = x.claim_a, x.claim_b
        return cls(
            id=x.id,
            project_id=x.project_id,
            claim_a_id=x.claim_a_id,
            claim_b_id=x.claim_b_id,
            agent_a=a.agent.name if a and a.agent else None,
            agent_b=b.agent.name if b and b.agent else None,
            intent_a=a.intent_text if a else None,
            intent_b=b.intent_text if b else None,
            position_a=(a.stance or {}).get(x.axis) if a else None,
            position_b=(b.stance or {}).get(x.axis) if b else None,
            axis=x.axis,
            shared_concepts=list(x.shared_concepts or []),
            severity=x.severity,
            status=x.status,
            resolution=x.resolution,
            resolution_note=x.resolution_note,
            resolved_by=x.resolved_by,
            created_at=x.created_at,
        )


class CountersOut(BaseModel):
    tokens_saved: int
    clashes_caught: int
    memory_count: int
    open_claims: int = 0
    open_clashes: int = 0
    agents: int = 0


# -- declare_intent -----------------------------------------------------------


class ContextItem(BaseModel):
    type: str
    content: str
    source: str | None = None
    entry_id: uuid.UUID | None = None
    similarity: float | None = None


class ClashSummary(BaseModel):
    with_agent: str
    their_intent: str
    axis: str
    your_position: str | None = None
    their_position: str | None = None
    shared_concepts: list[str] = Field(default_factory=list)
    severity: str = "hard"


class DeclareResult(BaseModel):
    claim_id: uuid.UUID
    verdict: Verdict
    context: list[ContextItem] = Field(default_factory=list)
    clash: ClashSummary | None = None
    clash_id: uuid.UUID | None = None
    ruling: ContextItem | None = None
    severity: str = "clear"
    project_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    duration_ms: int = 0


class CheckVerdictResult(BaseModel):
    clash_id: uuid.UUID
    status: str
    verdict: Verdict
    resolution: str | None = None
    resolution_note: str | None = None
    resolved_by: str | None = None
    ruling: ContextItem | None = None


class QueryMemoryEntry(BaseModel):
    type: str
    content: str
    source_agent: str | None = None
    created_at: datetime | None = None
    entry_id: uuid.UUID | None = None
    similarity: float | None = None


class QueryMemoryResult(BaseModel):
    entries: list[QueryMemoryEntry]
    tokens_used: int


class WriteMemoryResult(BaseModel):
    entry_id: uuid.UUID
    deduplicated: bool


class FileHandoffResult(BaseModel):
    entry_id: uuid.UUID
    pr_url: str | None = None
    pr_number: int | None = None


# -- REST requests ------------------------------------------------------------


class ResolveClashRequest(BaseModel):
    resolution: Literal["a_proceeds", "b_proceeds", "both_with_note"]
    note: str = ""
    resolved_by: str = "human"


class TokenEventCreate(BaseModel):
    agent_name: str
    kind: Literal["codebase_read", "memory_read"]
    tokens: int = Field(ge=0)


class DeclareRequest(BaseModel):
    agent_name: str
    developer_name: str | None = None  # ignored when authenticated: comes from the account
    plan_text: str
    task_ref: str | None = None
    branch: str | None = None
    wait_seconds: int = Field(default=0, ge=0, le=600)


class WriteMemoryRequest(BaseModel):
    agent_name: str
    type: Literal["discovery", "decision", "dead_end", "ruling", "handoff"]
    content: str
    concepts: list[str] = Field(default_factory=list)


class EventFrame(BaseModel):
    id: str
    type: str
    project_id: str
    ts: str
    data: dict


# -- auth / organisations -----------------------------------------------------------


class UserOut(ORM):
    id: uuid.UUID
    email: str
    name: str
    avatar_url: str | None = None
    github_login: str | None = None
    created_at: datetime | None = None


class MembershipOut(BaseModel):
    org_id: uuid.UUID
    org_name: str | None = None
    org_slug: str | None = None
    role: str
    user_id: uuid.UUID
    user_email: str | None = None
    user_name: str | None = None
    user_avatar_url: str | None = None


class MeOut(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]


class TokenOut(BaseModel):
    token: str
    token_type: str = "bearer"
    me: MeOut


class OrgOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    auto_join_domain: str | None = None
    created_at: datetime | None = None
    role: str | None = None  # the caller's role, when known
    integrations: dict | None = None  # {github: {connected, connected_by}, notion: {connected, tasks_db_id}}


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    slug: str | None = None
    auto_join_domain: str | None = None


class OrgUpdate(BaseModel):
    name: str | None = None
    auto_join_domain: str | None = None


class InviteCreate(BaseModel):
    email: str | None = None
    role: Literal["admin", "member"] = "member"


class InviteOut(ORM):
    id: uuid.UUID
    org_id: uuid.UUID
    org_name: str | None = None
    email: str | None = None
    role: str
    token: str | None = None
    url: str | None = None
    expires_at: datetime | None = None
    accepted_at: datetime | None = None


class RoleUpdate(BaseModel):
    role: Literal["admin", "member"]


class ProjectCreateInOrg(BaseModel):
    name: str
    repo_full_name: str | None = None


class ApiKeyCreate(BaseModel):
    name: str = Field(default="default", max_length=80)
    org_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None


class ApiKeyOut(ORM):
    id: uuid.UUID
    name: str
    prefix: str
    org_id: uuid.UUID
    project_id: uuid.UUID | None = None
    created_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreated(ApiKeyOut):
    key: str  # plaintext, shown once
    mcp_url: str


class NotionConnect(BaseModel):
    notion_token: str
    notion_tasks_db_id: str

"""The agent-facing MCP tools.

The four from the spec (signatures fixed):
    declare_intent, query_memory, write_memory, file_handoff
plus the ones the spec's own flow relies on:
    check_verdict  - poll / long-poll a clash after a `wait` verdict
    withdraw_claim - abandon a plan so it stops blocking others
    get_status     - my claims, clashes waiting on me, clashes I am blocking
    report_usage   - agents self-report codebase_read tokens (powers "tokens saved")

Every tool accepts an optional `project_id`. When omitted, the API key's bound
project is used, else the caller's only project.
"""

import uuid
from typing import Literal

import functools

from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from app.config import get_settings
from app.core import claims as claims_core
from app.core import handoff as handoff_core
from app.core import memory as memory_core
from app.core import verdict as verdict_core
from app.mcp.auth import bind_principal


def _agent_facing(fn):
    """Turn domain errors into ToolError so the agent sees the reason, not a generic failure."""
    from app.core.auth import AuthError, Forbidden

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except (AuthError, Forbidden, LookupError, ValueError) as e:
            raise ToolError(f"{type(e).__name__}: {e}") from e

    return wrapper


async def _require_claim_access(claim_id: uuid.UUID) -> None:
    from app.core.auth import current_principal, require_project_access
    from app.db.models import Claim
    from app.db.session import session_scope

    async with session_scope() as db:
        claim = await db.get(Claim, claim_id)
        if claim is None:
            raise LookupError(f"claim {claim_id} not found")
        await require_project_access(db, current_principal.get(), claim.project_id)


async def _require_clash_access(clash_id: uuid.UUID) -> None:
    from app.core.auth import current_principal, require_project_access
    from app.db.models import Clash
    from app.db.session import session_scope

    async with session_scope() as db:
        clash = await db.get(Clash, clash_id)
        if clash is None:
            raise LookupError(f"clash {clash_id} not found")
        await require_project_access(db, current_principal.get(), clash.project_id)


def register_tools(mcp) -> None:
    settings = get_settings()

    @mcp.tool(
        name="declare_intent",
        description=(
            "Declare what you plan to build BEFORE writing code. Returns a verdict: "
            "'proceed', 'proceed_with_context' (read the context first), or 'wait' "
            "(a hard clash with another agent's open plan; call check_verdict with the clash_id, "
            "or pass wait_seconds to hold this call open until a human rules)."
        ),
    )
    @_agent_facing
    async def declare_intent(
        agent_name: str = Field(description="Your agent's name, e.g. 'Agent A'"),
        developer_name: str | None = Field(default=None, description="The human you work for. Ignored when authenticated: taken from the API key's account."),
        plan_text: str = Field(description="Plain-language description of what you intend to change and how"),
        task_ref: str | None = Field(default=None, description="Ticket reference, e.g. 'ENG-1234'"),
        branch: str | None = Field(default=None, description="Git branch you will work on"),
        wait_seconds: int = Field(
            default=0, ge=0, le=600, description="If the verdict is 'wait', hold the call open this long for a ruling"
        ),
        project_id: str | None = Field(default=None, description="Project UUID; omit to use the server default"),
        ctx: Context = None,  # injected by the SDK
    ) -> dict:
        await bind_principal(ctx)
        result = await verdict_core.declare_intent(
            agent_name=agent_name,
            developer_name=developer_name,
            plan_text=plan_text,
            task_ref=task_ref,
            branch=branch,
            project_id=project_id,
            wait_seconds=min(wait_seconds, settings.max_wait_seconds),
        )
        return result.model_dump(mode="json")

    @mcp.tool(
        name="check_verdict",
        description=(
            "After a 'wait' verdict, check whether the clash has been resolved. "
            "Pass wait_seconds (up to 120) to long-poll until a human rules."
        ),
    )
    @_agent_facing
    async def check_verdict(
        clash_id: str = Field(description="clash_id returned by declare_intent"),
        wait_seconds: int = Field(default=0, ge=0, le=600),
        ctx: Context = None,  # injected by the SDK
    ) -> dict:
        await bind_principal(ctx)
        await _require_clash_access(uuid.UUID(clash_id))
        result = await verdict_core.check_verdict(uuid.UUID(clash_id), wait_seconds=min(wait_seconds, settings.max_wait_seconds))
        return result.model_dump(mode="json")

    @mcp.tool(
        name="query_memory",
        description=(
            "Ask the team's shared memory before reading the codebase. Vector search over discoveries, "
            "decisions, dead ends, rulings and handoffs. No LLM involved."
        ),
    )
    @_agent_facing
    async def query_memory(
        question: str = Field(description="What you want to know, e.g. 'how does login work'"),
        limit: int = Field(default=5, ge=1, le=25),
        agent_name: str | None = Field(default=None, description="Your agent name, for token accounting"),
        project_id: str | None = Field(default=None),
        ctx: Context = None,  # injected by the SDK
    ) -> dict:
        await bind_principal(ctx)
        result = await memory_core.query_memory(question=question, limit=limit, project_id=project_id, agent_name=agent_name)
        return result.model_dump(mode="json")

    @mcp.tool(
        name="write_memory",
        description=(
            "Record something the team should know: a discovery about how the code works, a decision, "
            "a dead end you hit, or a handoff. Near-duplicates are linked rather than duplicated."
        ),
    )
    @_agent_facing
    async def write_memory(
        agent_name: str,
        type: Literal["discovery", "decision", "dead_end", "ruling", "handoff"],
        content: str = Field(description="One to three sentences. Specific and reusable."),
        concepts: list[str] | None = Field(default=None, description="Short domain nouns this is about, e.g. ['session model']"),
        project_id: str | None = Field(default=None),
        ctx: Context = None,  # injected by the SDK
    ) -> dict:
        await bind_principal(ctx)
        result = await memory_core.write_memory(
            agent_name=agent_name, type=type, content=content, concepts=concepts or [], project_id=project_id
        )
        return result.model_dump(mode="json")

    @mcp.tool(
        name="file_handoff",
        description=(
            "When your work is ready for review: record what changed, what you deliberately left alone, "
            "your assumptions and uncertainties. Moves the claim to in_review and opens the pull request."
        ),
    )
    @_agent_facing
    async def file_handoff(
        claim_id: str = Field(description="claim_id returned by declare_intent"),
        changed: list[str] = Field(description="What you changed"),
        untouched: list[str] = Field(default_factory=list, description="What you deliberately did not touch"),
        assumptions: list[str] = Field(default_factory=list),
        uncertainties: list[str] = Field(default_factory=list),
        ctx: Context = None,  # injected by the SDK
    ) -> dict:
        await bind_principal(ctx)
        await _require_claim_access(uuid.UUID(claim_id))
        result = await handoff_core.file_handoff(
            claim_id=uuid.UUID(claim_id),
            changed=changed,
            untouched=untouched,
            assumptions=assumptions,
            uncertainties=uncertainties,
        )
        return result.model_dump(mode="json")

    @mcp.tool(
        name="withdraw_claim",
        description=(
            "Abandon a declared plan. Retires your claim and immediately releases any agent that was "
            "waiting on it. Use it when you change course or give up on the plan, so it stops blocking others."
        ),
    )
    @_agent_facing
    async def withdraw_claim(
        claim_id: str = Field(description="claim_id returned by declare_intent"),
        reason: str | None = Field(default=None, description="One sentence; becomes the note on any clash this releases"),
        ctx: Context = None,  # injected by the SDK
    ) -> dict:
        await bind_principal(ctx)
        result = await claims_core.withdraw_claim(uuid.UUID(claim_id), reason=reason)
        return result.model_dump(mode="json")

    @mcp.tool(
        name="get_status",
        description=(
            "Where you stand: your open and in-review claims, clashes waiting on a human ruling for you, "
            "and clashes where another agent is waiting on you. Call it when resuming work or before declaring."
        ),
    )
    @_agent_facing
    async def get_status(
        agent_name: str | None = Field(default=None, description="Limit to one agent; default: every agent owned by your account"),
        project_id: str | None = Field(default=None),
        ctx: Context = None,  # injected by the SDK
    ) -> dict:
        await bind_principal(ctx)
        result = await claims_core.status(agent_name=agent_name, project_id=project_id)
        return result.model_dump(mode="json")

    @mcp.tool(
        name="report_usage",
        description=(
            "Report tokens you spent reading the codebase directly (kind='codebase_read'). "
            "Used to compute how many tokens shared memory saves the team."
        ),
    )
    @_agent_facing
    async def report_usage(
        agent_name: str,
        tokens: int = Field(ge=0),
        kind: Literal["codebase_read", "memory_read"] = "codebase_read",
        project_id: str | None = Field(default=None),
        ctx: Context = None,  # injected by the SDK
    ) -> dict:
        await bind_principal(ctx)
        event_id = await memory_core.record_token_event(agent_name=agent_name, kind=kind, tokens=tokens, project_id=project_id)
        return {"event_id": str(event_id), "kind": kind, "tokens": tokens}

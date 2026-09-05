"""MCP server over streamable HTTP, mounted into the FastAPI app at /mcp.

Agents connect to  http://<host>:<port>/mcp
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from app.mcp.tools import register_tools

INSTRUCTIONS = """Consensus coordinates AI coding agents working on the same repository.

Workflow for an agent:
1. query_memory before reading the codebase.
2. declare_intent before writing code. Obey the verdict:
   - proceed: go ahead.
   - proceed_with_context: read `context` (and `ruling` if present) first, then go ahead.
   - wait: another agent's open plan conflicts with yours. Call check_verdict(clash_id, wait_seconds=120)
     until a human rules, then follow the ruling.
3. write_memory for every discovery, decision, or dead end worth sharing.
4. file_handoff when your change is ready for review.
"""

mcp_server = MCPServer(name="consensus", instructions=INSTRUCTIONS, version="0.1.0")
register_tools(mcp_server)


def build_mcp_app():
    """Starlette app exposing the transport at /mcp. Its session manager is run from the FastAPI lifespan."""
    return mcp_server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        # Bound to all interfaces in dev; agents on other machines must be able to reach it.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host="0.0.0.0",
    )

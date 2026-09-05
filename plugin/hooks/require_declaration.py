"""Consensus guardrail hook for Claude Code.

Turns "declare before you write" from a convention into a rule the editor
enforces:

  pre   PreToolUse on Edit/Write/MultiEdit/NotebookEdit. Blocks (exit 2) unless
        this session has a declaration whose verdict allows work. The message
        on stderr tells the agent what to do instead.
  post  PostToolUse on the Consensus tools. Records the outcome of
        declare_intent / check_verdict / withdraw_claim / file_handoff for the
        session so `pre` knows where things stand.

State lives in ~/.consensus/sessions/<session_id>.json, one file per Claude
Code session. No network calls, so the hook works offline and adds no latency.

Escape hatches:
  CONSENSUS_ENFORCE=0            disable the guardrail entirely
  CONSENSUS_ALLOW_PATHS=a,b,c    comma-separated path prefixes that never need a
                                 declaration (default: .consensus, docs, README)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("CONSENSUS_STATE_DIR") or Path.home() / ".consensus" / "sessions")
DEFAULT_ALLOW = (".consensus", "docs/", "README", "CHANGELOG", ".gitignore")
# Tool responses reach the hook either as structured objects or as JSON text inside a content
# block. In the second form the quotes are escaped once json.dumps has run, hence the optional
# backslashes: the same pattern matches  "verdict": "wait"  and  \"verdict\":\"wait\" .
Q = r'\\?"'
VERDICT_RE = re.compile(Q + r'verdict' + Q + r'\s*:\s*' + Q + r'(proceed_with_context|proceed|wait)' + Q)
CLAIM_RE = re.compile(Q + r'claim_id' + Q + r'\s*:\s*' + Q + r'([0-9a-fA-F-]{36})' + Q)
CLASH_RE = re.compile(Q + r'clash_id' + Q + r'\s*:\s*' + Q + r'([0-9a-fA-F-]{36})' + Q)
STATUS_RE = re.compile(Q + r'status' + Q + r'\s*:\s*' + Q + r'(resolved|auto_resolved|open)' + Q)


def _read_event() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}


def _state_path(session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "default")
    return STATE_DIR / f"{safe}.json"


def _load(session_id: str) -> dict:
    p = _state_path(session_id)
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save(session_id: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state["updated"] = int(time.time())
    _state_path(session_id).write_text(json.dumps(state), "utf-8")


def _allowed_path(tool_input: dict) -> bool:
    path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
    if not path:
        return False
    norm = path.replace("\\", "/")
    prefixes = [p.strip() for p in os.environ.get("CONSENSUS_ALLOW_PATHS", "").split(",") if p.strip()] or list(DEFAULT_ALLOW)
    base = norm.rsplit("/", 1)[-1]
    return any(norm.startswith(pre) or f"/{pre}" in norm or base.startswith(pre) for pre in prefixes)


def pre(event: dict) -> int:
    if os.environ.get("CONSENSUS_ENFORCE", "1") == "0":
        return 0
    if _allowed_path(event.get("tool_input") or {}):
        return 0
    state = _load(event.get("session_id", ""))
    verdict = state.get("verdict")
    if verdict in ("proceed", "proceed_with_context") and not state.get("handed_off"):
        return 0
    if verdict == "wait":
        clash = state.get("clash_id", "")
        sys.stderr.write(
            "Consensus: your declared plan clashes with another agent's open plan and is waiting on a human ruling. "
            f"Do not edit code yet. Call check_verdict(clash_id=\"{clash}\", wait_seconds=120) and follow the ruling, "
            "or withdraw_claim if you are abandoning this plan.\n"
        )
        return 2
    if state.get("handed_off"):
        sys.stderr.write(
            "Consensus: the last plan was handed off for review. Declare a new plan with declare_intent before editing again.\n"
        )
        return 2
    sys.stderr.write(
        "Consensus: declare your plan before editing code. Call query_memory to learn what the team already knows, "
        "then declare_intent(agent_name, plan_text, branch) and act on the verdict. "
        "Set CONSENSUS_ENFORCE=0 to disable this guardrail.\n"
    )
    return 2


def post(event: dict) -> int:
    session_id = event.get("session_id", "")
    tool = event.get("tool_name", "")
    blob = json.dumps(event.get("tool_response"), default=str)
    state = _load(session_id)

    if tool.endswith("declare_intent"):
        m = VERDICT_RE.search(blob)
        if m:
            state["verdict"] = m.group(1)
            state["handed_off"] = False
            c = CLAIM_RE.search(blob)
            if c:
                state["claim_id"] = c.group(1)
            k = CLASH_RE.search(blob)
            state["clash_id"] = k.group(1) if (k and m.group(1) == "wait") else None
    elif tool.endswith("check_verdict"):
        s = STATUS_RE.search(blob)
        if s and s.group(1) in ("resolved", "auto_resolved"):
            state["verdict"] = "proceed_with_context"
            state["clash_id"] = None
    elif tool.endswith("withdraw_claim"):
        state = {"verdict": None, "withdrawn": True}
    elif tool.endswith("file_handoff"):
        state["handed_off"] = True

    _save(session_id, state)
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    event = _read_event()
    try:
        return pre(event) if mode == "pre" else post(event)
    except Exception as e:  # never break the editor because of the guardrail
        sys.stderr.write(f"Consensus hook error (ignored): {e}\n")
        return 0


if __name__ == "__main__":
    sys.exit(main())

"""Plan text -> stance JSON. This is the ONE LLM call in the declare path.

Schema (fixed, spec section 7 step 2):
    {
      concepts: string[],
      error_handling: string|null,
      auth_check:     string|null,
      data_access:    string|null,
      api_shape:      string|null,
      summary:        string
    }

Axes the plan does not address MUST be null. A guessed position makes
everything look like it conflicts with everything.

Two providers:
  * AnthropicStanceExtractor  - structured output via output_config.format
  * KeywordStanceExtractor    - offline, deterministic; for tests and demos
                                without network access.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

from app.config import get_settings
from app.core.text import normalize_concept
from app.db.models import FOUR_AXES

log = logging.getLogger(__name__)


@dataclass
class Stance:
    concepts: list[str] = field(default_factory=list)
    error_handling: str | None = None
    auth_check: str | None = None
    data_access: str | None = None
    api_shape: str | None = None
    summary: str = ""

    def axis(self, name: str) -> str | None:
        return getattr(self, name)

    def to_dict(self) -> dict:
        return {
            "concepts": list(self.concepts),
            "error_handling": self.error_handling,
            "auth_check": self.auth_check,
            "data_access": self.data_access,
            "api_shape": self.api_shape,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Stance":
        def _clean(v):
            if v is None:
                return None
            v = str(v).strip()
            if not v or v.lower() in {"null", "none", "n/a", "not addressed", "not specified", "unspecified"}:
                return None
            return v

        concepts: list[str] = []
        seen: set[str] = set()
        for c in d.get("concepts") or []:
            c = str(c).strip()
            if not c:
                continue
            key = normalize_concept(c)
            if key in seen:
                continue
            seen.add(key)
            concepts.append(c)
        return cls(
            concepts=concepts,
            error_handling=_clean(d.get("error_handling")),
            auth_check=_clean(d.get("auth_check")),
            data_access=_clean(d.get("data_access")),
            api_shape=_clean(d.get("api_shape")),
            summary=str(d.get("summary") or "").strip(),
        )


class StanceExtractor(Protocol):
    async def extract(self, plan_text: str) -> Stance: ...


STANCE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-6 short domain nouns naming what the plan touches, e.g. 'session model', 'login endpoint'.",
        },
        "error_handling": {"type": ["string", "null"]},
        "auth_check": {"type": ["string", "null"]},
        "data_access": {"type": ["string", "null"]},
        "api_shape": {"type": ["string", "null"]},
        "summary": {"type": "string"},
    },
    "required": ["concepts", "error_handling", "auth_check", "data_access", "api_shape", "summary"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You extract a *stance* from an AI coding agent's plan so it can be compared, \
deterministically and without another model call, against other agents' plans.

Return JSON with:
- concepts: 2-6 short, generic domain nouns naming the things this plan touches or depends on. \
Prefer the shared vocabulary a team would use ("session model", "auth token", "login endpoint", \
"user table", "payment webhook") over file names or one-off phrasing. Always include the broader \
subsystem the plan changes, not only the specific piece. Never include file paths.
- error_handling: how errors are surfaced, if the plan takes a position (e.g. "raise 401 on invalid token").
- auth_check: how requests are authenticated/authorized, if the plan takes a position \
(e.g. "signed refresh token validated per request").
- data_access: where/how state is stored or read, if the plan takes a position \
(e.g. "sessions stored server-side in redis", "sessions are stateless signed tokens").
- api_shape: request/response contract, if the plan takes a position (e.g. "POST /login returns session id").
- summary: one sentence.

Each axis value must be a short phrase (under 12 words) stating the position, not a description of the plan.
An axis MUST be null when the plan does not take a position on it. Do not guess. Do not infer a \
position from what would be conventional. Null means "not addressed" and is the correct answer \
for most axes on most plans."""


class AnthropicStanceExtractor:
    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        import anthropic

        settings = get_settings()
        self.model = model or settings.stance_model
        self._client = anthropic.AsyncAnthropic(api_key=api_key or settings.anthropic_api_key, max_retries=2, timeout=60.0)

    async def extract(self, plan_text: str) -> Stance:
        extra: dict = {}
        if self.model.startswith(("claude-opus-5", "claude-fable")):
            # Server-side refusal fallbacks exist only on the Opus 5 / Fable tier.
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        response = await self._client.beta.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"<plan>\n{plan_text.strip()}\n</plan>"}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": STANCE_JSON_SCHEMA}},
            **extra,
        )
        if response.stop_reason == "refusal":
            log.warning("stance extraction refused: %s", getattr(response, "stop_details", None))
            return Stance(summary="(stance extraction refused)")
        text = next(b.text for b in response.content if b.type == "text")
        return Stance.from_dict(json.loads(text))


# --------------------------------------------------------------------------
# Offline extractor: a small rule set good enough for the demo scenario and
# for exercising the comparison logic without network access.
# --------------------------------------------------------------------------

# (regex, concept name). First match per concept wins; order matters only for readability.
_CONCEPT_RULES: list[tuple[str, str]] = [
    (r"\bsession(s)?\b", "session model"),
    (r"\brefresh[- ]?token", "refresh token flow"),
    (r"\bsigned[- ]token|\bjwt\b|\bauth(entication)? token", "auth token"),
    (r"\blog[- ]?in\b|\bsign[- ]?in\b", "login endpoint"),
    (r"\blog[- ]?out\b", "logout endpoint"),
    (r"\bauth(entication|orization|z|n)?\b", "authentication"),
    (r"\bpassword", "password handling"),
    (r"\buser(s)? (table|model|record)", "user model"),
    (r"\bpayment|\bbilling|\binvoice", "billing"),
    (r"\bwebhook", "webhooks"),
    (r"\brate[- ]?limit", "rate limiting"),
    (r"\bcache|\bcaching|\bredis\b", "caching layer"),
    (r"\bmigration|\bschema\b", "database schema"),
    (r"\bemail|\bnotification", "notifications"),
    (r"\bsearch\b|\bindex(ing)?\b", "search"),
    (r"\bupload|\bfile storage|\bs3\b", "file storage"),
    (r"\bpermission|\brole(s)?\b|\brbac\b", "permissions model"),
    (r"\bapi key", "api keys"),
    (r"\blogging|\bmetrics|\btracing|\bobservab", "observability"),
    (r"\bqueue|\bworker|\bbackground job", "background jobs"),
    (r"\bconfig(uration)?\b|\bsettings\b|\benv(ironment)? var", "configuration"),
    (r"\bfrontend|\bui\b|\breact\b", "frontend"),
    (r"\bcsv|\bexport\b|\breport(s|ing)?\b", "reporting"),
]

# Axis rules: (regex, canonical short position). First match wins per axis.
_AXIS_RULES: dict[str, list[tuple[str, str]]] = {
    "data_access": [
        (r"signed tokens?|stateless|refresh[- ]?token|jwt", "sessions are stateless signed tokens"),
        (r"server[- ]?side (session )?store|server[- ]?side session|stored? (on|in) (the )?server|session (id|store|table)", "sessions stored server-side"),
        (r"\bredis\b", "state stored in redis"),
        (r"in[- ]memory", "state stored in memory"),
        (r"\bpostgres|\bdatabase table|\bnew table|\bmigration", "state stored in database"),
        (r"\bcache", "reads served from cache"),
    ],
    "auth_check": [
        (r"refresh[- ]?token|signed tokens?|jwt", "validate signed token per request"),
        (r"session (id|cookie|lookup)|server[- ]?side session|look ?up (the )?session", "look up server-side session per request"),
        (r"api key", "api key check per request"),
        (r"no auth|unauthenticated|public endpoint", "no authentication required"),
        (r"\badmin only|\brole check|\bpermission check", "role-based permission check"),
    ],
    "error_handling": [
        (r"\b401\b", "respond 401 on auth failure"),
        (r"\b403\b", "respond 403 on forbidden"),
        (r"\b404\b", "respond 404 when missing"),
        (r"\b400\b|validation error", "respond 400 on invalid input"),
        (r"\b(raise|throw)s? (an? )?(exception|error)", "raise exception on failure"),
        (r"retry|retries|backoff", "retry with backoff on failure"),
        (r"return(s)? (null|none|empty)", "return empty on failure"),
    ],
    "api_shape": [
        (r"\b(post|get|put|patch|delete) (/[\w/{}-]*)", None),  # handled specially below
        (r"returns? (the )?session id", "response carries session id"),
        (r"returns? (a |the )?(signed |refresh |access )?token", "response carries token"),
        (r"graphql", "graphql schema"),
        (r"pagination|paginated", "paginated list response"),
    ],
}


class KeywordStanceExtractor:
    """Deterministic, offline stance extraction. No network, no randomness."""

    async def extract(self, plan_text: str) -> Stance:
        text = plan_text.strip()
        low = text.lower()

        concepts: list[str] = []
        for pattern, name in _CONCEPT_RULES:
            if re.search(pattern, low) and name not in concepts:
                concepts.append(name)
        concepts = concepts[:6]

        axes: dict[str, str | None] = {a: None for a in FOUR_AXES}
        for axis, rules in _AXIS_RULES.items():
            for pattern, position in rules:
                m = re.search(pattern, low)
                if not m:
                    continue
                if position is None:  # api_shape route pattern
                    verb, path = m.group(1).upper(), m.group(2)
                    suffix = ""
                    if re.search(r"returns? (the )?session id", low):
                        suffix = " returns session id"
                    elif re.search(r"returns? (a |the )?(signed |refresh |access )?token", low):
                        suffix = " returns token"
                    axes[axis] = f"{verb} {path}{suffix}"
                else:
                    axes[axis] = position
                break

        summary = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0][:200] if text else ""
        return Stance(
            concepts=concepts,
            error_handling=axes["error_handling"],
            auth_check=axes["auth_check"],
            data_access=axes["data_access"],
            api_shape=axes["api_shape"],
            summary=summary,
        )


def build_stance_extractor() -> StanceExtractor:
    settings = get_settings()
    if settings.stance_provider == "anthropic":
        if not settings.anthropic_api_key:
            log.warning("STANCE_PROVIDER=anthropic but ANTHROPIC_API_KEY is empty; falling back to keyword extractor")
            return KeywordStanceExtractor()
        return AnthropicStanceExtractor()
    return KeywordStanceExtractor()

"""Deterministic text normalisation used by the comparison step.

No LLM anywhere in this module. Everything here is lowercase / trim / small
hardcoded synonym maps, so the same two stances always compare the same way.
"""
from __future__ import annotations

import re

_WORD_RE = re.compile(r"[a-z0-9]+")
_COMPOUND_RE = re.compile(r"\b(server|client)[- ]?side\b")

# Words that carry no meaning for comparison purposes.
STOPWORDS = frozenset(
    """
    a an the and or of to in on for with by from at as is are be was were been being
    this that these those it its into via using use uses used will would should can
    could may might must do does did done yes than then so such we our
    when if after before per over each every all any only also just still
    """.split()
)

# Words that flip the meaning of what follows. They are never dropped: a position
# that says "not server-side" must contradict one that says "server-side".
NEGATIONS = frozenset("not no never without instead rather non nor".split())

# Generic nouns that appear in most concept names; sharing only one of these is
# not evidence that two concepts are the same ("session model" vs "user model").
GENERIC_TOKENS = frozenset(
    """
    model models module modules service services endpoint endpoints api apis flow flows
    handler handlers logic layer layers system systems code feature features change changes
    function functions method methods class classes object objects type types data
    table tables schema schemas route routes path paths field fields value values
    new old current existing add remove update create delete replace refactor
    """.split()
)

# Synonym map applied token-by-token after stemming. Keep it small and obvious.
SYNONYMS: dict[str, str] = {
    # HTTP / errors
    "raise": "throw",
    "throws": "throw",
    "return": "respond",
    "returns": "respond",
    "respond": "respond",
    "err": "error",
    "errors": "error",
    "exception": "error",
    "exceptions": "error",
    "http": "",
    "status": "",
    "code": "",
    "codes": "",
    # auth
    "authentication": "auth",
    "authenticate": "auth",
    "authenticated": "auth",
    "authorization": "auth",
    "authorize": "auth",
    "authorized": "auth",
    "authz": "auth",
    "authn": "auth",
    "login": "login",
    "signin": "login",
    "jwt": "token",
    "jwts": "token",
    "tokens": "token",
    "cookie": "cookie",
    "cookies": "cookie",
    "sessions": "session",
    # storage
    "redis": "redis",
    "database": "db",
    "postgres": "db",
    "postgresql": "db",
    "sql": "db",
    "store": "store",
    "stored": "store",
    "storage": "store",
    "persist": "store",
    "persisted": "store",
    "persistent": "store",
    "server": "server",
    "serverside": "server",
    "backend": "server",
    "client": "client",
    "clientside": "client",
    "stateless": "stateless",
    "signed": "signed",
    "sign": "signed",
    # shape
    "identifier": "id",
    "ids": "id",
    "uuid": "id",
    "json": "json",
    "payload": "body",
    "body": "body",
    "response": "response",
    "request": "request",
    "req": "request",
    "resp": "response",
    "endpoint": "endpoint",
    "endpoints": "endpoint",
    "route": "endpoint",
    "routes": "endpoint",
    "handler": "endpoint",
    "post": "post",
    "get": "get",
    "put": "put",
    "patch": "patch",
    "delete": "delete",
}


def _stem(tok: str) -> str:
    """Tiny, predictable stemmer: strips common English suffixes."""
    if len(tok) <= 3:
        return tok
    for suffix in ("ing", "ies", "es", "ed", "s"):
        if tok.endswith(suffix) and len(tok) - len(suffix) >= 3:
            base = tok[: -len(suffix)]
            if suffix == "ies":
                base += "y"
            elif suffix == "es" and not base.endswith(("s", "x", "z", "ch", "sh")):
                base = tok[:-1]  # "minutes" -> "minute", "routes" -> "route"; "boxes" -> "box"
            return base
    return tok


def tokens(text: str | None) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords, stem, map synonyms."""
    if not text:
        return []
    # "server-side", "server side" and "serverside" must all agree
    text = _COMPOUND_RE.sub(lambda m: m.group(1) + "side", text.lower())
    text = text.replace("-", " ").replace("_", " ").replace("/", " ")
    out: list[str] = []
    for raw in _WORD_RE.findall(text):
        if raw in NEGATIONS:
            out.append("!")
            continue
        if raw in STOPWORDS:
            continue
        tok = SYNONYMS.get(raw)
        if tok is None:
            tok = _stem(raw)
            tok = SYNONYMS.get(tok, tok)
        if tok:
            out.append(tok)
    return out


def polarised(text: str | None) -> tuple[set[str], set[str]]:
    """Split a position into (asserted, negated) token sets.

    Everything after a negation marker, up to the end of the phrase, is negated:
    "stateless signed tokens, not server-side store" -> ({stateless, signed, token}, {server, store})
    """
    pos: set[str] = set()
    neg: set[str] = set()
    negating = False
    for t in tokens(text):
        if t == "!":
            negating = True
            continue
        (neg if negating else pos).add(t)
    return pos, neg


def normalize(text: str | None) -> str:
    """Canonical string for equality comparison of an axis position (negation-aware)."""
    pos, neg = polarised(text)
    return " ".join(sorted(pos) + sorted("!" + n for n in neg))


def normalize_concept(concept: str) -> str:
    """Canonical string for a concept name ("Session Model" -> "session model")."""
    return " ".join(t for t in tokens(concept) if t != "!") or concept.strip().lower()


def significant_tokens(concept: str) -> set[str]:
    return {t for t in tokens(concept) if t != "!" and t not in GENERIC_TOKENS and len(t) >= 3}


def concepts_match(a: str, b: str) -> bool:
    """Two concept names refer to the same thing if they normalise identically or
    share at least one significant (non-generic) token.

    "session model" ~ "server-side session"  (share: session)
    "session model" !~ "user model"          (only share generic: model)
    """
    na, nb = normalize_concept(a), normalize_concept(b)
    if na == nb:
        return True
    return bool(significant_tokens(a) & significant_tokens(b))


def shared_concepts(a: list[str], b: list[str]) -> list[str]:
    """Concept names from both lists that match something on the other side."""
    out: list[str] = []
    seen: set[str] = set()
    for x in a:
        for y in b:
            if concepts_match(x, y):
                for c in (x, y):
                    key = normalize_concept(c)
                    if key not in seen:
                        seen.add(key)
                        out.append(c.strip())
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def overlap_coefficient(a: set[str], b: set[str]) -> float:
    """|A ∩ B| / min(|A|, |B|): 1.0 when one phrasing is a subset of the other."""
    if not a or not b:
        return 1.0 if not a and not b else 0.0
    return len(a & b) / min(len(a), len(b))


def positions_agree(a: str, b: str, min_overlap: float = 0.67) -> bool:
    """Deterministic 'same position' test for one stance axis.

    1. Anything asserted by one side and negated by the other is a contradiction.
       ("sessions stored server-side" vs "signed tokens, not server-side store")
    2. Otherwise the positions agree when their asserted tokens overlap enough that
       the difference is wording rather than substance (overlap coefficient, so a
       more verbose phrasing of the same position still matches).
    """
    pos_a, neg_a = polarised(a)
    pos_b, neg_b = polarised(b)
    if (pos_a & neg_b) or (pos_b & neg_a):
        return False
    if pos_a == pos_b:
        return True
    return overlap_coefficient(pos_a, pos_b) >= min_overlap

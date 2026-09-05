"""Unit tests for the deterministic comparison. No database, no network."""
from __future__ import annotations

import asyncio

from app.core.clash import compare, overall_severity
from app.core.stance import KeywordStanceExtractor, Stance
from app.core.text import concepts_match, normalize, positions_agree, shared_concepts


def test_normalize_collapses_wording():
    assert normalize("Return HTTP 400 on invalid input") == normalize("respond 400 on invalid input")
    assert normalize("server-side session store") == normalize("Server side sessions store")


def test_positions_agree_tolerates_minor_wording():
    assert positions_agree("sessions stored server-side", "session stored on the server side")
    assert not positions_agree("sessions stored server-side", "sessions are stateless signed tokens")


def test_concept_matching_ignores_generic_tokens():
    assert concepts_match("session model", "server-side session")
    assert not concepts_match("session model", "user model")
    assert shared_concepts(["Session Model", "login endpoint"], ["session store"]) == ["Session Model", "session store"]


def test_null_axes_are_skipped_not_guessed():
    new = Stance(concepts=["session model"], data_access="sessions are stateless signed tokens")
    other = Stance(concepts=["session model"], error_handling="respond 401 on auth failure")
    cmp = compare(new, other, similarity=0.3)
    assert cmp.concept_overlap
    assert cmp.divergent_axes == []
    assert cmp.severity == "soft"


def test_hard_clash_requires_overlap_and_divergence():
    new = Stance(concepts=["session model"], data_access="sessions stored server-side")
    other = Stance(concepts=["session model"], data_access="sessions are stateless signed tokens")
    cmp = compare(new, other, similarity=0.2)
    assert cmp.severity == "hard"
    assert cmp.primary.axis == "data_access"

    # Same divergence but nothing in common and low similarity -> not a clash at all.
    unrelated = Stance(concepts=["billing"], data_access="sessions are stateless signed tokens")
    assert compare(new, unrelated, similarity=0.2).severity == "clear"


def test_similarity_alone_can_establish_overlap():
    new = Stance(concepts=["checkout"], api_shape="POST /pay returns receipt id")
    other = Stance(concepts=["payments"], api_shape="POST /pay returns redirect url")
    assert compare(new, other, similarity=0.5).severity == "clear"
    assert compare(new, other, similarity=0.9).severity == "hard"


def test_overall_severity():
    hard = compare(Stance(concepts=["x"], api_shape="a b c"), Stance(concepts=["x"], api_shape="d e f"), 0.1)
    soft = compare(Stance(concepts=["x"]), Stance(concepts=["x"]), 0.1)
    assert overall_severity([hard, soft], memory_hits=0) == "hard"
    assert overall_severity([soft], memory_hits=0) == "soft"
    assert overall_severity([], memory_hits=2) == "context"
    assert overall_severity([], memory_hits=0) == "clear"


def test_keyword_extractor_on_golden_plans_leaves_untouched_axes_null():
    ex = KeywordStanceExtractor()
    a = asyncio.run(ex.extract("Replace the session model with a refresh-token flow. Sessions move from server-side store to signed tokens."))
    b = asyncio.run(ex.extract("Add a POST /login endpoint that creates a server-side session and returns the session id."))
    assert "session model" in a.concepts and "session model" in b.concepts
    assert a.error_handling is None and b.error_handling is None
    assert a.api_shape is None and b.api_shape.startswith("POST /login")
    assert a.data_access != b.data_access
    cmp = compare(b, a, similarity=0.0)
    assert cmp.severity == "hard"
    assert "session model" in cmp.shared_concepts

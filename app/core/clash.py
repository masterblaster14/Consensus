"""Deterministic comparison of a new stance against a candidate claim + severity.

No LLM. No file paths. Only concepts, embeddings, and the four stance axes.

    concept_overlap = shared concept names OR cosine(new, other) > threshold
    divergent_axes  = axes where both plans took a position and the positions differ

    hard    = overlap and divergent axes
    soft    = overlap, no divergent axes
    context = no overlap, but memory hits exist
    clear   = nothing
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config import get_settings
from app.core.stance import Stance
from app.core.text import positions_agree, shared_concepts
from app.db.models import FOUR_AXES

Severity = str  # "hard" | "soft" | "context" | "clear"


@dataclass
class AxisDivergence:
    axis: str
    ours: str
    theirs: str


@dataclass
class Comparison:
    concept_overlap: bool
    shared_concepts: list[str]
    similarity: float
    divergent_axes: list[AxisDivergence] = field(default_factory=list)

    @property
    def severity(self) -> Severity:
        if self.concept_overlap and self.divergent_axes:
            return "hard"
        if self.concept_overlap:
            return "soft"
        return "clear"

    @property
    def primary(self) -> AxisDivergence | None:
        return self.divergent_axes[0] if self.divergent_axes else None

    def to_dict(self) -> dict:
        return {
            "concept_overlap": self.concept_overlap,
            "shared_concepts": self.shared_concepts,
            "similarity": round(self.similarity, 4),
            "divergent_axes": [
                {"axis": d.axis, "ours": d.ours, "theirs": d.theirs} for d in self.divergent_axes
            ],
            "severity": self.severity,
        }


def compare(
    new: Stance,
    other: Stance,
    similarity: float,
    similarity_threshold: float | None = None,
    axis_jaccard: float | None = None,
) -> Comparison:
    settings = get_settings()
    threshold = settings.concept_similarity_threshold if similarity_threshold is None else similarity_threshold
    min_overlap = settings.axis_match_overlap if axis_jaccard is None else axis_jaccard

    shared = shared_concepts(new.concepts, other.concepts)
    overlap = bool(shared) or similarity > threshold

    divergent: list[AxisDivergence] = []
    for axis in FOUR_AXES:
        ours, theirs = new.axis(axis), other.axis(axis)
        if ours is None or theirs is None:
            continue  # null = not addressed = skipped. Never guessed.
        if not positions_agree(ours, theirs, min_overlap=min_overlap):
            divergent.append(AxisDivergence(axis=axis, ours=ours, theirs=theirs))

    return Comparison(concept_overlap=overlap, shared_concepts=shared, similarity=similarity, divergent_axes=divergent)


def overall_severity(comparisons: list[Comparison], memory_hits: int) -> Severity:
    sevs = {c.severity for c in comparisons}
    if "hard" in sevs:
        return "hard"
    if "soft" in sevs:
        return "soft"
    if memory_hits:
        return "context"
    return "clear"

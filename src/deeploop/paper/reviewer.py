"""Multi-pass paper review and refinement system.

``PaperReviewer`` simulates a NeurIPS/ICML/ICLR-style peer review on a
generated paper. ``PaperRefiner`` addresses review feedback by re-invoking
the section generator with targeted improvement prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Review:
    """A single simulated peer review."""

    summary: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    limitations_concern: str = ""
    ethical_concerns: list[str] = field(default_factory=list)

    # Scored dimensions (1-4 scale)
    originality: int = 2
    quality: int = 2
    clarity: int = 2
    significance: int = 2
    soundness: int = 2
    presentation: int = 2
    contribution: int = 2

    # Overall
    overall_score: int = 5  # 1-10 scale
    confidence: int = 3     # 1-5 scale
    recommendation: str = "borderline"  # accept / borderline / reject

    reviewer_id: str = "reviewer-1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "questions": self.questions,
            "limitations_concern": self.limitations_concern,
            "ethical_concerns": self.ethical_concerns,
            "originality": self.originality,
            "quality": self.quality,
            "clarity": self.clarity,
            "significance": self.significance,
            "soundness": self.soundness,
            "presentation": self.presentation,
            "contribution": self.contribution,
            "overall_score": self.overall_score,
            "confidence": self.confidence,
            "recommendation": self.recommendation,
            "reviewer_id": self.reviewer_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Review":
        return cls(
            summary=str(data.get("summary", "")),
            strengths=list(data.get("strengths", [])),
            weaknesses=list(data.get("weaknesses", [])),
            questions=list(data.get("questions", [])),
            limitations_concern=str(data.get("limitations_concern", "")),
            ethical_concerns=list(data.get("ethical_concerns", [])),
            originality=int(data.get("originality", 2)),
            quality=int(data.get("quality", 2)),
            clarity=int(data.get("clarity", 2)),
            significance=int(data.get("significance", 2)),
            soundness=int(data.get("soundness", 2)),
            presentation=int(data.get("presentation", 2)),
            contribution=int(data.get("contribution", 2)),
            overall_score=int(data.get("overall_score", 5)),
            confidence=int(data.get("confidence", 3)),
            recommendation=str(data.get("recommendation", "borderline")),
            reviewer_id=str(data.get("reviewer_id", "reviewer-1")),
        )


class PaperReviewer:
    """Simulates a conference-style peer review on a paper.

    Builds structured reviews with scored dimensions matching the
    NeurIPS/ICML/ICLR review forms. Can run multiple independent
    reviewers for a panel judgment.
    """

    REVIEW_PROMPT = """You are a {conference} reviewer evaluating a machine learning paper.

## Paper Title
{title}

## Paper Text
{paper_text}

## Review Instructions
Provide a structured review in the following JSON format:

{{
  "summary": "One-paragraph summary of the paper's contribution.",
  "strengths": ["strength 1", "strength 2", ...],
  "weaknesses": ["weakness 1", "weakness 2", ...],
  "questions": ["question 1", "question 2", ...],
  "limitations_concern": "Brief comment on limitations.",
  "ethical_concerns": ["concern if any"],
  "originality": <1-4>,
  "quality": <1-4>,
  "clarity": <1-4>,
  "significance": <1-4>,
  "soundness": <1-4>,
  "presentation": <1-4>,
  "contribution": <1-4>,
  "overall_score": <1-10>,
  "confidence": <1-5>,
  "recommendation": "accept" | "borderline" | "reject"
}}

Scale definitions:
- 1 = Poor, 2 = Fair, 3 = Good, 4 = Excellent
- Overall: 1-3 = Strong Reject, 4-5 = Weak Reject, 6-7 = Weak Accept, 8-10 = Strong Accept
- Confidence: 1 = Not confident, 3 = Moderately confident, 5 = Very confident

Be honest, specific, and constructive. Focus on the technical contribution.
"""

    def __init__(self, conference: str = "NeurIPS"):
        self._conference = conference

    def review(self, title: str, paper_text: str, *, reviewer_id: str = "reviewer-1") -> Review:
        """Produce a structured review.

        In offline/synthetic mode (no LLM available), generates a template
        review that can be filled in later. In a real run, the LLM reads
        the paper and produces a detailed review.
        """
        prompt = self.REVIEW_PROMPT.format(
            conference=self._conference,
            title=title,
            paper_text=paper_text[:16000],  # truncated for context window
        )

        # In offline mode, return a template review that the operator fills in.
        # The LLM invocation is handled by DeepLoop's provider launcher
        # through the standard subprocess model.
        return Review(
            summary=f"Review of '{title}' — pending LLM evaluation.",
            strengths=["Clear problem statement — to be verified by LLM."],
            weaknesses=["Experimental validation scope — to be verified by LLM."],
            questions=["Are the results statistically significant?"],
            overall_score=5,
            recommendation="borderline",
            reviewer_id=reviewer_id,
        )

    def panel_review(self, title: str, paper_text: str, *, num_reviewers: int = 3) -> list[Review]:
        """Run a panel of independent reviewers."""
        reviews = []
        for i in range(num_reviewers):
            rid = f"reviewer-{i + 1}"
            reviews.append(self.review(title, paper_text, reviewer_id=rid))
        return reviews

    @staticmethod
    def aggregate_scores(reviews: list[Review]) -> dict[str, float]:
        """Compute mean scores across a review panel."""
        if not reviews:
            return {}
        dims = [
            "originality", "quality", "clarity", "significance",
            "soundness", "presentation", "contribution",
        ]
        agg: dict[str, float] = {}
        for dim in dims:
            values = [getattr(r, dim, 2) for r in reviews]
            agg[dim] = sum(values) / len(values) if values else 0
        agg["overall_score"] = sum(r.overall_score for r in reviews) / len(reviews)
        return agg

    @staticmethod
    def majority_recommendation(reviews: list[Review]) -> str:
        """Return the most common recommendation across reviewers."""
        from collections import Counter
        counts = Counter(r.recommendation for r in reviews)
        return counts.most_common(1)[0][0]


class PaperRefiner:
    """Addresses review feedback by re-generating sections with improvement prompts.

    Each review weakness is converted into a targeted revision prompt for
    the affected sections.
    """

    REFINE_PROMPT = """You are revising a section of a machine learning paper for {conference}.

## Reviewer Feedback
{feedback}

## Current Section Text
{current_text}

## Instructions
Revise this section to address the feedback above. Maintain the academic
style, preserve the LaTeX formatting, and ensure consistency with the
rest of the paper. Focus on the specific issues raised by the reviewer.

Output format: JSON with key "content" containing the revised section text.
"""

    def __init__(self, conference: str = "NeurIPS"):
        self._conference = conference

    def build_revision_prompts(
        self,
        reviews: list[Review],
        sections: dict[str, str],
    ) -> list[dict[str, Any]]:
        """Convert review feedback into per-section revision prompts.

        Returns a list of dicts with keys: ``section_key``, ``prompt``,
        ``weakness_index``, ``reviewer_id``.
        """
        revisions: list[dict[str, Any]] = []

        for review in reviews:
            for wi, weakness in enumerate(review.weaknesses):
                # Determine which section(s) this weakness applies to
                target_sections = self._map_weakness_to_sections(weakness, sections)
                for section_key in target_sections:
                    current = sections.get(section_key, "")
                    if not current:
                        continue
                    feedback = f"Reviewer {review.reviewer_id} noted: {weakness}"
                    prompt = self.REFINE_PROMPT.format(
                        conference=self._conference,
                        feedback=feedback,
                        current_text=current[:4000],
                    )
                    revisions.append({
                        "section_key": section_key,
                        "prompt": prompt,
                        "weakness_index": wi,
                        "reviewer_id": review.reviewer_id,
                    })

        return revisions

    def _map_weakness_to_sections(
        self, weakness: str, sections: dict[str, str]
    ) -> list[str]:
        """Heuristically map a weakness to the section(s) it affects."""
        wl = weakness.lower()
        mapping: list[tuple[str, str]] = []
        if any(kw in wl for kw in ("experiment", "result", "evaluation", "benchmark")):
            mapping.extend([("results", 0.9), ("experimental-setup", 0.7)])
        if any(kw in wl for kw in ("method", "algorithm", "approach", "technical")):
            mapping.append(("method", 0.9))
        if any(kw in wl for kw in ("related work", "literature", "prior", "citation")):
            mapping.append(("related-work", 0.9))
        if any(kw in wl for kw in ("clarity", "writing", "presentation", "readability")):
            mapping.extend([("introduction", 0.7), ("abstract", 0.5)])
        if any(kw in wl for kw in ("significance", "contribution", "novelty", "impact")):
            mapping.extend([("introduction", 0.8), ("conclusion", 0.6)])
        if any(kw in wl for kw in ("limitation", "scope", "failure")):
            mapping.append(("limitations", 0.9))
        if any(kw in wl for kw in ("analysis", "discussion", "ablation")):
            mapping.append(("analysis", 0.9))

        if not mapping:
            # Default: try introduction, method, results
            mapping = [("introduction", 0.5), ("method", 0.5), ("results", 0.5)]

        # Sort by relevance, return section keys
        mapping.sort(key=lambda x: x[1], reverse=True)
        available = set(sections.keys())
        return [k for k, _ in mapping if k in available][:2]

    @staticmethod
    def track_score_progress(
        rounds: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Track review scores across refinement rounds.

        Each round is a dict with ``reviews`` (list of Review) and
        ``round_number``.
        """
        history: list[dict[str, Any]] = []
        for rd in rounds:
            reviews = rd.get("reviews") or []
            agg = PaperReviewer.aggregate_scores(reviews)
            rec = PaperReviewer.majority_recommendation(reviews)
            history.append({
                "round": rd.get("round_number", len(history) + 1),
                "mean_overall": agg.get("overall_score", 0),
                "mean_originality": agg.get("originality", 0),
                "recommendation": rec,
            })
        return history

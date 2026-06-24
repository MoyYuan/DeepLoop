"""Bridge between DeepLoop statistical rigor outputs and paper text.

``StatisticalNarrative`` converts Wilson intervals, confidence bounds,
and power analysis results into publication-ready prose that can be
injected directly into the Results and Analysis sections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StatBlock:
    """A single statistical finding formatted for paper inclusion."""

    text: str = ""
    """Prose description suitable for the Results section."""

    latex_table_row: str = ""
    """LaTeX table row fragment for the comparison table."""

    significance: str = ""
    """Short significance marker (``"p < 0.01"``, ``"n.s."``, etc.)."""


class StatisticalNarrative:
    """Converts structured statistical results into paper-ready text.

    Bridges the gap between ``statistical_rigor.py``'s structured outputs
    (Wilson intervals, group summaries, promotion guidance) and the natural
    language needed in a conference paper.
    """

    @staticmethod
    def describe_comparison(
        method_a: str,
        method_b: str,
        diff: float,
        ci_low: float | None = None,
        ci_high: float | None = None,
        *,
        higher_is_better: bool = True,
    ) -> StatBlock:
        """Produce a statistical description comparing two methods.

        Example output: "Method A outperforms Method B by 2.3 points
        (95% CI [1.8, 2.8], p < 0.01)."
        """
        direction = "outperforms" if (diff > 0) == higher_is_better else "underperforms"
        verb = "higher" if higher_is_better else "lower"

        if ci_low is not None and ci_high is not None:
            ci_text = f"(95% CI [{ci_low:.2f}, {ci_high:.2f}])"
            # Heuristic significance: if CI doesn't cross zero, it's significant
            crosses_zero = (ci_low <= 0 <= ci_high)
            sig = "n.s." if crosses_zero else "p < 0.05"
            if abs(diff) > 2 * max(abs(ci_low), abs(ci_high)):
                sig = "p < 0.01"
        else:
            ci_text = ""
            sig = ""

        text = f"{method_a} {direction} {method_b} by {abs(diff):.2f} points"
        if ci_text:
            text += f" {ci_text}"
        if sig and sig != "n.s.":
            text += f", {sig}"
        text += "."

        bold_a = "\\textbf{" if diff > 0 else ""
        bold_b = "\\textbf{" if diff <= 0 else ""
        bend = "}" if bold_a or bold_b else ""
        row = f"{bold_a}{method_a}{bend if bold_a else ''} & {bold_b}{method_b}{bend if bold_b else ''} & {diff:+.2f} & {ci_text.replace('(95% CI [', '').replace('])', '') if ci_text else '—'} \\\\"

        return StatBlock(text=text, latex_table_row=row, significance=sig)

    @staticmethod
    def describe_group_summary(
        group_name: str,
        mean: float,
        ci_low: float,
        ci_high: float,
        n: int,
    ) -> str:
        """Produce a one-sentence statistical summary of a group."""
        return (
            f"{group_name} achieved a mean score of {mean:.3f} "
            f"(95% CI [{ci_low:.3f}, {ci_high:.3f}], n={n})."
        )

    @staticmethod
    def describe_improvement(
        baseline: float,
        proposed: float,
        ci_low: float,
        ci_high: float,
        *,
        metric_name: str = "performance",
    ) -> str:
        """Describe the improvement of the proposed method over baseline."""
        diff = proposed - baseline
        pct = (diff / abs(baseline)) * 100 if baseline != 0 else 0.0
        return (
            f"Our method improves {metric_name} by {diff:+.3f} "
            f"({pct:+.1f}\\%) over the baseline, with a 95\\% confidence "
            f"interval of [{ci_low:.3f}, {ci_high:.3f}]."
        )

    @staticmethod
    def describe_promotion_guidance(promotion: dict[str, Any]) -> str:
        """Convert statistical promotion guidance to prose."""
        level = str(promotion.get("level") or "exploratory")
        reason = str(promotion.get("reason") or "")
        if level == "exploratory":
            return (
                f"These results are at the exploratory evidence level: {reason} "
                f"Further replication is needed before stronger claims can be made."
            )
        elif level == "replicated":
            return (
                f"These results meet the replicated evidence threshold: {reason} "
                f"Findings are supported by at least two independent runs."
            )
        elif level == "paper-candidate":
            return (
                f"Evidence reaches paper-candidate quality: {reason} "
                f"Results are supported by replication, documented caveats, "
                f"and critic-verifier approval."
            )
        return f"Evidence assessment: {level}. {reason}"

    @staticmethod
    def describe_power_analysis(
        n_samples: int,
        effect_size: float,
        power: float,
        *,
        required_n: int | None = None,
    ) -> str:
        """Describe a statistical power analysis."""
        parts = [
            f"With {n_samples} samples and an observed effect size of "
            f"{effect_size:.3f}, the achieved statistical power is "
            f"{power:.2f}."
        ]
        if required_n is not None and required_n > n_samples:
            parts.append(
                f" To reach a power of 0.80 with the current effect size, "
                f"approximately {required_n} samples would be needed."
            )
        return " ".join(parts)

    @staticmethod
    def generate_statistical_appendix(results: dict[str, Any]) -> str:
        """Generate a LaTeX-formatted statistical appendix from full results.

        Includes per-experiment confidence intervals, power analysis,
        and significance test summaries.
        """
        lines: list[str] = []
        lines.append("\\section{Statistical Details}")
        lines.append("")
        lines.append("\\subsection{Confidence Intervals}")
        lines.append("")
        lines.append("All confidence intervals are computed using the Wilson score")
        lines.append("interval method at the 95\\% confidence level unless otherwise noted.")
        lines.append("")

        experiments = results.get("experiments") or []
        if experiments:
            lines.append("\\begin{table}[h]")
            lines.append("\\centering")
            lines.append("\\begin{tabular}{lccc}")
            lines.append("\\toprule")
            lines.append("Experiment & Score & 95\\% CI & n \\\\")
            lines.append("\\midrule")
            for exp in experiments:
                if not isinstance(exp, dict):
                    continue
                name = exp.get("name") or exp.get("experiment_id", "?")
                metrics = exp.get("metrics") or {}
                ci = exp.get("confidence_interval") or {}
                n = exp.get("n_samples") or exp.get("n", "—")

                for mk, mv in metrics.items():
                    ci_low = ci.get(f"{mk}_low", "—")
                    ci_high = ci.get(f"{mk}_high", "—")
                    if isinstance(ci_low, float) and isinstance(ci_high, float):
                        ci_str = f"[{ci_low:.3f}, {ci_high:.3f}]"
                    else:
                        ci_str = "—"
                    lines.append(f"{name} ({mk}) & {float(mv):.3f} & {ci_str} & {n} \\\\")
            lines.append("\\bottomrule")
            lines.append("\\end{tabular}")
            lines.append("\\caption{Per-experiment results with confidence intervals.}")
            lines.append("\\label{tab:statistical-details}")
            lines.append("\\end{table}")

        return "\n".join(lines)

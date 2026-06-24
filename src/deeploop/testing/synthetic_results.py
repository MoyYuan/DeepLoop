"""Synthetic experiment results for paper pipeline testing.

Generates realistic-but-fake experiment data (learning curves, comparison
tables, ablation results, statistical analyses) so the paper generation
pipeline can be tested end-to-end without requiring real GPU experiments.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any


class SyntheticExperimentResults:
    """Generates realistic synthetic experiment data for paper testing.

    The generated data looks indistinguishable from real results to a
    casual reader — learning curves have plausible sigmoid shapes with
    noise, comparison tables show reasonable margins, and ablation
    studies demonstrate consistent component contributions.
    """

    def __init__(self, *, seed: int = 42):
        self._rng = random.Random(seed)

    def generate(self, *, num_experiments: int = 8, num_baselines: int = 4) -> dict[str, Any]:
        """Generate a complete set of synthetic experiment results.

        Returns a dict suitable for passing to
        :func:`deeploop.paper.generator.generate_paper` as
        *experiment_results*.
        """
        experiments = []
        base_metric = self._rng.uniform(0.70, 0.76)
        best_metric = base_metric
        for i in range(num_experiments):
            is_best = i == len(range(num_experiments)) - 2  # penultimate is best
            if is_best:
                metric = base_metric + self._rng.uniform(0.06, 0.10)
            else:
                delta = self._rng.uniform(-0.02, 0.04)
                metric = min(0.98, max(0.60, base_metric + delta * (i + 1) / num_experiments))
            best_metric = max(best_metric, metric)
            experiments.append({
                "experiment_id": f"exp-{i + 1:02d}",
                "name": f"Experiment {i + 1}",
                "status": "completed",
                "metrics": {"accuracy": round(metric, 4)},
                "confidence_interval": {
                    "accuracy_low": round(metric - 0.015, 4),
                    "accuracy_high": round(metric + 0.015, 4),
                },
                "n_samples": 3,
                "plan": f"Experiment {i + 1}: testing improved configuration." if i > 0 else "Baseline configuration.",
            })

        # Learning curves: sigmoid with noise
        curves = {}
        for label, final, noise in [("Training", best_metric, 0.01), ("Validation", best_metric - 0.03, 0.02)]:
            curve = []
            for step in range(20):
                progress = step / 19
                sigmoid = 1.0 / (1.0 + math.exp(-12 * (progress - 0.4)))
                value = final * sigmoid + self._rng.gauss(0, noise)
                curve.append(round(max(0.01, value), 4))
            curves[label] = curve
        curves["Baseline"] = [round(best_metric * 0.85 + self._rng.gauss(0, 0.01), 4) for _ in range(20)]

        # Comparison against baselines
        comparisons = {}
        baseline_methods = [
            ("Vanilla Baseline", best_metric - self._rng.uniform(0.06, 0.12)),
            ("Method A (2024)", best_metric - self._rng.uniform(0.03, 0.07)),
            ("Method B (2023)", best_metric - self._rng.uniform(0.08, 0.15)),
            ("Method C (2024)", best_metric - self._rng.uniform(0.02, 0.05)),
        ]
        for name, score in baseline_methods:
            comparisons[name] = {
                "value": round(max(0.60, score), 4),
                "std": round(self._rng.uniform(0.005, 0.020), 4),
            }
        comparisons["Our Method"] = {
            "value": round(best_metric, 4),
            "std": round(self._rng.uniform(0.003, 0.010), 4),
        }

        # Ablation study
        ablations = [
            {"component": "Full method", "delta": 0.0},
            {"component": "- Component A", "delta": round(-self._rng.uniform(0.02, 0.05), 4)},
            {"component": "- Component B", "delta": round(-self._rng.uniform(0.01, 0.03), 4)},
            {"component": "- Component C", "delta": round(-self._rng.uniform(0.03, 0.06), 4)},
            {"component": "- All components", "delta": round(-self._rng.uniform(0.06, 0.12), 4)},
        ]

        return {
            "experiments": experiments,
            "learning_curves": curves,
            "comparisons": comparisons,
            "ablations": ablations,
            "baselines": [b[0] for b in baseline_methods],
            "method_summary": (
                "Our method combines automated experiment design with "
                "structured hyperparameter optimization, achieving "
                f"{best_metric:.1%} accuracy on the benchmark task."
            ),
            "what_worked": (
                "Systematic exploration of the hyperparameter space yielded "
                f"a {best_metric - base_metric:+.1%} improvement over the baseline. "
                "The tree search strategy effectively identified promising "
                "configurations while avoiding local optima."
            ),
            "failure_modes": [
                "Occasional OOM on larger batch sizes — automatically recovered.",
                "2 of 10 experiments produced degenerate results due to "
                "inappropriate learning rate initialization.",
            ],
            "caveats": (
                "Results are limited to the CIFAR-10 benchmark. "
                "Generalization to other domains requires further validation. "
                "Experiments were run on a single GPU within a 2-hour budget."
            ),
        }

    def write(self, path: Path | str) -> Path:
        """Generate results and write them to a JSON file."""
        data = self.generate()
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return output


def generate_synthetic_statistical_report(experiment_results: dict[str, Any]) -> dict[str, Any]:
    """Generate a synthetic statistical report that matches the experiment results.

    This can be passed as *statistical_report* to ``generate_paper``.
    """
    experiments = experiment_results.get("experiments") or []
    comparisons = experiment_results.get("comparisons") or {}

    # Per-experiment CI
    exp_stats: dict[str, dict[str, Any]] = {}
    for exp in experiments:
        eid = exp.get("experiment_id", "unknown")
        metrics = exp.get("metrics") or {}
        ci = exp.get("confidence_interval") or {}
        exp_stats[eid] = {
            "mean": metrics,
            "confidence_interval": ci,
            "n": exp.get("n_samples", 3),
        }

    # Group comparisons with Wilson intervals
    comparison_stats: dict[str, dict[str, Any]] = {}
    best_val = max(
        (v.get("value", 0) if isinstance(v, dict) else v)
        for v in comparisons.values()
    )
    for method, data in comparisons.items():
        value = data.get("value", 0) if isinstance(data, dict) else data
        std = data.get("std", 0.015) if isinstance(data, dict) else 0.015
        is_best = abs(value - best_val) < 0.001
        comparison_stats[method] = {
            "value": value,
            "std": std,
            "confidence_interval": {
                "low": round(value - 1.96 * std, 4),
                "high": round(value + 1.96 * std, 4),
            },
            "is_best": is_best,
        }

    return {
        "significance": (
            "Our method significantly outperforms all baselines "
            f"(p < 0.05, Wilson score intervals)."
        ),
        "final_verdict": "Evidence meets paper-candidate quality.",
        "experiments": exp_stats,
        "comparisons": comparison_stats,
    }

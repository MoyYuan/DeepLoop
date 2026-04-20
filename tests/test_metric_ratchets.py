from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.runtime.metric_ratchets import MetricRatchetConfig, build_metric_ratchet_decision, metric_map


class MetricRatchetTests(unittest.TestCase):
    def test_metric_map_reads_top_level_and_nested_metrics(self) -> None:
        self.assertEqual(metric_map({"accuracy": 0.7, "loss": 0.3, "ignored": "x"}), {"accuracy": 0.7, "loss": 0.3})
        self.assertEqual(metric_map({"metrics": {"accuracy": 0.8, "loss": 0.2}}), {"accuracy": 0.8, "loss": 0.2})

    def test_ratchet_selects_best_anchor_and_keeps_candidate(self) -> None:
        config = MetricRatchetConfig(
            primary_metric="accuracy",
            higher_is_better=True,
            min_improvement=0.02,
            max_allowed_regression=0.02,
            guardrail_metrics=("loss",),
            route_on_keep="replication",
            route_on_discard="experiment-design",
        )

        decision = build_metric_ratchet_decision(
            config,
            candidate_metrics={"accuracy": 0.72, "loss": 0.31},
            anchors={
                "baseline": {"accuracy": 0.61, "loss": 0.42},
                "intervention": {"accuracy": 0.66, "loss": 0.37},
            },
        )

        self.assertEqual(decision["decision"], "keep")
        self.assertEqual(decision["anchor_label"], "intervention")
        self.assertEqual(decision["route_to"], "replication")
        self.assertEqual(decision["scores"]["candidate"], 0.72)

    def test_ratchet_discards_when_guardrail_regresses_beyond_threshold(self) -> None:
        config = MetricRatchetConfig(
            primary_metric="accuracy",
            higher_is_better=True,
            min_improvement=0.02,
            max_allowed_regression=0.01,
            guardrail_metrics=("loss",),
            route_on_keep="replication",
            route_on_discard="experiment-design",
        )

        decision = build_metric_ratchet_decision(
            config,
            candidate_metrics={"accuracy": 0.72, "loss": 0.40},
            anchors={
                "baseline": {"accuracy": 0.61, "loss": 0.42},
                "intervention": {"accuracy": 0.66, "loss": 0.31},
            },
        )

        self.assertEqual(decision["decision"], "discard")
        self.assertEqual(decision["route_to"], "experiment-design")
        self.assertGreater(decision["guardrails"]["loss"]["regression"], 0.01)


if __name__ == "__main__":
    unittest.main()

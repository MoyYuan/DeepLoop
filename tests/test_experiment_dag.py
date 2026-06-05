"""Tests for deeploop.research.experiment_dag.ExperimentDAG."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.experiment_dag import CycleError, ExperimentDAG, ExperimentVertex


class ExperimentDAGTests(unittest.TestCase):
    """Test ExperimentDAG."""

    def setUp(self):
        self.dag = ExperimentDAG()

    # ------------------------------------------------------------------
    # add_experiment
    # ------------------------------------------------------------------

    def test_add_experiment_adds_vertex(self):
        """add_experiment creates a vertex and stores it."""
        v = self.dag.add_experiment("exp1")
        self.assertIn("exp1", self.dag.vertices)
        self.assertIsInstance(v, ExperimentVertex)
        self.assertEqual(v.experiment_id, "exp1")
        self.assertEqual(v.status, "running")

    def test_add_experiment_with_parents(self):
        """add_experiment links to existing parents."""
        self.dag.add_experiment("parent1")
        v = self.dag.add_experiment("child1", parent_ids=["parent1"])
        self.assertEqual(v.parent_ids, ["parent1"])

    def test_add_experiment_duplicate_raises(self):
        """add_experiment raises ValueError for duplicate ID."""
        self.dag.add_experiment("exp1")
        with self.assertRaises(ValueError):
            self.dag.add_experiment("exp1")

    def test_add_experiment_unknown_parent_raises(self):
        """add_experiment raises ValueError for unknown parent."""
        with self.assertRaises(ValueError):
            self.dag.add_experiment("orphan", parent_ids=["unknown"])

    def test_add_experiment_with_kwargs(self):
        """add_experiment forwards kwargs to the vertex."""
        v = self.dag.add_experiment(
            "exp1", status="completed", metrics={"acc": 0.9}
        )
        self.assertEqual(v.status, "completed")
        self.assertEqual(v.metrics, {"acc": 0.9})

    # ------------------------------------------------------------------
    # update_result
    # ------------------------------------------------------------------

    def test_update_result_updates_status_and_metrics(self):
        """update_result modifies status and merges metrics."""
        self.dag.add_experiment("exp1")
        self.dag.update_result("exp1", "completed", {"accuracy": 0.95})
        v = self.dag.vertices["exp1"]
        self.assertEqual(v.status, "completed")
        self.assertEqual(v.metrics["accuracy"], 0.95)

    def test_update_result_raises_for_unknown(self):
        """update_result raises KeyError for unknown experiment."""
        with self.assertRaises(KeyError):
            self.dag.update_result("unknown", "completed", {})

    def test_update_result_invalid_status_raises(self):
        """update_result raises ValueError for invalid status."""
        self.dag.add_experiment("exp1")
        with self.assertRaises(ValueError):
            self.dag.update_result("exp1", "invalid_status", {})

    # ------------------------------------------------------------------
    # get_sota
    # ------------------------------------------------------------------

    def test_get_sota_higher_is_better(self):
        """get_sota returns the completed experiment with highest metric."""
        self.dag.add_experiment("exp1")
        self.dag.add_experiment("exp2")
        self.dag.update_result("exp1", "completed", {"accuracy": 0.8})
        self.dag.update_result("exp2", "completed", {"accuracy": 0.95})
        sota = self.dag.get_sota("accuracy", higher_is_better=True)
        self.assertIsNotNone(sota)
        self.assertEqual(sota.experiment_id, "exp2")  # type: ignore[union-attr]

    def test_get_sota_lower_is_better(self):
        """get_sota returns the completed experiment with lowest metric."""
        self.dag.add_experiment("exp1")
        self.dag.add_experiment("exp2")
        self.dag.update_result("exp1", "completed", {"loss": 0.2})
        self.dag.update_result("exp2", "completed", {"loss": 0.05})
        sota = self.dag.get_sota("loss", higher_is_better=False)
        self.assertIsNotNone(sota)
        self.assertEqual(sota.experiment_id, "exp2")  # type: ignore[union-attr]

    def test_get_sota_skips_non_completed(self):
        """get_sota only considers completed experiments."""
        self.dag.add_experiment("running_exp")
        self.dag.add_experiment("failed_exp")
        self.dag.update_result("failed_exp", "failed", {"accuracy": 0.9})
        self.dag.add_experiment("completed_exp")
        self.dag.update_result("completed_exp", "completed", {"accuracy": 0.7})
        sota = self.dag.get_sota("accuracy")
        self.assertEqual(sota.experiment_id, "completed_exp")

    def test_get_sota_empty_dag(self):
        """get_sota returns None for an empty DAG."""
        sota = self.dag.get_sota("accuracy")
        self.assertIsNone(sota)

    def test_get_sota_no_completed(self):
        """get_sota returns None when no completed experiments have the metric."""
        self.dag.add_experiment("exp1")
        sota = self.dag.get_sota("accuracy")
        self.assertIsNone(sota)

    # ------------------------------------------------------------------
    # lineage
    # ------------------------------------------------------------------

    def test_lineage_returns_ancestors(self):
        """lineage returns the ancestor chain root-first."""
        self.dag.add_experiment("A")
        self.dag.add_experiment("B", parent_ids=["A"])
        self.dag.add_experiment("C", parent_ids=["B"])
        lineage = self.dag.lineage("C")
        self.assertEqual(len(lineage), 3)
        self.assertEqual(lineage[0].experiment_id, "A")
        self.assertEqual(lineage[1].experiment_id, "B")
        self.assertEqual(lineage[2].experiment_id, "C")

    def test_lineage_single_node(self):
        """lineage returns [node] for a root node."""
        self.dag.add_experiment("A")
        lineage = self.dag.lineage("A")
        self.assertEqual(len(lineage), 1)
        self.assertEqual(lineage[0].experiment_id, "A")

    def test_lineage_raises_for_unknown(self):
        """lineage raises KeyError for unknown experiment."""
        with self.assertRaises(KeyError):
            self.dag.lineage("unknown")

    # ------------------------------------------------------------------
    # descendants
    # ------------------------------------------------------------------

    def test_descendants_returns_all_children(self):
        """descendants returns all nodes that descend from the given node."""
        self.dag.add_experiment("A")
        self.dag.add_experiment("B", parent_ids=["A"])
        self.dag.add_experiment("C", parent_ids=["A"])
        self.dag.add_experiment("D", parent_ids=["B"])
        desc = self.dag.descendants("A")
        desc_ids = {v.experiment_id for v in desc}
        self.assertIn("B", desc_ids)
        self.assertIn("C", desc_ids)
        self.assertIn("D", desc_ids)
        self.assertNotIn("A", desc_ids)

    def test_descendants_no_children(self):
        """descendants returns empty list for a leaf node."""
        self.dag.add_experiment("A")
        self.assertEqual(self.dag.descendants("A"), [])

    def test_descendants_raises_for_unknown(self):
        """descendants raises KeyError for unknown experiment."""
        with self.assertRaises(KeyError):
            self.dag.descendants("unknown")

    # ------------------------------------------------------------------
    # Cycle detection
    # ------------------------------------------------------------------

    def test_cycle_detection_via_duplicate(self):
        """Adding A->B and then re-adding A->B-A cycle raises ValueError."""
        self.dag.add_experiment("A")
        self.dag.add_experiment("B", parent_ids=["A"])
        # Adding A again with B as parent: A already exists -> ValueError
        with self.assertRaises(ValueError):
            self.dag.add_experiment("A", parent_ids=["B"])

    def test_cycle_detection_internal(self):
        """_would_create_cycle correctly identifies ancestor relationships."""
        self.dag.add_experiment("A")
        self.dag.add_experiment("B", parent_ids=["A"])
        # B can reach A via parent edges
        self.assertTrue(self.dag._would_create_cycle("B", "A"))
        # A cannot reach B via parent edges (A has no parents)
        self.assertFalse(self.dag._would_create_cycle("A", "B"))

    def test_cycle_error_type(self):
        """CycleError is a subclass of ValueError."""
        self.assertTrue(issubclass(CycleError, ValueError))

    # ------------------------------------------------------------------
    # summary
    # ------------------------------------------------------------------

    def test_summary_returns_non_empty_string(self):
        """summary() returns a non-empty string."""
        self.dag.add_experiment("A")
        result = self.dag.summary()
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_summary_includes_status(self):
        """summary() includes vertex status."""
        self.dag.add_experiment("A")
        result = self.dag.summary()
        self.assertIn("running", result)

    def test_summary_empty_dag(self):
        """summary() returns a marker string for empty DAG."""
        result = self.dag.summary()
        self.assertEqual(result, "_Empty DAG_")

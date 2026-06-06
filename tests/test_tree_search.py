"""Tests for deeploop.research.tree_search.ExperimentTree."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.research.tree_search import ExperimentNode, ExperimentTree


class ExperimentTreeTests(unittest.TestCase):
    """Test ExperimentTree and ExperimentNode."""

    def setUp(self):
        self.tree = ExperimentTree(
            root_code="print('hello')",
            root_plan="Initial experiment",
        )

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def test_root_exists(self):
        """Tree initializes with a root node."""
        self.assertIn(self.tree.root_id, self.tree.nodes)
        self.assertIsInstance(self.tree.nodes[self.tree.root_id], ExperimentNode)
        self.assertEqual(
            self.tree.nodes[self.tree.root_id].code, "print('hello')"
        )
        self.assertIsNone(self.tree.nodes[self.tree.root_id].metric)
        self.assertFalse(self.tree.nodes[self.tree.root_id].is_buggy)

    # ------------------------------------------------------------------
    # draft
    # ------------------------------------------------------------------

    def test_draft_adds_new_root_level_node(self):
        """draft() creates a new root-level node with no parent."""
        nid = self.tree.draft(code="print('draft')", plan="New hypothesis")
        self.assertIn(nid, self.tree.nodes)
        node = self.tree.nodes[nid]
        self.assertIsNone(node.parent_id)
        self.assertEqual(node.code, "print('draft')")
        self.assertEqual(node.plan, "New hypothesis")

    def test_draft_does_not_link_to_root(self):
        """draft() nodes are independent of the original root."""
        nid = self.tree.draft(code="x", plan="y")
        self.assertIsNone(self.tree.nodes[nid].parent_id)
        self.assertNotEqual(nid, self.tree.root_id)

    # ------------------------------------------------------------------
    # improve
    # ------------------------------------------------------------------

    def test_improve_adds_child_with_correct_parent(self):
        """improve() creates a child node linked to the given parent."""
        child_id = self.tree.improve(
            parent_id=self.tree.root_id,
            code="print('improved')",
            plan="Improvement",
            metric=0.85,
        )
        self.assertIn(child_id, self.tree.nodes)
        child = self.tree.nodes[child_id]
        self.assertEqual(child.parent_id, self.tree.root_id)
        self.assertEqual(child.metric, 0.85)
        self.assertFalse(child.is_buggy)
        # Parent's children list updated
        self.assertIn(child_id, self.tree.nodes[self.tree.root_id].children)

    def test_improve_records_metric(self):
        """improve() stores the metric on the child node."""
        child_id = self.tree.improve(
            parent_id=self.tree.root_id,
            code="c",
            plan="p",
            metric=0.95,
        )
        self.assertEqual(self.tree.nodes[child_id].metric, 0.95)

    def test_improve_unknown_parent_raises_key_error(self):
        """improve() raises KeyError for non-existent parent."""
        with self.assertRaises(KeyError):
            self.tree.improve(
                parent_id="nonexistent",
                code="c",
                plan="p",
                metric=0.5,
            )

    # ------------------------------------------------------------------
    # debug
    # ------------------------------------------------------------------

    def test_debug_adds_child_with_is_buggy_false(self):
        """debug() creates a non-buggy child from a buggy parent."""
        # Mark root as buggy first
        self.tree.nodes[self.tree.root_id].is_buggy = True
        fix_id = self.tree.debug(
            parent_id=self.tree.root_id,
            code="print('fixed')",
            plan="Bug fix",
        )
        self.assertIn(fix_id, self.tree.nodes)
        child = self.tree.nodes[fix_id]
        self.assertEqual(child.parent_id, self.tree.root_id)
        # The fix itself is NOT buggy
        self.assertFalse(child.is_buggy)

    def test_debug_sets_correct_parent(self):
        """debug() creates a child with the given parent."""
        nid = self.tree.draft(code="buggy", plan="buggy draft")
        self.tree.nodes[nid].is_buggy = True
        fix_id = self.tree.debug(parent_id=nid, code="fix", plan="fix")
        self.assertEqual(self.tree.nodes[fix_id].parent_id, nid)

    def test_debug_unknown_parent_raises_key_error(self):
        """debug() raises KeyError for non-existent parent."""
        with self.assertRaises(KeyError):
            self.tree.debug(
                parent_id="nonexistent",
                code="c",
                plan="p",
            )

    # ------------------------------------------------------------------
    # best_node
    # ------------------------------------------------------------------

    def test_best_node_returns_highest_metric_non_buggy(self):
        """best_node() returns the non-buggy node with highest metric."""
        n1 = self.tree.improve(self.tree.root_id, "c1", "p1", metric=0.7)
        n2 = self.tree.improve(self.tree.root_id, "c2", "p2", metric=0.9)
        n3 = self.tree.improve(self.tree.root_id, "c3", "p3", metric=0.5)
        # Mark n3 as buggy
        self.tree.nodes[n3].is_buggy = True

        best = self.tree.best_node()
        self.assertIsNotNone(best)
        self.assertEqual(best.node_id, n2)  # type: ignore[union-attr]
        self.assertEqual(best.metric, 0.9)  # type: ignore[union-attr]

    def test_best_node_empty_tree(self):
        """best_node() returns None when no evaluated non-buggy nodes exist."""
        # Root has metric=None, so it's not a candidate
        self.assertIsNone(self.tree.best_node())

    def test_best_node_skips_buggy(self):
        """best_node() ignores buggy nodes even if they have high metrics."""
        self.tree.nodes[self.tree.root_id].is_buggy = True
        self.tree.nodes[self.tree.root_id].metric = 0.99
        self.assertIsNone(self.tree.best_node())

    # ------------------------------------------------------------------
    # select_next
    # ------------------------------------------------------------------

    def test_select_next_improve_best_when_debug_prob_zero(self):
        """select_next with debug_probability=0 returns best node + improve."""
        tree = ExperimentTree(root_code="r", root_plan="r", num_drafts=1)
        child = tree.improve(
            tree.root_id, "c", "p", metric=0.8,
        )
        node_id, operation = tree.select_next(debug_probability=0.0)
        self.assertEqual(node_id, child)
        self.assertEqual(operation, "improve")

    def test_select_next_debug_when_buggy_and_prob_one(self):
        """select_next with debug_probability=1 returns buggy node + debug."""
        tree = ExperimentTree(root_code="r", root_plan="r", num_drafts=1)
        tree.nodes[tree.root_id].is_buggy = True
        tree.nodes[tree.root_id].metric = 0.3
        tree.improve(
            tree.root_id, "good", "good plan", metric=0.9,
        )
        # There is a buggy node and debug_probability=1.0
        node_id, operation = tree.select_next(debug_probability=1.0)
        self.assertEqual(node_id, tree.root_id)
        self.assertEqual(operation, "debug")

    def test_select_next_draft_when_no_candidates(self):
        """select_next returns draft when no suitable nodes exist."""
        node_id, operation = self.tree.select_next()
        # Root has no metric, no buggy nodes -> returns draft
        self.assertEqual(node_id, "")
        self.assertEqual(operation, "draft")

    # ------------------------------------------------------------------
    # higher_is_better
    # ------------------------------------------------------------------

    def test_best_node_higher_is_better_true(self):
        """With higher_is_better=True (default), best_node returns highest metric."""
        n1 = self.tree.improve(self.tree.root_id, "c1", "p1", metric=0.7)
        n2 = self.tree.improve(self.tree.root_id, "c2", "p2", metric=0.9)
        n3 = self.tree.improve(self.tree.root_id, "c3", "p3", metric=0.5)
        best = self.tree.best_node()
        self.assertIsNotNone(best)
        self.assertEqual(best.node_id, n2)  # type: ignore[union-attr]

    def test_best_node_higher_is_better_false(self):
        """With higher_is_better=False, best_node returns lowest metric."""
        tree = ExperimentTree(
            root_code="print('loss')", root_plan="Loss minimization",
            higher_is_better=False, num_drafts=1,
        )
        n1 = tree.improve(tree.root_id, "c1", "p1", metric=0.7)
        n2 = tree.improve(tree.root_id, "c2", "p2", metric=0.3)
        n3 = tree.improve(tree.root_id, "c3", "p3", metric=0.5)
        best = tree.best_node()
        self.assertIsNotNone(best)
        self.assertEqual(best.node_id, n2)  # type: ignore[union-attr]
        self.assertEqual(best.metric, 0.3)  # type: ignore[union-attr]

    def test_best_buggy_node_higher_is_better_false(self):
        """With higher_is_better=False, _best_buggy_node selects lowest metric."""
        tree = ExperimentTree(
            root_code="print('loss')", root_plan="Loss minimization",
            higher_is_better=False,
        )
        tree.nodes[tree.root_id].is_buggy = True
        tree.nodes[tree.root_id].metric = 0.9
        n1 = tree.draft(code="d1", plan="d1")
        tree.nodes[n1].is_buggy = True
        tree.nodes[n1].metric = 0.3
        n2 = tree.draft(code="d2", plan="d2")
        tree.nodes[n2].is_buggy = True
        tree.nodes[n2].metric = 0.5
        buggy = tree._best_buggy_node()
        self.assertIsNotNone(buggy)
        # Lowest metric among buggy nodes is 0.3
        self.assertEqual(buggy.node_id, n1)  # type: ignore[union-attr]

    def test_tree_with_higher_is_better_false(self):
        """End-to-end test with higher_is_better=False simulates loss minimization."""
        tree = ExperimentTree(
            root_code="print('loss')", root_plan="Initial loss",
            higher_is_better=False, num_drafts=1,
        )
        # Add an improvement with a lower (better) loss
        tree.improve(tree.root_id, "better", "Reduced loss", metric=0.2)
        # Add an improvement with a higher (worse) loss
        tree.improve(tree.root_id, "worse", "Increased loss", metric=0.8)
        best = tree.best_node()
        self.assertIsNotNone(best)
        self.assertEqual(best.metric, 0.2)  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # num_drafts and draft_nodes
    # ------------------------------------------------------------------

    def test_draft_nodes_returns_only_root_nodes(self):
        """draft_nodes property returns nodes with parent_id=None."""
        n1 = self.tree.draft(code="d1", plan="d1")
        n2 = self.tree.draft(code="d2", plan="d2")
        child = self.tree.improve(self.tree.root_id, "c", "p", metric=0.5)
        drafts = self.tree.draft_nodes
        draft_ids = {n.node_id for n in drafts}
        self.assertIn(self.tree.root_id, draft_ids)
        self.assertIn(n1, draft_ids)
        self.assertIn(n2, draft_ids)
        self.assertNotIn(child, draft_ids)
        for n in drafts:
            self.assertIsNone(n.parent_id)

    def test_select_next_forces_drafts_when_below_num_drafts(self):
        """select_next returns ('', 'draft') while draft count < num_drafts."""
        tree = ExperimentTree(root_code="r", root_plan="r", num_drafts=3)
        # Root is 1 draft; 1 < 3 so must draft
        node_id, operation = tree.select_next()
        self.assertEqual(node_id, "")
        self.assertEqual(operation, "draft")
        # Add one more draft: 2 < 3, still must draft
        tree.draft("d1", "d1")
        node_id, operation = tree.select_next()
        self.assertEqual(node_id, "")
        self.assertEqual(operation, "draft")

    def test_select_next_allows_improve_after_num_drafts_reached(self):
        """After creating enough drafts, select_next can return improve."""
        tree = ExperimentTree(root_code="r", root_plan="r", num_drafts=2)
        # Root is draft 1, add one more to reach num_drafts=2
        tree.draft("d1", "d1")
        # Now drafts satisfied; root has no metric, so add an improve
        child = tree.improve(tree.root_id, "c", "p", metric=0.9)
        node_id, operation = tree.select_next(debug_probability=0.0)
        self.assertEqual(node_id, child)
        self.assertEqual(operation, "improve")

    def test_custom_num_drafts(self):
        """Tree with num_drafts=2 forces only 2 drafts before allowing improvement."""
        tree = ExperimentTree(root_code="r", root_plan="r", num_drafts=2)
        # Root is draft 1, need one more to satisfy num_drafts=2
        tree.draft("d1", "d1")
        # Now drafts satisfied; add improve
        child = tree.improve(tree.root_id, "c", "p", metric=0.9)
        node_id, operation = tree.select_next(debug_probability=0.0)
        self.assertEqual(node_id, child)
        self.assertEqual(operation, "improve")
        # Verify there are exactly 2 draft roots
        self.assertEqual(len(tree.draft_nodes), 2)

    # ------------------------------------------------------------------
    # lineage
    # ------------------------------------------------------------------

    def test_lineage_returns_root_to_node_chain(self):
        """lineage() returns nodes from root to the given node."""
        child = self.tree.improve(
            self.tree.root_id, "c1", "p1", metric=0.8,
        )
        grandchild = self.tree.improve(
            child, "c2", "p2", metric=0.9,
        )
        lineage = self.tree.lineage(grandchild)
        self.assertEqual(len(lineage), 3)
        self.assertEqual(lineage[0].node_id, self.tree.root_id)
        self.assertEqual(lineage[1].node_id, child)
        self.assertEqual(lineage[2].node_id, grandchild)

    def test_lineage_single_node(self):
        """lineage() returns [root] for the root node itself."""
        lineage = self.tree.lineage(self.tree.root_id)
        self.assertEqual(len(lineage), 1)
        self.assertEqual(lineage[0].node_id, self.tree.root_id)

    def test_lineage_unknown_node_raises_key_error(self):
        """lineage() raises KeyError for non-existent node_id."""
        with self.assertRaises(KeyError):
            self.tree.lineage("nonexistent")

    # ------------------------------------------------------------------
    # summary
    # ------------------------------------------------------------------

    def test_summary_returns_non_empty_string(self):
        """summary() returns a non-empty string."""
        result = self.tree.summary()
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_summary_includes_node_count(self):
        """summary() includes total node count."""
        self.tree.improve(self.tree.root_id, "c", "p", metric=0.5)
        result = self.tree.summary()
        self.assertIn("2 nodes total", result)

    # ------------------------------------------------------------------
    # __len__ and __contains__
    # ------------------------------------------------------------------

    def test_len_returns_node_count(self):
        """__len__ returns the number of nodes."""
        self.assertEqual(len(self.tree), 1)
        self.tree.draft("c", "p")
        self.assertEqual(len(self.tree), 2)

    def test_contains_checks_node_id(self):
        """__contains__ checks if a node_id exists."""
        self.assertIn(self.tree.root_id, self.tree)
        self.assertNotIn("nonexistent", self.tree)

    # ------------------------------------------------------------------
    # Integration: draft → evaluate → improve cycle
    # ------------------------------------------------------------------

    def test_draft_evaluate_improve_cycle_progresses_metric(self):
        """Full draft→evaluate→improve cycle: best_node metric improves."""
        tree = ExperimentTree("code", "plan", higher_is_better=True, num_drafts=2)
        self.assertIsNone(tree.best_node())

        d1 = tree.draft("d1", "plan1")
        tree.nodes[d1].metric = 0.72
        d2 = tree.draft("d2", "plan2")
        tree.nodes[d2].metric = 0.85

        best = tree.best_node()
        self.assertIsNotNone(best)
        self.assertEqual(best.metric, 0.85)

        improved = tree.improve(best.node_id, "d2++", "improved", metric=0.91)
        self.assertIsNotNone(improved)
        self.assertEqual(tree.best_node().metric, 0.91)
        self.assertEqual(len(tree.nodes), 4)  # root + 2 drafts + 1 improve

    def test_best_node_recognizes_minimization_metric(self):
        """When higher_is_better=False, best_node returns minimum metric."""
        tree = ExperimentTree("code", "plan", higher_is_better=False, num_drafts=2)
        d1 = tree.draft("d1", "p1")
        tree.nodes[d1].metric = 0.5   # lower loss = better
        d2 = tree.draft("d2", "p2")
        tree.nodes[d2].metric = 0.3

        best = tree.best_node()
        self.assertEqual(best.metric, 0.3)

    # ------------------------------------------------------------------
    # Serialization round-trip
    # ------------------------------------------------------------------

    def test_serialize_deserialize_preserves_tree_state(self):
        """Round-trip preserves node count, metrics, and selection."""
        from deeploop.mission.mission_decision_engine import MissionDecisionEngine

        tree = ExperimentTree("c", "p", higher_is_better=True, num_drafts=2)
        d1 = tree.draft("a", "A")
        tree.nodes[d1].metric = 0.5
        d2 = tree.draft("b", "B")
        tree.nodes[d2].metric = 0.8

        data = MissionDecisionEngine._serialize_tree(tree)
        restored = MissionDecisionEngine._deserialize_tree(data)

        self.assertEqual(len(restored.nodes), len(tree.nodes))
        self.assertEqual(restored.higher_is_better, tree.higher_is_better)
        self.assertEqual(restored.num_drafts, tree.num_drafts)
        self.assertIsNotNone(restored.best_node())
        self.assertEqual(restored.best_node().metric, 0.8)
        self.assertEqual(len(restored.draft_nodes), len(tree.draft_nodes))

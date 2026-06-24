"""Best-first tree search over experiment designs, inspired by AIDE's tree search approach.

This module provides data structures and search logic for exploring the space of
experiment code improvements. The search tree maintains parent-child relationships,
tracks which nodes are buggy, and uses a best-first strategy to select the next
promising node for improvement or debugging.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class ExperimentNode:
    """A node in the experiment search tree.

    Attributes:
        node_id: Unique identifier for this node.
        code: Python source code implementing the experiment.
        plan: Natural language description of the design rationale.
        metric: Numeric score from evaluating the experiment, or None if not yet evaluated.
        parent_id: The node_id of this node's parent, or None for root nodes.
        is_buggy: Whether the experiment code failed during evaluation.
        children: Ordered list of child node_ids.
    """

    node_id: str
    code: str
    plan: str
    metric: float | None = None
    parent_id: str | None = None
    is_buggy: bool = False
    children: list[str] = field(default_factory=list)


class ExperimentTree:
    """Best-first search tree for experiment optimization.

    Maintains a directed acyclic graph of experiment nodes where edges represent
    improvement or debugging operations. The tree supports best-first selection:
    always preferring the most promising non-buggy node for further improvement,
    with a configurable probability to debug buggy nodes instead.
    """

    def __init__(self, root_code: str, root_plan: str, *, higher_is_better: bool = True, num_drafts: int = 5, max_debug_depth: int = 3) -> None:
        """Initialize the tree with a single root node.

        Args:
            root_code: Python source code for the initial experiment.
            root_plan: Natural language rationale for the initial design.
            higher_is_better: If True (default), higher metric values are better.
                Set to False for minimization tasks (loss, perplexity, error rate).
            num_drafts: Number of initial root-level drafts to force before any
                improvement or debugging. Ensures exploration diversity (default 5).
            max_debug_depth: Maximum number of consecutive buggy ancestors before
                debugging is skipped for a buggy node (default 3).
        """
        self.nodes: dict[str, ExperimentNode] = {}
        self.higher_is_better = higher_is_better
        self.num_drafts = max(1, num_drafts)
        self.max_debug_depth = max(1, max_debug_depth)
        self.root_id = self._add_node(root_code, root_plan)

    def _generate_node_id(self) -> str:
        """Produce a short unique identifier for a new node."""
        return uuid.uuid4().hex[:12]

    def _add_node(
        self,
        code: str,
        plan: str,
        *,
        parent_id: str | None = None,
        metric: float | None = None,
        is_buggy: bool = False,
    ) -> str:
        """Internal helper to create and register a new node.

        Args:
            code: Python source code for the experiment.
            plan: Natural language design rationale.
            parent_id: Optional parent node identifier.
            metric: Optional numeric evaluation score.
            is_buggy: Whether the experiment failed during evaluation.

        Returns:
            The generated node_id.

        Raises:
            ValueError: If *code* is empty (nodes must have executable code).
        """
        if not code or not code.strip():
            raise ValueError("ExperimentTree: cannot create node with empty code.")
        node_id = self._generate_node_id()
        node = ExperimentNode(
            node_id=node_id,
            code=code,
            plan=plan,
            metric=metric,
            parent_id=parent_id,
            is_buggy=is_buggy,
        )
        self.nodes[node_id] = node
        if parent_id is not None and parent_id in self.nodes:
            self.nodes[parent_id].children.append(node_id)
        return node_id

    def draft(self, code: str, plan: str) -> str:
        """Create a new root-level draft representing a new hypothesis.

        Draft nodes have no parent and serve as independent starting points
        in the search tree.

        Args:
            code: Python source code for the new experiment.
            plan: Natural language rationale for the new design.

        Returns:
            The node_id of the newly created draft node.
        """
        return self._add_node(code, plan, parent_id=None)

    def improve(self, parent_id: str, code: str, plan: str, metric: float) -> str:
        """Create a child node that improves upon a parent.

        The child inherits a numeric metric from the improvement operation.
        The parent is expected to be a non-buggy, evaluated node.

        Args:
            parent_id: The node_id of the node being improved.
            code: Python source code for the improved experiment.
            plan: Natural language description of the improvement.
            metric: Evaluation score for the improved experiment.

        Returns:
            The node_id of the newly created child node.

        Raises:
            KeyError: If parent_id does not exist in the tree.
        """
        if parent_id not in self.nodes:
            raise KeyError(f"Node {parent_id} not found in tree")
        return self._add_node(code, plan, parent_id=parent_id, metric=metric)

    def debug(self, parent_id: str, code: str, plan: str) -> str:
        """Create a child node that fixes a buggy parent.

        The child starts with is_buggy=False and no metric, since it has not
        been evaluated yet.

        Args:
            parent_id: The node_id of the buggy node being fixed.
            code: Python source code for the corrected experiment.
            plan: Natural language description of the fix.

        Returns:
            The node_id of the newly created child node.

        Raises:
            KeyError: If parent_id does not exist in the tree.
        """
        if parent_id not in self.nodes:
            raise KeyError(f"Node {parent_id} not found in tree")
        return self._add_node(code, plan, parent_id=parent_id, is_buggy=False)

    def best_node(self) -> ExperimentNode | None:
        """Return the non-buggy node with the best metric.

        Only considers nodes that have been evaluated (metric is not None)
        and are not marked as buggy. Respects ``higher_is_better``.

        Returns:
            The best-scoring ExperimentNode, or None if no evaluated non-buggy
            nodes exist.
        """
        candidates: list[ExperimentNode] = [
            node
            for node in self.nodes.values()
            if node.metric is not None and not node.is_buggy
        ]
        if not candidates:
            return None
        if self.higher_is_better:
            return max(candidates, key=lambda node: node.metric)  # type: ignore[arg-type]
        return min(candidates, key=lambda node: node.metric)  # type: ignore[arg-type]

    def _best_buggy_node(self) -> ExperimentNode | None:
        """Return the best-metric buggy node, or the most recently added.

        When multiple buggy nodes exist, prefer the one with the best metric
        (respecting ``higher_is_better``) as the most promising to debug.

        Returns:
            A buggy ExperimentNode, or None if no buggy nodes exist.
        """
        buggy = [
            node for node in self.nodes.values() if node.is_buggy
        ]
        if not buggy:
            return None
        evaluated = [n for n in buggy if n.metric is not None]
        if evaluated:
            if self.higher_is_better:
                return max(evaluated, key=lambda n: n.metric)  # type: ignore[arg-type]
            return min(evaluated, key=lambda n: n.metric)  # type: ignore[arg-type]
        return max(buggy, key=lambda n: int(n.node_id, 16))

    @property
    def draft_nodes(self) -> list[ExperimentNode]:
        """Return all root-level draft nodes (nodes with no parent)."""
        return [n for n in self.nodes.values() if n.parent_id is None]

    def _debug_depth(self, node_id: str) -> int:
        """Count consecutive buggy ancestors for a given node.

        Starting from the node's parent, counts how many consecutive
        ancestors are marked as buggy. This measures how many layers
        of debugging have been attempted.

        Args:
            node_id: The identifier of the node to check.

        Returns:
            The number of consecutive buggy ancestors.
        """
        depth = 0
        current_id: str | None = self.nodes[node_id].parent_id
        while current_id is not None and current_id in self.nodes:
            if not self.nodes[current_id].is_buggy:
                break
            depth += 1
            current_id = self.nodes[current_id].parent_id
        return depth

    def select_next(self, debug_probability: float = 0.3) -> tuple[str, str]:
        """Select the next node to work on.

        Uses a best-first strategy with an initial exploration phase:
        - Forces ``num_drafts`` root-level drafts before any improvement/debugging.
        - With probability `debug_probability`, pick a buggy node to debug.
        - Otherwise, pick the best non-buggy node to improve.
        - If no good nodes are available, fall back to the alternative operation.
        - If no suitable nodes exist at all, returns ("", "draft").

        Args:
            debug_probability: Probability (0.0 to 1.0) of choosing to debug
                a buggy node instead of improving the best node.

        Returns:
            A tuple of (node_id, operation) where operation is one of
            ``"improve"``, ``"debug"``, or ``"draft"``.
        """
        import random

        # Exploration phase: force initial drafts for diversity
        if len(self.draft_nodes) < self.num_drafts:
            return ("", "draft")

        best = self.best_node()
        buggy = self._best_buggy_node()

        if best is None and buggy is None:
            return ("", "draft")

        should_debug = (
            buggy is not None
            and self._debug_depth(buggy.node_id) < self.max_debug_depth
            and random.random() < debug_probability
        )

        if should_debug:
            return (buggy.node_id, "debug")  # type: ignore[union-attr]

        if best is not None:
            return (best.node_id, "improve")

        if best is None and buggy is not None and self._debug_depth(buggy.node_id) < self.max_debug_depth:
            return (buggy.node_id, "debug")

        return ("", "draft")

    def lineage(self, node_id: str) -> list[ExperimentNode]:
        """Return the chain of nodes from the root to the specified node.

        Traverses parent references upward until reaching a root node (one with
        no parent or whose parent_id matches root_id).

        Args:
            node_id: The identifier of the target node.

        Returns:
            An ordered list from root to the requested node.

        Raises:
            KeyError: If node_id does not exist in the tree.
        """
        if node_id not in self.nodes:
            raise KeyError(f"Node {node_id} not found in tree")

        path: list[ExperimentNode] = []
        current_id: str | None = node_id
        while current_id is not None and current_id in self.nodes:
            path.append(self.nodes[current_id])
            current_id = self.nodes[current_id].parent_id
        path.reverse()
        return path

    def summary(self) -> str:
        """Produce a human-readable markdown summary of the tree.

        Renders nodes in a tree-like indented format showing parent-child
        relationships, metrics, and buggy status.

        Returns:
            A multi-line string with the tree rendered in markdown.
        """
        if not self.nodes:
            return "*Empty tree*"

        lines: list[str] = ["## Experiment Search Tree\n"]

        def _render_subtree(node_id: str, depth: int) -> None:
            node = self.nodes[node_id]
            indent = "  " * depth
            marker = "-" if depth == 0 else "  -"
            metric_str = (
                f" metric={node.metric:.4f}" if node.metric is not None else ""
            )
            buggy_marker = " [BUGGY]" if node.is_buggy else ""
            lines.append(
                f"{indent}{marker} `{node.node_id}`{buggy_marker}{metric_str}"
            )
            plan_preview = node.plan.split("\n")[0][:120]
            lines.append(f"{indent}    plan: {plan_preview}")
            for child_id in node.children:
                _render_subtree(child_id, depth + 1)

        # Render root nodes (nodes with no parent or whose parent is missing)
        roots = [
            n
            for n in self.nodes.values()
            if n.parent_id is None or n.parent_id not in self.nodes
        ]
        # Ensure deterministic order: root_id first if it exists
        root_order = sorted(roots, key=lambda n: (n.node_id != self.root_id, n.node_id))
        for root in root_order:
            _render_subtree(root.node_id, 0)

        stats = [
            f"\n**{len(self.nodes)} nodes total**",
            f"**{sum(1 for n in self.nodes.values() if n.is_buggy)} buggy**",
            f"**{sum(1 for n in self.nodes.values() if n.metric is not None)} evaluated**",
        ]
        lines.append("".join(stats))
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self.nodes)

    def __contains__(self, node_id: str) -> bool:
        return node_id in self.nodes

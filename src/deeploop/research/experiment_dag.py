"""DAG-based experiment genealogy for SOTA selection and lineage tracking."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ExperimentVertex:
    """A single node in the experiment DAG.

    Attributes
    ----------
    experiment_id:
        Unique identifier for this experiment.
    status:
        One of 'running', 'completed', 'failed'.
    metrics:
        Arbitrary metric-name -> value mapping (used for SOTA selection).
    parent_ids:
        IDs of parent experiments this node derives from.
    timestamp:
        ISO-8601 timestamp string.
    """

    experiment_id: str
    status: str = "running"
    metrics: dict[str, float] = field(default_factory=dict)
    parent_ids: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CycleError(ValueError):
    """Raised when adding an edge would create a cycle in the DAG."""


class ExperimentDAG:
    """DAG tracking experiment genealogy for SOTA selection and lineage.

    Experiments (vertices) can have multiple parents, enabling faithful
    tracking of combined-branch experiments (e.g. merging a hyperparameter
    tuning branch with an architecture change branch).
    """

    def __init__(self) -> None:
        self.vertices: dict[str, ExperimentVertex] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_experiment(
        self,
        exp_id: str,
        parent_ids: list[str] | None = None,
        **kwargs: Any,
    ) -> ExperimentVertex:
        """Register a new experiment vertex.

        Parameters
        ----------
        exp_id:
            Unique identifier for the experiment.
        parent_ids:
            Zero or more parent experiment IDs (must already exist).
        **kwargs:
            Additional fields forwarded to the ``ExperimentVertex``
            constructor (e.g. ``status``, ``metrics``, ``timestamp``).

        Returns
        -------
        The newly created ``ExperimentVertex``.

        Raises
        ------
        ValueError
            If *exp_id* already exists, if any *parent_ids* are unknown,
            or if adding the edge would create a cycle.
        """
        if exp_id in self.vertices:
            raise ValueError(f"Experiment '{exp_id}' already exists in the DAG.")

        resolved_parents = list(parent_ids) if parent_ids is not None else []

        # Validate that all parents exist
        missing = [pid for pid in resolved_parents if pid not in self.vertices]
        if missing:
            raise ValueError(
                f"Cannot add experiment '{exp_id}': unknown parent(s): {missing}"
            )

        # Cycle detection: adding exp_id with these parents must not
        # create a cycle.  We check that none of the parents can reach
        # exp_id (which is trivially true since exp_id is new) AND that
        # no descendant of exp_id would become an ancestor of itself.
        # Since exp_id is new it has no descendants yet, so we only
        # need to verify that exp_id is not reachable from itself via
        # the proposed parents (impossible for a new node).  However,
        # we *also* need to verify that none of the proposed parents
        # already has exp_id in its transitive ancestor chain … which
        # again is impossible for a new node.
        #
        # The real cycle check is for *future* edges, but since we
        # enforce acyclicity on every add_experiment call, the graph
        # is always a DAG after each operation.  So we just validate
        # that the new vertex does not create a cycle — which is
        # automatically satisfied for a new sink node with existing
        # ancestors.  We perform a BFS from each proposed parent to
        # confirm we never reach exp_id (belt-and-suspenders).
        for pid in resolved_parents:
            if self._would_create_cycle(pid, exp_id):
                raise CycleError(
                    f"Adding experiment '{exp_id}' with parent '{pid}' "
                    f"would create a cycle in the DAG."
                )

        vertex = ExperimentVertex(
            experiment_id=exp_id,
            parent_ids=resolved_parents,
            **kwargs,
        )
        self.vertices[exp_id] = vertex
        return vertex

    def update_result(
        self,
        exp_id: str,
        status: str,
        metrics: dict[str, float],
    ) -> None:
        """Update an experiment's status and metrics after completion.

        Parameters
        ----------
        exp_id:
            Experiment to update.
        status:
            New status ('completed' or 'failed').
        metrics:
            Metric values to merge into the vertex.
        """
        if exp_id not in self.vertices:
            raise KeyError(f"Experiment '{exp_id}' not found in the DAG.")
        vertex = self.vertices[exp_id]
        valid_statuses = {"running", "completed", "failed"}
        if status not in valid_statuses:
            raise ValueError(
                f"Invalid status '{status}'; must be one of {valid_statuses}"
            )
        vertex.status = status
        vertex.metrics.update(metrics)

    def get_sota(
        self,
        metric: str,
        higher_is_better: bool = True,
    ) -> ExperimentVertex | None:
        """Return the state-of-the-art experiment by *metric*.

        Traverses all **completed** experiments in the DAG and returns
        the vertex with the best (highest or lowest) metric value.
        Returns ``None`` when no completed experiment has the requested
        metric.

        Parameters
        ----------
        metric:
            Which metric to compare.
        higher_is_better:
            If *True* (default), higher numeric values are considered
            better; otherwise lower values are better.
        """
        best: ExperimentVertex | None = None
        best_value: float | None = None

        for vertex in self.vertices.values():
            if vertex.status != "completed":
                continue
            value = vertex.metrics.get(metric)
            if value is None:
                continue
            if best is None:
                best = vertex
                best_value = value
            elif higher_is_better and value > best_value:  # type: ignore[operator]
                best = vertex
                best_value = value
            elif not higher_is_better and value < best_value:  # type: ignore[operator]
                best = vertex
                best_value = value

        return best

    def lineage(self, exp_id: str) -> list[ExperimentVertex]:
        """Return the full ancestor chain (breadth-first, root first).

        Parameters
        ----------
        exp_id:
            Starting experiment.

        Returns
        -------
        List of vertices from the earliest ancestors down to *exp_id*.
        """
        if exp_id not in self.vertices:
            raise KeyError(f"Experiment '{exp_id}' not found in the DAG.")

        visited: set[str] = set()
        result: list[ExperimentVertex] = []
        queue: deque[str] = deque()

        # BFS from the starting node upward through parents
        queue.append(exp_id)

        while queue:
            current_id = queue.popleft()
            if current_id in visited:
                continue
            visited.add(current_id)
            current = self.vertices[current_id]
            result.append(current)
            for parent_id in current.parent_ids:
                if parent_id not in visited:
                    queue.append(parent_id)

        # Reverse so earliest ancestors come first, then the node itself last
        result.reverse()
        return result

    def descendants(self, exp_id: str) -> list[ExperimentVertex]:
        """Return all descendants of *exp_id*.

        Parameters
        ----------
        exp_id:
            Root experiment to find descendants of.

        Returns
        -------
        List of vertices that descend from *exp_id*.
        """
        if exp_id not in self.vertices:
            raise KeyError(f"Experiment '{exp_id}' not found in the DAG.")

        # Build reverse-adjacency list (child -> list of parents is
        # already stored; we need parent -> list of children).
        children: dict[str, list[str]] = {}
        for vid, v in self.vertices.items():
            for pid in v.parent_ids:
                children.setdefault(pid, []).append(vid)

        # BFS from the starting node downward
        found: list[ExperimentVertex] = []
        visited: set[str] = set()
        queue: deque[str] = deque([exp_id])
        visited.add(exp_id)

        while queue:
            current_id = queue.popleft()
            for child_id in children.get(current_id, []):
                if child_id not in visited:
                    visited.add(child_id)
                    found.append(self.vertices[child_id])
                    queue.append(child_id)

        return found

    def summary(self) -> str:
        """Render a markdown summary of the DAG with metrics.

        Lines showing the tree structure and per-vertex metrics.
        Does NOT include a leading H1 heading so it can be composed
        into larger documents.
        """
        if not self.vertices:
            return "_Empty DAG_"

        # Build reverse adjacency (parent -> children)
        children: dict[str, list[str]] = {}
        for vid, v in self.vertices.items():
            for pid in v.parent_ids:
                children.setdefault(pid, []).append(vid)

        # Find root nodes (no parents)
        all_parents: set[str] = set()
        for v in self.vertices.values():
            all_parents.update(v.parent_ids)
        roots = sorted(
            vid for vid in self.vertices if vid not in all_parents
        )

        lines: list[str] = []
        for root_id in roots:
            self._render_subtree(lines, root_id, children, depth=0)

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _would_create_cycle(self, start: str, target: str) -> bool:
        """Return True if *target* is reachable from *start* in the DAG.

        Performs a BFS from *start* following parent edges upward.
        """
        visited: set[str] = set()
        queue: deque[str] = deque([start])
        while queue:
            current = queue.popleft()
            if current == target:
                return True
            if current in visited:
                continue
            visited.add(current)
            for pid in self.vertices[current].parent_ids:
                if pid not in visited:
                    queue.append(pid)
        return False

    def _render_subtree(
        self,
        lines: list[str],
        node_id: str,
        children: dict[str, list[str]],
        depth: int,
    ) -> None:
        """Recursively render a node and its children as markdown."""
        vertex = self.vertices[node_id]
        indent = "  " * depth
        prefix = "- " if depth == 0 else "  - " if depth == 1 else "    - "

        # Node line with status and key metrics
        metric_strs: list[str] = []
        for k, v in vertex.metrics.items():
            if isinstance(v, float):
                metric_strs.append(f"{k}={v:.4g}")
            else:
                metric_strs.append(f"{k}={v}")
        metrics_part = f"  [{', '.join(metric_strs)}]" if metric_strs else ""

        lines.append(
            f"{indent}{prefix}`{node_id}`  status={vertex.status}"
            f"{metrics_part}"
        )

        for child_id in sorted(children.get(node_id, [])):
            self._render_subtree(lines, child_id, children, depth + 1)

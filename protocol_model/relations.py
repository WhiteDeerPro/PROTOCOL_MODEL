"""Reusable strict partial-order representation for protocol executions."""

from __future__ import annotations

from dataclasses import dataclass, field
from heapq import heappop, heappush
from typing import Hashable, Iterable


Node = Hashable


class PartialOrderViolation(ValueError):
    """Raised when an edge would violate strict partial-order properties."""


@dataclass
class CausalGraph:
    """A finite DAG whose reachability relation is strict happens-before.

    Stored edges are direct observations/constraints. The semantic relation
    ``precedes(a, b)`` is their transitive closure. Two known nodes are
    concurrent when neither reaches the other.
    """

    _successors: dict[Node, set[Node]] = field(default_factory=dict)
    _predecessors: dict[Node, set[Node]] = field(default_factory=dict)

    @classmethod
    def from_edges(
        cls,
        nodes: Iterable[Node],
        edges: Iterable[tuple[Node, Node]],
    ) -> "CausalGraph":
        graph = cls()
        for node in nodes:
            graph.add_node(node)
        for before, after in edges:
            graph.add_edge(before, after)
        return graph

    @property
    def nodes(self) -> frozenset[Node]:
        return frozenset(self._successors)

    @property
    def edges(self) -> frozenset[tuple[Node, Node]]:
        return frozenset(
            (before, after)
            for before, successors in self._successors.items()
            for after in successors
        )

    def add_node(self, node: Node) -> None:
        self._successors.setdefault(node, set())
        self._predecessors.setdefault(node, set())

    def _require_node(self, node: Node) -> None:
        if node not in self._successors:
            raise KeyError(f"unknown causal node {node!r}")

    def add_edge(self, before: Node, after: Node) -> None:
        self._require_node(before)
        self._require_node(after)
        if before == after:
            raise PartialOrderViolation("strict partial order is irreflexive")
        if self.precedes(after, before):
            raise PartialOrderViolation(f"edge {before!r}->{after!r} creates a causal cycle")
        self._successors[before].add(after)
        self._predecessors[after].add(before)

    def precedes(self, before: Node, after: Node) -> bool:
        self._require_node(before)
        self._require_node(after)
        if before == after:
            return False
        frontier = list(self._successors[before])
        visited = set(frontier)
        while frontier:
            current = frontier.pop()
            if current == after:
                return True
            for successor in self._successors[current]:
                if successor not in visited:
                    visited.add(successor)
                    frontier.append(successor)
        return False

    def concurrent(self, left: Node, right: Node) -> bool:
        self._require_node(left)
        self._require_node(right)
        if left == right:
            return False
        return not self.precedes(left, right) and not self.precedes(right, left)

    def ancestors(self, node: Node) -> frozenset[Node]:
        self._require_node(node)
        frontier = list(self._predecessors[node])
        visited = set(frontier)
        while frontier:
            current = frontier.pop()
            for predecessor in self._predecessors[current]:
                if predecessor not in visited:
                    visited.add(predecessor)
                    frontier.append(predecessor)
        return frozenset(visited)

    def topological_order(self) -> tuple[Node, ...]:
        """Return one deterministic linear extension of the partial order."""

        indegree = {node: len(predecessors) for node, predecessors in self._predecessors.items()}
        ready: list[tuple[str, Node]] = []
        for node, degree in indegree.items():
            if degree == 0:
                heappush(ready, (repr(node), node))
        ordered: list[Node] = []
        while ready:
            _, node = heappop(ready)
            ordered.append(node)
            for successor in self._successors[node]:
                indegree[successor] -= 1
                if indegree[successor] == 0:
                    heappush(ready, (repr(successor), successor))
        if len(ordered) != len(self._successors):
            raise PartialOrderViolation("causal graph contains a cycle")
        return tuple(ordered)

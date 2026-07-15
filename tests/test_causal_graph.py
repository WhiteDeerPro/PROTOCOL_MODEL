from __future__ import annotations

import unittest

from protocol_model import CausalGraph, PartialOrderViolation


class CausalGraphTest(unittest.TestCase):
    def test_reachability_concurrency_and_linear_extension(self) -> None:
        graph = CausalGraph.from_edges(
            range(4), ((0, 1), (0, 2), (1, 3), (2, 3))
        )

        self.assertTrue(graph.precedes(0, 3))
        self.assertTrue(graph.concurrent(1, 2))
        self.assertEqual(frozenset((0, 1, 2)), graph.ancestors(3))
        order = graph.topological_order()
        self.assertLess(order.index(0), order.index(1))
        self.assertLess(order.index(1), order.index(3))

    def test_cycle_is_rejected_at_edge_insertion(self) -> None:
        graph = CausalGraph.from_edges((0, 1), ((0, 1),))

        with self.assertRaisesRegex(PartialOrderViolation, "cycle"):
            graph.add_edge(1, 0)


if __name__ == "__main__":
    unittest.main()

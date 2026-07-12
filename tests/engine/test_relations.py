import unittest

from protocol_model.relations import CausalGraph


class CausalGraphTests(unittest.TestCase):
    def test_transitive_precedence_and_concurrency(self):
        graph = CausalGraph.from_edges(("a", "b", "c", "x"), (("a", "b"), ("b", "c")))
        self.assertTrue(graph.precedes("a", "c"))
        self.assertTrue(graph.concurrent("c", "x"))
        self.assertEqual(graph.ancestors("c"), frozenset({"a", "b"}))

    def test_cycle_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cycle"):
            CausalGraph.from_edges(("a", "b"), (("a", "b"), ("b", "a")))


if __name__ == "__main__":
    unittest.main()

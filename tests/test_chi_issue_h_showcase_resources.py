from __future__ import annotations

import unittest

from protocol_model.visualization import (
    transaction_causal_dot,
    transaction_semantic_wavejson,
    transaction_time_space_dot,
)
from showcase.demos.chi.issue_h_flow_gallery.model import (
    execute_flow_gallery,
    flow_gallery_result,
)
from showcase.demos.chi.issue_h_flow_gallery.topology import (
    flow_case_topology_dot,
)


EXPECTED_CASES = (
    "clean-read-unique-fanout",
    "dirty-peer-clean-unique",
    "make-unique-local-intent",
    "clean-evict-retry",
    "writeback-snoop-cancel",
)


class ChiIssueHShowcaseResourceTest(unittest.TestCase):
    """Keep the selected executable flow witnesses live without publishing."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = execute_flow_gallery()
        cls.result = flow_gallery_result(cls.cases)

    def test_selected_flow_cases_remain_executable_evidence(self) -> None:
        self.assertEqual(EXPECTED_CASES, tuple(self.cases))
        self.assertEqual("PASS", self.result["verdict"])
        self.assertEqual(5, self.result["case_count"])
        self.assertEqual(
            [7, 5, 5, 5, 8],
            [
                self.result["cases"][case_id]["message_count"]
                for case_id in EXPECTED_CASES
            ],
        )
        self.assertTrue(
            all(
                case.passed
                and all(case.execution.assertions.values())
                for case in self.cases.values()
            )
        )
        self.assertEqual(
            2,
            len(
                self.result["cases"]["writeback-snoop-cancel"][
                    "operation_refs"
                ]
            ),
        )
        self.assertIn(
            "same-line cancel selects response",
            {
                edge.reason
                for edge in self.cases["writeback-snoop-cancel"]
                .view.causal_edges
            },
        )
        self.assertIn(
            "Home Snoop-response join",
            {
                edge.reason
                for edge in self.cases["clean-read-unique-fanout"]
                .view.causal_edges
            },
        )

    def test_each_case_has_linked_flow_views_and_topology_evidence(self) -> None:
        for case in self.cases.values():
            with self.subTest(case=case.case_id):
                time_space = transaction_time_space_dot(case.view)
                causality = transaction_causal_dot(case.view)
                timeline = transaction_semantic_wavejson(case.view)
                topology = flow_case_topology_dot(case)

                self.assertGreater(len(case.view.causal_edges), 0)
                self.assertIn("splines=line", time_space)
                self.assertIn('group="lifeline_0"', time_space)
                self.assertIn("Legend", time_space)
                self.assertIn("SEMANTIC EVENTS ONLY", timeline["foot"]["text"])
                self.assertIn("NOT PINS/CYCLES/RTL", timeline["foot"]["text"])
                self.assertIn("explicit causality", causality)
                self.assertIn(
                    "resolved SystemProtocol topology",
                    topology,
                )
                self.assertIn(
                    "solid arrows come from resolved construction",
                    topology,
                )
                self.assertIn(
                    "1 XP-like forwarding abstraction is shown explicitly",
                    topology,
                )
                self.assertIn(
                    "routing forwarder (XP abstraction)",
                    topology,
                )
                self.assertTrue(
                    case.execution.assertions[
                        "one_explicit_xp_forwarder"
                    ]
                )


if __name__ == "__main__":
    unittest.main()

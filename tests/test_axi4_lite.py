from __future__ import annotations

import unittest

from protocol_model.interface import InterfaceTrace
from protocol_model.protocols.amba.axi.axi4 import build_axi4_interface
from protocol_model.protocols.amba.axi.axi4_lite import (
    Axi4LiteConfig,
    Axi4LiteToAxi4,
    build_axi4_lite_interface,
)
from protocol_model.semantics import CanonicalEvent, Verdict


class Axi4LiteInterfaceTest(unittest.TestCase):
    @staticmethod
    def event(kind: str, payload: dict[str, object]) -> CanonicalEvent:
        return CanonicalEvent(kind, None, payload)

    def test_native_schema_contains_only_lite_signals(self) -> None:
        protocol = build_axi4_lite_interface(Axi4LiteConfig(data_width=32))

        self.assertEqual({"addr", "prot"}, set(protocol.event_kinds["AW"].schema.fields))
        self.assertEqual({"data", "strb"}, set(protocol.event_kinds["W"].schema.fields))
        self.assertEqual({"data", "resp"}, set(protocol.event_kinds["R"].schema.fields))

        exokay = self.event("B", {"resp": "EXOKAY"})
        rejected = protocol.open_session().step(
            protocol.open_session().initial_state(), exokay
        )
        self.assertTrue(rejected.fault.rule.endswith("event_schema"))

    def test_single_beat_read_and_independent_aw_w_join(self) -> None:
        protocol = build_axi4_lite_interface()
        trace = (
            self.event("W", {"data": 3, "strb": 0b1111}),
            self.event("AW", {"addr": 0x100, "prot": 0}),
            self.event("B", {"resp": "OKAY"}),
            self.event("AR", {"addr": 0x104, "prot": 0}),
            self.event("R", {"data": 7, "resp": "OKAY"}),
        )

        run = protocol.open_session().run(trace)

        self.assertEqual(Verdict.PASS, run.verdict)

    def test_native_trace_has_explicit_axi4_embedding(self) -> None:
        lite = build_axi4_lite_interface()
        native = (
            self.event("AW", {"addr": 0x100, "prot": 2}),
            self.event("W", {"data": 3, "strb": 0b1111}),
            self.event("B", {"resp": "OKAY"}),
            self.event("AR", {"addr": 0x104, "prot": 1}),
            self.event("R", {"data": 7, "resp": "SLVERR"}),
        )
        lite_run = lite.open_session().run(native)
        embedded = Axi4LiteToAxi4().trace(
            InterfaceTrace(lite_run.emissions, lite_run.final_state.causal_edges)
        )

        axi_run = build_axi4_interface().open_session().run(embedded.events)

        self.assertEqual(Verdict.PASS, lite_run.verdict)
        self.assertEqual(Verdict.PASS, axi_run.verdict)
        self.assertEqual(0, embedded.events[0].payload["len"])
        self.assertEqual(0, embedded.events[0].payload["cache"])
        self.assertTrue(embedded.events[1].payload["last"])

    def test_bounded_profile_can_limit_lite_outstanding_reads(self) -> None:
        protocol = build_axi4_lite_interface().with_resource_capacities(
            "axi4_lite_one_read",
            {"axi4_lite.read.pending_transactions": 1},
        )
        session = protocol.open_session()
        first = session.step(
            session.initial_state(), self.event("AR", {"addr": 0, "prot": 0})
        )
        second = session.step(
            first.state, self.event("AR", {"addr": 4, "prot": 0})
        )

        self.assertIsNone(first.fault)
        self.assertTrue(second.fault.rule.endswith("capacity"))


if __name__ == "__main__":
    unittest.main()

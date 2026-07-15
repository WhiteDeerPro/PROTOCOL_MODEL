from __future__ import annotations

from random import Random
import unittest

from protocol_model import AtomicFrame, CanonicalEvent, ReadyValidSignals, Verdict
from protocol_model.link.amba.axi.axi4_stream import (
    Axi4StreamConfig,
    Axi4StreamGenerationPolicy,
    Axi4StreamGenerator,
    Axi4StreamObservationSession,
    build_axi4_stream_continuous_profile,
    build_axi4_stream_link,
)


class Axi4StreamLinkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Axi4StreamConfig(
            data_width=24,
            id_width=2,
            dest_width=2,
            use_keep=True,
            use_strb=True,
        )

    @staticmethod
    def event(
        key: int,
        *,
        data: int = 0,
        keep: int = 0b111,
        strb: int = 0b111,
        last: bool,
        dest: int = 0,
    ) -> CanonicalEvent:
        return CanonicalEvent(
            "T",
            key,
            {"data": data, "keep": keep, "strb": strb, "last": last, "dest": dest},
        )

    def test_base_stream_allows_packet_interleaving_and_retains_transfer_order(self) -> None:
        protocol = build_axi4_stream_link(self.config)
        trace = (
            self.event(1, last=False),
            self.event(2, last=False),
            self.event(1, last=True),
            self.event(2, last=True),
        )

        run = protocol.open_session().run(trace)

        self.assertEqual(Verdict.PASS, run.verdict)
        self.assertEqual(((0, 1), (1, 2), (2, 3)), run.final_state.causal_edges)

    def test_reserved_tkeep_tstrb_combination_is_rejected(self) -> None:
        protocol = build_axi4_stream_link(self.config)
        invalid = self.event(0, keep=0b001, strb=0b010, last=True)

        transition = protocol.open_session().step(
            protocol.open_session().initial_state(), invalid
        )

        self.assertTrue(transition.fault.rule.endswith("event_schema"))
        self.assertIn("TSTRB", transition.fault.reason)

    def test_continuous_profile_rejects_interleaving_and_interior_nulls(self) -> None:
        config = Axi4StreamConfig(
            data_width=24,
            id_width=2,
            dest_width=2,
            use_keep=True,
            use_strb=False,
        )
        protocol = build_axi4_stream_continuous_profile(config)
        session = protocol.open_session()
        first = session.step(
            session.initial_state(),
            CanonicalEvent(
                "T", 1, {"data": 0, "keep": 0b111, "last": False, "dest": 0}
            ),
        )
        interleaved = session.step(
            first.state,
            CanonicalEvent(
                "T", 2, {"data": 0, "keep": 0b111, "last": True, "dest": 0}
            ),
        )

        self.assertIsNone(first.fault)
        self.assertEqual(
            "axi4_stream.continuous.packet_interleave", interleaved.fault.rule
        )

        null_inside = session.step(
            session.initial_state(),
            CanonicalEvent(
                "T", 1, {"data": 0, "keep": 0b011, "last": False, "dest": 0}
            ),
        )
        self.assertEqual(
            "axi4_stream.continuous.interior_null_byte", null_inside.fault.rule
        )

    def test_packet_generator_uses_native_link_offers(self) -> None:
        protocol = build_axi4_stream_link(self.config)
        trace = Axi4StreamGenerator(protocol).generate(
            Random(9),
            Axi4StreamGenerationPolicy(
                packet_lengths=(2, 1), stream_ids=(1, 2), destinations=(0, 1)
            ),
        )

        self.assertEqual(Verdict.PASS, protocol.open_session().run(trace.events).verdict)
        self.assertEqual([False, True, True], [event.payload["last"] for event in trace.events])

    def test_stream_observation_reuses_ready_valid_and_reset_epoch(self) -> None:
        config = Axi4StreamConfig(data_width=16)
        observer = Axi4StreamObservationSession(config=config)
        reset = AtomicFrame(
            0,
            "aclk",
            {"T": ReadyValidSignals(False, True), "reset": True},
        )
        reset_step = observer.step(observer.initial_state(), reset)
        transfer = CanonicalEvent("T", None, {"data": 3, "last": True})
        accepted = observer.step(
            reset_step.state,
            AtomicFrame(
                1,
                "aclk",
                {"T": ReadyValidSignals(True, True, transfer), "reset": False},
            ),
        )

        self.assertIsNone(accepted.fault)
        self.assertEqual(("T",), tuple(event.kind for event in accepted.emissions))
        self.assertTrue(observer.is_quiescent(accepted.state))


if __name__ == "__main__":
    unittest.main()

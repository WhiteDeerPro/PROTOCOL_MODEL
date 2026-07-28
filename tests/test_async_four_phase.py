from __future__ import annotations

import unittest

from protocol_model.protocols.asynchronous import (
    FourPhaseTokenConfig,
    build_four_phase_token_interface,
)
from protocol_model.observation import (
    AsynchronousSample,
    FourPhaseDataWindow,
    FourPhaseObserver,
    FourPhaseSignals,
)
from protocol_model.semantics import CanonicalEvent, Verdict
from protocol_model.virtual_dut.boundary import InterfacePort


class FourPhaseHandshakeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.protocol = build_four_phase_token_interface(
            FourPhaseTokenConfig(data_width=8)
        )
        self.transfer = self.protocol.event_kinds["transfer"].schema

    @staticmethod
    def event(reference: int, data: int) -> CanonicalEvent:
        return CanonicalEvent("TRANSFER", reference, {"data": data})

    @staticmethod
    def sample(
        sequence: int,
        req: bool,
        ack: bool,
        event: CanonicalEvent | None = None,
        *,
        reset: bool | None = None,
        timestamp: int | float | None = None,
    ) -> AsynchronousSample:
        observations = {
            "token": FourPhaseSignals(req, ack, event),
        }
        if reset is not None:
            observations["reset"] = reset
        return AsynchronousSample(
            sequence,
            observations,
            timestamp=timestamp,
            source="async-pins",
        )

    def observer(
        self,
        *,
        data_window: FourPhaseDataWindow = FourPhaseDataWindow.EARLY,
        reset: bool = False,
    ) -> FourPhaseObserver:
        return FourPhaseObserver(
            "token_handshake",
            "token",
            self.transfer,
            data_window,
            "reset" if reset else None,
        )

    def test_complete_cycle_emits_one_timestamped_transfer(self) -> None:
        event = self.event(4, 0x52)
        observer = self.observer()
        run = observer.run(
            (
                self.sample(0, False, False),
                self.sample(1, True, False, event),
                self.sample(2, True, False, event),
                self.sample(3, True, True, event, timestamp=12.5),
                self.sample(4, False, True),
                self.sample(5, False, False),
            )
        )

        self.assertEqual(Verdict.PASS, run.verdict)
        self.assertEqual(1, len(run.emissions))
        accepted = run.emissions[0]
        self.assertEqual(event.semantic_identity, accepted.semantic_identity)
        self.assertEqual(12.5, accepted.timestamp)
        self.assertEqual(3, accepted.sequence)
        self.assertIsNone(accepted.clock)

        link_run = self.protocol.open_session().run(run.emissions)
        self.assertEqual(Verdict.PASS, link_run.verdict)

    def test_waiting_for_ack_is_inconclusive_not_a_safety_failure(self) -> None:
        event = self.event(1, 0x11)
        run = self.observer().run(
            (
                self.sample(0, False, False),
                self.sample(1, True, False, event),
                self.sample(2, True, False, event),
            )
        )

        self.assertEqual(Verdict.INCONCLUSIVE, run.verdict)
        self.assertFalse(run.violations)

    def test_missing_timestamp_stays_unknown(self) -> None:
        event = self.event(8, 0x80)
        run = self.observer().run(
            (
                self.sample(0, False, False),
                self.sample(1, True, False, event),
                self.sample(2, True, True, event),
                self.sample(3, False, True),
                self.sample(4, False, False),
            )
        )

        self.assertEqual(Verdict.PASS, run.verdict)
        self.assertIsNone(run.emissions[0].timestamp)
        self.assertEqual(2, run.emissions[0].sequence)

    def test_sparse_timestamp_cannot_hide_time_regression(self) -> None:
        run = self.observer().run(
            (
                self.sample(0, False, False, timestamp=10),
                self.sample(1, False, False),
                self.sample(2, False, False, timestamp=5),
            )
        )

        self.assertEqual(Verdict.FAIL, run.verdict)
        self.assertEqual(
            "token_handshake.timestamp_order", run.violations[0].fault.rule
        )

    def test_ack_cannot_assert_before_request(self) -> None:
        run = self.observer().run(
            (
                self.sample(0, False, False),
                self.sample(1, False, True),
            )
        )

        self.assertEqual(Verdict.FAIL, run.verdict)
        self.assertEqual(
            "token_handshake.phase_order", run.violations[0].fault.rule
        )

    def test_payload_cannot_change_before_ack(self) -> None:
        run = self.observer().run(
            (
                self.sample(0, False, False),
                self.sample(1, True, False, self.event(3, 0x10)),
                self.sample(2, True, False, self.event(3, 0x20)),
            )
        )

        self.assertEqual(Verdict.FAIL, run.verdict)
        self.assertEqual(
            "token_handshake.event_stability", run.violations[0].fault.rule
        )

    def test_early_window_does_not_overconstrain_data_after_ack(self) -> None:
        event = self.event(6, 0xA0)
        run = self.observer().run(
            (
                self.sample(0, False, False),
                self.sample(1, True, False, event),
                self.sample(2, True, True, event),
                self.sample(3, True, True, self.event(6, 0xA1)),
                self.sample(4, False, True),
                self.sample(5, False, False),
            )
        )

        self.assertEqual(Verdict.PASS, run.verdict)

    def test_extended_early_window_holds_event_while_req_is_high(self) -> None:
        event = self.event(7, 0x70)
        run = self.observer(
            data_window=FourPhaseDataWindow.EXTENDED_EARLY
        ).run(
            (
                self.sample(0, False, False),
                self.sample(1, True, False, event),
                self.sample(2, True, True, event),
                self.sample(3, True, True, self.event(7, 0x71)),
            )
        )

        self.assertEqual(Verdict.FAIL, run.verdict)
        self.assertEqual(
            "token_handshake.event_stability", run.violations[0].fault.rule
        )

    def test_broad_window_holds_event_until_ack_returns_low(self) -> None:
        event = self.event(9, 0x90)
        run = self.observer(data_window=FourPhaseDataWindow.BROAD).run(
            (
                self.sample(0, False, False),
                self.sample(1, True, False, event),
                self.sample(2, True, True, event),
                self.sample(3, False, True, event),
                self.sample(4, False, True, self.event(9, 0x91)),
            )
        )

        self.assertEqual(Verdict.FAIL, run.verdict)
        self.assertEqual(
            "token_handshake.event_stability", run.violations[0].fault.rule
        )

    def test_reset_aborts_partial_exchange_without_ghost_transfer(self) -> None:
        first = self.event(1, 0x10)
        second = self.event(2, 0x20)
        observer = self.observer(reset=True)
        run = observer.run(
            (
                self.sample(0, False, False, reset=False),
                self.sample(1, True, False, first, reset=False),
                self.sample(2, False, False, reset=True),
                self.sample(3, False, False, reset=False),
                self.sample(4, True, False, second, reset=False),
                self.sample(5, True, True, second, reset=False),
                self.sample(6, False, True, reset=False),
                self.sample(7, False, False, reset=False),
            )
        )

        self.assertEqual(Verdict.PASS, run.verdict)
        self.assertEqual(
            (second.semantic_identity,),
            tuple(item.semantic_identity for item in run.emissions),
        )
        self.assertEqual(1, run.final_state.epoch)

    def test_protocol_is_attached_to_ports_not_to_the_backend_type(self) -> None:
        sender = InterfacePort(
            "out", self.protocol, "sender", clock_domain="source_clk"
        )
        receiver = InterfacePort(
            "in", self.protocol, "receiver", clock_domain="sink_clk"
        )

        self.assertEqual("source_clk", sender.clock_domain)
        self.assertEqual("sink_clk", receiver.clock_domain)
        self.assertTrue(sender.protocol.has_same_interface_shape_as(receiver.protocol))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from protocol_model import (
    AtomicFrame,
    CanonicalEvent,
    EventSchema,
    NaturalDomain,
    ReadyValidObserver,
    ReadyValidSignals,
    ResetEpochObserver,
)


class ObservationLayerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.observer = ReadyValidObserver(
            "request_handshake",
            "request",
            EventSchema("REQUEST", key=NaturalDomain()),
            "clk",
        )

    def frame(self, tick: int, signals: ReadyValidSignals, *, reset=False):
        return AtomicFrame(
            tick,
            "clk",
            {"request": signals, "reset": reset},
            "pins",
        )

    def test_acceptance_lowers_one_frame_to_a_timestamped_event(self) -> None:
        transition = self.observer.step(
            self.observer.initial_state(),
            self.frame(
                3,
                ReadyValidSignals(
                    True, True, CanonicalEvent("REQUEST", key=0)
                ),
            ),
        )

        self.assertIsNone(transition.fault)
        self.assertEqual(3, transition.emissions[0].timestamp)
        self.assertEqual("clk", transition.emissions[0].clock)
        self.assertEqual("pins", transition.emissions[0].source)

    def test_stalled_offer_cannot_change(self) -> None:
        first = self.observer.step(
            self.observer.initial_state(),
            self.frame(
                0,
                ReadyValidSignals(
                    True, False, CanonicalEvent("REQUEST", key=1)
                ),
            ),
        )
        changed = self.observer.step(
            first.state,
            self.frame(
                1,
                ReadyValidSignals(
                    True, True, CanonicalEvent("REQUEST", key=2)
                ),
            ),
        )

        self.assertEqual(
            "request_handshake.payload_stability", changed.fault.rule
        )

    def test_reset_epoch_clears_stalled_observation_state(self) -> None:
        reset_observer = ResetEpochObserver(
            "bus_reset",
            self.observer,
            "reset",
            inactive=lambda frame: not frame.get("request").valid,
            inactive_reason="VALID must be low during reset",
        )
        stalled = reset_observer.step(
            reset_observer.initial_state(),
            self.frame(
                0,
                ReadyValidSignals(
                    True, False, CanonicalEvent("REQUEST", key=1)
                ),
            ),
        )
        cleared = reset_observer.step(
            stalled.state,
            self.frame(1, ReadyValidSignals(False, False), reset=True),
        )

        self.assertIsNone(cleared.fault)
        self.assertTrue(cleared.state.in_reset)
        self.assertIsNone(cleared.state.inner_state.held_event)


if __name__ == "__main__":
    unittest.main()

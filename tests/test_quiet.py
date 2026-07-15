from __future__ import annotations

from random import Random
import unittest

from protocol_model import (
    AtomicFrame,
    EventOffer,
    QuietConstraint,
    QuietMode,
    ReadyValidSignals,
)
from protocol_model.link.amba.axi.axi4 import (
    Axi4ObservationPolicy,
    Axi4ObservationSession,
    build_axi4_read_only_profile,
)
from protocol_model.visualization import LaneDisplayPolicy


CHANNELS = ("AW", "W", "B", "AR", "R")


class QuietPatternTest(unittest.TestCase):
    def test_stable_constraint_accepts_repeated_value_and_rejects_change(self) -> None:
        constraint = QuietConstraint("sideband", QuietMode.STABLE)
        first = constraint.step(constraint.initial_state(), 3)
        repeated = constraint.step(first.state, 3)
        changed = constraint.step(repeated.state, 4)

        self.assertIsNone(repeated.fault)
        self.assertEqual(first.state, repeated.state)
        self.assertEqual("sideband.changed", changed.fault.rule)

    def test_ignore_is_not_a_tied_value_check(self) -> None:
        constraint = QuietConstraint("unobserved", QuietMode.IGNORE)

        transition = constraint.step(constraint.initial_state(), object())

        self.assertIsNone(transition.fault)
        self.assertFalse(transition.state.seen)


class Axi4QuietProfileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.protocol = build_axi4_read_only_profile()
        self.rng = Random(53)

    def test_link_profile_removes_write_event_offers_and_rejects_forced_aw(self) -> None:
        session = self.protocol.open_session()
        state = session.initial_state()

        self.assertEqual(
            {"AR"}, {offer.kind for offer in session.event_offers(state)}
        )
        forced = self.protocol.generate_event(
            EventOffer.constrained(
                "AW",
                key=1,
                payload={
                    "addr": 0x100,
                    "len": 0,
                    "size": 2,
                    "burst": "INCR",
                    "lock": 0,
                },
            ),
            self.rng,
        )

        rejected = session.step(state, forced)

        self.assertTrue(rejected.fault.rule.endswith("forbidden_event"))

    def test_observation_policy_requires_valid_low_even_without_handshake(self) -> None:
        observer = Axi4ObservationSession(
            self.protocol,
            policy=Axi4ObservationPolicy(frozenset(("AW", "W", "B"))),
        )
        aw = self.protocol.generate_event(
            EventOffer.constrained(
                "AW",
                key=2,
                payload={
                    "addr": 0x200,
                    "len": 0,
                    "size": 2,
                    "burst": "INCR",
                    "lock": 0,
                },
            ),
            self.rng,
        )
        observations = {
            name: ReadyValidSignals(False, False) for name in CHANNELS
        }
        observations["AW"] = ReadyValidSignals(True, False, aw)
        observations["reset"] = False
        state = observer.initial_state()

        rejected = observer.step(
            state, AtomicFrame(0, "aclk", observations, "axi-pins")
        )

        self.assertEqual(
            "axi4_read_only.observation.AW.inactive.tied_value",
            rejected.fault.rule,
        )
        self.assertEqual(state, rejected.state)

    def test_display_filter_is_an_explicit_presentation_choice(self) -> None:
        policy = LaneDisplayPolicy(
            hidden_lanes=frozenset(("AW",)), hide_inactive=True
        )

        self.assertFalse(policy.shows("AW", active=True))
        self.assertFalse(policy.shows("AR", active=False))
        self.assertTrue(policy.shows("AR", active=True))


if __name__ == "__main__":
    unittest.main()

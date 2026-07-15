from __future__ import annotations

from random import Random
import unittest

from protocol_model import AtomicFrame, EventOffer, ReadyValidSignals
from protocol_model.link.amba.axi.axi4 import Axi4ObservationSession, build_axi4_link


CHANNELS = ("AW", "W", "B", "AR", "R")


class Axi4ObservationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.protocol = build_axi4_link()
        self.observer = Axi4ObservationSession(self.protocol)
        self.rng = Random(41)

    def event(
        self,
        kind: str,
        *,
        key: int | None = None,
        payload: dict[str, object] | None = None,
    ):
        return self.protocol.generate_event(
            EventOffer.constrained(kind, key=key, payload=payload or {}),
            self.rng,
        )

    @staticmethod
    def frame(
        tick: int,
        active=None,
        *,
        reset: bool = False,
        ready: bool = True,
    ) -> AtomicFrame:
        active = active or {}
        observations = {
            name: ReadyValidSignals(
                valid=name in active,
                ready=ready,
                event=active.get(name),
            )
            for name in CHANNELS
        }
        observations["reset"] = reset
        return AtomicFrame(tick, "aclk", observations, "axi-pins")

    def reset_state(self):
        transition = self.observer.step(
            self.observer.initial_state(), self.frame(0, reset=True)
        )
        self.assertIsNone(transition.fault)
        return transition.state

    def test_observation_policy_exposes_its_derived_constraints(self) -> None:
        names = {item.name for item in self.observer.semantics.constraints}

        self.assertIn("axi4.observation.atomic_commit", names)
        self.assertIn("axi4.observation.response_visibility", names)
        self.assertIn(
            "axi4.observation.AR.ready_valid.payload_stability", names
        )

    def test_same_frame_aw_w_commit_as_one_link_batch(self) -> None:
        state = self.reset_state()
        aw = self.event(
            "AW",
            key=2,
            payload={
                "addr": 0x100,
                "len": 0,
                "size": 2,
                "burst": "INCR",
            },
        )
        w = self.event(
            "W", payload={"data": 0, "strb": 0, "last": True}
        )

        accepted = self.observer.step(
            state, self.frame(1, {"AW": aw, "W": w})
        )

        self.assertIsNone(accepted.fault)
        self.assertEqual(["W", "AW"], [event.kind for event in accepted.emissions])
        response = self.event("B", key=2, payload={"resp": "OKAY"})
        completed = self.observer.step(
            accepted.state, self.frame(2, {"B": response})
        )
        self.assertIsNone(completed.fault)
        self.assertTrue(self.observer.is_quiescent(completed.state))

    def test_same_frame_response_cannot_consume_new_obligation(self) -> None:
        state = self.reset_state()
        request = self.event(
            "AR",
            key=3,
            payload={
                "addr": 0x200,
                "len": 0,
                "size": 2,
                "burst": "INCR",
            },
        )
        response = self.event(
            "R",
            key=3,
            payload={"data": 0, "resp": "OKAY", "last": True},
        )

        rejected = self.observer.step(
            state, self.frame(1, {"AR": request, "R": response})
        )

        self.assertEqual("axi4.read.orphan_beat", rejected.fault.rule)
        self.assertEqual(state, rejected.state)

    def test_batch_fault_rolls_back_every_channel(self) -> None:
        state = self.reset_state()
        aw = self.event(
            "AW",
            key=1,
            payload={
                "addr": 0x300,
                "len": 1,
                "size": 2,
                "burst": "INCR",
            },
        )
        early_final = self.event(
            "W", payload={"data": 0, "strb": 0, "last": True}
        )

        rejected = self.observer.step(
            state, self.frame(1, {"AW": aw, "W": early_final})
        )

        self.assertEqual("axi4.write.join.beat_count", rejected.fault.rule)
        self.assertEqual(state, rejected.state)

    def test_stalled_payload_must_remain_stable(self) -> None:
        state = self.reset_state()
        first = self.event(
            "AR",
            key=1,
            payload={
                "addr": 0x400,
                "len": 0,
                "size": 2,
                "burst": "INCR",
            },
        )
        changed = self.event(
            "AR",
            key=1,
            payload={
                "addr": 0x408,
                "len": 0,
                "size": 2,
                "burst": "INCR",
            },
        )
        stalled = self.observer.step(
            state, self.frame(1, {"AR": first}, ready=False)
        )
        self.assertIsNone(stalled.fault)

        rejected = self.observer.step(
            stalled.state, self.frame(2, {"AR": changed}, ready=False)
        )

        self.assertTrue(rejected.fault.rule.endswith("payload_stability"))
        self.assertEqual(stalled.state, rejected.state)

    def test_reset_discards_pending_link_obligations(self) -> None:
        state = self.reset_state()
        request = self.event(
            "AR",
            key=4,
            payload={
                "addr": 0x500,
                "len": 0,
                "size": 2,
                "burst": "INCR",
            },
        )
        accepted = self.observer.step(state, self.frame(1, {"AR": request}))
        self.assertIsNone(accepted.fault)
        reset = self.observer.step(accepted.state, self.frame(2, reset=True))
        self.assertIsNone(reset.fault)

        response = self.event(
            "R",
            key=4,
            payload={"data": 0, "resp": "OKAY", "last": True},
        )
        rejected = self.observer.step(
            reset.state, self.frame(3, {"R": response})
        )

        self.assertEqual("axi4.read.orphan_beat", rejected.fault.rule)


if __name__ == "__main__":
    unittest.main()

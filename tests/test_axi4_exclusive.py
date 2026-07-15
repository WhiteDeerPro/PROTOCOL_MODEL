from __future__ import annotations

from random import Random
import unittest

from protocol_model import CanonicalEvent, EventOffer
from protocol_model.link.amba.axi.axi4 import build_axi4_link


class Axi4ExclusiveLinkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.protocol = build_axi4_link()
        self.session = self.protocol.open_session()
        self.state = self.session.initial_state()
        self.rng = Random(53)

    def event(self, kind: str, *, key=None, payload=None) -> CanonicalEvent:
        return self.protocol.generate_event(
            EventOffer.constrained(kind, key=key, payload=payload or {}),
            self.rng,
        )

    def address(
        self,
        kind: str,
        *,
        key: int = 1,
        addr: int = 0x100,
        length: int = 0,
        size: int = 2,
        lock: int = 1,
    ) -> CanonicalEvent:
        return self.event(
            kind,
            key=key,
            payload={
                "addr": addr,
                "len": length,
                "size": size,
                "burst": "INCR",
                "lock": lock,
            },
        )

    def accept(self, event: CanonicalEvent) -> None:
        transition = self.session.step(self.state, event)
        self.assertIsNone(transition.fault)
        self.state = transition.state

    def test_matching_exclusive_sequence_can_return_exokay(self) -> None:
        read = self.address("AR", key=3)
        self.accept(read)
        self.accept(
            self.event(
                "R",
                key=3,
                payload={"data": 0, "resp": "EXOKAY", "last": True},
            )
        )
        write = self.event("AW", key=3, payload=dict(read.payload))
        self.accept(write)
        self.accept(
            self.event("W", payload={"data": 0, "strb": 0, "last": True})
        )
        self.accept(self.event("B", key=3, payload={"resp": "EXOKAY"}))

        self.assertTrue(self.session.is_quiescent(self.state))
        self.assertIn((1, 2), self.state.causal_edges)

    def test_exclusive_write_waits_for_read_completion(self) -> None:
        read = self.address("AR", key=2)
        self.accept(read)
        write = self.event("AW", key=2, payload=dict(read.payload))

        rejected = self.session.step(self.state, write)

        self.assertEqual(
            "axi4.exclusive.write_before_read_complete", rejected.fault.rule
        )

    def test_unmatched_exclusive_write_cannot_report_success(self) -> None:
        self.accept(self.address("AW", key=4))
        self.accept(
            self.event("W", payload={"data": 0, "strb": 0, "last": True})
        )

        rejected = self.session.step(
            self.state, self.event("B", key=4, payload={"resp": "EXOKAY"})
        )

        self.assertEqual("axi4.exclusive.unmatched_success", rejected.fault.rule)

    def test_normal_read_cannot_receive_exokay(self) -> None:
        self.accept(self.address("AR", key=1, lock=0))

        rejected = self.session.step(
            self.state,
            self.event(
                "R",
                key=1,
                payload={"data": 0, "resp": "EXOKAY", "last": True},
            ),
        )

        self.assertEqual("axi4.exclusive.normal_read_exokay", rejected.fault.rule)

    def test_exclusive_read_does_not_mix_okay_and_exokay(self) -> None:
        self.accept(self.address("AR", key=5, length=1))
        self.accept(
            self.event(
                "R",
                key=5,
                payload={"data": 0, "resp": "EXOKAY", "last": False},
            )
        )

        rejected = self.session.step(
            self.state,
            self.event(
                "R",
                key=5,
                payload={"data": 0, "resp": "OKAY", "last": True},
            ),
        )

        self.assertEqual("axi4.exclusive.mixed_read_response", rejected.fault.rule)

    def test_later_same_id_exclusive_read_replaces_reservation(self) -> None:
        first = self.address("AR", key=7, addr=0x100)
        second = self.address("AR", key=7, addr=0x200)
        self.accept(first)
        self.accept(second)
        self.accept(
            self.event(
                "R",
                key=7,
                payload={"data": 0, "resp": "EXOKAY", "last": True},
            )
        )
        self.accept(
            self.event(
                "R",
                key=7,
                payload={"data": 0, "resp": "EXOKAY", "last": True},
            )
        )
        stale_write = self.event("AW", key=7, payload=dict(first.payload))
        self.accept(stale_write)
        self.accept(
            self.event("W", payload={"data": 0, "strb": 0, "last": True})
        )

        rejected = self.session.step(
            self.state, self.event("B", key=7, payload={"resp": "EXOKAY"})
        )

        self.assertEqual("axi4.exclusive.unmatched_success", rejected.fault.rule)

    def test_exclusive_address_aligns_to_total_transaction_size(self) -> None:
        template = self.address("AR", key=6, lock=0)
        payload = dict(template.payload)
        payload.update({"addr": 0x102, "len": 1, "size": 2, "lock": 1})
        misaligned = CanonicalEvent("AR", 6, payload)

        rejected = self.session.step(self.state, misaligned)

        self.assertTrue(rejected.fault.rule.endswith("event_schema"))
        self.assertIn("exclusive address", rejected.fault.reason)


if __name__ == "__main__":
    unittest.main()

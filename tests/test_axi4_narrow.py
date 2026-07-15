from __future__ import annotations

from random import Random
import unittest

from protocol_model import CanonicalEvent, EventOffer
from protocol_model.link.amba.axi.axi4 import (
    Axi4Config,
    beat_address,
    beat_byte_addresses,
    build_axi4_link,
    byte_lane_bounds,
    byte_lane_mask,
    stays_in_4kb,
)


def address_event(
    *, addr: int, length: int, size: int, burst: str
) -> CanonicalEvent:
    return CanonicalEvent(
        "AW",
        key=0,
        payload={"addr": addr, "len": length, "size": size, "burst": burst},
    )


class Axi4NarrowGeometryTest(unittest.TestCase):
    def test_unaligned_incrementing_first_beat_is_partial_then_rotates(self) -> None:
        address = address_event(addr=3, length=2, size=2, burst="INCR")

        self.assertEqual([3, 4, 8], [beat_address(address, i) for i in range(3)])
        self.assertEqual(
            [(3, 3), (4, 7), (0, 3)],
            [byte_lane_bounds(address, i, bus_bytes=8) for i in range(3)],
        )
        self.assertEqual(
            [0x08, 0xF0, 0x0F],
            [byte_lane_mask(address, i, bus_bytes=8) for i in range(3)],
        )
        self.assertEqual(
            (8, 9, 10, 11),
            beat_byte_addresses(address, 2, bus_bytes=8),
        )

    def test_unaligned_fixed_burst_keeps_first_beat_lanes(self) -> None:
        address = address_event(addr=3, length=2, size=2, burst="FIXED")

        self.assertEqual(
            [0x08, 0x08, 0x08],
            [byte_lane_mask(address, i, bus_bytes=8) for i in range(3)],
        )

        page_edge = address_event(
            addr=0xFFF, length=2, size=2, burst="FIXED"
        )
        self.assertTrue(stays_in_4kb(page_edge))

    def test_wrapping_narrow_burst_rotates_at_wrap_boundary(self) -> None:
        address = address_event(addr=12, length=3, size=2, burst="WRAP")

        self.assertEqual(
            [12, 0, 4, 8], [beat_address(address, i) for i in range(4)]
        )
        self.assertEqual(
            [0xF0, 0x0F, 0xF0, 0x0F],
            [byte_lane_mask(address, i, bus_bytes=8) for i in range(4)],
        )

    def test_geometry_rejects_transfer_wider_than_data_bus(self) -> None:
        address = address_event(addr=0, length=0, size=3, burst="INCR")

        with self.assertRaisesRegex(ValueError, "exceeds"):
            byte_lane_mask(address, 0, bus_bytes=4)

    def test_address_schema_rejects_container_overflow(self) -> None:
        schema = build_axi4_link(Axi4Config(address_width=8)).channels["AW"].event
        event = CanonicalEvent(
            "AW",
            key=0,
            payload={
                "addr": 0xFC,
                "len": 1,
                "size": 2,
                "burst": "INCR",
                "lock": 0,
                "cache": 0,
                "prot": 0,
                "qos": 0,
                "region": 0,
            },
        )

        self.assertTrue(
            any("address space" in reason for reason in schema.explain(event))
        )

    def test_write_monitor_rejects_strobes_outside_narrow_lanes(self) -> None:
        protocol = build_axi4_link()
        session = protocol.open_session()
        state = session.initial_state()
        rng = Random(59)
        aw = protocol.generate_event(
            EventOffer.constrained(
                "AW",
                key=1,
                payload={
                    "addr": 3,
                    "len": 0,
                    "size": 2,
                    "burst": "INCR",
                    "lock": 0,
                },
            ),
            rng,
        )
        state = session.step(state, aw).state
        w = protocol.generate_event(
            EventOffer.constrained(
                "W", payload={"data": 0, "strb": 0x10, "last": True}
            ),
            rng,
        )

        rejected = session.step(state, w)

        self.assertEqual("axi4.write.byte_lanes", rejected.fault.rule)


if __name__ == "__main__":
    unittest.main()

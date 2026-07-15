from __future__ import annotations

import unittest

from protocol_model import CanonicalEvent, Verdict
from protocol_model.link.amba.ace.ace_lite import build_ace_lite_data_link


def address_event(
    kind: str, *, domain: int, snoop: int, bar: int = 0
) -> CanonicalEvent:
    return CanonicalEvent(
        kind,
        1,
        {
            "addr": 0x100,
            "len": 0,
            "size": 3,
            "burst": "INCR",
            "lock": 0,
            "cache": 0,
            "prot": 0,
            "qos": 0,
            "region": 0,
            "domain": domain,
            "snoop": snoop,
            "bar": bar,
        },
    )


class AceLiteDataLinkTest(unittest.TestCase):
    def test_native_address_schema_and_roles(self) -> None:
        protocol = build_ace_lite_data_link()

        self.assertEqual("amba.ace_lite", protocol.family)
        self.assertEqual(
            {"manager", "coherent_interconnect"}, set(protocol.roles)
        )
        self.assertTrue(
            {"domain", "snoop", "bar"}
            <= set(protocol.channels["AR"].event.fields)
        )
        self.assertEqual(
            4, protocol.channels["AR"].event.fields["snoop"].domain.width
        )
        self.assertEqual(
            3, protocol.channels["AW"].event.fields["snoop"].domain.width
        )

    def test_read_once_uses_inherited_axi_completion_semantics(self) -> None:
        protocol = build_ace_lite_data_link()
        trace = (
            address_event("AR", domain=0b01, snoop=0),
            CanonicalEvent(
                "R", 1, {"data": 7, "resp": "OKAY", "last": True}
            ),
        )

        self.assertEqual(Verdict.PASS, protocol.open_session().run(trace).verdict)

    def test_profile_rejects_barrier_and_unsupported_snoop_domain(self) -> None:
        protocol = build_ace_lite_data_link()
        session = protocol.open_session()
        state = session.initial_state()

        barrier = session.step(
            state, address_event("AR", domain=0b01, snoop=0, bar=0b01)
        )
        line_unique_nonshareable = session.step(
            state, address_event("AW", domain=0b00, snoop=1)
        )

        self.assertIn("barrier", barrier.fault.reason)
        self.assertIn("snoop/domain", line_unique_nonshareable.fault.reason)

    def test_cacheable_transaction_rejects_system_domain(self) -> None:
        event = address_event("AR", domain=0b11, snoop=0)
        event = CanonicalEvent(
            event.kind,
            event.key,
            {**event.payload, "cache": 0b0100},
        )
        session = build_ace_lite_data_link().open_session()
        result = session.step(session.initial_state(), event)

        self.assertIn("System domain", result.fault.reason)


if __name__ == "__main__":
    unittest.main()

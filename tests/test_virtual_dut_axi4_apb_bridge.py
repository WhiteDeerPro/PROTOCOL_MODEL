from __future__ import annotations

import unittest

from protocol_model import (
    AddressRoute,
    AddressSpace,
    CanonicalEvent,
    CaptureModel,
    MemoryRegion,
    ProtocolLink,
    ProtocolPort,
    SystemAction,
    SystemProtocol,
    VirtualDut,
    VirtualDutPortRef,
    build_apb_address_space_vdut,
)
from protocol_model.integrations.recipes.amba.bridges import (
    build_axi4_to_apb_bridge_vdut,
)
from protocol_model.link.amba.apb.apb4 import build_apb4_link
from protocol_model.link.amba.axi.axi4 import Axi4Config, build_axi4_link


def _address_event(
    kind: str,
    *,
    key: int,
    address: int,
    length: int = 0,
) -> CanonicalEvent:
    return CanonicalEvent(
        kind,
        key,
        {
            "addr": address,
            "len": length,
            "size": 2,
            "burst": "INCR",
            "lock": 0,
            "cache": 0,
            "prot": 0,
            "qos": 0,
            "region": 0,
        },
    )


class Axi4ToApbBridgeTest(unittest.TestCase):
    @staticmethod
    def _system(*, capture_apb: bool = False) -> SystemProtocol:
        axi = build_axi4_link(Axi4Config(data_width=32))
        apb = build_apb4_link(data_width=32)
        manager = VirtualDut(
            "manager",
            {"axi": ProtocolPort("axi", axi, "manager")},
            model=CaptureModel(),
        )
        bridge = build_axi4_to_apb_bridge_vdut(
            "bridge",
            axi,
            apb,
            (
                AddressRoute(
                    "peripheral",
                    0x8000,
                    0x100,
                    "m_apb",
                    output_base_address=0x1000,
                ),
            ),
        )
        if capture_apb:
            peripheral = VirtualDut(
                "peripheral",
                {"apb": ProtocolPort("apb", apb, "completer")},
                model=CaptureModel(),
            )
        else:
            peripheral = build_apb_address_space_vdut(
                "peripheral",
                apb,
                AddressSpace(
                    (
                        MemoryRegion(
                            "ram",
                            0x100,
                            base_address=0x1000,
                            initial_content=bytes.fromhex(
                                "112233445566778899aabbcc"
                            ),
                        ),
                    )
                ),
            )
        links = (
            ProtocolLink(
                "axi",
                axi,
                {
                    "manager": VirtualDutPortRef("manager", "axi"),
                    "subordinate": VirtualDutPortRef("bridge", "s_axi"),
                },
            ),
            ProtocolLink(
                "apb",
                apb,
                {
                    "requester": VirtualDutPortRef("bridge", "m_apb"),
                    "completer": VirtualDutPortRef("peripheral", "apb"),
                },
            ),
        )
        return SystemProtocol(
            "axi4_apb",
            {item.name: item for item in (manager, bridge, peripheral)},
            {item.name: item for item in links},
        )

    @staticmethod
    def _manager_action(event: CanonicalEvent) -> SystemAction:
        return SystemAction(VirtualDutPortRef("manager", "axi"), event)

    def test_incr_burst_is_split_into_serial_remapped_apb_transfers(self) -> None:
        session = self._system().open_session()

        transition = session.step(
            session.initial_state(),
            self._manager_action(
                _address_event("AR", key=3, address=0x8000, length=2)
            ),
        )

        self.assertIsNone(transition.fault)
        apb_requests = tuple(
            item.event
            for item in transition.emissions
            if item.link == "apb" and item.event.kind == "READ"
        )
        responses = tuple(
            item.event
            for item in transition.emissions
            if item.link == "axi" and item.event.kind == "R"
        )
        self.assertEqual(
            (0x1000, 0x1004, 0x1008),
            tuple(item.payload["addr"] for item in apb_requests),
        )
        self.assertEqual(
            (0x44332211, 0x88776655, 0xCCBBAA99),
            tuple(item.payload["data"] for item in responses),
        )
        self.assertEqual((3, 3, 3), tuple(item.key for item in responses))
        self.assertEqual(
            (False, False, True),
            tuple(item.payload["last"] for item in responses),
        )
        self.assertTrue(session.is_quiescent(transition.state))

    def test_second_read_waits_while_the_single_apb_child_is_pending(self) -> None:
        session = self._system(capture_apb=True).open_session()
        first = session.step(
            session.initial_state(),
            self._manager_action(
                _address_event("AR", key=1, address=0x8000)
            ),
        )
        second = session.step(
            first.state,
            self._manager_action(
                _address_event("AR", key=2, address=0x8004)
            ),
        )

        self.assertIsNone(first.fault)
        self.assertIsNone(second.fault)
        self.assertEqual(
            ("AR", "READ"), tuple(item.event.kind for item in first.emissions)
        )
        self.assertEqual(
            ("AR",), tuple(item.event.kind for item in second.emissions)
        )

        first_completion = session.step(
            second.state,
            SystemAction(
                VirtualDutPortRef("peripheral", "apb"),
                CanonicalEvent(
                    "READ_RESPONSE", None, {"data": 0x11111111, "error": False}
                ),
            ),
        )
        second_completion = session.step(
            first_completion.state,
            SystemAction(
                VirtualDutPortRef("peripheral", "apb"),
                CanonicalEvent(
                    "READ_RESPONSE", None, {"data": 0x22222222, "error": False}
                ),
            ),
        )

        self.assertIsNone(first_completion.fault)
        self.assertIsNone(second_completion.fault)
        self.assertEqual(
            ("READ_RESPONSE", "R", "READ"),
            tuple(item.event.kind for item in first_completion.emissions),
        )
        self.assertEqual(1, first_completion.emissions[1].event.key)
        self.assertEqual(
            0x1004, first_completion.emissions[-1].event.payload["addr"]
        )
        self.assertEqual(
            ("READ_RESPONSE", "R"),
            tuple(item.event.kind for item in second_completion.emissions),
        )
        self.assertEqual(2, second_completion.emissions[-1].event.key)
        self.assertTrue(session.is_quiescent(second_completion.state))

    def test_aw_w_burst_joins_into_serial_apb_writes_and_one_b(self) -> None:
        session = self._system(capture_apb=True).open_session()
        address = session.step(
            session.initial_state(),
            self._manager_action(
                _address_event("AW", key=5, address=0x8000, length=1)
            ),
        )
        first_data = session.step(
            address.state,
            self._manager_action(
                CanonicalEvent(
                    "W",
                    None,
                    {"data": 0xAABBCCDD, "strb": 0b1111, "last": False},
                )
            ),
        )
        final_data = session.step(
            first_data.state,
            self._manager_action(
                CanonicalEvent(
                    "W",
                    None,
                    {"data": 0x11223344, "strb": 0b0101, "last": True},
                )
            ),
        )

        for transition in (address, first_data, final_data):
            self.assertIsNone(transition.fault)
        first_write = final_data.emissions[-1].event
        self.assertEqual("WRITE", first_write.kind)
        self.assertEqual(0x1000, first_write.payload["addr"])
        self.assertEqual(0b1111, first_write.payload["strb"])

        first_completion = session.step(
            final_data.state,
            SystemAction(
                VirtualDutPortRef("peripheral", "apb"),
                CanonicalEvent("WRITE_RESPONSE", None, {"error": False}),
            ),
        )
        second_write = first_completion.emissions[-1].event
        self.assertIsNone(first_completion.fault)
        self.assertEqual("WRITE", second_write.kind)
        self.assertEqual(0x1004, second_write.payload["addr"])
        self.assertEqual(0b0101, second_write.payload["strb"])

        final_completion = session.step(
            first_completion.state,
            SystemAction(
                VirtualDutPortRef("peripheral", "apb"),
                CanonicalEvent("WRITE_RESPONSE", None, {"error": False}),
            ),
        )

        self.assertIsNone(final_completion.fault)
        self.assertEqual(
            ("WRITE_RESPONSE", "B"),
            tuple(item.event.kind for item in final_completion.emissions),
        )
        response = final_completion.emissions[-1].event
        self.assertEqual(5, response.key)
        self.assertEqual("OKAY", response.payload["resp"])
        self.assertTrue(session.is_quiescent(final_completion.state))

    def test_route_miss_completes_every_axi_read_beat_without_apb_traffic(
        self,
    ) -> None:
        session = self._system().open_session()

        transition = session.step(
            session.initial_state(),
            self._manager_action(
                _address_event("AR", key=7, address=0x9000, length=1)
            ),
        )

        self.assertIsNone(transition.fault)
        self.assertFalse(any(item.link == "apb" for item in transition.emissions))
        responses = tuple(
            item.event
            for item in transition.emissions
            if item.event.kind == "R"
        )
        self.assertEqual(
            ("DECERR", "DECERR"),
            tuple(item.payload["resp"] for item in responses),
        )
        self.assertEqual(
            (False, True), tuple(item.payload["last"] for item in responses)
        )
        self.assertTrue(session.is_quiescent(transition.state))


if __name__ == "__main__":
    unittest.main()

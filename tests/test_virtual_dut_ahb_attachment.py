from __future__ import annotations

import unittest

from protocol_model import (
    AccessResult,
    AccessStatus,
    AddressRoute,
    AddressSpace,
    AddressWrite,
    CanonicalEvent,
    CaptureModel,
    MemoryRegion,
    ProtocolLink,
    ProtocolPort,
    SystemAction,
    SystemProtocol,
    VirtualDut,
    VirtualDutPortRef,
    build_ahb_address_fabric_vdut,
    build_ahb_address_space_vdut,
)
from protocol_model.integrations.attachments.amba.ahb import (
    AhbCompleterAttachment,
    AhbRequesterAttachment,
)
from protocol_model.link.amba.ahb.ahb5 import Ahb5Config, build_ahb5_link
from protocol_model.link.amba.ahb.ahb_lite import build_ahb_lite_link
from protocol_model.virtual_dut.attachments import AddressRequest


class AhbAttachmentTest(unittest.TestCase):
    def test_ahb5_narrow_write_joins_address_data_and_byte_lanes(self) -> None:
        protocol = build_ahb5_link(
            Ahb5Config(
                extended_memory_types=True,
                secure_transfers=True,
                write_strobes=True,
                user_request_width=3,
                user_data_width=4,
                user_response_width=2,
            )
        )
        requester = AhbRequesterAttachment(protocol)
        issued = requester.encode_request(
            requester.initial_state(),
            AddressRequest(
                9,
                AddressWrite(
                    0x1002,
                    2,
                    0xAABB,
                    byte_enable=0b01,
                    attributes={
                        "prot": 0b1000011,
                        "nonsecure": True,
                        "auser": 0b101,
                        "wuser": 0b1010,
                    },
                ),
            ),
        )

        self.assertIsNone(issued.fault)
        self.assertEqual(("WRITE", "WRITE_DATA"), tuple(e.kind for e in issued.events))
        self.assertEqual(0xAABB0000, issued.events[1].payload["data"])
        self.assertEqual(0b0100, issued.events[1].payload["strb"])

        completer = AhbCompleterAttachment(protocol)
        address = completer.decode_request(
            completer.initial_state(), issued.events[0]
        )
        data = completer.decode_request(address.state, issued.events[1])

        self.assertIsNone(address.access)
        self.assertIsInstance(data.access, AddressWrite)
        self.assertEqual(0xAABB, data.access.data)
        self.assertEqual(0b01, data.access.effective_byte_enable)
        self.assertEqual(0b1010, data.access.attributes["wuser"])

        response = completer.encode_completion(
            data.state, data.reply_context, AccessResult()
        )
        completion = requester.decode_completion(issued.state, response.events[0])
        self.assertIsNone(response.fault)
        self.assertEqual(
            {"resp": "OKAY", "buser": 0}, dict(response.events[0].payload)
        )
        self.assertEqual(9, completion.completion.request_id)
        self.assertEqual(AccessStatus.OK, completion.completion.result.status)

    def test_exclusive_ahb5_requires_a_dedicated_backend(self) -> None:
        protocol = build_ahb5_link(Ahb5Config(exclusive_transfers=True))

        with self.assertRaisesRegex(ValueError, "Exclusive Access Monitor"):
            AhbCompleterAttachment(protocol)
        with self.assertRaisesRegex(ValueError, "Exclusive Access Monitor"):
            AhbRequesterAttachment(protocol)


class AhbAddressFabricTest(unittest.TestCase):
    @staticmethod
    def _write_address(address: int) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef("manager", "ahb"),
            CanonicalEvent(
                "WRITE",
                None,
                {
                    "addr": address,
                    "size": 2,
                    "burst": "SINGLE",
                    "trans": "NONSEQ",
                    "prot": 0,
                    "lock": False,
                },
            ),
        )

    @staticmethod
    def _write_data(data: int) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef("manager", "ahb"),
            CanonicalEvent("WRITE_DATA", None, {"data": data}),
        )

    @staticmethod
    def _read(address: int) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef("manager", "ahb"),
            CanonicalEvent(
                "READ",
                None,
                {
                    "addr": address,
                    "size": 2,
                    "burst": "SINGLE",
                    "trans": "NONSEQ",
                    "prot": 0,
                    "lock": False,
                },
            ),
        )

    def _system(self) -> SystemProtocol:
        protocol = build_ahb_lite_link()
        manager = VirtualDut(
            "manager",
            {"ahb": ProtocolPort("ahb", protocol, "manager")},
            model=CaptureModel(),
        )
        fabric = build_ahb_address_fabric_vdut(
            "fabric",
            protocol,
            (AddressRoute("memory", 0x1000, 0x100, "memory"),),
        )
        memory = build_ahb_address_space_vdut(
            "memory",
            protocol,
            AddressSpace((MemoryRegion("ram", 0x100, base_address=0x1000),)),
        )
        links = (
            ProtocolLink(
                "upstream",
                protocol,
                {
                    "manager": VirtualDutPortRef("manager", "ahb"),
                    "subordinate": VirtualDutPortRef("fabric", "upstream"),
                },
            ),
            ProtocolLink(
                "downstream",
                protocol,
                {
                    "manager": VirtualDutPortRef("fabric", "memory"),
                    "subordinate": VirtualDutPortRef("memory", "ahb"),
                },
            ),
        )
        return SystemProtocol(
            "ahb_fabric",
            {item.name: item for item in (manager, fabric, memory)},
            {item.name: item for item in links},
        )

    def test_write_join_routes_then_returns_read_and_decode_error(self) -> None:
        session = self._system().open_session()
        state = session.initial_state()

        address = session.step(state, self._write_address(0x1000))
        written = session.step(address.state, self._write_data(0x11223344))
        read = session.step(written.state, self._read(0x1000))
        missing = session.step(read.state, self._read(0x2000))

        for transition in (address, written, read, missing):
            self.assertIsNone(transition.fault)
        self.assertEqual(("WRITE",), tuple(e.event.kind for e in address.emissions))
        self.assertEqual(
            (
                "WRITE_DATA",
                "WRITE",
                "WRITE_DATA",
                "WRITE_RESPONSE",
                "WRITE_RESPONSE",
            ),
            tuple(e.event.kind for e in written.emissions),
        )
        self.assertEqual(0x11223344, read.emissions[-1].event.payload["data"])
        self.assertEqual("ERROR", missing.emissions[-1].event.payload["resp"])
        self.assertTrue(session.is_quiescent(missing.state))


if __name__ == "__main__":
    unittest.main()

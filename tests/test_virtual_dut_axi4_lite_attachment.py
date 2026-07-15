from __future__ import annotations

import unittest

from protocol_model import (
    AccessResult,
    AccessStatus,
    AddressRead,
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
)
from protocol_model.integrations.attachments.amba.axi.axi4_lite import (
    Axi4LiteCompleterAttachment,
    Axi4LiteRequesterAttachment,
)
from protocol_model.integrations.recipes.amba.endpoints import (
    build_axi4_lite_address_space_vdut,
)
from protocol_model.link.amba.axi.axi4_lite import build_axi4_lite_link
from protocol_model.virtual_dut.attachments import AddressRequest


class Axi4LiteAttachmentTest(unittest.TestCase):
    def test_w_before_aw_joins_and_preserves_unaligned_byte_lanes(self) -> None:
        protocol = build_axi4_lite_link()
        completer = Axi4LiteCompleterAttachment(protocol)
        data = completer.decode_request(
            completer.initial_state(),
            CanonicalEvent("W", None, {"data": 0xAABBCCDD, "strb": 0b1100}),
        )
        joined = completer.decode_request(
            data.state,
            CanonicalEvent("AW", None, {"addr": 0x1002, "prot": 0b101}),
        )

        self.assertIsNone(data.access)
        self.assertIsInstance(joined.access, AddressWrite)
        self.assertEqual(2, joined.access.size)
        self.assertEqual(0xAABB, joined.access.data)
        self.assertEqual(0b11, joined.access.effective_byte_enable)
        self.assertEqual(0b101, joined.access.attributes["prot"])

        response = completer.encode_completion(
            joined.state,
            joined.reply_context,
            AccessResult(status=AccessStatus.DECODE_ERROR),
        )
        self.assertEqual("DECERR", response.events[0].payload["resp"])
        self.assertTrue(completer.is_quiescent(response.state))

    def test_requester_correlates_read_and_write_independently(self) -> None:
        protocol = build_axi4_lite_link()
        requester = Axi4LiteRequesterAttachment(protocol)
        read = requester.encode_request(
            requester.initial_state(),
            AddressRequest(
                3,
                # Native Lite has an implicit full-width transfer.
                AddressRead(0x1000, 4),
            ),
        )
        write = requester.encode_request(
            read.state,
            AddressRequest(7, AddressWrite(0x1004, 4, 0x11223344)),
        )

        completed_write = requester.decode_completion(
            write.state, CanonicalEvent("B", None, {"resp": "SLVERR"})
        )
        completed_read = requester.decode_completion(
            completed_write.state,
            CanonicalEvent(
                "R", None, {"data": 0xAABBCCDD, "resp": "OKAY"}
            ),
        )

        self.assertEqual(7, completed_write.completion.request_id)
        self.assertEqual(
            AccessStatus.ACCESS_ERROR,
            completed_write.completion.result.status,
        )
        self.assertEqual(3, completed_read.completion.request_id)
        self.assertEqual(0xAABBCCDD, completed_read.completion.result.data)
        self.assertTrue(requester.is_quiescent(completed_read.state))

    def test_address_space_endpoint_executes_write_read_and_decode_error(self) -> None:
        protocol = build_axi4_lite_link()
        manager = VirtualDut(
            "manager",
            {"axi": ProtocolPort("axi", protocol, "manager")},
            model=CaptureModel(),
        )
        memory = build_axi4_lite_address_space_vdut(
            "memory",
            protocol,
            AddressSpace((MemoryRegion("ram", 0x100, base_address=0x1000),)),
        )
        link = ProtocolLink(
            "axi_bus",
            protocol,
            {
                "manager": VirtualDutPortRef("manager", "axi"),
                "subordinate": VirtualDutPortRef("memory", "axi"),
            },
        )
        session = SystemProtocol(
            "axi4_lite_endpoint",
            {item.name: item for item in (manager, memory)},
            {link.name: link},
        ).open_session()
        state = session.initial_state()

        write_data = session.step(
            state,
            SystemAction(
                VirtualDutPortRef("manager", "axi"),
                CanonicalEvent(
                    "W", None, {"data": 0x11223344, "strb": 0b1111}
                ),
            ),
        )
        written = session.step(
            write_data.state,
            SystemAction(
                VirtualDutPortRef("manager", "axi"),
                CanonicalEvent("AW", None, {"addr": 0x1000, "prot": 0}),
            ),
        )
        read = session.step(
            written.state,
            SystemAction(
                VirtualDutPortRef("manager", "axi"),
                CanonicalEvent("AR", None, {"addr": 0x1000, "prot": 0}),
            ),
        )
        missing = session.step(
            read.state,
            SystemAction(
                VirtualDutPortRef("manager", "axi"),
                CanonicalEvent("AR", None, {"addr": 0x2000, "prot": 0}),
            ),
        )

        for transition in (write_data, written, read, missing):
            self.assertIsNone(transition.fault)
        self.assertEqual("B", written.emissions[-1].event.kind)
        self.assertEqual(0x11223344, read.emissions[-1].event.payload["data"])
        self.assertEqual("DECERR", missing.emissions[-1].event.payload["resp"])
        self.assertTrue(session.is_quiescent(missing.state))


if __name__ == "__main__":
    unittest.main()

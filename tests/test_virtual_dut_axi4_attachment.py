from __future__ import annotations

import unittest

from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4AddressSpaceAttachment,
    Axi4RequesterAttachment,
)
from protocol_model.integrations.recipes.amba.endpoints import (
    build_axi4_address_space_vdut,
)
from protocol_model.link.amba.axi.axi4 import Axi4Config, build_axi4_link
from protocol_model.semantics import CanonicalEvent
from protocol_model.system import (
    ProtocolLink,
    SystemAction,
    SystemProtocol,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address import (
    AccessStatus,
    AddressRead,
    AddressSpace,
    AddressWrite,
    MemoryRegion,
)
from protocol_model.virtual_dut.attachments import AddressRequest
from protocol_model.virtual_dut.backend import CaptureModel
from protocol_model.virtual_dut.boundary import ProtocolPort, VirtualDut


def _address_event(
    kind: str,
    *,
    key: int,
    address: int,
    length: int = 0,
    size: int = 2,
    burst: str = "INCR",
    lock: int = 0,
) -> CanonicalEvent:
    return CanonicalEvent(
        kind,
        key,
        {
            "addr": address,
            "len": length,
            "size": size,
            "burst": burst,
            "lock": lock,
            "cache": 0,
            "prot": 0,
            "qos": 0,
            "region": 0,
        },
    )


class Axi4AddressSpaceEndpointTest(unittest.TestCase):
    def _system(
        self, address_space: AddressSpace
    ) -> tuple[SystemProtocol, VirtualDutPortRef]:
        protocol = build_axi4_link(Axi4Config(data_width=32))
        manager_port = VirtualDutPortRef("manager", "axi")
        manager = VirtualDut(
            "manager",
            {"axi": ProtocolPort("axi", protocol, "manager")},
            model=CaptureModel(),
        )
        endpoint = build_axi4_address_space_vdut(
            "memory", protocol, address_space
        )
        link = ProtocolLink(
            "axi",
            protocol,
            {
                "manager": manager_port,
                "subordinate": VirtualDutPortRef("memory", "axi"),
            },
        )
        return (
            SystemProtocol(
                "axi_address_space",
                {item.name: item for item in (manager, endpoint)},
                {link.name: link},
            ),
            manager_port,
        )

    def test_narrow_incr_read_emits_one_lane_mapped_r_per_beat(self) -> None:
        system, manager = self._system(
            AddressSpace(
                (
                    MemoryRegion(
                        "ram",
                        0x100,
                        base_address=0x1000,
                        initial_content=bytes.fromhex("112233445566"),
                    ),
                )
            )
        )
        session = system.open_session()

        transition = session.step(
            session.initial_state(),
            SystemAction(
                manager,
                _address_event(
                    "AR", key=3, address=0x1000, length=2, size=1
                ),
            ),
        )

        self.assertIsNone(transition.fault)
        responses = [
            item.event for item in transition.emissions if item.event.kind == "R"
        ]
        self.assertEqual(3, len(responses))
        self.assertEqual((0x2211, 0x44330000, 0x6655), tuple(
            item.payload["data"] for item in responses
        ))
        self.assertEqual((False, False, True), tuple(
            item.payload["last"] for item in responses
        ))
        self.assertEqual((3, 3, 3), tuple(item.key for item in responses))
        self.assertTrue(session.is_quiescent(transition.state))

    def test_pre_aw_write_burst_joins_and_preserves_partial_strobes(self) -> None:
        system, manager = self._system(
            AddressSpace((MemoryRegion("ram", 0x100, base_address=0x1000),))
        )
        session = system.open_session()
        state = session.initial_state()

        first = session.step(
            state,
            SystemAction(
                manager,
                CanonicalEvent(
                    "W",
                    None,
                    {"data": 0xBBAA0000, "strb": 0b0100, "last": False},
                ),
            ),
        )
        second = session.step(
            first.state,
            SystemAction(
                manager,
                CanonicalEvent(
                    "W",
                    None,
                    {"data": 0x0000DDCC, "strb": 0b0011, "last": True},
                ),
            ),
        )
        joined = session.step(
            second.state,
            SystemAction(
                manager,
                _address_event(
                    "AW", key=5, address=0x1002, length=1, size=1
                ),
            ),
        )
        read = session.step(
            joined.state,
            SystemAction(
                manager,
                _address_event(
                    "AR", key=6, address=0x1002, length=1, size=1
                ),
            ),
        )

        for transition in (first, second, joined, read):
            self.assertIsNone(transition.fault)
        self.assertEqual("OKAY", joined.emissions[-1].event.payload["resp"])
        read_data = tuple(
            item.event.payload["data"]
            for item in read.emissions
            if item.event.kind == "R"
        )
        self.assertEqual((0x00AA0000, 0x0000DDCC), read_data)
        self.assertTrue(session.is_quiescent(read.state))

    def test_wrap_request_expands_to_ordered_address_accesses(self) -> None:
        protocol = build_axi4_link(Axi4Config(data_width=32))
        attachment = Axi4AddressSpaceAttachment(protocol)

        decoded = attachment.decode_request(
            attachment.initial_state(),
            _address_event(
                "AR",
                key=1,
                address=0x1006,
                length=3,
                size=1,
                burst="WRAP",
            ),
        )
        locked = attachment.decode_request(
            attachment.initial_state(),
            _address_event("AR", key=1, address=0x1000, lock=1),
        )

        self.assertIsNone(decoded.fault)
        self.assertEqual(
            (0x1006, 0x1000, 0x1002, 0x1004),
            tuple(item.address for item in decoded.request.accesses),
        )
        self.assertEqual("axi4_address_space_attachment.exclusive", locked.fault.rule)

    def test_read_and_write_burst_errors_keep_axi_completion_shape(self) -> None:
        system, manager = self._system(
            AddressSpace(
                (
                    MemoryRegion(
                        "rom", 0x100, base_address=0x1000, read_only=True
                    ),
                )
            )
        )
        session = system.open_session()
        missing = session.step(
            session.initial_state(),
            SystemAction(
                manager,
                _address_event(
                    "AR", key=1, address=0x2000, length=1, size=2
                ),
            ),
        )
        address = session.step(
            missing.state,
            SystemAction(
                manager,
                _address_event(
                    "AW", key=2, address=0x1000, length=1, size=2
                ),
            ),
        )
        first = session.step(
            address.state,
            SystemAction(
                manager,
                CanonicalEvent(
                    "W",
                    None,
                    {"data": 0x11223344, "strb": 0b1111, "last": False},
                ),
            ),
        )
        final = session.step(
            first.state,
            SystemAction(
                manager,
                CanonicalEvent(
                    "W",
                    None,
                    {"data": 0x55667788, "strb": 0b1111, "last": True},
                ),
            ),
        )

        for transition in (missing, address, first, final):
            self.assertIsNone(transition.fault)
        read_responses = tuple(
            item.event
            for item in missing.emissions
            if item.event.kind == "R"
        )
        self.assertEqual(2, len(read_responses))
        self.assertEqual(
            ("DECERR", "DECERR"),
            tuple(item.payload["resp"] for item in read_responses),
        )
        self.assertTrue(read_responses[-1].payload["last"])
        self.assertEqual("SLVERR", final.emissions[-1].event.payload["resp"])
        self.assertTrue(session.is_quiescent(final.state))


class Axi4RequesterAttachmentTest(unittest.TestCase):
    def test_serialized_requester_uses_local_wire_id_and_maps_errors(self) -> None:
        protocol = build_axi4_link(Axi4Config(data_width=32, id_width=2))
        requester = Axi4RequesterAttachment(protocol, wire_id=3)
        issued = requester.encode_request(
            requester.initial_state(),
            AddressRequest(
                10_000,
                AddressWrite(
                    0x1002,
                    2,
                    0xBBAA,
                    byte_enable=0b01,
                    attributes={"prot": 0b101},
                ),
            ),
        )

        self.assertIsNone(issued.fault)
        self.assertEqual(("AW", "W"), tuple(item.kind for item in issued.events))
        self.assertEqual(3, issued.events[0].key)
        self.assertEqual(0, issued.events[0].payload["len"])
        self.assertEqual(1, issued.events[0].payload["size"])
        self.assertEqual(0xBBAA0000, issued.events[1].payload["data"])
        self.assertEqual(0b0100, issued.events[1].payload["strb"])

        busy = requester.encode_request(
            issued.state, AddressRequest(10_001, AddressRead(0x1000, 4))
        )
        completed = requester.decode_completion(
            issued.state,
            CanonicalEvent("B", 3, {"resp": "DECERR"}),
        )

        self.assertEqual("axi4_requester.busy", busy.fault.rule)
        self.assertEqual(10_000, completed.completion.request_id)
        self.assertEqual(
            AccessStatus.DECODE_ERROR, completed.completion.result.status
        )
        self.assertTrue(requester.is_quiescent(completed.state))


if __name__ == "__main__":
    unittest.main()

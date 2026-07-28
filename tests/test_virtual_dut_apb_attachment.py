from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.endpoints import (
    build_apb_address_space_vdut,
)
from protocol_model.semantics import CanonicalEvent
from protocol_model.system import (
    InterfaceConnection,
    SystemAction,
    SystemProtocol,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address import (
    AccessResult,
    AddressSpace,
    AddressWrite,
    RegisterRegion,
    RegisterSpec,
)
from protocol_model.virtual_dut.backend import CaptureBackend, CaptureState
from protocol_model.virtual_dut.boundary import InterfacePort, VirtualDut
from protocol_model.integrations.attachments.amba.apb import (
    ApbCompleterAttachment,
    ApbRequesterAttachment,
)
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.protocols.amba.apb.apb5 import Apb5Config, build_apb5_interface
from protocol_model.virtual_dut.attachments import AddressRequest


class ApbAddressSpaceEndpointTest(unittest.TestCase):
    def test_apb5_attachment_derives_optional_fields_from_schema(self) -> None:
        protocol = build_apb5_interface(
            Apb5Config(
                rme_support=True,
                user_request_width=4,
                user_data_width=8,
                user_response_width=3,
            )
        )
        requester = ApbRequesterAttachment(protocol)
        issued = requester.encode_request(
            requester.initial_state(),
            AddressRequest(
                7,
                AddressWrite(
                    0x1000,
                    4,
                    0xAABBCCDD,
                    attributes={
                        "prot": 0b010,
                        "nse": True,
                        "auser": 0xA,
                        "wuser": 0x5A,
                    },
                ),
            ),
        )
        self.assertIsNone(issued.fault)
        self.assertEqual(
            {
                "addr": 0x1000,
                "prot": 0b010,
                "nse": True,
                "auser": 0xA,
                "data": 0xAABBCCDD,
                "strb": 0b1111,
                "wuser": 0x5A,
            },
            dict(issued.events[0].payload),
        )

        completer = ApbCompleterAttachment(protocol)
        decoded = completer.decode_request(None, issued.events[0])
        completion = completer.encode_completion(
            decoded.state, decoded.reply_context, AccessResult()
        )
        self.assertIsNone(completion.fault)
        self.assertEqual(
            {"error": False, "buser": 0},
            dict(completion.events[0].payload),
        )

    def test_apb_interface_executes_register_write_read_and_decode_error(self) -> None:
        protocol = build_apb4_interface()
        manager = VirtualDut(
            "manager",
            {"apb": InterfacePort("apb", protocol, "requester")},
            backend=CaptureBackend(),
        )
        registers = build_apb_address_space_vdut(
            "registers",
            protocol,
            AddressSpace(
                (
                    RegisterRegion(
                        "control",
                        (RegisterSpec("value", 0, reset=0x11223344),),
                        base_address=0x1000,
                    ),
                )
            ),
        )
        link = InterfaceConnection(
            "apb_bus",
            protocol,
            {
                "requester": VirtualDutPortRef("manager", "apb"),
                "completer": VirtualDutPortRef("registers", "apb"),
            },
        )
        system = SystemProtocol(
            "apb_register_system",
            {item.name: item for item in (manager, registers)},
            {link.name: link},
        )
        session = system.open_session()
        state = session.initial_state()

        written = session.step(
            state,
            SystemAction(
                VirtualDutPortRef("manager", "apb"),
                CanonicalEvent(
                    "WRITE",
                    None,
                    {
                        "addr": 0x1000,
                        "prot": 0b101,
                        "data": 0xAABBCCDD,
                        "strb": 0b1111,
                    },
                ),
            ),
        )
        read = session.step(
            written.state,
            SystemAction(
                VirtualDutPortRef("manager", "apb"),
                CanonicalEvent("READ", None, {"addr": 0x1000, "prot": 0b010}),
            ),
        )
        missing = session.step(
            read.state,
            SystemAction(
                VirtualDutPortRef("manager", "apb"),
                CanonicalEvent("READ", None, {"addr": 0x2000, "prot": 0}),
            ),
        )

        self.assertIsNone(written.fault)
        self.assertIsNone(read.fault)
        self.assertIsNone(missing.fault)
        self.assertEqual(
            ("WRITE", "WRITE_RESPONSE"),
            tuple(item.event.kind for item in written.emissions),
        )
        self.assertEqual(0xAABBCCDD, read.emissions[-1].event.payload["data"])
        self.assertFalse(read.emissions[-1].event.payload["error"])
        self.assertTrue(missing.emissions[-1].event.payload["error"])
        manager_state = missing.state.dut_states["manager"]
        self.assertIsInstance(manager_state, CaptureState)
        self.assertEqual(3, len(manager_state.received))


if __name__ == "__main__":
    unittest.main()

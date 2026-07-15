from __future__ import annotations

import unittest

from protocol_model.link.amba.axi.axi4_stream import (
    Axi4StreamConfig,
    build_axi4_stream_link,
)
from protocol_model.integrations.attachments.amba.axi.axi4_stream import (
    Axi4StreamReceiverAttachment,
    Axi4StreamTransmitterAttachment,
)
from protocol_model.integrations.recipes.amba.endpoints import (
    build_axi4_stream_capture_vdut,
)
from protocol_model.semantics import CanonicalEvent
from protocol_model.system import (
    ProtocolLink,
    SystemAction,
    SystemProtocol,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.attachments.stream import StreamTransfer
from protocol_model.virtual_dut.backend.stream import StreamCaptureState
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import ProtocolPort


class Axi4StreamAttachmentTest(unittest.TestCase):
    def test_optional_sidebands_round_trip_through_stream_operation(self) -> None:
        protocol = build_axi4_stream_link(
            Axi4StreamConfig(
                data_width=24,
                id_width=2,
                dest_width=3,
                user_width=4,
                use_keep=True,
                use_strb=True,
                use_last=True,
            )
        )
        transfer = StreamTransfer(
            data=0xA1B2C3,
            lane_count=3,
            keep=0b011,
            strobe=0b001,
            packet_end=True,
            stream_id=2,
            destination=5,
            attributes={"user": 0xA},
        )
        transmitter = Axi4StreamTransmitterAttachment(protocol)
        emitted = transmitter.encode_transfer(
            transmitter.initial_state(), transfer
        )
        receiver = Axi4StreamReceiverAttachment(protocol)
        decoded = receiver.decode_transfer(
            receiver.initial_state(), emitted.events[0]
        )

        self.assertIsNone(emitted.fault)
        self.assertIsNone(decoded.fault)
        self.assertEqual(transfer, decoded.transfer)

    def test_absent_optional_signals_reject_unrepresentable_transfer(self) -> None:
        protocol = build_axi4_stream_link(
            Axi4StreamConfig(
                data_width=16,
                use_keep=False,
                use_strb=False,
                use_last=False,
            )
        )
        transmitter = Axi4StreamTransmitterAttachment(protocol)

        null_byte = transmitter.encode_transfer(
            transmitter.initial_state(),
            StreamTransfer(
                data=0x11,
                lane_count=2,
                keep=0b01,
                strobe=0b01,
            ),
        )
        packet_boundary = transmitter.encode_transfer(
            transmitter.initial_state(),
            StreamTransfer(
                data=0x11,
                lane_count=2,
                keep=0b11,
                strobe=0b11,
                packet_end=True,
            ),
        )

        self.assertEqual("axi4_stream_transmitter.keep", null_byte.fault.rule)
        self.assertEqual(
            "axi4_stream_transmitter.packet_end", packet_boundary.fault.rule
        )

    def test_capture_backend_retains_normalized_transfer(self) -> None:
        protocol = build_axi4_stream_link(
            Axi4StreamConfig(data_width=16, use_keep=True)
        )
        source = VirtualDut(
            "source",
            {
                "stream": ProtocolPort(
                    "stream", protocol, "transmitter"
                )
            },
        )
        capture = build_axi4_stream_capture_vdut("capture", protocol)
        link = ProtocolLink(
            "stream_link",
            protocol,
            {
                "transmitter": VirtualDutPortRef("source", "stream"),
                "receiver": VirtualDutPortRef("capture", "stream"),
            },
        )
        system = SystemProtocol(
            "stream_capture_system",
            {item.name: item for item in (source, capture)},
            {link.name: link},
        )
        session = system.open_session()
        transition = session.step(
            session.initial_state(),
            SystemAction(
                VirtualDutPortRef("source", "stream"),
                CanonicalEvent(
                    "T",
                    None,
                    {"data": 0x2211, "keep": 0b01, "last": True},
                ),
            ),
        )

        self.assertIsNone(transition.fault)
        state = transition.state.dut_states["capture"]
        self.assertIsInstance(state, StreamCaptureState)
        self.assertEqual(1, len(state.captured))
        self.assertEqual("stream", state.captured[0].port)
        self.assertEqual(0b01, state.captured[0].transfer.keep)
        self.assertEqual(0b01, state.captured[0].transfer.strobe)
        self.assertEqual(0x2211, state.captured[0].transfer.data)
        self.assertTrue(session.is_quiescent(transition.state))


if __name__ == "__main__":
    unittest.main()

"""AXI4-Stream receiver integration."""

from __future__ import annotations

from protocol_model.link import LinkProtocol
from protocol_model.semantics import CanonicalEvent
from protocol_model.virtual_dut.attachments.stream import (
    StreamReceiverAttachment,
    StreamTransfer,
    StreamTransferDecode,
)
from protocol_model.virtual_dut.attachments.validation import incoming_event_fault

from .common import require_axi4_stream_role


class Axi4StreamReceiverAttachment(StreamReceiverAttachment):
    """Normalize one accepted T transfer into a protocol-neutral stream beat."""

    role = "receiver"

    def __init__(self, protocol: LinkProtocol) -> None:
        require_axi4_stream_role(protocol, self.role)
        self.protocol = protocol
        self.lane_count = int(protocol.parameters["data_width"]) // 8
        self.fields = frozenset(protocol.channels["T"].event.fields)

    def decode_transfer(
        self, state: object, event: CanonicalEvent
    ) -> StreamTransferDecode:
        fault = incoming_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="axi4_stream_receiver",
        )
        if fault is not None:
            return StreamTransferDecode(state, fault=fault)
        full_mask = (1 << self.lane_count) - 1
        keep = int(event.payload.get("keep", full_mask))
        strobe = int(event.payload.get("strb", keep))
        attributes = (
            {"user": int(event.payload["user"])}
            if "user" in self.fields
            else {}
        )
        return StreamTransferDecode(
            state,
            StreamTransfer(
                data=int(event.payload["data"]),
                lane_count=self.lane_count,
                keep=keep,
                strobe=strobe,
                packet_end=(
                    bool(event.payload["last"])
                    if "last" in self.fields
                    else None
                ),
                stream_id=event.key,
                destination=(
                    int(event.payload["dest"])
                    if "dest" in self.fields
                    else None
                ),
                attributes=attributes,
            ),
        )

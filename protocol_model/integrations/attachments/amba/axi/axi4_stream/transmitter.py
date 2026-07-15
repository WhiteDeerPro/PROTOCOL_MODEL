"""AXI4-Stream transmitter integration."""

from __future__ import annotations

from protocol_model.link import LinkProtocol
from protocol_model.semantics import CanonicalEvent, ConstraintScope, SemanticFault
from protocol_model.virtual_dut.attachments.base import AttachmentEmission
from protocol_model.virtual_dut.attachments.stream import (
    StreamTransfer,
    StreamTransmitterAttachment,
)
from protocol_model.virtual_dut.attachments.validation import outgoing_event_fault

from .common import require_axi4_stream_role


class Axi4StreamTransmitterAttachment(StreamTransmitterAttachment):
    """Encode representable stream transfers as accepted T events.

    Width conversion and packet-boundary synthesis are cross-port policies and
    are therefore left to a stream bridge backend.
    """

    role = "transmitter"

    def __init__(self, protocol: LinkProtocol) -> None:
        require_axi4_stream_role(protocol, self.role)
        self.protocol = protocol
        self.lane_count = int(protocol.parameters["data_width"]) // 8
        self.fields = frozenset(protocol.channels["T"].event.fields)
        self.id_present = bool(int(protocol.parameters["id_width"]))

    def encode_transfer(
        self, state: object, transfer: StreamTransfer
    ) -> AttachmentEmission:
        if not isinstance(transfer, StreamTransfer):
            raise TypeError(
                "Axi4StreamTransmitterAttachment requires StreamTransfer"
            )
        if transfer.lane_count != self.lane_count:
            return self._reject(
                state,
                "width",
                "stream transfer lane count does not match AXI4-Stream data width",
            )
        full_mask = (1 << self.lane_count) - 1
        if "keep" not in self.fields and transfer.keep != full_mask:
            return self._reject(
                state,
                "keep",
                "this AXI4-Stream port has no TKEEP and cannot carry null bytes",
            )
        if "strb" not in self.fields and transfer.strobe != transfer.keep:
            return self._reject(
                state,
                "strobe",
                "this AXI4-Stream port has no TSTRB and cannot carry position bytes",
            )
        if "last" in self.fields:
            if transfer.packet_end is None:
                return self._reject(
                    state,
                    "packet_end",
                    "a port with TLAST requires an explicit packet boundary value",
                )
        elif transfer.packet_end is not None:
            return self._reject(
                state,
                "packet_end",
                "this AXI4-Stream port cannot represent packet boundaries",
            )
        if not self.id_present and transfer.stream_id not in (None, 0):
            return self._reject(
                state,
                "stream_id",
                "this AXI4-Stream port cannot represent a nonzero TID",
            )
        if "dest" not in self.fields and transfer.destination not in (None, 0):
            return self._reject(
                state,
                "destination",
                "this AXI4-Stream port cannot represent a nonzero TDEST",
            )
        supported_attributes = {"user"} if "user" in self.fields else set()
        unknown = set(transfer.attributes) - supported_attributes
        if unknown:
            return self._reject(
                state,
                "attributes",
                "this AXI4-Stream port cannot encode attributes "
                f"{sorted(unknown)!r}",
            )

        payload: dict[str, object] = {"data": transfer.data}
        if "keep" in self.fields:
            payload["keep"] = transfer.keep
        if "strb" in self.fields:
            payload["strb"] = transfer.strobe
        if "last" in self.fields:
            payload["last"] = transfer.packet_end
        if "dest" in self.fields:
            payload["dest"] = (
                0 if transfer.destination is None else transfer.destination
            )
        if "user" in self.fields:
            payload["user"] = transfer.attributes.get("user", 0)
        event = CanonicalEvent(
            "T",
            (
                0
                if self.id_present and transfer.stream_id is None
                else transfer.stream_id
                if self.id_present
                else None
            ),
            payload,
        )
        fault = outgoing_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="axi4_stream_transmitter",
        )
        if fault is not None:
            return AttachmentEmission(state, fault=fault)
        return AttachmentEmission(state, (event,))

    @staticmethod
    def _reject(
        state: object, suffix: str, message: str
    ) -> AttachmentEmission:
        return AttachmentEmission(
            state,
            fault=SemanticFault(
                f"axi4_stream_transmitter.{suffix}",
                message,
                ConstraintScope.VIRTUAL_DUT,
            ),
        )

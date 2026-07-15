"""AHB subordinate integration for protocol-independent address backends."""

from __future__ import annotations

from protocol_model.link import LinkProtocol
from protocol_model.semantics import CanonicalEvent, ConstraintScope, SemanticFault
from protocol_model.virtual_dut.address.access import (
    AccessResult,
    AddressRead,
    AddressWrite,
    ByteOrder,
)
from protocol_model.virtual_dut.attachments.address import (
    AddressCompleterAttachment,
    AddressRequestDecode,
    AttachmentEmission,
)
from protocol_model.virtual_dut.attachments.validation import (
    incoming_event_fault,
    outgoing_event_fault,
)

from .common import (
    AhbAccessContext,
    AhbCompleterState,
    default_payload_value,
    extract_transfer_strobes,
    extract_transfer_value,
    place_transfer_value,
    require_ahb_address_profile,
)


class AhbCompleterAttachment(AddressCompleterAttachment):
    """Join AHB write address/data events and serve AddressAccess operations."""

    role = "subordinate"

    def __init__(
        self,
        protocol: LinkProtocol,
        *,
        byte_order: ByteOrder | str = ByteOrder.LITTLE,
    ) -> None:
        self.byte_order = require_ahb_address_profile(
            protocol, self.role, byte_order
        )
        self.protocol = protocol
        self.data_width = int(protocol.parameters["data_width"])
        self.bus_bytes = self.data_width // 8
        self.write_data_fields = frozenset(
            protocol.channels["WRITE_DATA"].event.fields
        )

    def initial_state(self) -> AhbCompleterState:
        return AhbCompleterState()

    @staticmethod
    def _request_attributes(event: CanonicalEvent) -> dict[str, object]:
        return {
            name: value
            for name, value in event.payload.items()
            if name not in {"addr", "size", "burst", "trans"}
        }

    def decode_request(
        self, state: object, event: CanonicalEvent
    ) -> AddressRequestDecode:
        if not isinstance(state, AhbCompleterState):
            raise TypeError("AhbCompleterAttachment requires AhbCompleterState")
        fault = incoming_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="ahb_completer",
        )
        if fault is not None:
            return AddressRequestDecode(state, fault=fault)

        if event.kind in {"READ", "WRITE"}:
            if state.pending_write is not None:
                return AddressRequestDecode(
                    state,
                    fault=self._fault(
                        "write_join",
                        "AHB write address is still waiting for WRITE_DATA",
                    ),
                )
            size = 1 << int(event.payload["size"])
            context = AhbAccessContext(
                event.kind,
                int(event.payload["addr"]),
                size,
                self._request_attributes(event),
            )
            if event.kind == "WRITE":
                return AddressRequestDecode(AhbCompleterState(context))
            return AddressRequestDecode(
                state,
                AddressRead(context.address, context.size, context.attributes),
                context,
            )

        if event.kind != "WRITE_DATA":
            return AddressRequestDecode(
                state,
                fault=self._fault(
                    "direction", f"AHB subordinate cannot consume {event.kind!r}"
                ),
            )
        context = state.pending_write
        if context is None:
            return AddressRequestDecode(
                state,
                fault=self._fault(
                    "orphan_write_data", "WRITE_DATA has no saved write address"
                ),
            )
        attributes = dict(context.attributes)
        for name in self.write_data_fields - {"data", "strb"}:
            attributes[name] = event.payload[name]
        data = extract_transfer_value(
            int(event.payload["data"]),
            address=context.address,
            size=context.size,
            bus_bytes=self.bus_bytes,
        )
        byte_enable = (
            extract_transfer_strobes(
                int(event.payload["strb"]),
                address=context.address,
                size=context.size,
                bus_bytes=self.bus_bytes,
            )
            if "strb" in self.write_data_fields
            else (1 << context.size) - 1
        )
        return AddressRequestDecode(
            AhbCompleterState(),
            AddressWrite(
                context.address,
                context.size,
                data,
                byte_enable,
                attributes,
            ),
            context,
        )

    def encode_completion(
        self, state: object, context: object | None, result: AccessResult
    ) -> AttachmentEmission:
        if not isinstance(state, AhbCompleterState):
            raise TypeError("AhbCompleterAttachment requires AhbCompleterState")
        if not isinstance(context, AhbAccessContext):
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "context", "AHB attachment lost its transfer context"
                ),
            )
        if context.request_kind == "READ" and result.succeeded and result.data is None:
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "read_data", "successful AHB read completion requires data"
                ),
            )

        response_kind = (
            "READ_RESPONSE"
            if context.request_kind == "READ"
            else "WRITE_RESPONSE"
        )
        fields = self.protocol.channels[response_kind].event.fields
        payload = {
            name: default_payload_value(field)
            for name, field in fields.items()
            if name not in {"data", "resp"}
        }
        payload["resp"] = "OKAY" if result.succeeded else "ERROR"
        if response_kind == "READ_RESPONSE":
            value = 0 if result.data is None else int(result.data)
            try:
                payload["data"] = place_transfer_value(
                    value,
                    address=context.address,
                    size=context.size,
                    bus_bytes=self.bus_bytes,
                )
            except ValueError as error:
                return AttachmentEmission(
                    state, fault=self._fault("read_data", str(error))
                )
        event = CanonicalEvent(response_kind, None, payload)
        fault = outgoing_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="ahb_completer",
        )
        if fault is not None:
            return AttachmentEmission(state, fault=fault)
        return AttachmentEmission(state, (event,))

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, AhbCompleterState)
            and state.pending_write is None
        )

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"ahb_completer.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )

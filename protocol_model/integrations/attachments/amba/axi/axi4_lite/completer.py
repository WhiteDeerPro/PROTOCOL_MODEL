"""AXI4-Lite subordinate integration for address-oriented backends."""

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
    Axi4LiteAccessContext,
    Axi4LiteCompleterState,
    Axi4LiteWriteData,
    access_status_to_response,
    extract_transfer_strobes,
    extract_transfer_value,
    implicit_transfer_geometry,
    place_transfer_value,
    require_axi4_lite_address_profile,
)


class Axi4LiteCompleterAttachment(AddressCompleterAttachment):
    """FIFO-join independent AW/W events and serve AddressAccess operations."""

    role = "subordinate"

    def __init__(
        self,
        protocol: LinkProtocol,
        *,
        byte_order: ByteOrder | str = ByteOrder.LITTLE,
    ) -> None:
        self.byte_order = require_axi4_lite_address_profile(
            protocol, self.role, byte_order
        )
        self.protocol = protocol
        self.data_width = int(protocol.parameters["data_width"])
        self.bus_bytes = self.data_width // 8

    def initial_state(self) -> Axi4LiteCompleterState:
        return Axi4LiteCompleterState()

    def _address_context(
        self, event: CanonicalEvent, request_kind: str
    ) -> Axi4LiteAccessContext:
        address = int(event.payload["addr"])
        _, size = implicit_transfer_geometry(address, self.bus_bytes)
        return Axi4LiteAccessContext(
            request_kind,
            address,
            size,
            {"prot": event.payload["prot"]},
        )

    def _joined_write(
        self,
        state: Axi4LiteCompleterState,
        context: Axi4LiteAccessContext,
        data: Axi4LiteWriteData,
    ) -> AddressRequestDecode:
        return AddressRequestDecode(
            state,
            AddressWrite(
                context.address,
                context.size,
                extract_transfer_value(
                    data.data,
                    address=context.address,
                    bus_bytes=self.bus_bytes,
                ),
                extract_transfer_strobes(
                    data.strb,
                    address=context.address,
                    bus_bytes=self.bus_bytes,
                ),
                context.attributes,
            ),
            context,
        )

    def decode_request(
        self, state: object, event: CanonicalEvent
    ) -> AddressRequestDecode:
        if not isinstance(state, Axi4LiteCompleterState):
            raise TypeError(
                "Axi4LiteCompleterAttachment requires Axi4LiteCompleterState"
            )
        fault = incoming_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="axi4_lite_completer",
        )
        if fault is not None:
            return AddressRequestDecode(state, fault=fault)

        if event.kind == "AR":
            context = self._address_context(event, "READ")
            return AddressRequestDecode(
                state,
                AddressRead(
                    context.address, context.size, context.attributes
                ),
                context,
            )

        if event.kind == "AW":
            context = self._address_context(event, "WRITE")
            if state.pending_w:
                next_state = Axi4LiteCompleterState(
                    state.pending_aw, state.pending_w[1:]
                )
                return self._joined_write(
                    next_state, context, state.pending_w[0]
                )
            return AddressRequestDecode(
                Axi4LiteCompleterState(
                    (*state.pending_aw, context), state.pending_w
                )
            )

        if event.kind == "W":
            data = Axi4LiteWriteData(
                int(event.payload["data"]), int(event.payload["strb"])
            )
            if state.pending_aw:
                next_state = Axi4LiteCompleterState(
                    state.pending_aw[1:], state.pending_w
                )
                return self._joined_write(
                    next_state, state.pending_aw[0], data
                )
            return AddressRequestDecode(
                Axi4LiteCompleterState(
                    state.pending_aw, (*state.pending_w, data)
                )
            )

        return AddressRequestDecode(
            state,
            fault=self._fault(
                "direction",
                f"AXI4-Lite subordinate cannot consume {event.kind!r}",
            ),
        )

    def encode_completion(
        self, state: object, context: object | None, result: AccessResult
    ) -> AttachmentEmission:
        if not isinstance(state, Axi4LiteCompleterState):
            raise TypeError(
                "Axi4LiteCompleterAttachment requires Axi4LiteCompleterState"
            )
        if not isinstance(context, Axi4LiteAccessContext):
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "context", "AXI4-Lite attachment lost its request context"
                ),
            )

        response = access_status_to_response(result.status)
        if context.request_kind == "READ":
            if result.succeeded and result.data is None:
                return AttachmentEmission(
                    state,
                    fault=self._fault(
                        "read_data",
                        "successful AXI4-Lite read completion requires data",
                    ),
                )
            try:
                data = (
                    0
                    if result.data is None
                    else place_transfer_value(
                        int(result.data),
                        address=context.address,
                        size=context.size,
                        bus_bytes=self.bus_bytes,
                    )
                )
            except ValueError as error:
                return AttachmentEmission(
                    state, fault=self._fault("read_data", str(error))
                )
            event = CanonicalEvent(
                "R", None, {"data": data, "resp": response}
            )
        else:
            event = CanonicalEvent("B", None, {"resp": response})

        fault = outgoing_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="axi4_lite_completer",
        )
        if fault is not None:
            return AttachmentEmission(state, fault=fault)
        return AttachmentEmission(state, (event,))

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, Axi4LiteCompleterState)
            and not state.pending_aw
            and not state.pending_w
        )

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"axi4_lite_completer.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )

"""AXI4-Lite manager integration for address-oriented backends."""

from __future__ import annotations

from protocol_model.link import LinkProtocol
from protocol_model.semantics import CanonicalEvent, ConstraintScope, SemanticFault
from protocol_model.virtual_dut.address.access import (
    AccessResult,
    AccessStatus,
    AddressRead,
    AddressWrite,
    ByteOrder,
)
from protocol_model.virtual_dut.attachments.address import (
    AddressCompletion,
    AddressCompletionDecode,
    AddressRequest,
    AddressRequesterAttachment,
    AttachmentEmission,
)
from protocol_model.virtual_dut.attachments.validation import (
    incoming_event_fault,
    outgoing_event_fault,
)

from .common import (
    Axi4LitePendingRead,
    Axi4LiteRequesterState,
    extract_transfer_value,
    implicit_transfer_geometry,
    place_transfer_strobes,
    place_transfer_value,
    require_axi4_lite_address_profile,
    response_to_access_status,
)


class Axi4LiteRequesterAttachment(AddressRequesterAttachment):
    """Issue native Lite requests and correlate independent read/write FIFOs."""

    role = "manager"

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
        self.address_width = int(protocol.parameters["address_width"])
        self.data_width = int(protocol.parameters["data_width"])
        self.bus_bytes = self.data_width // 8

    def initial_state(self) -> Axi4LiteRequesterState:
        return Axi4LiteRequesterState()

    def _validate_access(self, access) -> str | None:
        if access.address + access.size > 1 << self.address_width:
            return "AXI4-Lite access exceeds the configured address width"
        _, implicit_size = implicit_transfer_geometry(
            access.address, self.bus_bytes
        )
        if access.size != implicit_size:
            return (
                "AXI4-Lite AddressAccess size must match the implicit "
                "full-width transfer span"
            )
        unknown = set(access.attributes) - {"prot"}
        if unknown:
            return (
                "AXI4-Lite requester cannot encode attributes "
                f"{sorted(unknown)!r}"
            )
        return None

    def encode_request(
        self, state: object, request: AddressRequest
    ) -> AttachmentEmission:
        if not isinstance(state, Axi4LiteRequesterState):
            raise TypeError(
                "Axi4LiteRequesterAttachment requires Axi4LiteRequesterState"
            )
        access = request.access
        reason = self._validate_access(access)
        if reason is not None:
            return AttachmentEmission(
                state, fault=self._fault("access_geometry", reason)
            )

        address_payload = {
            "addr": access.address,
            "prot": access.attributes.get("prot", 0),
        }
        if isinstance(access, AddressRead):
            events = (CanonicalEvent("AR", None, address_payload),)
            next_state = Axi4LiteRequesterState(
                (
                    *state.pending_reads,
                    Axi4LitePendingRead(
                        request.request_id, access.address, access.size
                    ),
                ),
                state.pending_writes,
            )
        else:
            assert isinstance(access, AddressWrite)
            try:
                data = place_transfer_value(
                    access.data,
                    address=access.address,
                    size=access.size,
                    bus_bytes=self.bus_bytes,
                )
                strb = place_transfer_strobes(
                    access.effective_byte_enable,
                    address=access.address,
                    size=access.size,
                    bus_bytes=self.bus_bytes,
                )
            except ValueError as error:
                return AttachmentEmission(
                    state,
                    fault=self._fault("access_geometry", str(error)),
                )
            events = (
                CanonicalEvent("AW", None, address_payload),
                CanonicalEvent("W", None, {"data": data, "strb": strb}),
            )
            next_state = Axi4LiteRequesterState(
                state.pending_reads,
                (*state.pending_writes, request.request_id),
            )

        for event in events:
            fault = outgoing_event_fault(
                self.protocol,
                self.role,
                event,
                rule_prefix="axi4_lite_requester",
            )
            if fault is not None:
                return AttachmentEmission(state, fault=fault)
        return AttachmentEmission(next_state, events)

    def decode_completion(
        self, state: object, event: CanonicalEvent
    ) -> AddressCompletionDecode:
        if not isinstance(state, Axi4LiteRequesterState):
            raise TypeError(
                "Axi4LiteRequesterAttachment requires Axi4LiteRequesterState"
            )
        fault = incoming_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="axi4_lite_requester",
        )
        if fault is not None:
            return AddressCompletionDecode(state, fault=fault)

        if event.kind == "R":
            if not state.pending_reads:
                return AddressCompletionDecode(
                    state,
                    fault=self._fault(
                        "orphan_completion",
                        "AXI4-Lite R has no pending read request",
                    ),
                )
            pending = state.pending_reads[0]
            status = response_to_access_status(event.payload["resp"])
            data = (
                extract_transfer_value(
                    int(event.payload["data"]),
                    address=pending.address,
                    bus_bytes=self.bus_bytes,
                )
                if status is AccessStatus.OK
                else None
            )
            return AddressCompletionDecode(
                Axi4LiteRequesterState(
                    state.pending_reads[1:], state.pending_writes
                ),
                AddressCompletion(
                    pending.request_id,
                    AccessResult(status=status, data=data),
                ),
            )

        if event.kind == "B":
            if not state.pending_writes:
                return AddressCompletionDecode(
                    state,
                    fault=self._fault(
                        "orphan_completion",
                        "AXI4-Lite B has no pending write request",
                    ),
                )
            return AddressCompletionDecode(
                Axi4LiteRequesterState(
                    state.pending_reads, state.pending_writes[1:]
                ),
                AddressCompletion(
                    state.pending_writes[0],
                    AccessResult(
                        status=response_to_access_status(
                            event.payload["resp"]
                        )
                    ),
                ),
            )

        return AddressCompletionDecode(
            state,
            fault=self._fault(
                "completion_kind",
                f"AXI4-Lite manager cannot consume {event.kind!r}",
            ),
        )

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, Axi4LiteRequesterState)
            and not state.pending_reads
            and not state.pending_writes
        )

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"axi4_lite_requester.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )

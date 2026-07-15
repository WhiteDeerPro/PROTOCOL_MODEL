"""Serialized AXI4 manager attachment for an AddressFabric egress."""

from __future__ import annotations

from dataclasses import dataclass

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
    event_is_forbidden,
    extract_single_value,
    place_single_strobes,
    place_single_value,
    require_axi4_address_protocol,
    response_status,
    single_address_payload,
    validate_single_access,
)


@dataclass(frozen=True)
class Axi4RequesterState:
    request_id: int | None = None
    request_kind: str | None = None
    address: int = 0
    size: int = 0


class Axi4RequesterAttachment(AddressRequesterAttachment):
    """Issue one aligned normal AXI4 transfer at a time.

    `AddressRequest.request_id` is a fabric owner token, not an AXI ID. This
    serialized profile therefore reuses one configured wire ID and stores the
    owner token locally until R or B completes the transfer.
    """

    role = "manager"

    def __init__(
        self,
        protocol: LinkProtocol,
        *,
        wire_id: int = 0,
        byte_order: ByteOrder | str = ByteOrder.LITTLE,
    ) -> None:
        self.byte_order = require_axi4_address_protocol(
            protocol, self.role, byte_order
        )
        id_width = int(protocol.parameters["id_width"])
        if (
            not isinstance(wire_id, int)
            or isinstance(wire_id, bool)
            or not 0 <= wire_id < 1 << id_width
        ):
            raise ValueError("AXI4 requester wire ID does not fit the ID width")
        self.protocol = protocol
        self.wire_id = wire_id
        self.data_width = int(protocol.parameters["data_width"])
        self.bus_bytes = self.data_width // 8
        self.address_width = int(protocol.parameters["address_width"])

    def initial_state(self) -> Axi4RequesterState:
        return Axi4RequesterState()

    def encode_request(
        self, state: object, request: AddressRequest
    ) -> AttachmentEmission:
        if not isinstance(state, Axi4RequesterState):
            raise TypeError("Axi4RequesterAttachment requires Axi4RequesterState")
        if state.request_id is not None:
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "busy", "AXI4 requester already owns a pending transfer"
                ),
            )
        access = request.access
        geometry_reason = validate_single_access(
            access,
            bus_bytes=self.bus_bytes,
            address_width=self.address_width,
        )
        if geometry_reason is not None:
            return AttachmentEmission(
                state, fault=self._fault("access_geometry", geometry_reason)
            )

        address_payload, supported_attributes = single_address_payload(access)
        unknown_attributes = set(access.attributes) - supported_attributes
        if unknown_attributes:
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "attributes",
                    "AXI4 requester cannot encode attributes "
                    f"{sorted(unknown_attributes)!r}",
                ),
            )

        if isinstance(access, AddressRead):
            request_kind = "READ"
            events = (
                CanonicalEvent("AR", self.wire_id, address_payload),
            )
        else:
            assert isinstance(access, AddressWrite)
            request_kind = "WRITE"
            try:
                data = place_single_value(
                    access.data,
                    address=access.address,
                    size=access.size,
                    bus_bytes=self.bus_bytes,
                )
                strobes = place_single_strobes(
                    access.effective_byte_enable,
                    address=access.address,
                    size=access.size,
                    bus_bytes=self.bus_bytes,
                )
            except ValueError as error:
                return AttachmentEmission(
                    state, fault=self._fault("write_data", str(error))
                )
            events = (
                CanonicalEvent("AW", self.wire_id, address_payload),
                CanonicalEvent(
                    "W",
                    None,
                    {"data": data, "strb": strobes, "last": True},
                ),
            )

        for event in events:
            if event_is_forbidden(self.protocol, event.kind):
                return AttachmentEmission(
                    state,
                    fault=self._fault(
                        "profile", f"AXI4 link profile disables {event.kind}"
                    ),
                )
            fault = outgoing_event_fault(
                self.protocol,
                self.role,
                event,
                rule_prefix="axi4_requester",
            )
            if fault is not None:
                return AttachmentEmission(state, fault=fault)
        return AttachmentEmission(
            Axi4RequesterState(
                request.request_id,
                request_kind,
                access.address,
                access.size,
            ),
            events,
        )

    def decode_completion(
        self, state: object, event: CanonicalEvent
    ) -> AddressCompletionDecode:
        if not isinstance(state, Axi4RequesterState):
            raise TypeError("Axi4RequesterAttachment requires Axi4RequesterState")
        fault = incoming_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="axi4_requester",
        )
        if fault is not None:
            return AddressCompletionDecode(state, fault=fault)
        if state.request_id is None or state.request_kind is None:
            return AddressCompletionDecode(
                state,
                fault=self._fault(
                    "orphan_completion",
                    "AXI4 completion has no issued AddressRequest",
                ),
            )
        expected_kind = "R" if state.request_kind == "READ" else "B"
        if event.kind != expected_kind:
            return AddressCompletionDecode(
                state,
                fault=self._fault(
                    "completion_kind",
                    f"AXI4 {state.request_kind} requires {expected_kind}, "
                    f"not {event.kind}",
                ),
            )
        if event.key != self.wire_id:
            return AddressCompletionDecode(
                state,
                fault=self._fault(
                    "completion_id",
                    f"AXI4 completion ID {event.key!r} does not match "
                    f"wire ID {self.wire_id}",
                ),
            )
        if event.kind == "R" and not bool(event.payload["last"]):
            return AddressCompletionDecode(
                state,
                fault=self._fault(
                    "read_last", "single-access AXI4 requester requires RLAST"
                ),
            )
        if event.payload["resp"] == "EXOKAY":
            return AddressCompletionDecode(
                state,
                fault=self._fault(
                    "exclusive_response",
                    "normal single-access requester cannot receive EXOKAY",
                ),
            )

        status = response_status(event.payload["resp"])
        data = None
        if event.kind == "R" and status is AccessStatus.OK:
            data = extract_single_value(
                int(event.payload["data"]),
                address=state.address,
                size=state.size,
                bus_bytes=self.bus_bytes,
            )
        return AddressCompletionDecode(
            Axi4RequesterState(),
            AddressCompletion(
                state.request_id,
                AccessResult(status=status, data=data),
            ),
        )

    def is_quiescent(self, state: object) -> bool:
        return isinstance(state, Axi4RequesterState) and state.request_id is None

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"axi4_requester.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )

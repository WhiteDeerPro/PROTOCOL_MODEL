"""AHB manager integration for protocol-independent address fabrics."""

from __future__ import annotations

from dataclasses import dataclass
from math import log2

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
    default_payload_value,
    extract_transfer_value,
    place_transfer_strobes,
    place_transfer_value,
    require_ahb_address_profile,
)


@dataclass(frozen=True)
class AhbRequesterState:
    request_id: int | None = None
    request_kind: str | None = None
    address: int = 0
    size: int = 0


class AhbRequesterAttachment(AddressRequesterAttachment):
    """Issue SINGLE transfers and correlate the sole AHB completion."""

    role = "manager"

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
        self.read_fields = protocol.channels["READ"].event.fields
        self.write_fields = protocol.channels["WRITE"].event.fields
        self.write_data_fields = protocol.channels["WRITE_DATA"].event.fields

    def initial_state(self) -> AhbRequesterState:
        return AhbRequesterState()

    def _request_payload(self, access, fields) -> tuple[dict[str, object], set[str]]:
        payload: dict[str, object] = {
            "addr": access.address,
            "size": int(log2(access.size)),
            "burst": "SINGLE",
            "trans": "NONSEQ",
        }
        attribute_names = set(fields) - {"addr", "size", "burst", "trans"}
        for name in sorted(attribute_names):
            payload[name] = access.attributes.get(
                name, default_payload_value(fields[name])
            )
        return payload, attribute_names

    def encode_request(
        self, state: object, request: AddressRequest
    ) -> AttachmentEmission:
        if not isinstance(state, AhbRequesterState):
            raise TypeError("AhbRequesterAttachment requires AhbRequesterState")
        if state.request_id is not None:
            return AttachmentEmission(
                state,
                fault=self._fault("busy", "AHB requester has a pending transfer"),
            )
        access = request.access
        if (
            access.size > self.bus_bytes
            or access.size & (access.size - 1)
            or access.address % access.size
        ):
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "access_geometry",
                    "AHB request size must be an aligned power of two within the data bus",
                ),
            )

        is_read = isinstance(access, AddressRead)
        fields = self.read_fields if is_read else self.write_fields
        payload, request_attributes = self._request_payload(access, fields)
        supported_attributes = set(request_attributes)
        events = []
        kind = "READ" if is_read else "WRITE"
        events.append(CanonicalEvent(kind, None, payload))

        if not is_read:
            assert isinstance(access, AddressWrite)
            data_attributes = set(self.write_data_fields) - {"data", "strb"}
            supported_attributes.update(data_attributes)
            data_payload = {
                "data": place_transfer_value(
                    access.data,
                    address=access.address,
                    size=access.size,
                    bus_bytes=self.bus_bytes,
                )
            }
            if "strb" in self.write_data_fields:
                data_payload["strb"] = place_transfer_strobes(
                    access.effective_byte_enable,
                    address=access.address,
                    size=access.size,
                    bus_bytes=self.bus_bytes,
                )
            elif access.effective_byte_enable != (1 << access.size) - 1:
                return AttachmentEmission(
                    state,
                    fault=self._fault(
                        "byte_enable",
                        "this AHB link cannot encode a partial write without HWSTRB",
                    ),
                )
            for name in sorted(data_attributes):
                data_payload[name] = access.attributes.get(
                    name, default_payload_value(self.write_data_fields[name])
                )
            events.append(CanonicalEvent("WRITE_DATA", None, data_payload))

        unknown = set(access.attributes) - supported_attributes
        if unknown:
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "attributes",
                    f"AHB requester cannot encode attributes {sorted(unknown)!r}",
                ),
            )
        for event in events:
            fault = outgoing_event_fault(
                self.protocol,
                self.role,
                event,
                rule_prefix="ahb_requester",
            )
            if fault is not None:
                return AttachmentEmission(state, fault=fault)
        return AttachmentEmission(
            AhbRequesterState(
                request.request_id, kind, access.address, access.size
            ),
            tuple(events),
        )

    def decode_completion(
        self, state: object, event: CanonicalEvent
    ) -> AddressCompletionDecode:
        if not isinstance(state, AhbRequesterState):
            raise TypeError("AhbRequesterAttachment requires AhbRequesterState")
        fault = incoming_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="ahb_requester",
        )
        if fault is not None:
            return AddressCompletionDecode(state, fault=fault)
        if state.request_id is None or state.request_kind is None:
            return AddressCompletionDecode(
                state,
                fault=self._fault(
                    "orphan_completion", "AHB completion has no issued request"
                ),
            )
        expected = (
            "READ_RESPONSE"
            if state.request_kind == "READ"
            else "WRITE_RESPONSE"
        )
        if event.kind != expected:
            return AddressCompletionDecode(
                state,
                fault=self._fault(
                    "completion_kind",
                    f"AHB {state.request_kind} requires {expected}, not {event.kind}",
                ),
            )
        succeeded = event.payload["resp"] == "OKAY"
        data = None
        if succeeded and event.kind == "READ_RESPONSE":
            data = extract_transfer_value(
                int(event.payload["data"]),
                address=state.address,
                size=state.size,
                bus_bytes=self.bus_bytes,
            )
        return AddressCompletionDecode(
            AhbRequesterState(),
            AddressCompletion(
                state.request_id,
                AccessResult(
                    status=AccessStatus.OK if succeeded else AccessStatus.ACCESS_ERROR,
                    data=data,
                ),
            ),
        )

    def is_quiescent(self, state: object) -> bool:
        return isinstance(state, AhbRequesterState) and state.request_id is None

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"ahb_requester.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )

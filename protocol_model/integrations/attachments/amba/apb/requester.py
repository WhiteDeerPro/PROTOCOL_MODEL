"""APB requester integration for protocol-independent address backends."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import LinkProtocol
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    SemanticFault,
)
from protocol_model.virtual_dut.address.access import (
    AccessResult,
    AccessStatus,
    AddressRead,
    AddressWrite,
)
from protocol_model.virtual_dut.attachments.address import (
    AddressCompletion,
    AddressCompletionDecode,
    AddressRequest,
    AddressRequesterAttachment,
    AttachmentEmission,
)
from protocol_model.virtual_dut.attachments.validation import outgoing_event_fault

from .common import require_apb_role


@dataclass(frozen=True)
class ApbRequesterState:
    request_id: int | None = None
    request_kind: str | None = None


class ApbRequesterAttachment(AddressRequesterAttachment):
    """Issue one APB request and correlate its sole pending completion."""

    role = "requester"

    def __init__(self, protocol: LinkProtocol) -> None:
        require_apb_role(protocol, self.role)
        self.protocol = protocol
        self.data_width = int(protocol.parameters["data_width"])
        self.bytes_per_transfer = self.data_width // 8
        self.read_request_fields = frozenset(
            protocol.channels["READ"].event.fields
        )
        self.write_request_fields = frozenset(
            protocol.channels["WRITE"].event.fields
        )

    def initial_state(self) -> ApbRequesterState:
        return ApbRequesterState()

    def encode_request(
        self, state: object, request: AddressRequest
    ) -> AttachmentEmission:
        if not isinstance(state, ApbRequesterState):
            raise TypeError("ApbRequesterAttachment requires ApbRequesterState")
        if state.request_id is not None:
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "busy", "APB requester already owns a pending transfer"
                ),
            )
        access = request.access
        if access.size != self.bytes_per_transfer:
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "access_size",
                    "APB requester requires one full data-width address access",
                ),
            )
        is_read = isinstance(access, AddressRead)
        request_fields = (
            self.read_request_fields if is_read else self.write_request_fields
        )
        supported_attributes = request_fields - {"addr", "data", "strb"}
        unknown_attributes = set(access.attributes) - supported_attributes
        if unknown_attributes:
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "attributes",
                    "APB requester cannot encode attributes "
                    f"{sorted(unknown_attributes)!r}",
                ),
            )

        payload: dict[str, object] = {"addr": access.address}
        for name in sorted(supported_attributes):
            payload[name] = access.attributes.get(name, 0)
        if is_read:
            kind = "READ"
        else:
            assert isinstance(access, AddressWrite)
            kind = "WRITE"
            payload["data"] = access.data
            if "strb" in request_fields:
                payload["strb"] = access.effective_byte_enable
            elif access.effective_byte_enable != (1 << access.size) - 1:
                return AttachmentEmission(
                    state,
                    fault=self._fault(
                        "byte_enable",
                        "this APB link cannot encode a partial write without PSTRB",
                    ),
                )
        event = CanonicalEvent(kind, None, payload)
        fault = outgoing_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="apb_attachment",
        )
        if fault is not None:
            return AttachmentEmission(state, fault=fault)
        return AttachmentEmission(
            ApbRequesterState(request.request_id, kind), (event,)
        )

    def decode_completion(
        self, state: object, event: CanonicalEvent
    ) -> AddressCompletionDecode:
        if not isinstance(state, ApbRequesterState):
            raise TypeError("ApbRequesterAttachment requires ApbRequesterState")
        if state.request_id is None or state.request_kind is None:
            return AddressCompletionDecode(
                state,
                fault=self._fault(
                    "orphan_completion",
                    "APB requester received a completion without a request",
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
                    f"APB {state.request_kind} requires {expected}, "
                    f"not {event.kind}",
                ),
            )
        status = (
            AccessStatus.ACCESS_ERROR
            if bool(event.payload["error"])
            else AccessStatus.OK
        )
        data = (
            int(event.payload["data"])
            if event.kind == "READ_RESPONSE"
            else None
        )
        return AddressCompletionDecode(
            ApbRequesterState(),
            AddressCompletion(
                state.request_id,
                AccessResult(status=status, data=data),
            ),
        )

    def is_quiescent(self, state: object) -> bool:
        return isinstance(state, ApbRequesterState) and state.request_id is None

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"apb_requester.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )

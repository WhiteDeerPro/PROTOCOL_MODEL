"""APB completer integration for protocol-independent address backends."""

from __future__ import annotations

from protocol_model.link import LinkProtocol
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    SemanticFault,
)
from protocol_model.virtual_dut.address.access import (
    AccessResult,
    AddressRead,
    AddressWrite,
)
from protocol_model.virtual_dut.attachments.address import (
    AddressCompleterAttachment,
    AddressRequestDecode,
    AttachmentEmission,
)
from protocol_model.virtual_dut.attachments.validation import outgoing_event_fault

from .common import ApbAccessContext, require_apb_role


class ApbCompleterAttachment(AddressCompleterAttachment):
    """Accept APB requests and return protocol-independent access results."""

    role = "completer"

    def __init__(self, protocol: LinkProtocol) -> None:
        require_apb_role(protocol, self.role)
        self.protocol = protocol
        self.data_width = int(protocol.parameters["data_width"])
        self.bytes_per_transfer = self.data_width // 8

    def decode_request(
        self, state: object, event: CanonicalEvent
    ) -> AddressRequestDecode:
        attributes = {
            name: value
            for name, value in event.payload.items()
            if name not in {"addr", "data", "strb"}
        }
        if event.kind == "READ":
            access = AddressRead(
                int(event.payload["addr"]),
                self.bytes_per_transfer,
                attributes,
            )
        elif event.kind == "WRITE":
            access = AddressWrite(
                int(event.payload["addr"]),
                self.bytes_per_transfer,
                int(event.payload["data"]),
                int(
                    event.payload.get(
                        "strb", (1 << self.bytes_per_transfer) - 1
                    )
                ),
                attributes,
            )
        else:
            return AddressRequestDecode(
                state,
                fault=SemanticFault(
                    "apb_completer.direction",
                    f"APB completer cannot accept event {event.kind!r}",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        return AddressRequestDecode(
            state, access, ApbAccessContext(event.kind)
        )

    def encode_completion(
        self, state: object, context: object | None, result: AccessResult
    ) -> AttachmentEmission:
        if not isinstance(context, ApbAccessContext):
            return AttachmentEmission(
                state,
                fault=SemanticFault(
                    "apb_completer.context",
                    "APB attachment lost its request context",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        if (
            context.request_kind == "READ"
            and result.succeeded
            and result.data is None
        ):
            return AttachmentEmission(
                state,
                fault=SemanticFault(
                    "apb_completer.read_data",
                    "successful APB read completion requires data",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        error = not result.succeeded
        if context.request_kind == "READ":
            response_fields = self.protocol.channels[
                "READ_RESPONSE"
            ].event.fields
            event = CanonicalEvent(
                "READ_RESPONSE",
                None,
                {
                    "data": 0 if result.data is None else result.data,
                    "error": error,
                    **{
                        name: 0
                        for name in response_fields
                        if name not in {"data", "error"}
                    },
                },
            )
        else:
            response_fields = self.protocol.channels[
                "WRITE_RESPONSE"
            ].event.fields
            event = CanonicalEvent(
                "WRITE_RESPONSE",
                None,
                {
                    "error": error,
                    **{
                        name: 0
                        for name in response_fields
                        if name != "error"
                    },
                },
            )
        fault = outgoing_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="apb_attachment",
        )
        if fault is not None:
            return AttachmentEmission(state, fault=fault)
        return AttachmentEmission(state, (event,))

"""Ingress attachment contract for typed address-domain operations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from protocol_model.interface import InterfaceProtocol
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    SemanticFault,
)

from ..address.access import AccessResult, AddressRead, AddressWrite
from .address import AddressCompleterAttachment
from .base import AttachmentEmission, InterfaceAttachment


if TYPE_CHECKING:
    from ..translation.signature import OperationSignature


@dataclass(frozen=True)
class AddressOperationDecode:
    state: object
    operation: object | None = None
    reply_context: object | None = None
    fault: SemanticFault | None = None


class AddressOperationCompleterAttachment(InterfaceAttachment, ABC):
    """Decode one address-domain operation and encode its typed completion.

    The contract intentionally remains inside the address domain.  Stream and
    coherent-message attachments can retain operation forms suited to their
    own completion and ordering rules.
    """

    protocol: InterfaceProtocol
    role: str
    operation_signature: OperationSignature

    def initial_state(self) -> object:
        return None

    @abstractmethod
    def decode_operation(
        self, state: object, event: CanonicalEvent
    ) -> AddressOperationDecode:
        raise NotImplementedError

    @abstractmethod
    def encode_operation_completion(
        self, state: object, context: object | None, result: object
    ) -> AttachmentEmission:
        raise NotImplementedError

    def is_quiescent(self, state: object) -> bool:
        return True


class AddressAccessOperationAdapter(AddressOperationCompleterAttachment):
    """Expose a single-access completer through the operation-level SPI.

    The adapter stays inside the address domain.  It does not translate a
    protocol or preserve a retired API; it lets single accesses and grouped
    address operations share one executor/backend boundary.
    """

    def __init__(
        self,
        attachment: AddressCompleterAttachment,
        operation_signature: OperationSignature,
    ) -> None:
        if not isinstance(attachment, AddressCompleterAttachment):
            raise TypeError(
                "address access operation adapter requires an address completer"
            )
        if set(operation_signature.request_types) != {
            AddressRead,
            AddressWrite,
        } or operation_signature.completion_types != (AccessResult,):
            raise ValueError(
                "address access operation signature must contain read/write "
                "requests and AccessResult completion"
            )
        self.attachment = attachment
        self.protocol = attachment.protocol
        self.role = attachment.role
        self.operation_signature = operation_signature

    def initial_state(self) -> object:
        return self.attachment.initial_state()

    def decode_operation(
        self, state: object, event: CanonicalEvent
    ) -> AddressOperationDecode:
        decoded = self.attachment.decode_request(state, event)
        return AddressOperationDecode(
            decoded.state,
            decoded.access,
            decoded.reply_context,
            decoded.fault,
        )

    def encode_operation_completion(
        self, state: object, context: object | None, result: object
    ) -> AttachmentEmission:
        if not isinstance(result, AccessResult):
            return AttachmentEmission(
                state,
                fault=SemanticFault(
                    "address_access_operation_adapter.result_type",
                    "single-access completion must be an AccessResult",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        return self.attachment.encode_completion(state, context, result)

    def is_quiescent(self, state: object) -> bool:
        return self.attachment.is_quiescent(state)


__all__ = [
    "AddressAccessOperationAdapter",
    "AddressOperationCompleterAttachment",
    "AddressOperationDecode",
]

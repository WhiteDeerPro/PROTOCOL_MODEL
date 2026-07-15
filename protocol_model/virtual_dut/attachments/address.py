"""Protocol-independent contracts for address-oriented port attachments."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from protocol_model.link import LinkProtocol
from protocol_model.semantics import CanonicalEvent, SemanticFault

from ..address.access import AccessResult, AddressAccess
from .base import AttachmentEmission, ProtocolAttachment


def _validate_request_id(request_id: int, *, subject: str) -> None:
    if (
        not isinstance(request_id, int)
        or isinstance(request_id, bool)
        or request_id < 0
    ):
        raise ValueError(f"{subject} id must be a non-negative integer")


@dataclass(frozen=True)
class AddressRequest:
    """One protocol-independent request issued toward an address endpoint."""

    request_id: int
    access: AddressAccess

    def __post_init__(self) -> None:
        _validate_request_id(self.request_id, subject="address request")


@dataclass(frozen=True)
class AddressCompletion:
    """One endpoint result correlated to an issued address request."""

    request_id: int
    result: AccessResult

    def __post_init__(self) -> None:
        _validate_request_id(self.request_id, subject="address completion")


@dataclass(frozen=True)
class AddressRequestDecode:
    state: object
    access: AddressAccess | None = None
    reply_context: object | None = None
    fault: SemanticFault | None = None


@dataclass(frozen=True)
class AddressCompletionDecode:
    state: object
    completion: AddressCompletion | None = None
    fault: SemanticFault | None = None


class AddressCompleterAttachment(ProtocolAttachment, ABC):
    """Accept address requests and encode endpoint completions on one port."""

    protocol: LinkProtocol
    role: str

    def initial_state(self) -> object:
        return None

    @abstractmethod
    def decode_request(
        self, state: object, event: CanonicalEvent
    ) -> AddressRequestDecode:
        raise NotImplementedError

    @abstractmethod
    def encode_completion(
        self, state: object, context: object | None, result: AccessResult
    ) -> AttachmentEmission:
        raise NotImplementedError

    def is_quiescent(self, state: object) -> bool:
        return True


class AddressRequesterAttachment(ProtocolAttachment, ABC):
    """Encode address requests and accept correlated completions on one port."""

    protocol: LinkProtocol
    role: str

    def initial_state(self) -> object:
        return None

    @abstractmethod
    def encode_request(
        self, state: object, request: AddressRequest
    ) -> AttachmentEmission:
        raise NotImplementedError

    @abstractmethod
    def decode_completion(
        self, state: object, event: CanonicalEvent
    ) -> AddressCompletionDecode:
        raise NotImplementedError

    def is_quiescent(self, state: object) -> bool:
        return True

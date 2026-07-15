"""Protocol-independent parent operation envelopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from .lifecycle import TokenRef


RequestT = TypeVar("RequestT")


@dataclass(frozen=True)
class DecodedOperation(Generic[RequestT]):
    """A semantic operation plus opaque context needed for the wire reply."""

    operation: RequestT
    reply_context: object | None = None


@dataclass(frozen=True)
class ParentEnvelope(Generic[RequestT]):
    """One accepted parent owned by a translation executor."""

    token: TokenRef
    operation: RequestT
    reply_context: object | None
    ingress_binding: str

    def __post_init__(self) -> None:
        if self.token.kind != "parent":
            raise ValueError("parent envelope requires a parent token")
        if not isinstance(self.ingress_binding, str) or not self.ingress_binding:
            raise ValueError("parent envelope requires an ingress binding")

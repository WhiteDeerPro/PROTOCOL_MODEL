"""Protocol-independent contracts for ordered stream transfers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Hashable, Mapping

from protocol_model.semantics import CanonicalEvent, SemanticFault

from .base import AttachmentEmission, ProtocolAttachment


@dataclass(frozen=True)
class StreamTransfer:
    """One accepted stream beat, independent of its wire protocol.

    ``keep`` identifies byte positions carried by the transfer and ``strobe``
    identifies the subset containing data rather than position bytes.  A
    ``packet_end`` value of ``None`` means that the source protocol does not
    expose packet boundaries; it is distinct from an explicit non-final beat.
    """

    data: int
    lane_count: int
    keep: int
    strobe: int
    packet_end: bool | None = None
    stream_id: Hashable = None
    destination: Hashable = None
    attributes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.lane_count, int)
            or isinstance(self.lane_count, bool)
            or self.lane_count <= 0
        ):
            raise ValueError("stream lane count must be a positive integer")
        if (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or not 0 <= self.data < 1 << (8 * self.lane_count)
        ):
            raise ValueError("stream data does not fit its byte lanes")
        mask_limit = 1 << self.lane_count
        for name, value in (("keep", self.keep), ("strobe", self.strobe)):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value < mask_limit
            ):
                raise ValueError(f"stream {name} mask does not fit its byte lanes")
        if self.strobe & ~self.keep:
            raise ValueError("stream strobe must be a subset of keep")
        if self.packet_end is not None and not isinstance(self.packet_end, bool):
            raise ValueError("stream packet end must be bool or None")
        try:
            hash(self.stream_id)
            hash(self.destination)
        except TypeError as error:
            raise ValueError("stream identity and destination must be hashable") from error
        object.__setattr__(
            self, "attributes", MappingProxyType(dict(self.attributes))
        )


@dataclass(frozen=True)
class StreamTransferDecode:
    state: object
    transfer: StreamTransfer | None = None
    fault: SemanticFault | None = None


class StreamReceiverAttachment(ProtocolAttachment, ABC):
    """Decode incoming protocol events into accepted stream transfers."""

    @abstractmethod
    def decode_transfer(
        self, state: object, event: CanonicalEvent
    ) -> StreamTransferDecode:
        raise NotImplementedError


class StreamTransmitterAttachment(ProtocolAttachment, ABC):
    """Encode stream transfers emitted by a backend onto one protocol port."""

    @abstractmethod
    def encode_transfer(
        self, state: object, transfer: StreamTransfer
    ) -> AttachmentEmission:
        raise NotImplementedError

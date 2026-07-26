"""Serialized protocol-independent memory-copy requester backend."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from protocol_model.semantics import ConstraintScope, SemanticFault

from ..address.access import AccessStatus, AddressRead, AddressWrite
from ..attachments.address import (
    AddressRequest,
    AddressRequesterAttachment,
)
from ..binding.port import InterfaceAttachmentBinding
from .base import VirtualDutBackend
from .transition import DutTransition, PortEmission, PortInput


@dataclass(frozen=True)
class MemoryCopyDescriptor:
    """One fixed-size sequence of aligned, single-access copies.

    A zero stride repeatedly accesses the same address.  This is useful for a
    data register whose next sample appears at a fixed address.  Omitting a
    stride advances by one beat and therefore describes an ordinary contiguous
    memory copy.  The engine processes beats in ascending descriptor order and
    does not snapshot source data, so overlapping source/destination regions
    do not have ``memmove`` semantics.  A zero-length descriptor emits no
    access, while its configured endpoints still follow alignment and
    integration-level address-range checks.
    """

    source_address: int
    destination_address: int
    length_bytes: int
    beat_bytes: int
    source_stride: int | None = None
    destination_stride: int | None = None

    def __post_init__(self) -> None:
        for value, subject in (
            (self.source_address, "source address"),
            (self.destination_address, "destination address"),
            (self.length_bytes, "length"),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(
                    f"memory-copy descriptor {subject} must be non-negative"
                )
        if (
            not isinstance(self.beat_bytes, int)
            or isinstance(self.beat_bytes, bool)
            or self.beat_bytes <= 0
            or self.beat_bytes & (self.beat_bytes - 1)
        ):
            raise ValueError(
                "memory-copy beat size must be a positive power of two"
            )
        if self.length_bytes % self.beat_bytes:
            raise ValueError(
                "memory-copy length must contain a whole number of beats"
            )

        source_stride = (
            self.beat_bytes
            if self.source_stride is None
            else self.source_stride
        )
        destination_stride = (
            self.beat_bytes
            if self.destination_stride is None
            else self.destination_stride
        )
        for value, subject in (
            (source_stride, "source stride"),
            (destination_stride, "destination stride"),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
                or value % self.beat_bytes
            ):
                raise ValueError(
                    f"memory-copy {subject} must be zero or a non-negative "
                    "multiple of the beat size"
                )
        for value, subject in (
            (self.source_address, "source address"),
            (self.destination_address, "destination address"),
        ):
            if value % self.beat_bytes:
                raise ValueError(
                    f"memory-copy {subject} must be beat-aligned"
                )

        object.__setattr__(self, "source_stride", source_stride)
        object.__setattr__(self, "destination_stride", destination_stride)

    @property
    def beat_count(self) -> int:
        return self.length_bytes // self.beat_bytes

    def source_for_beat(self, beat_index: int) -> int:
        return self.source_address + beat_index * self.source_stride

    def destination_for_beat(self, beat_index: int) -> int:
        return self.destination_address + beat_index * self.destination_stride


class MemoryCopyPhase(str, Enum):
    NEED_READ = "need_read"
    READ_PENDING = "read_pending"
    NEED_WRITE = "need_write"
    WRITE_PENDING = "write_pending"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True)
class MemoryCopyError:
    """A normal endpoint error that stopped the copy engine."""

    operation: str
    address: int
    status: AccessStatus

    def __post_init__(self) -> None:
        if self.operation not in {"read", "write"}:
            raise ValueError("memory-copy error operation must be read or write")
        if self.status is AccessStatus.OK:
            raise ValueError("a successful access is not a memory-copy error")


@dataclass(frozen=True)
class SerializedMemoryCopyState:
    """Public execution state for one configured memory-copy run."""

    phase: MemoryCopyPhase
    attachment_state: object
    beat_index: int = 0
    bytes_copied: int = 0
    next_request_id: int = 0
    pending_request_id: int | None = None
    buffered_data: int | None = None
    error: MemoryCopyError | None = None

    @property
    def done(self) -> bool:
        return self.phase is MemoryCopyPhase.DONE

    @property
    def failed(self) -> bool:
        return self.phase is MemoryCopyPhase.ERROR


class SerializedMemoryCopyBackend(VirtualDutBackend):
    """Copy aligned beats through one address-requester attachment.

    The descriptor is construction-time configuration.  ``advance()`` issues
    at most one read or write while ``accept()`` consumes the corresponding
    completion.  There is exactly one outstanding request across both
    directions, so requester attachments for APB, AHB, AXI4-Lite, and the
    serialized full-AXI profile can all be reused.

    Endpoint statuses such as DECERR/SLVERR are device-visible results and
    move the engine to ``ERROR``.  Malformed completions or an attachment that
    cannot encode the configured descriptor remain model faults.
    """

    def __init__(
        self,
        binding: InterfaceAttachmentBinding,
        descriptor: MemoryCopyDescriptor,
    ) -> None:
        if not isinstance(binding, InterfaceAttachmentBinding):
            raise TypeError(
                "serialized memory copy requires an attachment binding"
            )
        if not isinstance(binding.attachment, AddressRequesterAttachment):
            raise TypeError(
                "serialized memory copy requires an address requester"
            )
        if not isinstance(descriptor, MemoryCopyDescriptor):
            raise TypeError(
                "serialized memory copy requires a MemoryCopyDescriptor"
            )
        self.binding = binding
        self.attachment = binding.attachment
        self.descriptor = descriptor

    def local_attachment_bindings(self):
        return {self.binding.name: self.binding}

    def initial_state(self) -> SerializedMemoryCopyState:
        phase = (
            MemoryCopyPhase.DONE
            if self.descriptor.length_bytes == 0
            else MemoryCopyPhase.NEED_READ
        )
        return SerializedMemoryCopyState(
            phase,
            self.attachment.initial_state(),
        )

    def accept(self, state: object, action: PortInput) -> DutTransition:
        self._require_state(state)
        assert isinstance(state, SerializedMemoryCopyState)
        if action.port != self.binding.name:
            return DutTransition(
                state,
                fault=self._fault(
                    "unknown_port",
                    f"memory-copy engine has no port {action.port!r}",
                ),
            )
        if state.phase not in {
            MemoryCopyPhase.READ_PENDING,
            MemoryCopyPhase.WRITE_PENDING,
        }:
            return DutTransition(
                state,
                fault=self._fault(
                    "unexpected_completion",
                    f"memory-copy engine cannot accept a completion while "
                    f"{state.phase.value}",
                ),
            )

        decoded = self.attachment.decode_completion(
            state.attachment_state, action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)
        if decoded.completion is None:
            return DutTransition(
                replace(state, attachment_state=decoded.state)
            )

        completion = decoded.completion
        if completion.request_id != state.pending_request_id:
            return DutTransition(
                state,
                fault=self._fault(
                    "completion_owner",
                    f"completion {completion.request_id} does not match "
                    f"pending request {state.pending_request_id}",
                ),
            )
        if completion.result.effects:
            return DutTransition(
                state,
                fault=self._fault(
                    "completion_effect",
                    "memory-copy completions cannot carry endpoint-local effects",
                ),
            )

        is_read = state.phase is MemoryCopyPhase.READ_PENDING
        address = (
            self.descriptor.source_for_beat(state.beat_index)
            if is_read
            else self.descriptor.destination_for_beat(state.beat_index)
        )
        if completion.result.status is not AccessStatus.OK:
            failure = MemoryCopyError(
                "read" if is_read else "write",
                address,
                completion.result.status,
            )
            return DutTransition(
                replace(
                    state,
                    phase=MemoryCopyPhase.ERROR,
                    attachment_state=decoded.state,
                    pending_request_id=None,
                    buffered_data=None,
                    error=failure,
                )
            )

        if is_read:
            if completion.result.data is None:
                return DutTransition(
                    state,
                    fault=self._fault(
                        "missing_read_data",
                        "a successful memory-copy read completed without data",
                    ),
                )
            return DutTransition(
                replace(
                    state,
                    phase=MemoryCopyPhase.NEED_WRITE,
                    attachment_state=decoded.state,
                    pending_request_id=None,
                    buffered_data=completion.result.data,
                )
            )

        copied = state.bytes_copied + self.descriptor.beat_bytes
        next_beat = state.beat_index + 1
        return DutTransition(
            replace(
                state,
                phase=(
                    MemoryCopyPhase.DONE
                    if copied == self.descriptor.length_bytes
                    else MemoryCopyPhase.NEED_READ
                ),
                attachment_state=decoded.state,
                beat_index=next_beat,
                bytes_copied=copied,
                pending_request_id=None,
                buffered_data=None,
            )
        )

    def advance(
        self, state: SerializedMemoryCopyState, *, steps: int = 1
    ) -> DutTransition:
        self._require_state(state)
        if (
            not isinstance(steps, int)
            or isinstance(steps, bool)
            or steps <= 0
        ):
            raise ValueError("memory-copy advance steps must be positive")

        current = state
        emissions: list[PortEmission] = []
        for _ in range(steps):
            transition = self._advance_once(current)
            if transition.fault is not None:
                return DutTransition(state, fault=transition.fault)
            current = transition.state
            emissions.extend(transition.emissions)
            if transition.emissions:
                break
        return DutTransition(current, tuple(emissions))

    def _advance_once(
        self, state: SerializedMemoryCopyState
    ) -> DutTransition:
        if state.phase not in {
            MemoryCopyPhase.NEED_READ,
            MemoryCopyPhase.NEED_WRITE,
        }:
            return DutTransition(state)

        request_id = state.next_request_id
        if state.phase is MemoryCopyPhase.NEED_READ:
            access = AddressRead(
                self.descriptor.source_for_beat(state.beat_index),
                self.descriptor.beat_bytes,
            )
            pending_phase = MemoryCopyPhase.READ_PENDING
        else:
            if state.buffered_data is None:
                return DutTransition(
                    state,
                    fault=self._fault(
                        "missing_write_data",
                        "memory-copy write phase has no buffered read data",
                    ),
                )
            access = AddressWrite(
                self.descriptor.destination_for_beat(state.beat_index),
                self.descriptor.beat_bytes,
                state.buffered_data,
            )
            pending_phase = MemoryCopyPhase.WRITE_PENDING

        encoded = self.attachment.encode_request(
            state.attachment_state,
            AddressRequest(request_id, access),
        )
        if encoded.fault is not None:
            return DutTransition(state, fault=encoded.fault)
        return DutTransition(
            replace(
                state,
                phase=pending_phase,
                attachment_state=encoded.state,
                next_request_id=request_id + 1,
                pending_request_id=request_id,
            ),
            tuple(
                PortEmission(self.binding.name, event)
                for event in encoded.events
            ),
        )

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, SerializedMemoryCopyState)
            and state.phase in {MemoryCopyPhase.DONE, MemoryCopyPhase.ERROR}
            and self.attachment.is_quiescent(state.attachment_state)
        )

    @staticmethod
    def _require_state(state: object) -> None:
        if not isinstance(state, SerializedMemoryCopyState):
            raise TypeError(
                "SerializedMemoryCopyBackend requires "
                "SerializedMemoryCopyState"
            )

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"serialized_memory_copy.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )


__all__ = [
    "MemoryCopyDescriptor",
    "MemoryCopyError",
    "MemoryCopyPhase",
    "SerializedMemoryCopyBackend",
    "SerializedMemoryCopyState",
]

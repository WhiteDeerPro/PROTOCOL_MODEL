"""Explicitly serviced sensor FIFO exposed through one address register."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticFault,
)

from ..address.access import AccessResult, AccessStatus, AddressRead
from ..attachments.address import AddressCompleterAttachment
from ..binding.port import InterfaceAttachmentBinding
from .base import VirtualDutBackend
from .transition import DutTransition, PortEmission, PortInput


class SensorEmptyPolicy(str, Enum):
    """Response used when software or a DMA reads an empty sensor FIFO."""

    BLOCK = "block"
    ACCESS_ERROR = "access_error"


class SensorFullPolicy(str, Enum):
    """Behavior of a sample opportunity when no FIFO slot is available."""

    BLOCK = "block"
    DROP_NEWEST = "drop_newest"


@dataclass(frozen=True)
class SensorFifoConfig:
    data_address: int
    sample_bytes: int
    capacity: int
    empty_policy: SensorEmptyPolicy | str = SensorEmptyPolicy.BLOCK
    full_policy: SensorFullPolicy | str = SensorFullPolicy.DROP_NEWEST

    def __post_init__(self) -> None:
        if (
            not isinstance(self.data_address, int)
            or isinstance(self.data_address, bool)
            or self.data_address < 0
        ):
            raise ValueError("sensor FIFO data address must be non-negative")
        if (
            not isinstance(self.sample_bytes, int)
            or isinstance(self.sample_bytes, bool)
            or self.sample_bytes <= 0
            or self.sample_bytes & (self.sample_bytes - 1)
        ):
            raise ValueError(
                "sensor FIFO sample size must be a positive power of two"
            )
        if self.data_address % self.sample_bytes:
            raise ValueError("sensor FIFO data address must be sample-aligned")
        if (
            not isinstance(self.capacity, int)
            or isinstance(self.capacity, bool)
            or self.capacity <= 0
        ):
            raise ValueError("sensor FIFO capacity must be positive")
        try:
            empty_policy = (
                self.empty_policy
                if isinstance(self.empty_policy, SensorEmptyPolicy)
                else SensorEmptyPolicy(self.empty_policy)
            )
        except (TypeError, ValueError) as error:
            raise ValueError("unknown sensor FIFO empty policy") from error
        try:
            full_policy = (
                self.full_policy
                if isinstance(self.full_policy, SensorFullPolicy)
                else SensorFullPolicy(self.full_policy)
            )
        except (TypeError, ValueError) as error:
            raise ValueError("unknown sensor FIFO full policy") from error
        object.__setattr__(self, "empty_policy", empty_policy)
        object.__setattr__(self, "full_policy", full_policy)


@dataclass(frozen=True)
class SensorSampleContext:
    """Stable input to a deterministic sample policy."""

    service_index: int
    accepted_samples: int
    queue_depth: int
    capacity: int


SensorSamplePolicy = Callable[[SensorSampleContext], int]


@dataclass(frozen=True)
class SensorFifoState:
    attachment_state: object
    samples: tuple[int, ...] = ()
    service_index: int = 0
    accepted_samples: int = 0
    samples_read: int = 0
    overrun_count: int = 0

    @property
    def queue_depth(self) -> int:
        return len(self.samples)


@dataclass(frozen=True)
class SensorFifoBoundaryProjection:
    """Immutable facts useful to construction and visualization."""

    port: str
    data_address: int
    sample_bytes: int
    capacity: int
    empty_policy: SensorEmptyPolicy
    full_policy: SensorFullPolicy


class SensorFifoBackend(VirtualDutBackend):
    """Produce deterministic samples and pop them through a data register.

    ``advance()`` represents an explicit sensor service opportunity, not an
    autonomous clock.  The caller-provided policy receives only immutable
    counters and must return the same sample for the same context.  Reading
    the configured address removes the oldest sample after the attachment can
    encode its successful completion.

    ``DROP_NEWEST`` models a physical producer that cannot be backpressured;
    its overrun counter is protocol-visible model state.  ``BLOCK`` instead
    returns a typed resource demand and leaves the service action unaccepted.
    """

    def __init__(
        self,
        binding: InterfaceAttachmentBinding,
        config: SensorFifoConfig,
        sample_policy: SensorSamplePolicy,
    ) -> None:
        if not isinstance(binding, InterfaceAttachmentBinding):
            raise TypeError("sensor FIFO requires an attachment binding")
        if not isinstance(binding.attachment, AddressCompleterAttachment):
            raise TypeError("sensor FIFO requires an address completer")
        if not isinstance(config, SensorFifoConfig):
            raise TypeError("sensor FIFO requires SensorFifoConfig")
        if not callable(sample_policy):
            raise TypeError("sensor FIFO sample policy must be callable")
        self.binding = binding
        self.attachment = binding.attachment
        self.config = config
        self.sample_policy = sample_policy
        self.bindings: Mapping[str, InterfaceAttachmentBinding] = MappingProxyType(
            {binding.name: binding}
        )

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, InterfaceAttachmentBinding]:
        return self.bindings

    def boundary_projections(self) -> Mapping[str, object]:
        return {
            "sensor_fifo": SensorFifoBoundaryProjection(
                self.binding.name,
                self.config.data_address,
                self.config.sample_bytes,
                self.config.capacity,
                self.config.empty_policy,
                self.config.full_policy,
            )
        }

    def initial_state(self) -> SensorFifoState:
        return SensorFifoState(self.attachment.initial_state())

    def accept(self, state: object, action: PortInput) -> DutTransition:
        self._require_state(state)
        assert isinstance(state, SensorFifoState)
        if action.port != self.binding.name:
            return DutTransition(
                state,
                fault=self._fault(
                    "unknown_port",
                    f"sensor FIFO has no port {action.port!r}",
                ),
            )

        decoded = self.attachment.decode_request(
            state.attachment_state, action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)
        if decoded.access is None:
            return DutTransition(
                replace(state, attachment_state=decoded.state)
            )

        access = decoded.access
        exact_register = (
            access.address == self.config.data_address
            and access.size == self.config.sample_bytes
        )
        if not exact_register:
            return self._complete(
                state,
                decoded.state,
                decoded.reply_context,
                AccessResult(status=AccessStatus.DECODE_ERROR),
            )
        if not isinstance(access, AddressRead):
            return self._complete(
                state,
                decoded.state,
                decoded.reply_context,
                AccessResult(status=AccessStatus.ACCESS_ERROR),
            )
        if not state.samples:
            if self.config.empty_policy is SensorEmptyPolicy.BLOCK:
                return DutTransition(
                    state,
                    blocked=ResourceDemand(
                        "sensor_fifo.sample_available",
                        ConstraintScope.VIRTUAL_DUT,
                        available=0,
                        capacity=self.config.capacity,
                        reason="sensor FIFO data register was read while empty",
                        location=self.binding.name,
                    ),
                )
            return self._complete(
                state,
                decoded.state,
                decoded.reply_context,
                AccessResult(status=AccessStatus.ACCESS_ERROR),
            )

        sample = state.samples[0]
        completed = self.attachment.encode_completion(
            decoded.state,
            decoded.reply_context,
            AccessResult(data=sample),
        )
        if completed.fault is not None:
            return DutTransition(state, fault=completed.fault)
        return DutTransition(
            replace(
                state,
                attachment_state=completed.state,
                samples=state.samples[1:],
                samples_read=state.samples_read + 1,
            ),
            tuple(
                PortEmission(self.binding.name, event)
                for event in completed.events
            ),
        )

    def _complete(
        self,
        original: SensorFifoState,
        attachment_state: object,
        reply_context: object | None,
        result: AccessResult,
    ) -> DutTransition:
        completed = self.attachment.encode_completion(
            attachment_state, reply_context, result
        )
        if completed.fault is not None:
            return DutTransition(original, fault=completed.fault)
        return DutTransition(
            replace(original, attachment_state=completed.state),
            tuple(
                PortEmission(self.binding.name, event)
                for event in completed.events
            ),
        )

    def advance(
        self, state: SensorFifoState, *, steps: int = 1
    ) -> DutTransition:
        self._require_state(state)
        if (
            not isinstance(steps, int)
            or isinstance(steps, bool)
            or steps <= 0
        ):
            raise ValueError("sensor FIFO advance steps must be positive")

        original = state
        current = state
        for _ in range(steps):
            context = SensorSampleContext(
                current.service_index,
                current.accepted_samples,
                len(current.samples),
                self.config.capacity,
            )
            try:
                sample = self.sample_policy(context)
            except Exception as error:
                return DutTransition(
                    original,
                    fault=self._fault(
                        "sample_policy",
                        f"sample policy raised {type(error).__name__}: {error}",
                    ),
                )
            if (
                not isinstance(sample, int)
                or isinstance(sample, bool)
                or not 0 <= sample < 1 << (8 * self.config.sample_bytes)
            ):
                return DutTransition(
                    original,
                    fault=self._fault(
                        "sample_value",
                        "sample policy result does not fit the configured width",
                    ),
                )

            if len(current.samples) == self.config.capacity:
                if self.config.full_policy is SensorFullPolicy.BLOCK:
                    return DutTransition(
                        original,
                        blocked=ResourceDemand(
                            "sensor_fifo.free_slot",
                            ConstraintScope.VIRTUAL_DUT,
                            available=0,
                            capacity=self.config.capacity,
                            reason="sensor sample FIFO is full",
                            location=self.binding.name,
                        ),
                    )
                current = replace(
                    current,
                    service_index=current.service_index + 1,
                    overrun_count=current.overrun_count + 1,
                )
                continue

            current = replace(
                current,
                samples=(*current.samples, sample),
                service_index=current.service_index + 1,
                accepted_samples=current.accepted_samples + 1,
            )
        return DutTransition(current)

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, SensorFifoState)
            and self.attachment.is_quiescent(state.attachment_state)
        )

    def queue_usage(self, state: SensorFifoState) -> tuple[int, int]:
        self._require_state(state)
        return len(state.samples), self.config.capacity

    @staticmethod
    def _require_state(state: object) -> None:
        if not isinstance(state, SensorFifoState):
            raise TypeError("SensorFifoBackend requires SensorFifoState")

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"sensor_fifo.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )


def incrementing_sample_policy(
    *, start: int = 0, increment: int = 1
) -> SensorSamplePolicy:
    """Return a deterministic sample sequence indexed by service attempts."""

    if not isinstance(start, int) or isinstance(start, bool):
        raise ValueError("sample sequence start must be an integer")
    if not isinstance(increment, int) or isinstance(increment, bool):
        raise ValueError("sample sequence increment must be an integer")

    def policy(context: SensorSampleContext) -> int:
        return start + context.service_index * increment

    return policy


__all__ = [
    "SensorEmptyPolicy",
    "SensorFifoBackend",
    "SensorFifoBoundaryProjection",
    "SensorFifoConfig",
    "SensorFifoState",
    "SensorFullPolicy",
    "SensorSampleContext",
    "SensorSamplePolicy",
    "incrementing_sample_policy",
]

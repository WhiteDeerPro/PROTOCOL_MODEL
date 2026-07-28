"""Finite queued address responder with explicit manual advancement."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    ResourceExhaustionPolicy,
    SemanticFault,
)

from ..address.access import (
    AccessResult,
    AccessStatus,
    AddressAccess,
    AddressStep,
)
from ..address.target import AddressTarget
from ..attachments.address import AddressCompleterAttachment
from ..binding.port import InterfaceAttachmentBinding
from .base import VirtualDutBackend
from .transition import DutTransition, PortEmission, PortInput


@dataclass(frozen=True)
class AddressDelayContext:
    request_serial: int
    port: str
    queued_before: int
    accepted_at_advance: int


AddressDelayPolicy = Callable[[AddressAccess, AddressDelayContext], int]


class QueuedAddressPhase(str, Enum):
    DELAYING = "delaying"
    READY = "ready"


@dataclass(frozen=True)
class QueuedAddressRequest:
    request_serial: int
    port: str
    access: AddressAccess
    reply_context: object | None
    phase: QueuedAddressPhase
    remaining_delay_steps: int = 0

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_serial, int)
            or isinstance(self.request_serial, bool)
            or self.request_serial < 0
        ):
            raise ValueError("queued address request serial must be non-negative")
        if not self.port:
            raise ValueError("queued address request requires a port")
        if not isinstance(self.phase, QueuedAddressPhase):
            raise TypeError("queued address request requires a valid phase")
        if (
            not isinstance(self.remaining_delay_steps, int)
            or isinstance(self.remaining_delay_steps, bool)
            or self.remaining_delay_steps < 0
        ):
            raise ValueError("queued address delay steps must be non-negative")
        if (
            self.phase is QueuedAddressPhase.READY
            and self.remaining_delay_steps != 0
        ):
            raise ValueError("a ready address request cannot retain delay steps")
        if (
            self.phase is QueuedAddressPhase.DELAYING
            and self.remaining_delay_steps == 0
        ):
            raise ValueError("a delaying address request needs a delay step")


@dataclass(frozen=True)
class QueuedAddressErrorCompletion:
    """One accepted overflow request waiting for an ordered error response.

    The marker occupies a single emergency slot associated with its ingress
    port.  It is intentionally not a normal request-FIFO entry: when it reaches
    the service head, the responder encodes ``ACCESS_ERROR`` without invoking
    the address handler.
    """

    request_serial: int
    port: str
    reply_context: object | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_serial, int)
            or isinstance(self.request_serial, bool)
            or self.request_serial < 0
        ):
            raise ValueError(
                "queued address error marker serial must be non-negative"
            )
        if not isinstance(self.port, str) or not self.port:
            raise ValueError("queued address error marker requires a port")


QueuedAddressEntry = QueuedAddressRequest | QueuedAddressErrorCompletion


@dataclass(frozen=True)
class QueuedAddressResponderState:
    handler_state: object
    attachment_states: Mapping[str, object]
    queue: tuple[QueuedAddressEntry, ...] = ()
    next_request_serial: int = 0
    advance_index: int = 0

    def __post_init__(self) -> None:
        attachment_states = dict(self.attachment_states)
        if any(not name for name in attachment_states):
            raise ValueError("queued responder attachment names must be non-empty")
        queue = tuple(self.queue)
        if any(
            not isinstance(
                item,
                (QueuedAddressRequest, QueuedAddressErrorCompletion),
            )
            for item in queue
        ):
            raise TypeError("queued responder queue has an invalid entry")
        error_ports = tuple(
            item.port
            for item in queue
            if isinstance(item, QueuedAddressErrorCompletion)
        )
        if len(set(error_ports)) != len(error_ports):
            raise ValueError(
                "queued responder allows one emergency error marker per port"
            )
        if any(item.port not in attachment_states for item in queue):
            raise ValueError(
                "queued responder entry references an unknown attachment state"
            )
        live_serials = tuple(item.request_serial for item in queue)
        if len(set(live_serials)) != len(live_serials):
            raise ValueError("queued responder request serials must be unique")
        for value, subject in (
            (self.next_request_serial, "next request serial"),
            (self.advance_index, "advance index"),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"queued responder {subject} must be non-negative")
        if live_serials and self.next_request_serial <= max(live_serials):
            raise ValueError(
                "queued responder next serial must exceed every live entry"
            )
        object.__setattr__(
            self,
            "attachment_states",
            MappingProxyType(attachment_states),
        )
        object.__setattr__(self, "queue", queue)


class QueuedAddressResponderBackend(VirtualDutBackend):
    """Queue complete address requests and service them on explicit advances.

    Request acceptance never executes the handler and never emits a response.
    ``advance()`` is a deliberate execution boundary: every queued request
    ages by one delay step, then at most one READY FIFO head performs its
    handler access and emits a completion.  Delay is counted from request
    acceptance, while completion order remains FIFO.

    ``capacity`` counts complete ``AddressAccess`` values in this FIFO.
    Protocol fragments such as unmatched AXI-Lite AW/W remain owned by the
    attachment state.  On exhaustion, ``BLOCK`` leaves the event unaccepted
    for runtime retry; ``ERROR_COMPLETION`` accepts one overflow request per
    port into a bounded emergency slot and returns ``ACCESS_ERROR`` only after
    every older FIFO entry; ``FAULT`` reports a model/use-contract violation.
    While that port's emergency slot is occupied, a further overflow request
    blocks.  Only ``BLOCK`` transitions represent event-level backpressure.

    ``SystemSession`` routes delayed emissions only when a caller sends a
    ``DutAdvanceAction``.  This is an explicit service opportunity, not an
    autonomous clock or background task.
    """

    def __init__(
        self,
        handler: AddressTarget,
        bindings: Mapping[str, InterfaceAttachmentBinding],
        *,
        capacity: int,
        delay_policy: AddressDelayPolicy,
        exhaustion_policy: ResourceExhaustionPolicy | str = (
            ResourceExhaustionPolicy.BLOCK
        ),
    ) -> None:
        if not isinstance(handler, AddressTarget):
            raise TypeError(
                "queued address responder requires an AddressTarget"
            )
        bindings = dict(bindings)
        if not bindings:
            raise ValueError("queued address responder requires a binding")
        if any(
            not isinstance(binding, InterfaceAttachmentBinding)
            for binding in bindings.values()
        ):
            raise TypeError(
                "queued address responder requires attachment bindings"
            )
        if set(bindings) != {binding.name for binding in bindings.values()}:
            raise ValueError("queued responder binding keys must match ports")
        if any(
            not isinstance(
                binding.attachment, AddressCompleterAttachment
            )
            for binding in bindings.values()
        ):
            raise TypeError(
                "queued responder bindings require address completers"
            )
        if (
            not isinstance(capacity, int)
            or isinstance(capacity, bool)
            or capacity <= 0
        ):
            raise ValueError("queued responder capacity must be positive")
        if not callable(delay_policy):
            raise TypeError("queued responder delay policy must be callable")
        try:
            normalized_exhaustion_policy = ResourceExhaustionPolicy(
                exhaustion_policy
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "queued responder requires a valid resource exhaustion policy"
            ) from error

        self.handler = handler
        self.bindings = MappingProxyType(bindings)
        self.attachments = MappingProxyType(
            {
                name: binding.attachment
                for name, binding in bindings.items()
            }
        )
        self.capacity = capacity
        self.delay_policy = delay_policy
        self.exhaustion_policy = normalized_exhaustion_policy

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, InterfaceAttachmentBinding]:
        return self.bindings

    def initial_state(self) -> QueuedAddressResponderState:
        return QueuedAddressResponderState(
            self.handler.initial_state(),
            {
                name: attachment.initial_state()
                for name, attachment in self.attachments.items()
            },
        )

    def accept(self, state: object, action: PortInput) -> DutTransition:
        self._require_state(state)
        assert isinstance(state, QueuedAddressResponderState)
        attachment = self.attachments.get(action.port)
        if attachment is None:
            return DutTransition(
                state,
                fault=self._fault(
                    "unknown_port",
                    f"queued responder has no port {action.port!r}",
                ),
            )
        decoded = attachment.decode_request(
            state.attachment_states[action.port], action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)
        attachment_states = dict(state.attachment_states)
        attachment_states[action.port] = decoded.state
        if decoded.access is None:
            return DutTransition(
                replace(state, attachment_states=attachment_states)
            )
        regular_usage = sum(
            isinstance(item, QueuedAddressRequest) for item in state.queue
        )
        if regular_usage >= self.capacity:
            reason = (
                "queued responder request FIFO is full "
                f"({regular_usage}/{self.capacity})"
            )
            if self.exhaustion_policy is ResourceExhaustionPolicy.BLOCK:
                return DutTransition(
                    state,
                    blocked=ResourceDemand(
                        "request_fifo",
                        ConstraintScope.VIRTUAL_DUT,
                        available=self.capacity - regular_usage,
                        capacity=self.capacity,
                        reason=reason,
                        location=action.port,
                    ),
                )
            if self.exhaustion_policy is ResourceExhaustionPolicy.FAULT:
                return DutTransition(
                    state,
                    fault=self._fault("capacity", reason),
                )

            if any(
                isinstance(item, QueuedAddressErrorCompletion)
                and item.port == action.port
                for item in state.queue
            ):
                return DutTransition(
                    state,
                    blocked=ResourceDemand(
                        "error_completion_slot",
                        ConstraintScope.VIRTUAL_DUT,
                        available=0,
                        capacity=1,
                        reason=(
                            f"queued responder port {action.port!r} already "
                            "has an ordered overflow error pending"
                        ),
                        location=action.port,
                    ),
                )
            marker = QueuedAddressErrorCompletion(
                state.next_request_serial,
                action.port,
                decoded.reply_context,
            )
            return DutTransition(
                QueuedAddressResponderState(
                    state.handler_state,
                    attachment_states,
                    (*state.queue, marker),
                    state.next_request_serial + 1,
                    state.advance_index,
                ),
            )

        context = AddressDelayContext(
            state.next_request_serial,
            action.port,
            len(state.queue),
            state.advance_index,
        )
        try:
            delay_steps = self.delay_policy(decoded.access, context)
        except Exception as error:
            return DutTransition(
                state,
                fault=self._fault(
                    "delay_policy",
                    f"delay policy raised {type(error).__name__}: {error}",
                ),
            )
        if (
            not isinstance(delay_steps, int)
            or isinstance(delay_steps, bool)
            or delay_steps < 0
        ):
            return DutTransition(
                state,
                fault=self._fault(
                    "delay_policy",
                    "delay policy must return a non-negative integer",
                ),
            )
        queued = QueuedAddressRequest(
            state.next_request_serial,
            action.port,
            decoded.access,
            decoded.reply_context,
            (
                QueuedAddressPhase.READY
                if delay_steps == 0
                else QueuedAddressPhase.DELAYING
            ),
            delay_steps,
        )
        return DutTransition(
            QueuedAddressResponderState(
                state.handler_state,
                attachment_states,
                (*state.queue, queued),
                state.next_request_serial + 1,
                state.advance_index,
            )
        )

    def advance(
        self, state: QueuedAddressResponderState, *, steps: int = 1
    ) -> DutTransition:
        """Age the queue and service at most one head per explicit step."""

        self._require_state(state)
        if (
            not isinstance(steps, int)
            or isinstance(steps, bool)
            or steps <= 0
        ):
            raise ValueError("queued responder advance steps must be positive")

        original = state
        candidate = state
        emissions: list[PortEmission] = []
        for _ in range(steps):
            candidate = replace(
                candidate, advance_index=candidate.advance_index + 1
            )
            if not candidate.queue:
                continue
            aged_queue: list[QueuedAddressEntry] = []
            for request in candidate.queue:
                if isinstance(request, QueuedAddressErrorCompletion):
                    aged_queue.append(request)
                    continue
                if request.phase is QueuedAddressPhase.READY:
                    aged_queue.append(request)
                    continue
                remaining = request.remaining_delay_steps - 1
                aged_queue.append(
                    replace(
                        request,
                        phase=(
                            QueuedAddressPhase.READY
                            if remaining == 0
                            else QueuedAddressPhase.DELAYING
                        ),
                        remaining_delay_steps=remaining,
                    )
                )
            candidate = replace(candidate, queue=tuple(aged_queue))
            head = candidate.queue[0]
            if (
                isinstance(head, QueuedAddressRequest)
                and head.phase is QueuedAddressPhase.DELAYING
            ):
                continue

            attachment = self.attachments[head.port]
            if isinstance(head, QueuedAddressErrorCompletion):
                encoded = attachment.encode_completion(
                    candidate.attachment_states[head.port],
                    head.reply_context,
                    AccessResult(status=AccessStatus.ACCESS_ERROR),
                )
                if encoded.fault is not None:
                    return DutTransition(original, fault=encoded.fault)
                attachment_states = dict(candidate.attachment_states)
                attachment_states[head.port] = encoded.state
                candidate = QueuedAddressResponderState(
                    candidate.handler_state,
                    attachment_states,
                    candidate.queue[1:],
                    candidate.next_request_serial,
                    candidate.advance_index,
                )
                emissions.extend(
                    PortEmission(head.port, event)
                    for event in encoded.events
                )
                continue

            try:
                handled = self.handler.access(
                    candidate.handler_state, head.access
                )
            except Exception as error:
                return DutTransition(
                    original,
                    fault=self._fault(
                        "handler",
                        f"address handler raised {type(error).__name__}: {error}",
                    ),
                )
            if not isinstance(handled, AddressStep):
                return DutTransition(
                    original,
                    fault=self._fault(
                        "handler_result",
                        "address target must return AddressStep",
                    ),
                )
            if handled.result.effects:
                return DutTransition(
                    original,
                    fault=self._fault(
                        "unhandled_effect",
                        "queued responder has no consumer for handler effects",
                    ),
                )
            encoded = attachment.encode_completion(
                candidate.attachment_states[head.port],
                head.reply_context,
                handled.result,
            )
            if encoded.fault is not None:
                return DutTransition(original, fault=encoded.fault)
            attachment_states = dict(candidate.attachment_states)
            attachment_states[head.port] = encoded.state
            candidate = QueuedAddressResponderState(
                handled.state,
                attachment_states,
                candidate.queue[1:],
                candidate.next_request_serial,
                candidate.advance_index,
            )
            emissions.extend(
                PortEmission(head.port, event) for event in encoded.events
            )
        return DutTransition(candidate, tuple(emissions))

    def is_quiescent(self, state: object) -> bool:
        if not isinstance(state, QueuedAddressResponderState):
            return False
        return not state.queue and all(
            attachment.is_quiescent(state.attachment_states[name])
            for name, attachment in self.attachments.items()
        )

    def queue_usage(self, state: QueuedAddressResponderState) -> tuple[int, int]:
        self._require_state(state)
        return (
            sum(isinstance(item, QueuedAddressRequest) for item in state.queue),
            self.capacity,
        )

    def _require_state(self, state: object) -> None:
        if not isinstance(state, QueuedAddressResponderState):
            raise TypeError(
                "QueuedAddressResponderBackend requires "
                "QueuedAddressResponderState"
            )
        if set(state.attachment_states) != set(self.attachments):
            raise ValueError(
                "queued responder state does not match configured attachments"
            )
        if (
            sum(
                isinstance(item, QueuedAddressRequest)
                for item in state.queue
            )
            > self.capacity
        ):
            raise ValueError("queued responder state exceeds request capacity")

    @staticmethod
    def _fault(suffix: str, reason: str) -> SemanticFault:
        return SemanticFault(
            f"queued_address_responder.{suffix}",
            reason,
            ConstraintScope.VIRTUAL_DUT,
        )


def constant_address_delay(delay_steps: int) -> AddressDelayPolicy:
    """Return a policy whose requests mature after fixed advance steps."""

    if (
        not isinstance(delay_steps, int)
        or isinstance(delay_steps, bool)
        or delay_steps < 0
    ):
        raise ValueError("constant address delay must be non-negative")

    def policy(
        _access: AddressAccess, _context: AddressDelayContext
    ) -> int:
        return delay_steps

    return policy


__all__ = [
    "AddressDelayContext",
    "AddressDelayPolicy",
    "QueuedAddressEntry",
    "QueuedAddressErrorCompletion",
    "QueuedAddressPhase",
    "QueuedAddressRequest",
    "QueuedAddressResponderBackend",
    "QueuedAddressResponderState",
    "constant_address_delay",
]

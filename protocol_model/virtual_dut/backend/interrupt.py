"""Protocol-neutral edge interrupt collection and target handling."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    ResourceExhaustionPolicy,
    SemanticFault,
)

from ..attachments.notification import (
    Notification,
    NotificationHandlerAttachment,
    NotificationNotifierAttachment,
)
from ..binding.port import InterfaceAttachmentBinding
from .base import VirtualDutBackend
from .transition import DutTransition, PortEmission, PortInput


@dataclass(frozen=True)
class PendingInterrupt:
    arrival_serial: int
    ingress_port: str
    notification: Notification


@dataclass(frozen=True)
class ActiveInterrupt:
    pending: PendingInterrupt
    delivery: Notification


@dataclass(frozen=True)
class InterruptControllerState:
    attachment_states: Mapping[str, object]
    pending: tuple[PendingInterrupt, ...] = ()
    active: ActiveInterrupt | None = None
    next_arrival_serial: int = 0
    next_delivery_reference: int = 0
    completed_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attachment_states",
            MappingProxyType(dict(self.attachment_states)),
        )


class PriorityInterruptControllerBackend(VirtualDutBackend):
    """Collect edge occurrences and serialize them to one target.

    The lower numeric priority wins and equal-priority notifications retain
    arrival order.  An ingress COMPLETE is emitted after the controller has
    safely queued an edge.  The target-facing notification remains active
    until its matching COMPLETE/EOI arrives; only then can another item be
    selected.

    Capacity counts both queued and active occurrences.  Exhaustion is a
    typed unaccepted ``BLOCK`` transition by default.  ``FAULT`` is available
    for scenarios that treat overflow as a use-contract violation.  This
    notification transport has no error completion, so ``ERROR_COMPLETION``
    is rejected during construction.
    """

    def __init__(
        self,
        ingress_bindings: Mapping[str, InterfaceAttachmentBinding],
        target_binding: InterfaceAttachmentBinding,
        *,
        capacity: int,
        exhaustion_policy: ResourceExhaustionPolicy | str = (
            ResourceExhaustionPolicy.BLOCK
        ),
    ) -> None:
        ingress_bindings = dict(ingress_bindings)
        if not ingress_bindings:
            raise ValueError("interrupt controller requires an ingress port")
        if set(ingress_bindings) != {
            item.name for item in ingress_bindings.values()
        }:
            raise ValueError("interrupt ingress binding keys must match ports")
        if any(
            not isinstance(item.attachment, NotificationHandlerAttachment)
            for item in ingress_bindings.values()
        ):
            raise TypeError(
                "interrupt controller ingress requires handler attachments"
            )
        if not isinstance(target_binding, InterfaceAttachmentBinding):
            raise TypeError("interrupt controller requires a target binding")
        if not isinstance(
            target_binding.attachment, NotificationNotifierAttachment
        ):
            raise TypeError(
                "interrupt controller target requires a notifier attachment"
            )
        if target_binding.name in ingress_bindings:
            raise ValueError("interrupt target and ingress ports must differ")
        if (
            not isinstance(capacity, int)
            or isinstance(capacity, bool)
            or capacity <= 0
        ):
            raise ValueError("interrupt controller capacity must be positive")
        try:
            normalized_exhaustion_policy = ResourceExhaustionPolicy(
                exhaustion_policy
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "interrupt controller requires a valid resource exhaustion policy"
            ) from error
        if (
            normalized_exhaustion_policy
            is ResourceExhaustionPolicy.ERROR_COMPLETION
        ):
            raise ValueError(
                "interrupt notification has no protocol-visible error completion; "
                "use BLOCK or FAULT"
            )

        self.ingress_bindings = MappingProxyType(ingress_bindings)
        self.ingress_attachments = MappingProxyType(
            {
                name: binding.attachment
                for name, binding in ingress_bindings.items()
            }
        )
        self.target_binding = target_binding
        self.target_attachment = target_binding.attachment
        self.bindings = MappingProxyType(
            {**ingress_bindings, target_binding.name: target_binding}
        )
        self.capacity = capacity
        self.exhaustion_policy = normalized_exhaustion_policy
        self.reference_modulus = 1 << int(
            target_binding.port.protocol.parameters["reference_width"]
        )

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, InterfaceAttachmentBinding]:
        return self.bindings

    def initial_state(self) -> InterruptControllerState:
        return InterruptControllerState(
            {
                name: binding.attachment.initial_state()
                for name, binding in self.bindings.items()
            }
        )

    def accept(self, state: object, action: PortInput) -> DutTransition:
        self._require_state(state)
        assert isinstance(state, InterruptControllerState)
        if action.port in self.ingress_attachments:
            return self._accept_ingress(state, action)
        if action.port == self.target_binding.name:
            return self._accept_target_completion(state, action)
        return DutTransition(
            state,
            fault=self._fault(
                "unknown_port",
                f"interrupt controller has no port {action.port!r}",
            ),
        )

    def _accept_ingress(
        self, state: InterruptControllerState, action: PortInput
    ) -> DutTransition:
        attachment = self.ingress_attachments[action.port]
        decoded = attachment.decode_notification(
            state.attachment_states[action.port], action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)
        if decoded.notification is None:
            return DutTransition(
                state,
                fault=self._fault(
                    "missing_notification",
                    "interrupt ingress produced no notification operation",
                ),
            )
        if self.occupancy(state) >= self.capacity:
            reason = (
                "interrupt controller queue is full "
                f"({self.occupancy(state)}/{self.capacity})"
            )
            if self.exhaustion_policy is ResourceExhaustionPolicy.BLOCK:
                return DutTransition(
                    state,
                    blocked=ResourceDemand(
                        "notification_entries",
                        ConstraintScope.VIRTUAL_DUT,
                        available=self.capacity - self.occupancy(state),
                        capacity=self.capacity,
                        reason=reason,
                        location=action.port,
                    ),
                )
            return DutTransition(
                state,
                fault=self._fault("capacity", reason),
            )
        completed = attachment.encode_completion(
            decoded.state, decoded.reply_context
        )
        if completed.fault is not None:
            return DutTransition(state, fault=completed.fault)
        attachment_states = dict(state.attachment_states)
        attachment_states[action.port] = completed.state
        queued = PendingInterrupt(
            state.next_arrival_serial,
            action.port,
            decoded.notification,
        )
        candidate = InterruptControllerState(
            attachment_states,
            (*state.pending, queued),
            state.active,
            state.next_arrival_serial + 1,
            state.next_delivery_reference,
            state.completed_count,
        )
        return DutTransition(
            candidate,
            tuple(
                PortEmission(action.port, event)
                for event in completed.events
            ),
        )

    def _accept_target_completion(
        self, state: InterruptControllerState, action: PortInput
    ) -> DutTransition:
        decoded = self.target_attachment.decode_completion(
            state.attachment_states[action.port], action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)
        if state.active is None:
            return DutTransition(
                state,
                fault=self._fault(
                    "orphan_eoi",
                    "target completion has no active interrupt",
                ),
            )
        completion = decoded.completion
        if completion is None:
            return DutTransition(
                state,
                fault=self._fault(
                    "missing_completion",
                    "target attachment produced no completion operation",
                ),
            )
        delivery = state.active.delivery
        if (
            completion.notification_ref != delivery.notification_ref
            or completion.interrupt_id != delivery.interrupt_id
        ):
            return DutTransition(
                state,
                fault=self._fault(
                    "eoi_correlation",
                    "target completion does not match the active interrupt",
                ),
            )
        attachment_states = dict(state.attachment_states)
        attachment_states[action.port] = decoded.state
        candidate = InterruptControllerState(
            attachment_states,
            state.pending,
            None,
            state.next_arrival_serial,
            state.next_delivery_reference,
            state.completed_count + 1,
        )
        return self._activate_next(candidate)

    def advance(
        self, state: InterruptControllerState, *, steps: int = 1
    ) -> DutTransition:
        self._require_state(state)
        if (
            not isinstance(steps, int)
            or isinstance(steps, bool)
            or steps <= 0
        ):
            raise ValueError("interrupt controller advance steps must be positive")
        original = state
        candidate = state
        emissions: list[PortEmission] = []
        for _ in range(steps):
            activated = self._activate_next(candidate)
            if activated.fault is not None:
                return DutTransition(original, fault=activated.fault)
            candidate = activated.state
            emissions.extend(activated.emissions)
        return DutTransition(candidate, tuple(emissions))

    def _activate_next(
        self, state: InterruptControllerState
    ) -> DutTransition:
        if state.active is not None or not state.pending:
            return DutTransition(state)
        selected_index = min(
            range(len(state.pending)),
            key=lambda index: (
                state.pending[index].notification.priority,
                state.pending[index].arrival_serial,
            ),
        )
        selected = state.pending[selected_index]
        pending = list(state.pending)
        del pending[selected_index]
        delivery = Notification(
            state.next_delivery_reference,
            selected.notification.interrupt_id,
            selected.notification.priority,
        )
        encoded = self.target_attachment.encode_notification(
            state.attachment_states[self.target_binding.name], delivery
        )
        if encoded.fault is not None:
            return DutTransition(state, fault=encoded.fault)
        attachment_states = dict(state.attachment_states)
        attachment_states[self.target_binding.name] = encoded.state
        candidate = InterruptControllerState(
            attachment_states,
            tuple(pending),
            ActiveInterrupt(selected, delivery),
            state.next_arrival_serial,
            (state.next_delivery_reference + 1) % self.reference_modulus,
            state.completed_count,
        )
        return DutTransition(
            candidate,
            tuple(
                PortEmission(self.target_binding.name, event)
                for event in encoded.events
            ),
        )

    def occupancy(self, state: InterruptControllerState) -> int:
        self._require_state(state)
        return len(state.pending) + (state.active is not None)

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, InterruptControllerState)
            and not state.pending
            and state.active is None
            and all(
                binding.attachment.is_quiescent(
                    state.attachment_states[name]
                )
                for name, binding in self.bindings.items()
            )
        )

    @staticmethod
    def _require_state(state: object) -> None:
        if not isinstance(state, InterruptControllerState):
            raise TypeError(
                "PriorityInterruptControllerBackend requires "
                "InterruptControllerState"
            )

    @staticmethod
    def _fault(suffix: str, reason: str) -> SemanticFault:
        return SemanticFault(
            f"interrupt_controller.{suffix}",
            reason,
            ConstraintScope.VIRTUAL_DUT,
        )


@dataclass(frozen=True)
class InterruptTargetState:
    attachment_state: object
    active: Notification | None = None
    handled: tuple[Notification, ...] = ()


class ExplicitEoiInterruptTargetBackend(VirtualDutBackend):
    """Capture one delivered interrupt and emit EOI on explicit advance."""

    def __init__(self, binding: InterfaceAttachmentBinding) -> None:
        if not isinstance(binding, InterfaceAttachmentBinding):
            raise TypeError("interrupt target requires a port binding")
        if not isinstance(
            binding.attachment, NotificationHandlerAttachment
        ):
            raise TypeError("interrupt target requires a handler attachment")
        self.binding = binding
        self.attachment = binding.attachment

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, InterfaceAttachmentBinding]:
        return {self.binding.name: self.binding}

    def initial_state(self) -> InterruptTargetState:
        return InterruptTargetState(self.attachment.initial_state())

    def accept(self, state: object, action: PortInput) -> DutTransition:
        self._require_state(state)
        assert isinstance(state, InterruptTargetState)
        if action.port != self.binding.name:
            return DutTransition(
                state,
                fault=SemanticFault(
                    "interrupt_target.unknown_port",
                    f"interrupt target has no port {action.port!r}",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        if state.active is not None:
            return DutTransition(
                state,
                blocked=ResourceDemand(
                    "active_interrupt_slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=1,
                    reason=(
                        "interrupt target already has an active notification"
                    ),
                    location=action.port,
                ),
            )
        decoded = self.attachment.decode_notification(
            state.attachment_state, action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)
        if decoded.notification is None:
            return DutTransition(
                state,
                fault=SemanticFault(
                    "interrupt_target.missing_notification",
                    "interrupt target attachment produced no notification",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        return DutTransition(
            InterruptTargetState(
                decoded.state, decoded.notification, state.handled
            )
        )

    def advance(
        self, state: InterruptTargetState, *, steps: int = 1
    ) -> DutTransition:
        self._require_state(state)
        if (
            not isinstance(steps, int)
            or isinstance(steps, bool)
            or steps <= 0
        ):
            raise ValueError("interrupt target advance steps must be positive")
        candidate = state
        emissions: list[PortEmission] = []
        for _ in range(steps):
            if candidate.active is None:
                continue
            completed = self.attachment.encode_completion(
                candidate.attachment_state, candidate.active
            )
            if completed.fault is not None:
                return DutTransition(state, fault=completed.fault)
            emissions.extend(
                PortEmission(self.binding.name, event)
                for event in completed.events
            )
            candidate = InterruptTargetState(
                completed.state,
                None,
                (*candidate.handled, candidate.active),
            )
        return DutTransition(candidate, tuple(emissions))

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, InterruptTargetState)
            and state.active is None
            and self.attachment.is_quiescent(state.attachment_state)
        )

    @staticmethod
    def _require_state(state: object) -> None:
        if not isinstance(state, InterruptTargetState):
            raise TypeError(
                "ExplicitEoiInterruptTargetBackend requires "
                "InterruptTargetState"
            )


__all__ = [
    "ActiveInterrupt",
    "ExplicitEoiInterruptTargetBackend",
    "InterruptControllerState",
    "InterruptTargetState",
    "PendingInterrupt",
    "PriorityInterruptControllerBackend",
]

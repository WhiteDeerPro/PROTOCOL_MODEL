"""Attachments for the project edge-interrupt notification interface."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.control.interrupt import (
    INTERRUPT_NOTIFICATION_FAMILY,
)
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    SemanticFault,
)
from protocol_model.virtual_dut.attachments.base import AttachmentEmission
from protocol_model.virtual_dut.attachments.notification import (
    Notification,
    NotificationCompletion,
    NotificationCompletionDecode,
    NotificationDecode,
    NotificationHandlerAttachment,
    NotificationNotifierAttachment,
)
from protocol_model.virtual_dut.attachments.validation import (
    incoming_event_fault,
    outgoing_event_fault,
)


_INTERRUPT_EVENT_KINDS = {"notify", "complete"}


def _require_interrupt_link(protocol: InterfaceProtocol, role: str) -> None:
    if protocol.interface_family != INTERRUPT_NOTIFICATION_FAMILY:
        raise ValueError(
            "interrupt attachment requires an interrupt-notification "
            "InterfaceProtocol family"
        )
    if role not in protocol.roles:
        raise ValueError(f"interrupt notification protocol has no {role!r} role")
    if set(protocol.event_kinds) != _INTERRUPT_EVENT_KINDS:
        raise ValueError(
            "interrupt attachment requires native notify/complete channels"
        )
    if protocol.parameters.get("trigger_mode") != "edge":
        raise ValueError("current notification attachment supports edge mode")


@dataclass(frozen=True)
class InterruptNotifierAttachmentState:
    pending: tuple[tuple[int, int], ...] = ()


class InterruptNotifierAttachment(NotificationNotifierAttachment):
    """Map notifications onto NOTIFY and correlate FIFO COMPLETE events."""

    role = "notifier"

    def __init__(self, protocol: InterfaceProtocol) -> None:
        _require_interrupt_link(protocol, self.role)
        self.protocol = protocol

    def initial_state(self) -> InterruptNotifierAttachmentState:
        return InterruptNotifierAttachmentState()

    def encode_notification(
        self, state: object, notification: Notification
    ) -> AttachmentEmission:
        if not isinstance(state, InterruptNotifierAttachmentState):
            raise TypeError(
                "InterruptNotifierAttachment requires "
                "InterruptNotifierAttachmentState"
            )
        if notification.attributes:
            return AttachmentEmission(
                state,
                fault=self._fault(
                    "attributes",
                    "edge interrupt transport cannot encode notification attributes",
                ),
            )
        event = CanonicalEvent(
            "INTERRUPT_NOTIFY",
            notification.notification_ref,
            {
                "interrupt_id": notification.interrupt_id,
                "priority": notification.priority,
            },
        )
        fault = outgoing_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="interrupt_notifier",
        )
        if fault is not None:
            return AttachmentEmission(state, fault=fault)
        return AttachmentEmission(
            InterruptNotifierAttachmentState(
                (
                    *state.pending,
                    (notification.notification_ref, notification.interrupt_id),
                )
            ),
            (event,),
        )

    def decode_completion(
        self, state: object, event: CanonicalEvent
    ) -> NotificationCompletionDecode:
        if not isinstance(state, InterruptNotifierAttachmentState):
            raise TypeError(
                "InterruptNotifierAttachment requires "
                "InterruptNotifierAttachmentState"
            )
        fault = incoming_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="interrupt_notifier",
        )
        if fault is not None:
            return NotificationCompletionDecode(state, fault=fault)
        if not state.pending:
            return NotificationCompletionDecode(
                state,
                fault=self._fault(
                    "orphan_completion",
                    "interrupt COMPLETE has no locally pending notification",
                ),
            )
        reference, interrupt_id = state.pending[0]
        if event.key != reference:
            return NotificationCompletionDecode(
                state,
                fault=self._fault(
                    "completion_order",
                    f"oldest notification reference is {reference!r}, "
                    f"got {event.key!r}",
                ),
            )
        if int(event.payload["interrupt_id"]) != interrupt_id:
            return NotificationCompletionDecode(
                state,
                fault=self._fault(
                    "completion_interrupt_id",
                    f"notification {reference!r} uses interrupt id "
                    f"{interrupt_id}, got {event.payload['interrupt_id']!r}",
                ),
            )
        return NotificationCompletionDecode(
            InterruptNotifierAttachmentState(state.pending[1:]),
            NotificationCompletion(reference, interrupt_id),
        )

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, InterruptNotifierAttachmentState)
            and not state.pending
        )

    @staticmethod
    def _fault(suffix: str, reason: str) -> SemanticFault:
        return SemanticFault(
            f"interrupt_notifier.{suffix}",
            reason,
            ConstraintScope.VIRTUAL_DUT,
        )


class InterruptHandlerAttachment(NotificationHandlerAttachment):
    """Map received NOTIFY events to operations and encode COMPLETE."""

    role = "handler"

    def __init__(self, protocol: InterfaceProtocol) -> None:
        _require_interrupt_link(protocol, self.role)
        self.protocol = protocol

    def decode_notification(
        self, state: object, event: CanonicalEvent
    ) -> NotificationDecode:
        fault = incoming_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="interrupt_handler",
        )
        if fault is not None:
            return NotificationDecode(state, fault=fault)
        notification = Notification(
            int(event.key),
            int(event.payload["interrupt_id"]),
            int(event.payload["priority"]),
        )
        return NotificationDecode(state, notification, notification)

    def encode_completion(
        self, state: object, context: object | None
    ) -> AttachmentEmission:
        if not isinstance(context, Notification):
            return AttachmentEmission(
                state,
                fault=SemanticFault(
                    "interrupt_handler.reply_context",
                    "interrupt completion requires its decoded notification",
                    ConstraintScope.VIRTUAL_DUT,
                ),
            )
        event = CanonicalEvent(
            "INTERRUPT_COMPLETE",
            context.notification_ref,
            {"interrupt_id": context.interrupt_id},
        )
        fault = outgoing_event_fault(
            self.protocol,
            self.role,
            event,
            rule_prefix="interrupt_handler",
        )
        if fault is not None:
            return AttachmentEmission(state, fault=fault)
        return AttachmentEmission(state, (event,))


__all__ = [
    "InterruptHandlerAttachment",
    "InterruptNotifierAttachment",
    "InterruptNotifierAttachmentState",
]

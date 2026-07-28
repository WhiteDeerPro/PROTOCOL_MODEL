"""A small acknowledged edge-notification InterfaceProtocol.

This is a project-level control contract, not an implementation of Arm GIC or
another interrupt-controller architecture.  One NOTIFY represents one queued
edge occurrence.  COMPLETE means that the receiver has finished its local
responsibility for that occurrence: a collecting controller can complete when
it has retained the notification, while a processor-facing target completes
when it performs its EOI/acknowledge action.
"""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.interface import (
    InterfaceEventKind,
    InterfaceProtocol,
)
from protocol_model.semantics import (
    BitVectorDomain,
    CanonicalEvent,
    ConstraintKind,
    ConstraintScope,
    EventOffer,
    EventField,
    EventSchema,
    ObligationDecl,
    ResourceDecl,
    SemanticComponent,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
)


INTERRUPT_NOTIFICATION_FAMILY = "control.interrupt_notification"


@dataclass(frozen=True)
class InterruptNotificationConfig:
    """Transport widths and an optional outstanding-notification bound."""

    interrupt_id_width: int = 16
    priority_width: int = 8
    reference_width: int = 16
    maximum_outstanding: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("interrupt_id_width", self.interrupt_id_width),
            ("priority_width", self.priority_width),
            ("reference_width", self.reference_width),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer")
        if self.maximum_outstanding is not None and (
            not isinstance(self.maximum_outstanding, int)
            or isinstance(self.maximum_outstanding, bool)
            or self.maximum_outstanding <= 0
        ):
            raise ValueError("maximum_outstanding must be positive or None")


@dataclass(frozen=True)
class _PendingNotification:
    reference: int
    interrupt_id: int
    origin_index: int


@dataclass(frozen=True)
class InterruptNotificationLinkState:
    pending: tuple[_PendingNotification, ...] = ()


@dataclass(frozen=True)
class InterruptNotificationLifecycleMonitor(
    SemanticComponent[
        CanonicalEvent,
        InterruptNotificationLinkState,
        _PendingNotification,
    ]
):
    """Correlate FIFO completions and reject reused live references."""

    name: str
    maximum_outstanding: int | None = None
    resource_name: str = "interrupt_notification.pending"

    @property
    def event_kinds(self) -> frozenset[str]:
        return frozenset(("INTERRUPT_NOTIFY", "INTERRUPT_COMPLETE"))

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in self.event_kinds

    def initial_state(self) -> InterruptNotificationLinkState:
        return InterruptNotificationLinkState()

    def is_quiescent(self, state: InterruptNotificationLinkState) -> bool:
        return not state.pending

    def resource_usage(
        self, state: InterruptNotificationLinkState
    ) -> dict[str, int]:
        return {self.resource_name: len(state.pending)}

    def event_offers(
        self, state: InterruptNotificationLinkState
    ) -> tuple[EventOffer, ...]:
        offers = []
        if (
            self.maximum_outstanding is None
            or len(state.pending) < self.maximum_outstanding
        ):
            offers.append(EventOffer.unconstrained("INTERRUPT_NOTIFY"))
        if state.pending:
            oldest = state.pending[0]
            offers.append(
                EventOffer.constrained(
                    "INTERRUPT_COMPLETE",
                    key=oldest.reference,
                    payload={"interrupt_id": oldest.interrupt_id},
                )
            )
        return tuple(offers)

    def step(
        self,
        state: InterruptNotificationLinkState,
        event: CanonicalEvent,
    ) -> SemanticStep[InterruptNotificationLinkState, _PendingNotification]:
        if event.trace_index is None:
            return self._fault(
                state,
                "trace_index",
                "interrupt events must be normalized by an InterfaceSession",
            )
        if event.kind == "INTERRUPT_NOTIFY":
            if (
                self.maximum_outstanding is not None
                and len(state.pending) >= self.maximum_outstanding
            ):
                return self._fault(
                    state,
                    "capacity",
                    "the notification interface has no free outstanding entry",
                )
            if any(item.reference == event.key for item in state.pending):
                return self._fault(
                    state,
                    "live_reference_reuse",
                    f"notification reference {event.key!r} is already pending",
                )
            pending = _PendingNotification(
                int(event.key),
                int(event.payload["interrupt_id"]),
                event.trace_index,
            )
            return SemanticStep(
                InterruptNotificationLinkState((*state.pending, pending))
            )
        if event.kind != "INTERRUPT_COMPLETE":
            return self._fault(
                state,
                "alphabet",
                f"unexpected interrupt event {event.kind!r}",
            )
        if not state.pending:
            return self._fault(
                state,
                "orphan_completion",
                "interrupt completion has no pending notification",
            )
        oldest = state.pending[0]
        if event.key != oldest.reference:
            return self._fault(
                state,
                "completion_order",
                f"oldest notification reference is {oldest.reference!r}, "
                f"got {event.key!r}",
            )
        if int(event.payload["interrupt_id"]) != oldest.interrupt_id:
            return self._fault(
                state,
                "completion_interrupt_id",
                f"notification {oldest.reference!r} carries interrupt id "
                f"{oldest.interrupt_id}, got "
                f"{event.payload['interrupt_id']!r}",
            )
        return SemanticStep(
            InterruptNotificationLinkState(state.pending[1:]),
            (oldest,),
            causal_predecessors=(oldest.origin_index,),
        )

    def _fault(
        self,
        state: InterruptNotificationLinkState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[InterruptNotificationLinkState, _PendingNotification]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}", reason, ConstraintScope.INTERFACE
            ),
        )


def build_interrupt_notification_interface(
    config: InterruptNotificationConfig | None = None,
) -> InterfaceProtocol:
    """Build an acknowledged, FIFO-completed edge-notification interface.

    A lower numeric priority value denotes a higher priority.  The InterfaceProtocol
    validates transport lifecycles only; arbitration between several incoming
    connections remains behavior of an interrupt-controller VirtualDut.
    """

    config = config or InterruptNotificationConfig()
    reference = BitVectorDomain(config.reference_width)
    interrupt_id = EventField(
        "interrupt_id",
        BitVectorDomain(config.interrupt_id_width),
        "stable interrupt source identifier",
    )
    notify = EventSchema(
        "INTERRUPT_NOTIFY",
        {
            "interrupt_id": interrupt_id,
            "priority": EventField(
                "priority",
                BitVectorDomain(config.priority_width),
                "lower numeric value has higher priority",
            ),
        },
        reference,
    )
    complete = EventSchema(
        "INTERRUPT_COMPLETE",
        {"interrupt_id": interrupt_id},
        reference,
    )
    event_kinds = {
        "notify": InterfaceEventKind(
            "notify", "notifier", "handler", notify
        ),
        "complete": InterfaceEventKind(
            "complete", "handler", "notifier", complete
        ),
    }
    monitor = InterruptNotificationLifecycleMonitor(
        "interrupt_notification.lifecycle",
        config.maximum_outstanding,
    )
    fragment = SemanticFragment(
        "interrupt_notification.edge_semantics",
        constraints=(
            SemanticConstraint(
                "interrupt_notification.edge_occurrence",
                "each NOTIFY denotes one retained edge occurrence",
                ConstraintScope.INTERFACE,
                targets=("INTERRUPT_NOTIFY",),
            ),
            SemanticConstraint(
                "interrupt_notification.completion_correlation",
                "COMPLETE returns the oldest live reference and interrupt id",
                ConstraintScope.INTERFACE,
                kind=ConstraintKind.RELATION,
                targets=("INTERRUPT_NOTIFY", "INTERRUPT_COMPLETE"),
            ),
        ),
        resources=(
            ResourceDecl(
                "interrupt_notification.pending",
                ConstraintScope.INTERFACE,
                capacity=config.maximum_outstanding,
                description="edge occurrences accepted but not locally completed",
                acquired_by=("INTERRUPT_NOTIFY",),
                released_by=("matching INTERRUPT_COMPLETE", "reset"),
            ),
        ),
        obligations=(
            ObligationDecl(
                "interrupt_notification.eventual_completion",
                ConstraintScope.INTERFACE,
                "INTERRUPT_NOTIFY",
                "INTERRUPT_COMPLETE",
                "a retained edge is eventually completed when the handler progresses",
            ),
        ),
        sources=("Protocol Model edge-notification control contract",),
    )
    return InterfaceProtocol.define(
        "interrupt_edge_notification",
        interface_family=INTERRUPT_NOTIFICATION_FAMILY,
        roles=frozenset(("notifier", "handler")),
        event_kinds=event_kinds,
        fragments=(fragment,),
        parameters={
            "interrupt_id_width": config.interrupt_id_width,
            "priority_width": config.priority_width,
            "reference_width": config.reference_width,
            "maximum_outstanding": config.maximum_outstanding,
            "trigger_mode": "edge",
        },
        monitors={monitor.name: monitor},
    )


__all__ = [
    "INTERRUPT_NOTIFICATION_FAMILY",
    "InterruptNotificationConfig",
    "InterruptNotificationLifecycleMonitor",
    "InterruptNotificationLinkState",
    "build_interrupt_notification_interface",
]

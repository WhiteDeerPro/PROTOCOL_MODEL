"""Immutable queue, arbitration, and owner state for address crossbars."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..address.access import AccessStatus, AddressAccess, AddressRead, AddressWrite
from .ownership import RoutedAddressRequest


def _non_negative_integer(value: object, *, subject: str) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{subject} must be a non-negative integer")


@dataclass(frozen=True)
class QueuedRoutedAddressRequest:
    """One complete ingress operation waiting for local scheduling.

    A route miss deliberately has no egress or output access.  Keeping it in
    the same ingress FIFO prevents a local error response from overtaking an
    earlier mapped operation.
    """

    request_id: int
    ingress_port: str
    input_access: AddressAccess
    reply_context: object | None
    egress_port: str | None = None
    output_access: AddressAccess | None = None

    def __post_init__(self) -> None:
        _non_negative_integer(
            self.request_id, subject="queued crossbar request id"
        )
        if not isinstance(self.ingress_port, str) or not self.ingress_port:
            raise ValueError("queued crossbar request requires an ingress port")
        if not isinstance(self.input_access, (AddressRead, AddressWrite)):
            raise TypeError("queued crossbar request requires AddressAccess")
        if (self.egress_port is None) != (self.output_access is None):
            raise ValueError(
                "queued crossbar request must have both an egress and output "
                "access, or neither for a route miss"
            )
        if self.egress_port is not None and (
            not isinstance(self.egress_port, str) or not self.egress_port
        ):
            raise ValueError(
                "queued crossbar request egress must be a non-empty name"
            )
        if self.output_access is not None and not isinstance(
            self.output_access, (AddressRead, AddressWrite)
        ):
            raise TypeError(
                "queued crossbar output operation requires AddressAccess"
            )

    @property
    def is_route_miss(self) -> bool:
        return self.egress_port is None


@dataclass(frozen=True)
class QueuedIngressErrorCompletion:
    """One overflow request retained for an ordered local error response.

    Each ingress has at most one such emergency marker.  It carries only the
    reply context needed by the ingress attachment; it is never routed to an
    egress and therefore consumes no downstream owner-table entry.
    """

    request_id: int
    ingress_port: str
    reply_context: object | None
    status: AccessStatus = AccessStatus.ACCESS_ERROR

    def __post_init__(self) -> None:
        _non_negative_integer(
            self.request_id, subject="crossbar error marker request id"
        )
        if not isinstance(self.ingress_port, str) or not self.ingress_port:
            raise ValueError(
                "crossbar error marker requires an ingress port"
            )
        if self.status is not AccessStatus.ACCESS_ERROR:
            raise ValueError(
                "crossbar overflow marker must encode ACCESS_ERROR"
            )


QueuedCrossbarEntry = (
    QueuedRoutedAddressRequest | QueuedIngressErrorCompletion
)


@dataclass(frozen=True)
class ScheduledAddressCrossbarState:
    """Atomic snapshot of every local crossbar transport and shared resource."""

    ingress_states: Mapping[str, object]
    egress_states: Mapping[str, object]
    ingress_queues: Mapping[str, tuple[QueuedCrossbarEntry, ...]]
    pending: Mapping[int, RoutedAddressRequest]
    round_robin_cursors: Mapping[str, int]
    next_request_id: int = 0
    advance_index: int = 0

    def __post_init__(self) -> None:
        ingress_states = dict(self.ingress_states)
        egress_states = dict(self.egress_states)
        ingress_queues = {
            name: tuple(queue) for name, queue in self.ingress_queues.items()
        }
        pending = dict(self.pending)
        cursors = dict(self.round_robin_cursors)

        if any(not isinstance(name, str) or not name for name in ingress_states):
            raise ValueError("crossbar ingress state names must be non-empty")
        if any(not isinstance(name, str) or not name for name in egress_states):
            raise ValueError("crossbar egress state names must be non-empty")
        if set(ingress_states) != set(ingress_queues):
            raise ValueError(
                "crossbar ingress queues must match ingress attachment states"
            )
        if set(egress_states) != set(cursors):
            raise ValueError(
                "crossbar arbitration cursors must match egress attachment states"
            )

        queued_ids: set[int] = set()
        for ingress, queue in ingress_queues.items():
            if any(
                not isinstance(
                    item,
                    (
                        QueuedRoutedAddressRequest,
                        QueuedIngressErrorCompletion,
                    ),
                )
                for item in queue
            ):
                raise TypeError("crossbar ingress queue has an invalid entry")
            if any(item.ingress_port != ingress for item in queue):
                raise ValueError(
                    "crossbar queued request does not match its ingress queue"
                )
            ids = {item.request_id for item in queue}
            if len(ids) != len(queue) or queued_ids.intersection(ids):
                raise ValueError("crossbar queued request ids must be unique")
            queued_ids.update(ids)
            error_markers = sum(
                isinstance(item, QueuedIngressErrorCompletion)
                for item in queue
            )
            if error_markers > 1:
                raise ValueError(
                    "crossbar ingress allows one emergency error marker"
                )

        if any(
            not isinstance(item, RoutedAddressRequest)
            for item in pending.values()
        ):
            raise TypeError("crossbar pending table has an invalid owner entry")
        if any(
            request_id != owner.request_id
            for request_id, owner in pending.items()
        ):
            raise ValueError("crossbar pending keys must match owner request ids")
        if queued_ids.intersection(pending):
            raise ValueError("crossbar request cannot be both queued and active")
        active_ingresses = tuple(item.ingress_port for item in pending.values())
        active_egresses = tuple(item.egress_port for item in pending.values())
        if len(set(active_ingresses)) != len(active_ingresses):
            raise ValueError("crossbar ingress has more than one active request")
        if len(set(active_egresses)) != len(active_egresses):
            raise ValueError("crossbar egress has more than one active request")

        for value, subject in (
            (self.next_request_id, "crossbar next request id"),
            (self.advance_index, "crossbar advance index"),
        ):
            _non_negative_integer(value, subject=subject)
        live_ids = queued_ids.union(pending)
        if live_ids and self.next_request_id <= max(live_ids):
            raise ValueError(
                "crossbar next request id must exceed every live request id"
            )
        for cursor in cursors.values():
            _non_negative_integer(cursor, subject="crossbar arbitration cursor")

        object.__setattr__(
            self, "ingress_states", MappingProxyType(ingress_states)
        )
        object.__setattr__(
            self, "egress_states", MappingProxyType(egress_states)
        )
        object.__setattr__(
            self, "ingress_queues", MappingProxyType(ingress_queues)
        )
        object.__setattr__(self, "pending", MappingProxyType(pending))
        object.__setattr__(
            self, "round_robin_cursors", MappingProxyType(cursors)
        )


__all__ = [
    "QueuedCrossbarEntry",
    "QueuedIngressErrorCompletion",
    "QueuedRoutedAddressRequest",
    "ScheduledAddressCrossbarState",
]

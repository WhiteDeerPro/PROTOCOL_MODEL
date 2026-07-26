"""Explicitly scheduled N-ingress/M-egress address crossbar backend."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    ResourceExhaustionPolicy,
    SemanticFault,
)

from ..address.access import AccessResult, AccessStatus
from ..arbitration import round_robin_grant
from ..attachments.address import (
    AddressCompleterAttachment,
    AddressRequest,
    AddressRequesterAttachment,
)
from ..backend.base import VirtualDutBackend
from ..backend.transition import DutTransition, PortEmission, PortInput
from ..binding.port import InterfaceAttachmentBinding
from .crossbar_state import (
    QueuedIngressErrorCompletion,
    QueuedRoutedAddressRequest,
    ScheduledAddressCrossbarState,
)
from .projection import (
    ADDRESS_ROUTER_PROJECTION,
    AddressRouterBoundaryProjection,
)
from .route import AddressRoute, validate_address_routes
from .ownership import RoutedAddressRequest


class ScheduledAddressCrossbarBackend(VirtualDutBackend):
    """Finite per-ingress queues, per-egress arbitration, and owner return.

    Complete address operations are admitted into an ingress FIFO.  A caller
    supplies explicit service opportunities through ``advance()``; one
    opportunity can grant at most one request per free egress and at most one
    request per idle ingress.  Each ingress and egress retains at most one
    active request until its downstream completion returns.

    Ingress queue exhaustion defaults to an unaccepted ``BLOCK`` transition.
    The system runtime can atomically retry the triggering event.  Optional
    ``ERROR_COMPLETION`` accepts one overflow request per ingress into a
    bounded emergency slot.  Its local error is emitted only after older work
    from that ingress completes; a further overflow blocks until the marker is
    released.  ``FAULT`` is the other explicit alternative.  Error completion
    is not backpressure, and this event-level contract does not claim
    cycle-accurate READY timing.
    """

    def __init__(
        self,
        ingress_ports: Mapping[str, InterfaceAttachmentBinding],
        egress_ports: Mapping[str, InterfaceAttachmentBinding],
        routes: tuple[AddressRoute, ...],
        *,
        ingress_queue_capacity: int,
        exhaustion_policy: ResourceExhaustionPolicy | str = (
            ResourceExhaustionPolicy.BLOCK
        ),
    ) -> None:
        ingress_bindings = dict(ingress_ports)
        egress_bindings = dict(egress_ports)
        if not ingress_bindings:
            raise ValueError("address crossbar requires at least one ingress")
        if not egress_bindings:
            raise ValueError("address crossbar requires at least one egress")
        if any(
            not isinstance(binding, InterfaceAttachmentBinding)
            for binding in (*ingress_bindings.values(), *egress_bindings.values())
        ):
            raise TypeError("address crossbar ports require attachment bindings")
        if set(ingress_bindings) != {
            binding.name for binding in ingress_bindings.values()
        }:
            raise ValueError("crossbar ingress keys must match port names")
        if set(egress_bindings) != {
            binding.name for binding in egress_bindings.values()
        }:
            raise ValueError("crossbar egress keys must match port names")
        overlap = set(ingress_bindings).intersection(egress_bindings)
        if overlap:
            raise ValueError(
                "crossbar ingress and egress names must differ: "
                f"{sorted(overlap)!r}"
            )
        if any(
            not isinstance(binding.attachment, AddressCompleterAttachment)
            for binding in ingress_bindings.values()
        ):
            raise TypeError(
                "address crossbar ingresses require completer attachments"
            )
        if any(
            not isinstance(binding.attachment, AddressRequesterAttachment)
            for binding in egress_bindings.values()
        ):
            raise TypeError(
                "address crossbar egresses require requester attachments"
            )
        if (
            not isinstance(ingress_queue_capacity, int)
            or isinstance(ingress_queue_capacity, bool)
            or ingress_queue_capacity <= 0
        ):
            raise ValueError(
                "crossbar ingress queue capacity must be positive"
            )
        try:
            normalized_exhaustion_policy = ResourceExhaustionPolicy(
                exhaustion_policy
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "address crossbar requires a valid resource exhaustion policy"
            ) from error

        self.ingress_ports = tuple(ingress_bindings)
        self.egress_ports = tuple(egress_bindings)
        self.ingress_bindings = MappingProxyType(ingress_bindings)
        self.egress_bindings = MappingProxyType(egress_bindings)
        self.ingress_attachments = MappingProxyType(
            {
                name: binding.attachment
                for name, binding in ingress_bindings.items()
            }
        )
        self.egress_attachments = MappingProxyType(
            {
                name: binding.attachment
                for name, binding in egress_bindings.items()
            }
        )
        self.bindings = MappingProxyType(
            {**ingress_bindings, **egress_bindings}
        )
        self.routes = validate_address_routes(routes, self.egress_ports)
        self.ingress_queue_capacity = ingress_queue_capacity
        self.exhaustion_policy = normalized_exhaustion_policy
        self._boundary_projections = MappingProxyType(
            {
                ADDRESS_ROUTER_PROJECTION: AddressRouterBoundaryProjection(
                    self.ingress_ports,
                    self.egress_ports,
                    self.routes,
                )
            }
        )

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, InterfaceAttachmentBinding]:
        return self.bindings

    def boundary_projections(self) -> Mapping[str, object]:
        return self._boundary_projections

    def initial_state(self) -> ScheduledAddressCrossbarState:
        return ScheduledAddressCrossbarState(
            ingress_states={
                name: attachment.initial_state()
                for name, attachment in self.ingress_attachments.items()
            },
            egress_states={
                name: attachment.initial_state()
                for name, attachment in self.egress_attachments.items()
            },
            ingress_queues={name: () for name in self.ingress_ports},
            pending={},
            round_robin_cursors={name: 0 for name in self.egress_ports},
        )

    def accept(self, state: object, action: PortInput) -> DutTransition:
        self._require_state(state)
        assert isinstance(state, ScheduledAddressCrossbarState)
        if action.port in self.ingress_attachments:
            return self._accept_ingress(state, action)
        if action.port in self.egress_attachments:
            return self._accept_egress(state, action)
        return DutTransition(
            state,
            fault=self._fault(
                "unknown_port", f"crossbar has no port {action.port!r}"
            ),
        )

    def _accept_ingress(
        self,
        state: ScheduledAddressCrossbarState,
        action: PortInput,
    ) -> DutTransition:
        attachment = self.ingress_attachments[action.port]
        decoded = attachment.decode_request(
            state.ingress_states[action.port], action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)

        ingress_states = dict(state.ingress_states)
        ingress_states[action.port] = decoded.state
        if decoded.access is None:
            return DutTransition(
                replace(state, ingress_states=ingress_states)
            )

        queue = state.ingress_queues[action.port]
        regular_usage = sum(
            isinstance(item, QueuedRoutedAddressRequest) for item in queue
        )
        if regular_usage >= self.ingress_queue_capacity:
            reason = (
                f"crossbar ingress {action.port!r} request FIFO is full "
                f"({regular_usage}/{self.ingress_queue_capacity})"
            )
            if self.exhaustion_policy is ResourceExhaustionPolicy.BLOCK:
                return DutTransition(
                    state,
                    blocked=ResourceDemand(
                        "ingress_request_fifo",
                        ConstraintScope.VIRTUAL_DUT,
                        available=(
                            self.ingress_queue_capacity - regular_usage
                        ),
                        capacity=self.ingress_queue_capacity,
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
                isinstance(item, QueuedIngressErrorCompletion)
                for item in queue
            ):
                return DutTransition(
                    state,
                    blocked=ResourceDemand(
                        "ingress_error_completion_slot",
                        ConstraintScope.VIRTUAL_DUT,
                        available=0,
                        capacity=1,
                        reason=(
                            f"crossbar ingress {action.port!r} already has "
                            "an ordered overflow error pending"
                        ),
                        location=action.port,
                    ),
                )
            marker = QueuedIngressErrorCompletion(
                state.next_request_id,
                action.port,
                decoded.reply_context,
            )
            ingress_queues = dict(state.ingress_queues)
            ingress_queues[action.port] = (*queue, marker)
            return DutTransition(
                replace(
                    state,
                    ingress_states=ingress_states,
                    ingress_queues=ingress_queues,
                    next_request_id=state.next_request_id + 1,
                ),
            )

        route = next(
            (item for item in self.routes if item.contains(decoded.access)),
            None,
        )
        request_id = state.next_request_id
        queued = QueuedRoutedAddressRequest(
            request_id=request_id,
            ingress_port=action.port,
            input_access=decoded.access,
            reply_context=decoded.reply_context,
            egress_port=None if route is None else route.egress_port,
            output_access=(
                None if route is None else route.translate(decoded.access)
            ),
        )
        ingress_queues = dict(state.ingress_queues)
        ingress_queues[action.port] = (*queue, queued)
        return DutTransition(
            replace(
                state,
                ingress_states=ingress_states,
                ingress_queues=ingress_queues,
                next_request_id=request_id + 1,
            )
        )

    def _accept_egress(
        self,
        state: ScheduledAddressCrossbarState,
        action: PortInput,
    ) -> DutTransition:
        attachment = self.egress_attachments[action.port]
        decoded = attachment.decode_completion(
            state.egress_states[action.port], action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)

        egress_states = dict(state.egress_states)
        egress_states[action.port] = decoded.state
        if decoded.completion is None:
            return DutTransition(
                replace(state, egress_states=egress_states)
            )

        completion = decoded.completion
        owner = state.pending.get(completion.request_id)
        if owner is None:
            return DutTransition(
                state,
                fault=self._fault(
                    "unknown_completion",
                    f"no request owns completion {completion.request_id}",
                ),
            )
        if owner.egress_port != action.port:
            return DutTransition(
                state,
                fault=self._fault(
                    "completion_port",
                    f"completion {completion.request_id} arrived on "
                    f"{action.port!r}, not {owner.egress_port!r}",
                ),
            )
        if completion.result.effects:
            return DutTransition(
                state,
                fault=self._fault(
                    "completion_effect",
                    "address crossbar completion boundary does not carry "
                    "endpoint-local effects",
                ),
            )

        ingress_attachment = self.ingress_attachments[owner.ingress_port]
        encoded = ingress_attachment.encode_completion(
            state.ingress_states[owner.ingress_port],
            owner.reply_context,
            completion.result,
        )
        if encoded.fault is not None:
            return DutTransition(state, fault=encoded.fault)

        ingress_states = dict(state.ingress_states)
        ingress_states[owner.ingress_port] = encoded.state
        pending = dict(state.pending)
        del pending[completion.request_id]
        return DutTransition(
            replace(
                state,
                ingress_states=ingress_states,
                egress_states=egress_states,
                pending=pending,
            ),
            tuple(
                PortEmission(owner.ingress_port, event)
                for event in encoded.events
            ),
        )

    def advance(
        self,
        state: ScheduledAddressCrossbarState,
        *,
        steps: int = 1,
    ) -> DutTransition:
        """Run explicit service opportunities without assigning time units."""

        self._require_state(state)
        if (
            not isinstance(steps, int)
            or isinstance(steps, bool)
            or steps <= 0
        ):
            raise ValueError("crossbar advance steps must be positive")

        original = state
        candidate = state
        emissions: list[PortEmission] = []
        for _ in range(steps):
            advanced = self._advance_once(candidate)
            if advanced.fault is not None:
                return DutTransition(original, fault=advanced.fault)
            candidate = advanced.state
            assert isinstance(candidate, ScheduledAddressCrossbarState)
            emissions.extend(advanced.emissions)
        return DutTransition(candidate, tuple(emissions))

    def _advance_once(
        self, state: ScheduledAddressCrossbarState
    ) -> DutTransition:
        ingress_states = dict(state.ingress_states)
        egress_states = dict(state.egress_states)
        ingress_queues = dict(state.ingress_queues)
        pending = dict(state.pending)
        cursors = dict(state.round_robin_cursors)
        emissions: list[PortEmission] = []

        active_ingresses = {
            owner.ingress_port for owner in state.pending.values()
        }
        active_egresses = {
            owner.egress_port for owner in state.pending.values()
        }
        heads = {
            ingress: state.ingress_queues[ingress][0]
            for ingress in self.ingress_ports
            if ingress not in active_ingresses
            and state.ingress_queues[ingress]
        }
        serviced_ingresses: set[str] = set()

        # Route misses and overflow markers are ordered local completions, not
        # bypasses around an earlier active operation from the same ingress.
        for ingress in self.ingress_ports:
            head = heads.get(ingress)
            if isinstance(head, QueuedIngressErrorCompletion):
                status = head.status
            elif (
                isinstance(head, QueuedRoutedAddressRequest)
                and head.is_route_miss
            ):
                status = AccessStatus.DECODE_ERROR
            else:
                continue
            attachment = self.ingress_attachments[ingress]
            encoded = attachment.encode_completion(
                ingress_states[ingress],
                head.reply_context,
                AccessResult(status=status),
            )
            if encoded.fault is not None:
                return DutTransition(state, fault=encoded.fault)
            ingress_states[ingress] = encoded.state
            ingress_queues[ingress] = ingress_queues[ingress][1:]
            emissions.extend(
                PortEmission(ingress, event) for event in encoded.events
            )
            serviced_ingresses.add(ingress)

        for egress in self.egress_ports:
            if egress in active_egresses:
                continue
            eligible = tuple(
                ingress
                for ingress, head in heads.items()
                if ingress not in serviced_ingresses
                and isinstance(head, QueuedRoutedAddressRequest)
                and head.egress_port == egress
            )
            grant = round_robin_grant(
                self.ingress_ports,
                eligible,
                cursors[egress],
            )
            if grant is None:
                continue
            ingress, next_cursor = grant
            head = heads[ingress]
            assert isinstance(head, QueuedRoutedAddressRequest)
            assert head.output_access is not None
            attachment = self.egress_attachments[egress]
            encoded = attachment.encode_request(
                egress_states[egress],
                AddressRequest(head.request_id, head.output_access),
            )
            if encoded.fault is not None:
                return DutTransition(state, fault=encoded.fault)

            egress_states[egress] = encoded.state
            ingress_queues[ingress] = ingress_queues[ingress][1:]
            pending[head.request_id] = RoutedAddressRequest(
                head.request_id,
                ingress,
                egress,
                head.input_access,
                head.output_access,
                head.reply_context,
            )
            cursors[egress] = next_cursor
            emissions.extend(
                PortEmission(egress, event) for event in encoded.events
            )
            serviced_ingresses.add(ingress)

        return DutTransition(
            ScheduledAddressCrossbarState(
                ingress_states=ingress_states,
                egress_states=egress_states,
                ingress_queues=ingress_queues,
                pending=pending,
                round_robin_cursors=cursors,
                next_request_id=state.next_request_id,
                advance_index=state.advance_index + 1,
            ),
            tuple(emissions),
        )

    def is_quiescent(self, state: object) -> bool:
        if not isinstance(state, ScheduledAddressCrossbarState):
            return False
        try:
            self._require_state(state)
        except (TypeError, ValueError):
            return False
        return (
            not state.pending
            and all(not queue for queue in state.ingress_queues.values())
            and all(
                attachment.is_quiescent(state.ingress_states[name])
                for name, attachment in self.ingress_attachments.items()
            )
            and all(
                attachment.is_quiescent(state.egress_states[name])
                for name, attachment in self.egress_attachments.items()
            )
        )

    def queue_usage(
        self,
        state: ScheduledAddressCrossbarState,
        ingress_port: str,
    ) -> tuple[int, int]:
        self._require_state(state)
        if ingress_port not in self.ingress_attachments:
            raise ValueError(f"unknown crossbar ingress {ingress_port!r}")
        return (
            sum(
                isinstance(item, QueuedRoutedAddressRequest)
                for item in state.ingress_queues[ingress_port]
            ),
            self.ingress_queue_capacity,
        )

    def _require_state(self, state: object) -> None:
        if not isinstance(state, ScheduledAddressCrossbarState):
            raise TypeError(
                "ScheduledAddressCrossbarBackend requires "
                "ScheduledAddressCrossbarState"
            )
        if set(state.ingress_states) != set(self.ingress_ports):
            raise ValueError("crossbar state does not match configured ingresses")
        if set(state.egress_states) != set(self.egress_ports):
            raise ValueError("crossbar state does not match configured egresses")
        if any(
            sum(
                isinstance(item, QueuedRoutedAddressRequest)
                for item in queue
            )
            > self.ingress_queue_capacity
            for queue in state.ingress_queues.values()
        ):
            raise ValueError("crossbar state exceeds ingress queue capacity")
        if any(
            isinstance(item, QueuedRoutedAddressRequest)
            and item.egress_port is not None
            and item.egress_port not in self.egress_attachments
            for queue in state.ingress_queues.values()
            for item in queue
        ):
            raise ValueError("crossbar queue references an unknown egress")
        if any(
            owner.ingress_port not in self.ingress_attachments
            or owner.egress_port not in self.egress_attachments
            for owner in state.pending.values()
        ):
            raise ValueError("crossbar pending owner references an unknown port")
        if any(
            cursor >= len(self.ingress_ports)
            for cursor in state.round_robin_cursors.values()
        ):
            raise ValueError("crossbar arbitration cursor is outside ingress order")

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"address_crossbar.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )


__all__ = ["ScheduledAddressCrossbarBackend"]

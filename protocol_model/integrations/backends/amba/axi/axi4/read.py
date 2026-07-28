"""Transaction-level N-ingress/M-egress AXI4 read routing.

The backend consumes already accepted canonical AR/R events.  It therefore
models routing, ID ordering, ownership, and finite admission without choosing
an RTL arbitration or timing implementation.  The order in which a scenario
submits accepted AR events is the grant order of that execution witness.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.axi.axi4 import (
    AXI4_FAMILY,
    beat_byte_addresses,
    transfer_count,
)
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    ResourceDemand,
    SemanticFault,
)
from protocol_model.virtual_dut.attachments import (
    CanonicalEventRelayAttachment,
)
from protocol_model.virtual_dut.backend.base import VirtualDutBackend
from protocol_model.virtual_dut.backend.transition import (
    DutTransition,
    PortEmission,
    PortInput,
)
from protocol_model.virtual_dut.binding.port import InterfaceAttachmentBinding
from protocol_model.virtual_dut.fabric.projection import (
    ADDRESS_ROUTER_PROJECTION,
    AddressRouterBoundaryProjection,
)
from protocol_model.virtual_dut.fabric.route import (
    AddressRoute,
    validate_address_routes,
)


RAW_ID_SERIALIZED = "raw-id-serialized"


def _require_read_only_protocol(protocol: InterfaceProtocol) -> None:
    """Reject interface declarations that can legally emit unhandled events.

    A five-channel AXI boundary is suitable when a monotonic interface profile
    explicitly forbids AW/W/B.  The smaller AR/R-only interface is suitable as
    well.  Merely containing AR and R is insufficient: a plain Full AXI
    declaration would promise events that this read-slice backend cannot route.
    """

    unhandled = set(protocol.event_kinds) - {"AR", "R"}
    enabled_unhandled = unhandled.intersection(protocol.enabled_event_kinds)
    if enabled_unhandled:
        raise ValueError(
            "AXI4 read crossbar requires an AR/R-only interface or a "
            "profile that forbids every other event kind; enabled kinds: "
            f"{sorted(enabled_unhandled)!r}"
        )


def _positive_integer(value: object, *, subject: str) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ValueError(f"{subject} must be positive")


def _non_negative_integer(value: object, *, subject: str) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{subject} must be a non-negative integer")


@dataclass(frozen=True)
class Axi4ReadRouteTableProfile:
    """Finite transaction metadata available to every ingress namespace.

    ``active_id_capacity`` is applied independently to each manager-facing
    ingress.  ``outstanding_bursts_per_id`` bounds accepted bursts in one
    ``(ingress, RID)`` ordering domain.
    """

    active_id_capacity: int = 8
    outstanding_bursts_per_id: int = 8

    def __post_init__(self) -> None:
        _positive_integer(
            self.active_id_capacity,
            subject="AXI4 read active-ID capacity",
        )
        _positive_integer(
            self.outstanding_bursts_per_id,
            subject="AXI4 read per-ID burst capacity",
        )


@dataclass(frozen=True)
class Axi4PendingRead:
    """One accepted burst and all metadata needed to return its R beats.

    The current raw-ID profile preserves the upstream RID downstream.  The
    two fields remain distinct so a future prefix/remap policy can replace the
    downstream identity without changing return ownership or upstream order.
    """

    serial: int
    ingress_port: str
    upstream_id: int
    egress_port: str
    downstream_id: int
    remaining_beats: int

    def __post_init__(self) -> None:
        _non_negative_integer(
            self.serial, subject="AXI4 pending-read serial"
        )
        for value, subject in (
            (self.upstream_id, "AXI4 upstream RID"),
            (self.downstream_id, "AXI4 downstream RID"),
        ):
            _non_negative_integer(value, subject=subject)
        for value, subject in (
            (self.ingress_port, "AXI4 pending-read ingress"),
            (self.egress_port, "AXI4 pending-read egress"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{subject} must be a non-empty name")
        _positive_integer(
            self.remaining_beats,
            subject="AXI4 pending-read remaining beat count",
        )


@dataclass(frozen=True)
class Axi4ReadRouteLock:
    """Derived view of one manager-local RID destination lock."""

    ingress_port: str
    read_id: int
    egress_port: str
    outstanding_bursts: int


@dataclass(frozen=True)
class Axi4ReadCrossbarState:
    """Sparse, immutable pending-burst ledger for one crossbar instance."""

    pending: tuple[Axi4PendingRead, ...] = ()
    next_serial: int = 0

    def __post_init__(self) -> None:
        pending = tuple(self.pending)
        if any(not isinstance(item, Axi4PendingRead) for item in pending):
            raise TypeError("AXI4 read crossbar ledger has an invalid entry")
        serials = tuple(item.serial for item in pending)
        if len(set(serials)) != len(serials):
            raise ValueError("AXI4 read pending serials must be unique")
        if serials != tuple(sorted(serials)):
            raise ValueError("AXI4 read pending ledger must follow serial order")
        _non_negative_integer(
            self.next_serial, subject="AXI4 next pending-read serial"
        )
        if serials and self.next_serial <= serials[-1]:
            raise ValueError(
                "AXI4 next pending-read serial must exceed every live entry"
            )
        object.__setattr__(self, "pending", pending)


class Axi4ReadCrossbarBackend(VirtualDutBackend):
    """Route AXI4 read-only AR/R between arbitrary ingress/egress counts.

    The current profile forwards ARID without prefixing or remapping it.  A
    single pending-burst ledger is authoritative:

    * entries sharing ``(ingress, upstream RID)`` derive a destination lock;
    * entries sharing ``(egress, downstream RID)`` derive the return-owner
      FIFO in request-acceptance order.

    Different managers that use the same RID at one subordinate are therefore
    merged into one legal downstream ordering stream.  This is conservative
    in concurrency but sufficient to restore every ordinary read response to
    its manager without a second mutable owner table.
    """

    def __init__(
        self,
        ingress_bindings: Mapping[str, InterfaceAttachmentBinding],
        egress_bindings: Mapping[str, InterfaceAttachmentBinding],
        routes: tuple[AddressRoute, ...],
        *,
        table_profile: Axi4ReadRouteTableProfile | None = None,
    ) -> None:
        ingress_bindings = dict(ingress_bindings)
        egress_bindings = dict(egress_bindings)
        if not ingress_bindings:
            raise ValueError("AXI4 read crossbar requires at least one ingress")
        if not egress_bindings:
            raise ValueError("AXI4 read crossbar requires at least one egress")
        for bindings, subject in (
            (ingress_bindings, "ingress"),
            (egress_bindings, "egress"),
        ):
            if set(bindings) != {
                binding.name for binding in bindings.values()
            }:
                raise ValueError(
                    f"AXI4 read crossbar {subject} keys must match port names"
                )
            if any(
                not isinstance(binding, InterfaceAttachmentBinding)
                for binding in bindings.values()
            ):
                raise TypeError(
                    f"AXI4 read crossbar {subject} values require bindings"
                )
        overlap = set(ingress_bindings).intersection(egress_bindings)
        if overlap:
            raise ValueError(
                "AXI4 read crossbar ingress and egress names overlap: "
                f"{sorted(overlap)!r}"
            )

        bindings = (*ingress_bindings.values(), *egress_bindings.values())
        if any(
            not isinstance(binding.attachment, CanonicalEventRelayAttachment)
            for binding in bindings
        ):
            raise TypeError(
                "AXI4 read crossbar requires canonical relay attachments"
            )
        if any(
            binding.attachment.role != "subordinate"
            for binding in ingress_bindings.values()
        ):
            raise ValueError(
                "AXI4 read crossbar ingresses require subordinate roles"
            )
        if any(
            binding.attachment.role != "manager"
            for binding in egress_bindings.values()
        ):
            raise ValueError(
                "AXI4 read crossbar egresses require manager roles"
            )

        protocol = next(iter(ingress_bindings.values())).port.protocol
        if protocol.interface_family != AXI4_FAMILY:
            raise ValueError(
                "AXI4 read crossbar requires an AXI4 interface family"
            )
        if not {"AR", "R"}.issubset(protocol.event_kinds):
            raise ValueError("AXI4 read crossbar requires AR and R event kinds")
        _require_read_only_protocol(protocol)
        if any(
            not protocol.has_same_interface_shape_as(binding.port.protocol)
            for binding in bindings
        ):
            raise ValueError(
                "AXI4 read crossbar ports must use one interface shape"
            )

        id_count = 1 << int(protocol.parameters["id_width"])
        normalized_profile = (
            Axi4ReadRouteTableProfile(active_id_capacity=min(8, id_count))
            if table_profile is None
            else table_profile
        )
        if not isinstance(normalized_profile, Axi4ReadRouteTableProfile):
            raise TypeError("AXI4 read crossbar table profile has wrong type")
        if normalized_profile.active_id_capacity > id_count:
            raise ValueError(
                "AXI4 read active-ID capacity exceeds the RID namespace"
            )

        self.protocol = protocol
        self.ingress_ports = tuple(ingress_bindings)
        self.egress_ports = tuple(egress_bindings)
        self.ingress_bindings = MappingProxyType(ingress_bindings)
        self.egress_bindings = MappingProxyType(egress_bindings)
        self.bindings = MappingProxyType(
            {**ingress_bindings, **egress_bindings}
        )
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
        self.routes = validate_address_routes(routes, self.egress_ports)
        self.table_profile = normalized_profile
        self.id_count = id_count
        self.id_policy = RAW_ID_SERIALIZED
        self.bus_bytes = int(protocol.parameters["data_width"]) // 8
        self.address_limit = 1 << int(protocol.parameters["address_width"])
        for route in self.routes:
            output_base = (
                route.base_address
                if route.output_base_address is None
                else route.output_base_address
            )
            if route.limit_address > self.address_limit:
                raise ValueError(
                    f"route {route.name!r} exceeds AXI4 input address width"
                )
            if output_base + route.size_bytes > self.address_limit:
                raise ValueError(
                    f"route {route.name!r} exceeds AXI4 output address width"
                )
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

    def initial_state(self) -> Axi4ReadCrossbarState:
        return Axi4ReadCrossbarState()

    def accept(self, state: object, action: PortInput) -> DutTransition:
        self._require_state(state)
        assert isinstance(state, Axi4ReadCrossbarState)
        if action.port in self.ingress_attachments:
            return self._accept_ar(state, action.port, action.event)
        if action.port in self.egress_attachments:
            return self._accept_r(state, action.port, action.event)
        return DutTransition(
            state,
            fault=self._fault(
                "unknown_port",
                f"AXI4 read crossbar has no port {action.port!r}",
            ),
        )

    def _accept_ar(
        self,
        state: Axi4ReadCrossbarState,
        ingress_port: str,
        event: CanonicalEvent,
    ) -> DutTransition:
        attachment = self.ingress_attachments[ingress_port]
        fault = attachment.incoming_fault(
            event, rule_prefix="axi4_read_crossbar.ingress"
        )
        if fault is not None:
            return DutTransition(state, fault=fault)
        if event.kind != "AR":
            return DutTransition(
                state,
                fault=self._fault(
                    "ingress_kind",
                    "read-only AXI4 crossbar ingress accepts AR events",
                ),
            )
        if len(self.ingress_ports) > 1 and bool(event.payload["lock"]):
            return DutTransition(
                state,
                fault=self._fault(
                    "raw_id_exclusive",
                    "multi-ingress raw-ID routing does not preserve "
                    "source-qualified exclusive identity",
                ),
            )

        read_id = int(event.key)
        route = self._route_for(event)
        same_domain = tuple(
            item
            for item in state.pending
            if item.ingress_port == ingress_port
            and item.upstream_id == read_id
        )
        if same_domain and (
            route is None
            or any(item.egress_port != route.egress_port for item in same_domain)
        ):
            destination = "local DECERR" if route is None else route.egress_port
            return DutTransition(
                state,
                blocked=ResourceDemand(
                    "axi4_read_id_destination",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=1,
                    reason=(
                        f"{ingress_port} RID {read_id} is locked to "
                        f"{same_domain[0].egress_port!r}; request for "
                        f"{destination!r} waits for prior RLAST"
                    ),
                    location=ingress_port,
                ),
            )

        if route is None:
            responses = self._decode_error_events(event)
            for response in responses:
                fault = attachment.outgoing_fault(
                    response,
                    rule_prefix="axi4_read_crossbar.decode_error",
                )
                if fault is not None:
                    return DutTransition(state, fault=fault)
            return DutTransition(
                state,
                tuple(
                    PortEmission(ingress_port, response)
                    for response in responses
                ),
            )

        if same_domain:
            if (
                len(same_domain)
                >= self.table_profile.outstanding_bursts_per_id
            ):
                return DutTransition(
                    state,
                    blocked=ResourceDemand(
                        "axi4_read_outstanding_per_id",
                        ConstraintScope.VIRTUAL_DUT,
                        available=0,
                        capacity=(
                            self.table_profile.outstanding_bursts_per_id
                        ),
                        reason=(
                            f"{ingress_port} RID {read_id} reached its "
                            "outstanding-burst limit"
                        ),
                        location=ingress_port,
                    ),
                )
        else:
            active_ids = {
                item.upstream_id
                for item in state.pending
                if item.ingress_port == ingress_port
            }
            if len(active_ids) >= self.table_profile.active_id_capacity:
                return DutTransition(
                    state,
                    blocked=ResourceDemand(
                        "axi4_read_route_table",
                        ConstraintScope.VIRTUAL_DUT,
                        available=0,
                        capacity=self.table_profile.active_id_capacity,
                        reason=(
                            f"{ingress_port} has no free active-RID slot"
                        ),
                        location=ingress_port,
                    ),
                )

        downstream_id = read_id
        forwarded = replace(
            self._translate_ar(event, route), key=downstream_id
        )
        fault = self.egress_attachments[route.egress_port].outgoing_fault(
            forwarded, rule_prefix="axi4_read_crossbar.egress"
        )
        if fault is not None:
            return DutTransition(state, fault=fault)
        pending = (
            *state.pending,
            Axi4PendingRead(
                serial=state.next_serial,
                ingress_port=ingress_port,
                upstream_id=read_id,
                egress_port=route.egress_port,
                downstream_id=downstream_id,
                remaining_beats=transfer_count(event),
            ),
        )
        return DutTransition(
            Axi4ReadCrossbarState(pending, state.next_serial + 1),
            (PortEmission(route.egress_port, forwarded),),
        )

    def _accept_r(
        self,
        state: Axi4ReadCrossbarState,
        egress_port: str,
        event: CanonicalEvent,
    ) -> DutTransition:
        attachment = self.egress_attachments[egress_port]
        fault = attachment.incoming_fault(
            event, rule_prefix="axi4_read_crossbar.egress"
        )
        if fault is not None:
            return DutTransition(state, fault=fault)
        if event.kind != "R":
            return DutTransition(
                state,
                fault=self._fault(
                    "egress_kind",
                    "read-only AXI4 crossbar egress accepts R events",
                ),
            )

        downstream_id = int(event.key)
        owner = next(
            (
                item
                for item in state.pending
                if item.egress_port == egress_port
                and item.downstream_id == downstream_id
            ),
            None,
        )
        if owner is None:
            return DutTransition(
                state,
                fault=self._fault(
                    "orphan_response",
                    f"R response on {egress_port!r} for downstream RID "
                    f"{downstream_id} has no pending owner",
                ),
            )

        expected_last = owner.remaining_beats == 1
        if bool(event.payload["last"]) is not expected_last:
            return DutTransition(
                state,
                fault=self._fault(
                    "response_last",
                    f"pending read {owner.serial} has "
                    f"{owner.remaining_beats} beats remaining; RLAST must "
                    f"be {expected_last}",
                ),
            )
        forwarded = replace(event, key=owner.upstream_id)
        fault = self.ingress_attachments[owner.ingress_port].outgoing_fault(
            forwarded, rule_prefix="axi4_read_crossbar.ingress"
        )
        if fault is not None:
            return DutTransition(state, fault=fault)

        if expected_last:
            pending = tuple(
                item for item in state.pending if item.serial != owner.serial
            )
        else:
            pending = tuple(
                replace(item, remaining_beats=item.remaining_beats - 1)
                if item.serial == owner.serial
                else item
                for item in state.pending
            )
        return DutTransition(
            Axi4ReadCrossbarState(pending, state.next_serial),
            (PortEmission(owner.ingress_port, forwarded),),
        )

    def route_locks(
        self, state: Axi4ReadCrossbarState
    ) -> Mapping[tuple[str, int], Axi4ReadRouteLock]:
        self._require_state(state)
        grouped: dict[tuple[str, int], list[Axi4PendingRead]] = {}
        for item in state.pending:
            grouped.setdefault(
                (item.ingress_port, item.upstream_id), []
            ).append(item)
        return MappingProxyType(
            {
                key: Axi4ReadRouteLock(
                    ingress_port=key[0],
                    read_id=key[1],
                    egress_port=items[0].egress_port,
                    outstanding_bursts=len(items),
                )
                for key, items in grouped.items()
            }
        )

    def return_owner_queues(
        self, state: Axi4ReadCrossbarState
    ) -> Mapping[tuple[str, int], tuple[Axi4PendingRead, ...]]:
        self._require_state(state)
        grouped: dict[tuple[str, int], list[Axi4PendingRead]] = {}
        for item in state.pending:
            grouped.setdefault(
                (item.egress_port, item.downstream_id), []
            ).append(item)
        return MappingProxyType(
            {key: tuple(items) for key, items in grouped.items()}
        )

    def active_id_usage(
        self,
        state: Axi4ReadCrossbarState,
        ingress_port: str,
    ) -> tuple[int, int]:
        self._require_state(state)
        if ingress_port not in self.ingress_attachments:
            raise ValueError(f"unknown AXI4 read ingress {ingress_port!r}")
        usage = len(
            {
                item.upstream_id
                for item in state.pending
                if item.ingress_port == ingress_port
            }
        )
        return usage, self.table_profile.active_id_capacity

    def _route_for(self, event: CanonicalEvent) -> AddressRoute | None:
        touched = self._burst_byte_addresses(event)
        for route in self.routes:
            if not all(
                route.base_address <= address < route.limit_address
                for address in touched
            ):
                continue
            forwarded = self._translate_ar(event, route)
            delta = (
                0
                if route.output_base_address is None
                else route.output_base_address - route.base_address
            )
            if self._burst_byte_addresses(forwarded) == tuple(
                address + delta for address in touched
            ):
                return route
        return None

    def _burst_byte_addresses(
        self, event: CanonicalEvent
    ) -> tuple[int, ...]:
        return tuple(
            byte_address
            for beat_index in range(transfer_count(event))
            for byte_address in beat_byte_addresses(
                event, beat_index, bus_bytes=self.bus_bytes
            )
        )

    @staticmethod
    def _translate_ar(
        event: CanonicalEvent, route: AddressRoute
    ) -> CanonicalEvent:
        if route.output_base_address is None:
            return event
        payload = dict(event.payload)
        payload["addr"] = (
            route.output_base_address
            + int(event.payload["addr"])
            - route.base_address
        )
        return replace(event, payload=payload)

    @staticmethod
    def _decode_error_events(
        request: CanonicalEvent,
    ) -> tuple[CanonicalEvent, ...]:
        count = transfer_count(request)
        return tuple(
            CanonicalEvent(
                "R",
                request.key,
                {
                    "data": 0,
                    "resp": "DECERR",
                    "last": index == count - 1,
                },
            )
            for index in range(count)
        )

    def is_quiescent(self, state: object) -> bool:
        if not isinstance(state, Axi4ReadCrossbarState):
            return False
        try:
            self._require_state(state)
        except (TypeError, ValueError):
            return False
        return not state.pending

    def _require_state(self, state: object) -> None:
        if not isinstance(state, Axi4ReadCrossbarState):
            raise TypeError(
                "Axi4ReadCrossbarBackend requires Axi4ReadCrossbarState"
            )
        if any(
            item.ingress_port not in self.ingress_attachments
            or item.egress_port not in self.egress_attachments
            for item in state.pending
        ):
            raise ValueError("AXI4 read ledger references an unknown port")
        if any(
            item.upstream_id >= self.id_count
            or item.downstream_id >= self.id_count
            for item in state.pending
        ):
            raise ValueError("AXI4 read ledger contains an out-of-range RID")
        if self.id_policy == RAW_ID_SERIALIZED and any(
            item.downstream_id != item.upstream_id
            for item in state.pending
        ):
            raise ValueError(
                "raw-ID AXI4 read policy requires identical upstream and "
                "downstream IDs"
            )

        by_domain: dict[tuple[str, int], list[Axi4PendingRead]] = {}
        for item in state.pending:
            by_domain.setdefault(
                (item.ingress_port, item.upstream_id), []
            ).append(item)
        if any(
            len({item.egress_port for item in items}) != 1
            for items in by_domain.values()
        ):
            raise ValueError(
                "AXI4 read ordering domain spans more than one egress"
            )
        if any(
            len(items) > self.table_profile.outstanding_bursts_per_id
            for items in by_domain.values()
        ):
            raise ValueError(
                "AXI4 read ordering domain exceeds its burst capacity"
            )
        for ingress in self.ingress_ports:
            active_ids = {
                read_id
                for (port, read_id) in by_domain
                if port == ingress
            }
            if len(active_ids) > self.table_profile.active_id_capacity:
                raise ValueError(
                    f"AXI4 read ingress {ingress!r} exceeds active-ID capacity"
                )

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"axi4_read_crossbar.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )


__all__ = [
    "RAW_ID_SERIALIZED",
    "Axi4PendingRead",
    "Axi4ReadCrossbarBackend",
    "Axi4ReadCrossbarState",
    "Axi4ReadRouteLock",
    "Axi4ReadRouteTableProfile",
]

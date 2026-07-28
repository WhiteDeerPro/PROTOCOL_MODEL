"""Transaction-level N-ingress/M-egress AXI4 write routing.

The backend consumes already accepted canonical AW/W/B events.  Each ingress
assembles its ID-less W stream independently and FIFO-joins complete W bursts
with AW descriptors.  A joined burst is forwarded atomically as one AW
followed by all of its W beats; consequently this model constrains transaction
ownership and ordering without prescribing a cut-through RTL implementation or
cycle-level arbitration schedule.  The order in which callers submit the
event that completes a joined burst is the grant order of that execution
witness.
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
from protocol_model.protocols.amba.axi.axi4.burst import (
    write_strobe_violation,
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

from protocol_model.integrations.attachments.amba.axi.axi4.burst_translation import (
    Axi4BurstAssemblyProfile,
)
from protocol_model.integrations.attachments.amba.axi.axi4.subordinate import (
    Axi4SubordinateState,
)


RAW_ID_SERIALIZED = "raw-id-serialized"


def _require_write_only_protocol(protocol: InterfaceProtocol) -> None:
    """Reject interface declarations that can legally emit unhandled reads."""

    unhandled = set(protocol.event_kinds) - {"AW", "W", "B"}
    enabled_unhandled = unhandled.intersection(protocol.enabled_event_kinds)
    if enabled_unhandled:
        raise ValueError(
            "AXI4 write crossbar requires an AW/W/B-only interface or a "
            "profile that forbids every other event kind; enabled kinds: "
            f"{sorted(enabled_unhandled)!r}"
        )


def _positive_integer(value: object, *, subject: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{subject} must be positive")


def _non_negative_integer(value: object, *, subject: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{subject} must be a non-negative integer")


@dataclass(frozen=True)
class Axi4WriteRouteTableProfile:
    """Finite response-owner metadata available to every ingress namespace."""

    active_id_capacity: int = 8
    outstanding_bursts_per_id: int = 8

    def __post_init__(self) -> None:
        _positive_integer(
            self.active_id_capacity,
            subject="AXI4 write active-ID capacity",
        )
        _positive_integer(
            self.outstanding_bursts_per_id,
            subject="AXI4 write per-ID burst capacity",
        )


@dataclass(frozen=True)
class Axi4PendingWrite:
    """One forwarded write awaiting its downstream B response."""

    serial: int
    ingress_port: str
    upstream_id: int
    egress_port: str
    downstream_id: int
    beat_count: int

    def __post_init__(self) -> None:
        _non_negative_integer(self.serial, subject="AXI4 pending-write serial")
        for value, subject in (
            (self.upstream_id, "AXI4 upstream BID"),
            (self.downstream_id, "AXI4 downstream BID"),
        ):
            _non_negative_integer(value, subject=subject)
        for value, subject in (
            (self.ingress_port, "AXI4 pending-write ingress"),
            (self.egress_port, "AXI4 pending-write egress"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{subject} must be a non-empty name")
        _positive_integer(
            self.beat_count,
            subject="AXI4 pending-write beat count",
        )


@dataclass(frozen=True)
class Axi4WriteRouteLock:
    """Derived view of one manager-local BID destination lock.

    ``egress_port`` is ``None`` while the ordering domain is locked to a local
    decode-error completion rather than a fabric output.
    """

    ingress_port: str
    write_id: int
    egress_port: str | None
    outstanding_bursts: int


@dataclass(frozen=True)
class Axi4WriteCrossbarState:
    """Immutable ingress assembly and sparse pending-response ledger."""

    ingress_states: Mapping[str, Axi4SubordinateState]
    pending: tuple[Axi4PendingWrite, ...] = ()
    next_serial: int = 0

    def __post_init__(self) -> None:
        ingress_states = dict(self.ingress_states)
        if any(not isinstance(name, str) or not name for name in ingress_states):
            raise ValueError("AXI4 write ingress names must be non-empty")
        if any(
            not isinstance(state, Axi4SubordinateState)
            for state in ingress_states.values()
        ):
            raise TypeError("AXI4 write crossbar has an invalid ingress state")

        pending = tuple(self.pending)
        if any(not isinstance(item, Axi4PendingWrite) for item in pending):
            raise TypeError("AXI4 write crossbar ledger has an invalid entry")
        serials = tuple(item.serial for item in pending)
        if len(set(serials)) != len(serials):
            raise ValueError("AXI4 write pending serials must be unique")
        if serials != tuple(sorted(serials)):
            raise ValueError("AXI4 write pending ledger must follow serial order")
        _non_negative_integer(
            self.next_serial,
            subject="AXI4 next pending-write serial",
        )
        if serials and self.next_serial <= serials[-1]:
            raise ValueError(
                "AXI4 next pending-write serial must exceed every live entry"
            )

        object.__setattr__(
            self,
            "ingress_states",
            MappingProxyType(ingress_states),
        )
        object.__setattr__(self, "pending", pending)


class Axi4WriteCrossbarBackend(VirtualDutBackend):
    """Route FIFO-joined AXI4 AW/W bursts and return B to their owner.

    The current raw-ID profile forwards AWID unchanged.  Entries sharing
    ``(ingress, upstream ID)`` derive a destination lock, while entries sharing
    ``(egress, downstream ID)`` derive the downstream B owner FIFO.  Different
    managers reusing one raw ID at an egress are therefore serialized into one
    downstream response-order domain.

    A route miss is retained until its complete W burst has joined the AW and
    then produces one local DECERR.  Exclusive writes are rejected because the
    raw-ID model does not provide source-qualified reservation identity.
    """

    def __init__(
        self,
        ingress_bindings: Mapping[str, InterfaceAttachmentBinding],
        egress_bindings: Mapping[str, InterfaceAttachmentBinding],
        routes: tuple[AddressRoute, ...],
        *,
        assembly_profile: Axi4BurstAssemblyProfile | None = None,
        table_profile: Axi4WriteRouteTableProfile | None = None,
    ) -> None:
        ingress_bindings = dict(ingress_bindings)
        egress_bindings = dict(egress_bindings)
        if not ingress_bindings:
            raise ValueError("AXI4 write crossbar requires at least one ingress")
        if not egress_bindings:
            raise ValueError("AXI4 write crossbar requires at least one egress")
        for bindings, subject in (
            (ingress_bindings, "ingress"),
            (egress_bindings, "egress"),
        ):
            if set(bindings) != {
                binding.name for binding in bindings.values()
            }:
                raise ValueError(
                    f"AXI4 write crossbar {subject} keys must match port names"
                )
            if any(
                not isinstance(binding, InterfaceAttachmentBinding)
                for binding in bindings.values()
            ):
                raise TypeError(
                    f"AXI4 write crossbar {subject} values require bindings"
                )
        overlap = set(ingress_bindings).intersection(egress_bindings)
        if overlap:
            raise ValueError(
                "AXI4 write crossbar ingress and egress names overlap: "
                f"{sorted(overlap)!r}"
            )

        bindings = (*ingress_bindings.values(), *egress_bindings.values())
        if any(
            not isinstance(binding.attachment, CanonicalEventRelayAttachment)
            for binding in bindings
        ):
            raise TypeError(
                "AXI4 write crossbar requires canonical relay attachments"
            )
        if any(
            binding.attachment.role != "subordinate"
            for binding in ingress_bindings.values()
        ):
            raise ValueError(
                "AXI4 write crossbar ingresses require subordinate roles"
            )
        if any(
            binding.attachment.role != "manager"
            for binding in egress_bindings.values()
        ):
            raise ValueError(
                "AXI4 write crossbar egresses require manager roles"
            )

        protocol = next(iter(ingress_bindings.values())).port.protocol
        if protocol.interface_family != AXI4_FAMILY:
            raise ValueError(
                "AXI4 write crossbar requires an AXI4 interface family"
            )
        if not {"AW", "W", "B"}.issubset(protocol.event_kinds):
            raise ValueError(
                "AXI4 write crossbar requires AW, W, and B event kinds"
            )
        _require_write_only_protocol(protocol)
        if any(
            not protocol.has_same_interface_shape_as(binding.port.protocol)
            for binding in bindings
        ):
            raise ValueError(
                "AXI4 write crossbar ports must use one interface shape"
            )

        id_count = 1 << int(protocol.parameters["id_width"])
        normalized_assembly = (
            Axi4BurstAssemblyProfile()
            if assembly_profile is None
            else assembly_profile
        )
        if not isinstance(normalized_assembly, Axi4BurstAssemblyProfile):
            raise TypeError("AXI4 write assembly profile has wrong type")
        normalized_table = (
            Axi4WriteRouteTableProfile(active_id_capacity=min(8, id_count))
            if table_profile is None
            else table_profile
        )
        if not isinstance(normalized_table, Axi4WriteRouteTableProfile):
            raise TypeError("AXI4 write crossbar table profile has wrong type")
        if normalized_table.active_id_capacity > id_count:
            raise ValueError(
                "AXI4 write active-ID capacity exceeds the BID namespace"
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
        self.assembly_profile = normalized_assembly
        self.table_profile = normalized_table
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

    def initial_state(self) -> Axi4WriteCrossbarState:
        return Axi4WriteCrossbarState(
            {
                ingress: Axi4SubordinateState()
                for ingress in self.ingress_ports
            }
        )

    def accept(self, state: object, action: PortInput) -> DutTransition:
        self.validate_state(state)
        assert isinstance(state, Axi4WriteCrossbarState)
        if action.port in self.ingress_attachments:
            return self._accept_ingress(state, action.port, action.event)
        if action.port in self.egress_attachments:
            return self._accept_b(state, action.port, action.event)
        return DutTransition(
            state,
            fault=self._fault(
                "unknown_port",
                f"AXI4 write crossbar has no port {action.port!r}",
            ),
        )

    def _accept_ingress(
        self,
        state: Axi4WriteCrossbarState,
        ingress_port: str,
        event: CanonicalEvent,
    ) -> DutTransition:
        attachment = self.ingress_attachments[ingress_port]
        fault = attachment.incoming_fault(
            event,
            rule_prefix="axi4_write_crossbar.ingress",
        )
        if fault is not None:
            return DutTransition(state, fault=fault)
        if event.kind not in {"AW", "W"}:
            return DutTransition(
                state,
                fault=self._fault(
                    "ingress_kind",
                    "write-only AXI4 crossbar ingress accepts AW or W events",
                ),
            )

        original_ingress = state.ingress_states[ingress_port]
        if event.kind == "AW":
            if bool(event.payload["lock"]):
                return DutTransition(
                    state,
                    fault=self._fault(
                        "exclusive",
                        "transaction-level raw-ID write routing does not "
                        "provide an Exclusive Access Monitor",
                    ),
                )
            blocked = self._aw_admission_demand(
                state,
                ingress_port,
                event,
            )
            if blocked is not None:
                return DutTransition(state, blocked=blocked)
            candidate = Axi4SubordinateState(
                (*original_ingress.pending_addresses, event),
                original_ingress.completed_data,
                original_ingress.current_data,
            )
            if (
                len(original_ingress.pending_addresses) == 0
                and candidate.current_data
            ):
                relation_fault = self._data_prefix_fault(
                    event,
                    candidate.current_data,
                )
                if relation_fault is not None:
                    return DutTransition(state, fault=relation_fault)
        else:
            current = (*original_ingress.current_data, event)
            if original_ingress.pending_addresses:
                relation_fault = self._data_prefix_fault(
                    original_ingress.pending_addresses[0],
                    current,
                )
                if relation_fault is not None:
                    return DutTransition(state, fault=relation_fault)
            candidate = (
                Axi4SubordinateState(
                    original_ingress.pending_addresses,
                    (*original_ingress.completed_data, current),
                    (),
                )
                if bool(event.payload["last"])
                else Axi4SubordinateState(
                    original_ingress.pending_addresses,
                    original_ingress.completed_data,
                    current,
                )
            )

        if not candidate.pending_addresses or not candidate.completed_data:
            blocked = self._assembly_capacity_demand(
                ingress_port,
                candidate,
            )
            if blocked is not None:
                return DutTransition(state, blocked=blocked)
            ingress_states = dict(state.ingress_states)
            ingress_states[ingress_port] = candidate
            return DutTransition(
                Axi4WriteCrossbarState(
                    ingress_states,
                    state.pending,
                    state.next_serial,
                )
            )

        descriptor = candidate.pending_addresses[0]
        data = candidate.completed_data[0]
        relation_fault = self._complete_data_fault(descriptor, data)
        if relation_fault is not None:
            return DutTransition(state, fault=relation_fault)
        drained = Axi4SubordinateState(
            candidate.pending_addresses[1:],
            candidate.completed_data[1:],
            candidate.current_data,
        )
        blocked = self._assembly_capacity_demand(ingress_port, drained)
        if blocked is not None:
            return DutTransition(state, blocked=blocked)
        return self._forward_joined(
            state,
            ingress_port,
            drained,
            descriptor,
            data,
        )

    def _forward_joined(
        self,
        state: Axi4WriteCrossbarState,
        ingress_port: str,
        drained: Axi4SubordinateState,
        descriptor: CanonicalEvent,
        data: tuple[CanonicalEvent, ...],
    ) -> DutTransition:
        write_id = int(descriptor.key)
        route = self._route_for(descriptor)
        same_domain = tuple(
            item
            for item in state.pending
            if item.ingress_port == ingress_port
            and item.upstream_id == write_id
        )
        if same_domain and (
            route is None
            or any(item.egress_port != route.egress_port for item in same_domain)
        ):
            destination = "local DECERR" if route is None else route.egress_port
            return DutTransition(
                state,
                blocked=ResourceDemand(
                    "axi4_write_id_destination",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=1,
                    reason=(
                        f"{ingress_port} BID {write_id} is locked to "
                        f"{same_domain[0].egress_port!r}; request for "
                        f"{destination!r} waits for the prior B response"
                    ),
                    location=ingress_port,
                ),
            )

        if route is None:
            response = CanonicalEvent(
                "B",
                descriptor.key,
                {"resp": "DECERR"},
            )
            fault = self.ingress_attachments[ingress_port].outgoing_fault(
                response,
                rule_prefix="axi4_write_crossbar.decode_error",
            )
            if fault is not None:
                return DutTransition(state, fault=fault)
            ingress_states = dict(state.ingress_states)
            ingress_states[ingress_port] = drained
            return DutTransition(
                Axi4WriteCrossbarState(
                    ingress_states,
                    state.pending,
                    state.next_serial,
                ),
                (PortEmission(ingress_port, response),),
            )

        if same_domain:
            if len(same_domain) >= self.table_profile.outstanding_bursts_per_id:
                return DutTransition(
                    state,
                    blocked=ResourceDemand(
                        "axi4_write_outstanding_per_id",
                        ConstraintScope.VIRTUAL_DUT,
                        available=0,
                        capacity=self.table_profile.outstanding_bursts_per_id,
                        reason=(
                            f"{ingress_port} BID {write_id} reached its "
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
                        "axi4_write_route_table",
                        ConstraintScope.VIRTUAL_DUT,
                        available=0,
                        capacity=self.table_profile.active_id_capacity,
                        reason=(
                            f"{ingress_port} has no free active-BID slot"
                        ),
                        location=ingress_port,
                    ),
                )

        downstream_id = write_id
        forwarded_aw = replace(
            self._translate_aw(descriptor, route),
            key=downstream_id,
        )
        egress_attachment = self.egress_attachments[route.egress_port]
        for forwarded in (forwarded_aw, *data):
            fault = egress_attachment.outgoing_fault(
                forwarded,
                rule_prefix="axi4_write_crossbar.egress",
            )
            if fault is not None:
                return DutTransition(state, fault=fault)

        ingress_states = dict(state.ingress_states)
        ingress_states[ingress_port] = drained
        pending = (
            *state.pending,
            Axi4PendingWrite(
                serial=state.next_serial,
                ingress_port=ingress_port,
                upstream_id=write_id,
                egress_port=route.egress_port,
                downstream_id=downstream_id,
                beat_count=len(data),
            ),
        )
        return DutTransition(
            Axi4WriteCrossbarState(
                ingress_states,
                pending,
                state.next_serial + 1,
            ),
            tuple(
                PortEmission(route.egress_port, forwarded)
                for forwarded in (forwarded_aw, *data)
            ),
        )

    def _accept_b(
        self,
        state: Axi4WriteCrossbarState,
        egress_port: str,
        event: CanonicalEvent,
    ) -> DutTransition:
        attachment = self.egress_attachments[egress_port]
        fault = attachment.incoming_fault(
            event,
            rule_prefix="axi4_write_crossbar.egress",
        )
        if fault is not None:
            return DutTransition(state, fault=fault)
        if event.kind != "B":
            return DutTransition(
                state,
                fault=self._fault(
                    "egress_kind",
                    "write-only AXI4 crossbar egress accepts B events",
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
                    f"B response on {egress_port!r} for downstream BID "
                    f"{downstream_id} has no pending owner",
                ),
            )
        if event.payload["resp"] == "EXOKAY":
            return DutTransition(
                state,
                fault=self._fault(
                    "exclusive_response",
                    "non-exclusive write crossbar cannot return EXOKAY",
                ),
            )

        forwarded = replace(event, key=owner.upstream_id)
        fault = self.ingress_attachments[owner.ingress_port].outgoing_fault(
            forwarded,
            rule_prefix="axi4_write_crossbar.ingress",
        )
        if fault is not None:
            return DutTransition(state, fault=fault)
        pending = tuple(
            item for item in state.pending if item.serial != owner.serial
        )
        return DutTransition(
            Axi4WriteCrossbarState(
                state.ingress_states,
                pending,
                state.next_serial,
            ),
            (PortEmission(owner.ingress_port, forwarded),),
        )

    def route_locks(
        self,
        state: Axi4WriteCrossbarState,
    ) -> Mapping[tuple[str, int], Axi4WriteRouteLock]:
        self.validate_state(state)
        grouped: dict[tuple[str, int], list[str | None]] = {}
        for item in state.pending:
            grouped.setdefault(
                (item.ingress_port, item.upstream_id),
                [],
            ).append(item.egress_port)
        for ingress_port, ingress in state.ingress_states.items():
            for descriptor in ingress.pending_addresses:
                route = self._route_for(descriptor)
                grouped.setdefault(
                    (ingress_port, int(descriptor.key)),
                    [],
                ).append(None if route is None else route.egress_port)
        return MappingProxyType(
            {
                key: Axi4WriteRouteLock(
                    ingress_port=key[0],
                    write_id=key[1],
                    egress_port=destinations[0],
                    outstanding_bursts=len(destinations),
                )
                for key, destinations in grouped.items()
            }
        )

    def return_owner_queues(
        self,
        state: Axi4WriteCrossbarState,
    ) -> Mapping[tuple[str, int], tuple[Axi4PendingWrite, ...]]:
        self.validate_state(state)
        grouped: dict[tuple[str, int], list[Axi4PendingWrite]] = {}
        for item in state.pending:
            grouped.setdefault(
                (item.egress_port, item.downstream_id),
                [],
            ).append(item)
        return MappingProxyType(
            {key: tuple(items) for key, items in grouped.items()}
        )

    def active_id_usage(
        self,
        state: Axi4WriteCrossbarState,
        ingress_port: str,
    ) -> tuple[int, int]:
        self.validate_state(state)
        if ingress_port not in self.ingress_attachments:
            raise ValueError(f"unknown AXI4 write ingress {ingress_port!r}")
        usage = len(
            {
                write_id
                for write_id, _ in self._ingress_ordering_domains(
                    state,
                    ingress_port,
                )
            }
        )
        return usage, self.table_profile.active_id_capacity

    def _aw_admission_demand(
        self,
        state: Axi4WriteCrossbarState,
        ingress_port: str,
        descriptor: CanonicalEvent,
    ) -> ResourceDemand | None:
        """Reserve one destination/ordering slot when AW is accepted."""

        write_id = int(descriptor.key)
        route = self._route_for(descriptor)
        destination = None if route is None else route.egress_port
        domains = self._ingress_ordering_domains(state, ingress_port)
        same_domain = tuple(
            existing_destination
            for existing_id, existing_destination in domains
            if existing_id == write_id
        )
        if same_domain and any(
            existing_destination != destination
            for existing_destination in same_domain
        ):
            requested = (
                "local DECERR" if destination is None else destination
            )
            locked = (
                "local DECERR"
                if same_domain[0] is None
                else same_domain[0]
            )
            return ResourceDemand(
                "axi4_write_id_destination",
                ConstraintScope.VIRTUAL_DUT,
                available=0,
                capacity=1,
                reason=(
                    f"{ingress_port} BID {write_id} is locked to "
                    f"{locked!r}; AW for {requested!r} waits for the "
                    "ordering domain to retire"
                ),
                location=ingress_port,
            )
        if (
            len(same_domain)
            >= self.table_profile.outstanding_bursts_per_id
        ):
            return ResourceDemand(
                "axi4_write_outstanding_per_id",
                ConstraintScope.VIRTUAL_DUT,
                available=0,
                capacity=self.table_profile.outstanding_bursts_per_id,
                reason=(
                    f"{ingress_port} BID {write_id} reached its "
                    "accepted-burst limit"
                ),
                location=ingress_port,
            )
        if not same_domain:
            active_ids = {existing_id for existing_id, _ in domains}
            if len(active_ids) >= self.table_profile.active_id_capacity:
                return ResourceDemand(
                    "axi4_write_route_table",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.table_profile.active_id_capacity,
                    reason=(
                        f"{ingress_port} has no free active-BID slot"
                    ),
                    location=ingress_port,
                )
        return None

    def _ingress_ordering_domains(
        self,
        state: Axi4WriteCrossbarState,
        ingress_port: str,
    ) -> tuple[tuple[int, str | None], ...]:
        """Return accepted WAIT_W and WAIT_B destinations for one ingress."""

        domains: list[tuple[int, str | None]] = [
            (item.upstream_id, item.egress_port)
            for item in state.pending
            if item.ingress_port == ingress_port
        ]
        for descriptor in state.ingress_states[ingress_port].pending_addresses:
            route = self._route_for(descriptor)
            domains.append(
                (
                    int(descriptor.key),
                    None if route is None else route.egress_port,
                )
            )
        return tuple(domains)

    def assembly_usage(
        self,
        state: Axi4WriteCrossbarState,
        ingress_port: str,
    ) -> Mapping[str, tuple[int, int]]:
        """Return retained port-local AW/W storage use and capacity."""

        self.validate_state(state)
        if ingress_port not in self.ingress_attachments:
            raise ValueError(f"unknown AXI4 write ingress {ingress_port!r}")
        ingress = state.ingress_states[ingress_port]
        profile = self.assembly_profile
        return MappingProxyType(
            {
                "pending_aw": (
                    len(ingress.pending_addresses),
                    profile.max_pending_aw,
                ),
                "pre_aw_w_bursts": (
                    len(ingress.completed_data),
                    profile.max_pre_aw_w_bursts,
                ),
                "buffered_w_beats": (
                    self._buffered_w_beats(ingress),
                    profile.max_buffered_w_beats,
                ),
            }
        )

    def _assembly_capacity_demand(
        self,
        ingress_port: str,
        ingress: Axi4SubordinateState,
    ) -> ResourceDemand | None:
        profile = self.assembly_profile
        checks = (
            (
                "axi4_write_pending_aw",
                len(ingress.pending_addresses),
                profile.max_pending_aw,
                "AW descriptor FIFO",
            ),
            (
                "axi4_write_pre_aw_w_bursts",
                len(ingress.completed_data),
                profile.max_pre_aw_w_bursts,
                "complete pre-AW W burst FIFO",
            ),
            (
                "axi4_write_buffered_w_beats",
                self._buffered_w_beats(ingress),
                profile.max_buffered_w_beats,
                "buffered W beat storage",
            ),
        )
        for resource, usage, capacity, description in checks:
            if usage <= capacity:
                continue
            return ResourceDemand(
                resource,
                ConstraintScope.VIRTUAL_DUT,
                available=0,
                capacity=capacity,
                reason=(
                    f"{ingress_port} {description} is full "
                    f"({usage - 1}/{capacity})"
                ),
                location=ingress_port,
            )
        return None

    def _data_prefix_fault(
        self,
        descriptor: CanonicalEvent,
        data: tuple[CanonicalEvent, ...],
    ) -> SemanticFault | None:
        expected = transfer_count(descriptor)
        if len(data) > expected:
            return self._fault(
                "write_beat_count",
                f"W burst exceeded AW length of {expected} beats",
            )
        for index, beat in enumerate(data):
            expected_last = index + 1 == expected
            if bool(beat.payload["last"]) is not expected_last:
                return self._fault(
                    "write_last",
                    f"W beat {index + 1}/{expected} requires "
                    f"last={expected_last}",
                )
            reason = write_strobe_violation(
                descriptor,
                index,
                beat,
                bus_bytes=self.bus_bytes,
            )
            if reason is not None:
                return self._fault("write_strobes", reason)
        return None

    def _complete_data_fault(
        self,
        descriptor: CanonicalEvent,
        data: tuple[CanonicalEvent, ...],
    ) -> SemanticFault | None:
        expected = transfer_count(descriptor)
        if len(data) != expected:
            return self._fault(
                "write_beat_count",
                f"completed W burst has {len(data)} beats; "
                f"AW requires {expected}",
            )
        return self._data_prefix_fault(descriptor, data)

    def _route_for(self, event: CanonicalEvent) -> AddressRoute | None:
        touched = self._burst_byte_addresses(event)
        for route in self.routes:
            if not all(
                route.base_address <= address < route.limit_address
                for address in touched
            ):
                continue
            forwarded = self._translate_aw(event, route)
            delta = (
                0
                if route.output_base_address is None
                else route.output_base_address - route.base_address
            )
            if self._burst_byte_addresses(forwarded) != tuple(
                address + delta for address in touched
            ):
                continue
            # W has no address and is forwarded unchanged.  Remapping may not
            # move a transfer to different physical data lanes.
            if any(
                tuple(
                    address % self.bus_bytes
                    for address in beat_byte_addresses(
                        event,
                        index,
                        bus_bytes=self.bus_bytes,
                    )
                )
                != tuple(
                    address % self.bus_bytes
                    for address in beat_byte_addresses(
                        forwarded,
                        index,
                        bus_bytes=self.bus_bytes,
                    )
                )
                for index in range(transfer_count(event))
            ):
                continue
            return route
        return None

    def _burst_byte_addresses(
        self,
        event: CanonicalEvent,
    ) -> tuple[int, ...]:
        return tuple(
            byte_address
            for beat_index in range(transfer_count(event))
            for byte_address in beat_byte_addresses(
                event,
                beat_index,
                bus_bytes=self.bus_bytes,
            )
        )

    @staticmethod
    def _translate_aw(
        event: CanonicalEvent,
        route: AddressRoute,
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
    def _buffered_w_beats(state: Axi4SubordinateState) -> int:
        return len(state.current_data) + sum(
            len(burst) for burst in state.completed_data
        )

    def is_quiescent(self, state: object) -> bool:
        if not isinstance(state, Axi4WriteCrossbarState):
            return False
        try:
            self.validate_state(state)
        except (TypeError, ValueError):
            return False
        return not state.pending and all(
            not ingress.pending_addresses
            and not ingress.completed_data
            and not ingress.current_data
            for ingress in state.ingress_states.values()
        )

    def validate_state(self, state: object) -> None:
        """Reject a snapshot inconsistent with this configured crossbar."""

        if not isinstance(state, Axi4WriteCrossbarState):
            raise TypeError(
                "Axi4WriteCrossbarBackend requires Axi4WriteCrossbarState"
            )
        if set(state.ingress_states) != set(self.ingress_ports):
            raise ValueError(
                "AXI4 write state does not match configured ingresses"
            )
        for ingress_port, ingress in state.ingress_states.items():
            if ingress.pending_addresses and ingress.completed_data:
                raise ValueError(
                    "AXI4 write state contains an undrained AW/W pair"
                )
            if any(
                event.kind != "AW" for event in ingress.pending_addresses
            ):
                raise ValueError("AXI4 write AW FIFO contains another event")
            bursts = (*ingress.completed_data, ingress.current_data)
            if any(event.kind != "W" for burst in bursts for event in burst):
                raise ValueError("AXI4 write W storage contains another event")
            if any(
                not burst
                or not bool(burst[-1].payload["last"])
                or any(bool(event.payload["last"]) for event in burst[:-1])
                for burst in ingress.completed_data
            ):
                raise ValueError("AXI4 complete W burst has invalid WLAST")
            if any(bool(event.payload["last"]) for event in ingress.current_data):
                raise ValueError("AXI4 partial W burst contains WLAST")
            demand = self._assembly_capacity_demand(ingress_port, ingress)
            if demand is not None:
                raise ValueError(
                    f"AXI4 write state exceeds {demand.resource} capacity"
                )
            if ingress.pending_addresses and ingress.current_data:
                fault = self._data_prefix_fault(
                    ingress.pending_addresses[0],
                    ingress.current_data,
                )
                if fault is not None:
                    raise ValueError(fault.reason)
            if any(
                int(event.key) >= self.id_count
                for event in ingress.pending_addresses
            ):
                raise ValueError("AXI4 write AW FIFO contains out-of-range ID")
            if any(
                bool(event.payload["lock"])
                for event in ingress.pending_addresses
            ):
                raise ValueError("AXI4 write state contains an exclusive AW")

        if any(
            item.ingress_port not in self.ingress_attachments
            or item.egress_port not in self.egress_attachments
            for item in state.pending
        ):
            raise ValueError("AXI4 write ledger references an unknown port")
        if any(
            item.upstream_id >= self.id_count
            or item.downstream_id >= self.id_count
            for item in state.pending
        ):
            raise ValueError("AXI4 write ledger contains an out-of-range BID")
        if self.id_policy == RAW_ID_SERIALIZED and any(
            item.downstream_id != item.upstream_id for item in state.pending
        ):
            raise ValueError(
                "raw-ID AXI4 write policy requires identical upstream and "
                "downstream IDs"
            )

        for ingress in self.ingress_ports:
            domains = self._ingress_ordering_domains(state, ingress)
            by_id: dict[int, list[str | None]] = {}
            for write_id, destination in domains:
                by_id.setdefault(write_id, []).append(destination)
            if any(
                len(set(destinations)) != 1
                for destinations in by_id.values()
            ):
                raise ValueError(
                    "AXI4 write ordering domain spans more than one "
                    "destination"
                )
            if any(
                len(destinations)
                > self.table_profile.outstanding_bursts_per_id
                for destinations in by_id.values()
            ):
                raise ValueError(
                    "AXI4 write ordering domain exceeds its burst capacity"
                )
            active_ids = set(by_id)
            if len(active_ids) > self.table_profile.active_id_capacity:
                raise ValueError(
                    f"AXI4 write ingress {ingress!r} exceeds active-ID capacity"
                )

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"axi4_write_crossbar.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )


__all__ = [
    "RAW_ID_SERIALIZED",
    "Axi4PendingWrite",
    "Axi4WriteCrossbarBackend",
    "Axi4WriteCrossbarState",
    "Axi4WriteRouteLock",
    "Axi4WriteRouteTableProfile",
]

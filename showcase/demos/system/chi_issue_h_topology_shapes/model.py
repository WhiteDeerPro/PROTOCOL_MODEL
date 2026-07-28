"""Executable CHI topology-shape witnesses built by the caller.

The two cases in this module deliberately share one restricted ReadNoSnp
operation.  Their variable is the caller-owned SystemProtocol topology:

* a bidirectional four-router ring with an uneven leaf attachment; and
* a generated bidirectional 4x4 mesh with four corner endpoints.

Protocol behavior continues to come from ``protocol_model``.  This module is
only a reusable showcase assembly; it is not a built-in CHI topology recipe.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiReadNoSnpDirectLedger,
    ChiReadNoSnpDirectProfile,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiDirectHomeNode,
    ChiExactNodeRoute,
    ChiParticipantBinding,
    ChiParticipantPortBinding,
    ChiStoreForwardRouterNode,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiReadNoSnpMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    ChiNetworkEventKind,
    ChiReadNoSnpSystemEventKind,
    ChiReadNoSnpSystemSession,
    ChiSubmitRead,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiDatChannelProfile,
    ChiReqChannelProfile,
    ChiTransportLinkProfile,
)
from protocol_model.semantics import Verdict
from protocol_model.system import (
    ElaboratedSystemProtocol,
    SystemProtocol,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.boundary import (
    DutBehaviorTag,
    TransportDirection,
    TransportPort,
    VirtualDut,
)


REQUESTER_NODE_ID = 0x07
FIRST_LEAF_NODE_ID = 0x08
SECOND_LEAF_NODE_ID = 0x09
HOME_NODE_ID = 0x21
READ_ADDRESS = 0x4020
READ_VALUE = 0x5300_4020

REQ = frozenset((ChiChannelKind.REQ,))
DAT = frozenset((ChiChannelKind.DAT,))
REQ_DAT = frozenset((ChiChannelKind.REQ, ChiChannelKind.DAT))

RING_CASE = "heterogeneous-ring-star"
MESH_CASE = "four-by-four-mesh"


@dataclass(frozen=True)
class TopologyEndpointSpec:
    """One endpoint attached to a generated router topology."""

    name: str
    node_id: int
    router: str
    tx_channels: frozenset[ChiChannelKind]
    rx_channels: frozenset[ChiChannelKind]
    role: str = "leaf"

    def __post_init__(self) -> None:
        if self.role not in {"requester", "home", "leaf"}:
            raise ValueError(f"unknown topology endpoint role {self.role!r}")


@dataclass(frozen=True)
class GeneratedTopologyAssembly:
    """Construction objects retained for execution and presentation."""

    case: str
    shape: str
    system: SystemProtocol
    elaborated: ElaboratedSystemProtocol
    session: ChiReadNoSnpSystemSession
    requester: ChiParticipantBinding
    home: ChiParticipantBinding
    routers: Mapping[str, ChiStoreForwardRouterNode]
    router_bindings: tuple[ChiParticipantBinding, ...]
    adjacency: Mapping[str, tuple[str, ...]]
    endpoints: tuple[TopologyEndpointSpec, ...]
    request: ChiReadNoSnpMessage
    next_hop: Callable[[str, str], str]

    def expected_egress(
        self,
        router_name: str,
        endpoint: TopologyEndpointSpec,
    ) -> str:
        """Return the exact-route egress implied by this case."""

        if endpoint.router == router_name:
            return f"tx_local_{endpoint.name}"
        return f"tx_{self.next_hop(router_name, endpoint.router)}"


def _port(name: str, direction: TransportDirection) -> TransportPort:
    return TransportPort(
        name,
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        direction,
        clock_domain="chi_clk",
    )


def _link_profile(
    name: str,
    channels: frozenset[ChiChannelKind],
) -> ChiTransportLinkProfile:
    return ChiTransportLinkProfile(
        request=(
            ChiReqChannelProfile(
                representation=ChiIssueHReqProfile(),
                credit_capacities=(1,),
                observation=f"{name}.req",
            )
            if ChiChannelKind.REQ in channels
            else None
        ),
        data=(
            ChiDatChannelProfile(
                representation=ChiIssueHDatProfile(data_width=128),
                credit_capacity=1,
                observation=f"{name}.dat",
            )
            if ChiChannelKind.DAT in channels
            else None
        ),
        response=None,
        snoop=None,
        clock="chi_clk",
        activation_observation=f"{name}.active",
    )


def _endpoint_dut(spec: TopologyEndpointSpec) -> VirtualDut:
    tags = {
        "requester": frozenset((DutBehaviorTag.INITIATING,)),
        "home": frozenset((DutBehaviorTag.ADDRESSABLE,)),
        "leaf": frozenset(),
    }[spec.role]
    descriptions = {
        "requester": "restricted CHI RN-I requester",
        "home": "restricted CHI direct Home",
        "leaf": "declared but idle CHI leaf endpoint",
    }
    return VirtualDut(
        spec.name,
        {
            "tx": _port("tx", TransportDirection.TRANSMIT),
            "rx": _port("rx", TransportDirection.RECEIVE),
        },
        behavior_tags=tags,
        description=descriptions[spec.role],
    )


def _router_dut(
    name: str,
    neighbors: tuple[str, ...],
    local_endpoints: tuple[TopologyEndpointSpec, ...],
) -> VirtualDut:
    ingress_names = (
        *(f"rx_{neighbor}" for neighbor in neighbors),
        *(f"rx_local_{endpoint.name}" for endpoint in local_endpoints),
    )
    egress_names = (
        *(f"tx_{neighbor}" for neighbor in neighbors),
        *(f"tx_local_{endpoint.name}" for endpoint in local_endpoints),
    )
    return VirtualDut(
        name,
        {
            **{
                port_name: _port(
                    port_name,
                    TransportDirection.RECEIVE,
                )
                for port_name in ingress_names
            },
            **{
                port_name: _port(
                    port_name,
                    TransportDirection.TRANSMIT,
                )
                for port_name in egress_names
            },
        },
        behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
        description="exact-NodeID finite store-and-forward router",
    )


def _build_generated_network(
    case: str,
    shape: str,
    *,
    adjacency: Mapping[str, tuple[str, ...]],
    endpoints: tuple[TopologyEndpointSpec, ...],
    next_hop: Callable[[str, str], str],
) -> GeneratedTopologyAssembly:
    router_names = tuple(adjacency)
    if any(
        router not in adjacency.get(neighbor, ())
        for router, neighbors in adjacency.items()
        for neighbor in neighbors
    ):
        raise ValueError("generated topology adjacency must be bidirectional")
    if any(endpoint.router not in adjacency for endpoint in endpoints):
        raise ValueError("generated endpoint references an unknown router")
    requester_specs = tuple(
        endpoint for endpoint in endpoints if endpoint.role == "requester"
    )
    home_specs = tuple(
        endpoint for endpoint in endpoints if endpoint.role == "home"
    )
    if len(requester_specs) != 1 or len(home_specs) != 1:
        raise ValueError(
            "generated read topology requires one requester and one Home"
        )
    requester_spec = requester_specs[0]
    home_spec = home_specs[0]
    if requester_spec.node_id != REQUESTER_NODE_ID:
        raise ValueError("generated requester uses an unexpected NodeID")
    if home_spec.node_id != HOME_NODE_ID:
        raise ValueError("generated Home uses an unexpected NodeID")

    local_by_router = {
        router: tuple(
            endpoint
            for endpoint in endpoints
            if endpoint.router == router
        )
        for router in router_names
    }
    endpoint_duts = {
        endpoint.name: _endpoint_dut(endpoint)
        for endpoint in endpoints
    }
    router_duts = {
        router: _router_dut(
            router,
            tuple(adjacency[router]),
            local_by_router[router],
        )
        for router in router_names
    }
    routers = {
        router: ChiStoreForwardRouterNode(
            router,
            ingress_ports=tuple(
                name
                for name, port in router_duts[router].ports.items()
                if port.direction is TransportDirection.RECEIVE
            ),
            egress_ports=tuple(
                name
                for name, port in router_duts[router].ports.items()
                if port.direction is TransportDirection.TRANSMIT
            ),
            routes=tuple(
                ChiExactNodeRoute(
                    endpoint.node_id,
                    (
                        f"tx_local_{endpoint.name}"
                        if endpoint.router == router
                        else f"tx_{next_hop(router, endpoint.router)}"
                    ),
                    endpoint.rx_channels,
                )
                for endpoint in endpoints
            ),
            queue_capacity=1,
        )
        for router in router_names
    }

    builder = SystemProtocolBuilder(f"chi_issue_h_{case.replace('-', '_')}")
    for dut in (*endpoint_duts.values(), *router_duts.values()):
        builder.add_dut(dut)

    port_channels: dict[
        tuple[str, str],
        frozenset[ChiChannelKind],
    ] = {}

    def connect(
        connection_name: str,
        transmitter: tuple[str, str],
        receiver: tuple[str, str],
        channels: frozenset[ChiChannelKind],
    ) -> None:
        builder.connect_transport(
            connection_name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef(*transmitter),
            VirtualDutPortRef(*receiver),
            profile=_link_profile(connection_name, channels),
        )
        port_channels[transmitter] = channels
        port_channels[receiver] = channels

    for source, neighbors in adjacency.items():
        for target in neighbors:
            connect(
                f"{source}_to_{target}",
                (source, f"tx_{target}"),
                (target, f"rx_{source}"),
                REQ_DAT,
            )
    for endpoint in endpoints:
        connect(
            f"{endpoint.name}_to_{endpoint.router}",
            (endpoint.name, "tx"),
            (endpoint.router, f"rx_local_{endpoint.name}"),
            endpoint.tx_channels,
        )
        connect(
            f"{endpoint.router}_to_{endpoint.name}",
            (endpoint.router, f"tx_local_{endpoint.name}"),
            (endpoint.name, "rx"),
            endpoint.rx_channels,
        )

    system = builder.build()
    elaborated = system.elaborate()
    duts = elaborated.spec.virtual_duts
    profile = ChiReadNoSnpDirectProfile(
        requester_node_id=REQUESTER_NODE_ID,
        home_node_id=HOME_NODE_ID,
        data_width=128,
        outstanding_capacity=2,
    )
    requester_component = ChiReadNoSnpDirectLedger("rn.reads", profile)
    home_component = ChiDirectHomeNode(
        "hn.home",
        profile,
        lambda _request: READ_VALUE,
        request_capacity=1,
    )

    def binding_ports(
        dut_name: str,
    ) -> tuple[ChiParticipantPortBinding, ...]:
        dut = duts[dut_name]
        return tuple(
            ChiParticipantPortBinding(
                port,
                port_channels[(dut_name, port_name)],
            )
            for port_name, port in dut.ports.items()
        )

    requester = ChiParticipantBinding(
        requester_component.name,
        duts[requester_spec.name],
        requester_component,
        binding_ports(requester_spec.name),
        frozenset((REQUESTER_NODE_ID,)),
    )
    home = ChiParticipantBinding(
        home_component.name,
        duts[home_spec.name],
        home_component,
        binding_ports(home_spec.name),
        frozenset((HOME_NODE_ID,)),
    )
    router_bindings = tuple(
        ChiParticipantBinding(
            f"{router}.router",
            duts[router],
            routers[router],
            binding_ports(router),
        )
        for router in router_names
    )
    session = ChiReadNoSnpSystemSession(
        elaborated,
        requester=requester,
        home=home,
        routers=router_bindings,
    )
    request = ChiReadNoSnpMessage(
        transaction_id=3,
        address=READ_ADDRESS,
        size=4,
        order=0,
        allow_retry=True,
        protocol_credit_type=0,
        expect_completion_ack=False,
        memory_attributes=0,
    )
    return GeneratedTopologyAssembly(
        case=case,
        shape=shape,
        system=system,
        elaborated=elaborated,
        session=session,
        requester=requester,
        home=home,
        routers=routers,
        router_bindings=router_bindings,
        adjacency=dict(adjacency),
        endpoints=endpoints,
        request=request,
        next_hop=next_hop,
    )


def ring_next_hop(current: str, target: str) -> str:
    """Select the shorter deterministic direction around the four-node ring."""

    order = ("r0", "r1", "r2", "r3")
    current_index = order.index(current)
    target_index = order.index(target)
    clockwise = (target_index - current_index) % len(order)
    counterclockwise = (current_index - target_index) % len(order)
    step = 1 if clockwise <= counterclockwise else -1
    return order[(current_index + step) % len(order)]


def build_heterogeneous_ring_star() -> GeneratedTopologyAssembly:
    """Build a ring backbone with uneven, star-like leaf attachment."""

    return _build_generated_network(
        RING_CASE,
        "four-router bidirectional ring with nonuniform leaves",
        adjacency={
            "r0": ("r1", "r3"),
            "r1": ("r0", "r2"),
            "r2": ("r1", "r3"),
            "r3": ("r2", "r0"),
        },
        endpoints=(
            TopologyEndpointSpec(
                "rn",
                REQUESTER_NODE_ID,
                "r0",
                REQ,
                DAT,
                "requester",
            ),
            TopologyEndpointSpec(
                "leaf_a",
                FIRST_LEAF_NODE_ID,
                "r1",
                REQ_DAT,
                REQ_DAT,
            ),
            TopologyEndpointSpec(
                "leaf_b",
                SECOND_LEAF_NODE_ID,
                "r1",
                REQ_DAT,
                REQ_DAT,
            ),
            TopologyEndpointSpec(
                "hn",
                HOME_NODE_ID,
                "r2",
                DAT,
                REQ,
                "home",
            ),
        ),
        next_hop=ring_next_hop,
    )


def mesh_adjacency(
    width: int = 4,
    height: int = 4,
) -> dict[str, tuple[str, ...]]:
    """Return deterministic cardinal adjacency for a bounded 2-D mesh."""

    if width < 2 or height < 2 or width > 9 or height > 9:
        raise ValueError("mesh dimensions must be between 2 and 9")
    adjacency: dict[str, tuple[str, ...]] = {}
    for x in range(width):
        for y in range(height):
            neighbors = []
            for next_x, next_y in (
                (x - 1, y),
                (x + 1, y),
                (x, y - 1),
                (x, y + 1),
            ):
                if 0 <= next_x < width and 0 <= next_y < height:
                    neighbors.append(f"r{next_x}{next_y}")
            adjacency[f"r{x}{y}"] = tuple(neighbors)
    return adjacency


def xy_next_hop(current: str, target: str) -> str:
    """Use deterministic X-then-Y dimension-order routing."""

    current_x, current_y = int(current[1]), int(current[2])
    target_x, target_y = int(target[1]), int(target[2])
    if current_x != target_x:
        step = 1 if target_x > current_x else -1
        return f"r{current_x + step}{current_y}"
    if current_y != target_y:
        step = 1 if target_y > current_y else -1
        return f"r{current_x}{current_y + step}"
    raise ValueError("XY next hop is undefined at the target router")


def build_four_by_four_mesh() -> GeneratedTopologyAssembly:
    """Build the fixed public 4x4 scale witness."""

    return _build_generated_network(
        MESH_CASE,
        "four-by-four bidirectional mesh with corner endpoints",
        adjacency=mesh_adjacency(),
        endpoints=(
            TopologyEndpointSpec(
                "rn",
                REQUESTER_NODE_ID,
                "r00",
                REQ,
                DAT,
                "requester",
            ),
            TopologyEndpointSpec(
                "corner_a",
                FIRST_LEAF_NODE_ID,
                "r03",
                REQ_DAT,
                REQ_DAT,
            ),
            TopologyEndpointSpec(
                "corner_b",
                SECOND_LEAF_NODE_ID,
                "r30",
                REQ_DAT,
                REQ_DAT,
            ),
            TopologyEndpointSpec(
                "hn",
                HOME_NODE_ID,
                "r33",
                DAT,
                REQ,
                "home",
            ),
        ),
        next_hop=xy_next_hop,
    )


def _topology_counts(
    assembly: GeneratedTopologyAssembly,
) -> dict[str, int]:
    router_names = set(assembly.routers)
    plan = assembly.elaborated.transport_plan
    if plan is None:
        raise RuntimeError("generated topology has no transport plan")
    backbone = tuple(
        hop
        for hop in plan.hops
        if hop.transmitter.dut in router_names
        and hop.receiver.dut in router_names
    )
    physical_edges = (
        sum(len(neighbors) for neighbors in assembly.adjacency.values()) // 2
    )
    return {
        "router_count": len(router_names),
        "endpoint_count": len(assembly.endpoints),
        "virtual_dut_count": len(assembly.system.virtual_duts),
        "physical_backbone_edge_count": physical_edges,
        "directed_backbone_hop_count": len(backbone),
        "directed_endpoint_hop_count": len(plan.hops) - len(backbone),
        "directed_hop_count": len(plan.hops),
        "exact_route_count": sum(
            len(router.routes) for router in assembly.routers.values()
        ),
    }


def _route_nodes(
    assembly: GeneratedTopologyAssembly,
    route: tuple[str, ...],
) -> tuple[str, ...]:
    if not route:
        raise ValueError("executed route must not be empty")
    first = assembly.system.connections[route[0]]
    nodes = [first.transmitter.dut, first.receiver.dut]
    for connection_name in route[1:]:
        connection = assembly.system.connections[connection_name]
        if connection.transmitter.dut != nodes[-1]:
            raise ValueError("executed route is not contiguous")
        nodes.append(connection.receiver.dut)
    return tuple(nodes)


def execute_topology_read(
    assembly: GeneratedTopologyAssembly,
) -> dict[str, object]:
    """Execute one ReadNoSnp round trip and return compact public evidence."""

    session = assembly.session
    issued = session.step(
        session.initial_state(),
        ChiSubmitRead(assembly.requester.name, assembly.request),
    )
    if issued.fault is not None:
        raise RuntimeError(f"read submission faulted: {issued.fault.reason}")
    if issued.blocked is not None:
        raise RuntimeError(f"read submission blocked: {issued.blocked.reason}")
    run = session.run_until_quiescent(issued.state, max_steps=4096)
    if run.verdict is not Verdict.PASS:
        reason = "unknown" if run.blocked is None else run.blocked.reason
        raise RuntimeError(
            f"{assembly.case} ended as {run.verdict.value}: {reason}"
        )

    events = (*issued.emissions, *run.emissions)
    completed = run.final_state.requester.completed
    if len(completed) != 1:
        raise RuntimeError("topology read did not produce one completion")
    response = completed[0].response
    complete_events = tuple(
        event
        for event in events
        if event.kind is ChiReadNoSnpSystemEventKind.COMPLETE
    )
    if len(complete_events) != 1:
        raise RuntimeError("topology read did not emit one completion")
    complete_lineage = tuple(complete_events[0].lineage)
    request_route = tuple(session.request_route_connections)
    data_route = tuple(session.data_route_connections)
    required_hops = (*request_route, *data_route)
    network_kinds = tuple(
        event.detail.kind
        for event in events
        if event.detail is not None
    )
    router_transfer_count = (
        len(request_route) - 1 + len(data_route) - 1
    )
    counts = _topology_counts(assembly)
    assertions = {
        "verdict_is_pass": run.verdict is Verdict.PASS,
        "one_completion": len(completed) == 1,
        "read_value_matches": response.data == READ_VALUE,
        "router_accept_count_matches_routes": (
            network_kinds.count(ChiNetworkEventKind.ROUTER_ACCEPT)
            == router_transfer_count
        ),
        "router_forward_count_matches_routes": (
            network_kinds.count(ChiNetworkEventKind.ROUTER_FORWARD)
            == router_transfer_count
        ),
        "lineage_covers_every_executed_hop": all(
            any(label.startswith(f"{name}@") for label in complete_lineage)
            for name in required_hops
        ),
        "session_is_quiescent": session.is_quiescent(run.final_state),
    }
    if not all(assertions.values()):
        failed = ", ".join(
            name for name, passed in assertions.items() if not passed
        )
        raise RuntimeError(
            f"{assembly.case} assertions failed: {failed}"
        )

    used_connections = frozenset(required_hops)
    return {
        "schema": "protocol-model.showcase.chi-topology-shape/v1",
        "case": assembly.case,
        "shape": assembly.shape,
        "verdict": run.verdict.value,
        "profile": {
            "issue": "H",
            "operation": "ReadNoSnp -> CompData",
            "data_width": 128,
            "requester_node_id": REQUESTER_NODE_ID,
            "home_node_id": HOME_NODE_ID,
            "outstanding_capacity": 2,
            "home_request_capacity": 1,
            "router_queue_capacity": 1,
            "link_credit_capacity": 1,
            "channels": ("REQ", "DAT"),
        },
        "topology": {
            **counts,
            "routers": tuple(assembly.routers),
            "endpoints": tuple(
                {
                    "name": endpoint.name,
                    "node_id": endpoint.node_id,
                    "router": endpoint.router,
                    "role": endpoint.role,
                }
                for endpoint in assembly.endpoints
            ),
            "adjacency": dict(assembly.adjacency),
            "directed_connections": tuple(assembly.system.connections),
            "used_connections": tuple(
                name
                for name in assembly.system.connections
                if name in used_connections
            ),
            "idle_connections": tuple(
                name
                for name in assembly.system.connections
                if name not in used_connections
            ),
        },
        "transaction": {
            "request": {
                "message": type(assembly.request).__name__,
                "transaction_id": assembly.request.transaction_id,
                "address": assembly.request.address,
            },
            "response": {
                "message": type(response).__name__,
                "transaction_id": response.transaction_id,
                "data": response.data,
                "data_id": response.data_id,
            },
            "request_route": request_route,
            "request_nodes": _route_nodes(assembly, request_route),
            "data_route": data_route,
            "data_nodes": _route_nodes(assembly, data_route),
            "completion_lineage": complete_lineage,
        },
        "runtime": {
            "committed_microsteps": run.final_state.committed_microsteps,
            "emission_count": len(events),
            "network_event_counts": dict(
                sorted(
                    Counter(kind.value for kind in network_kinds).items()
                )
            ),
            "router_stats": {
                name: {
                    "accepted": state.accepted_count,
                    "forwarded": state.forwarded_count,
                    "depth": state.depth,
                }
                for name, state in run.final_state.network.routers.items()
            },
        },
        "assertions": assertions,
        "scope": {
            "shared_bus_or_broadcast": False,
            "shared_bus_arbitration": False,
            "adaptive_routing": False,
            "rsp_or_snp_channels": False,
            "coherence_lifecycle": False,
            "deadlock_or_fairness_proof": False,
            "raw_pin_waveform": False,
        },
    }


def execute_heterogeneous_ring_star(
) -> tuple[GeneratedTopologyAssembly, dict[str, object]]:
    assembly = build_heterogeneous_ring_star()
    return assembly, execute_topology_read(assembly)


def execute_four_by_four_mesh(
) -> tuple[GeneratedTopologyAssembly, dict[str, object]]:
    assembly = build_four_by_four_mesh()
    return assembly, execute_topology_read(assembly)


def execute_topology_shapes() -> dict[
    str,
    tuple[GeneratedTopologyAssembly, dict[str, object]],
]:
    """Execute both public cases in stable navigation order."""

    ring = execute_heterogeneous_ring_star()
    mesh = execute_four_by_four_mesh()
    return {
        RING_CASE: ring,
        MESH_CASE: mesh,
    }


__all__ = [
    "DAT",
    "FIRST_LEAF_NODE_ID",
    "GeneratedTopologyAssembly",
    "HOME_NODE_ID",
    "MESH_CASE",
    "REQ",
    "REQ_DAT",
    "READ_ADDRESS",
    "READ_VALUE",
    "REQUESTER_NODE_ID",
    "RING_CASE",
    "SECOND_LEAF_NODE_ID",
    "TopologyEndpointSpec",
    "build_four_by_four_mesh",
    "build_heterogeneous_ring_star",
    "execute_four_by_four_mesh",
    "execute_heterogeneous_ring_star",
    "execute_topology_read",
    "execute_topology_shapes",
    "mesh_adjacency",
    "ring_next_hop",
    "xy_next_hop",
]

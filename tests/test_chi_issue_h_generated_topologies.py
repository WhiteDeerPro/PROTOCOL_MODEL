"""Generated CHI route witnesses over caller-built transport graphs.

These tests exercise resolved topology, exact-NodeID routing, and one
restricted ReadNoSnp round trip.  They do not claim shared-bus arbitration,
performance, deadlock/fairness proof, or broader CHI protocol completeness.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import unittest

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


@dataclass(frozen=True)
class _EndpointSpec:
    name: str
    node_id: int
    router: str
    tx_channels: frozenset[ChiChannelKind]
    rx_channels: frozenset[ChiChannelKind]


@dataclass(frozen=True)
class _GeneratedAssembly:
    system: SystemProtocol
    elaborated: ElaboratedSystemProtocol
    session: ChiReadNoSnpSystemSession
    requester: ChiParticipantBinding
    home: ChiParticipantBinding
    routers: Mapping[str, ChiStoreForwardRouterNode]
    router_bindings: tuple[ChiParticipantBinding, ...]
    adjacency: Mapping[str, tuple[str, ...]]
    endpoints: tuple[_EndpointSpec, ...]
    request: ChiReadNoSnpMessage


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


def _endpoint_dut(spec: _EndpointSpec) -> VirtualDut:
    tags = (
        frozenset((DutBehaviorTag.INITIATING,))
        if spec.name == "rn"
        else frozenset((DutBehaviorTag.ADDRESSABLE,))
        if spec.name == "hn"
        else frozenset()
    )
    return VirtualDut(
        spec.name,
        {
            "tx": _port("tx", TransportDirection.TRANSMIT),
            "rx": _port("rx", TransportDirection.RECEIVE),
        },
        behavior_tags=tags,
        description="test-local CHI leaf endpoint",
    )


def _router_dut(
    name: str,
    neighbors: tuple[str, ...],
    local_endpoints: tuple[_EndpointSpec, ...],
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
                    port_name, TransportDirection.RECEIVE
                )
                for port_name in ingress_names
            },
            **{
                port_name: _port(
                    port_name, TransportDirection.TRANSMIT
                )
                for port_name in egress_names
            },
        },
        behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
        description="test-local exact-NodeID store-and-forward router",
    )


def _build_generated_network(
    name: str,
    *,
    adjacency: Mapping[str, tuple[str, ...]],
    endpoints: tuple[_EndpointSpec, ...],
    next_hop: Callable[[str, str], str],
) -> _GeneratedAssembly:
    router_names = tuple(adjacency)
    if any(
        router not in adjacency.get(neighbor, ())
        for router, neighbors in adjacency.items()
        for neighbor in neighbors
    ):
        raise ValueError("generated topology adjacency must be bidirectional")
    if any(endpoint.router not in adjacency for endpoint in endpoints):
        raise ValueError("generated endpoint references an unknown router")

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

    builder = SystemProtocolBuilder(name)
    for dut in (*endpoint_duts.values(), *router_duts.values()):
        builder.add_dut(dut)

    port_channels: dict[
        tuple[str, str], frozenset[ChiChannelKind]
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

    def binding_ports(dut_name: str) -> tuple[
        ChiParticipantPortBinding, ...
    ]:
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
        duts["rn"],
        requester_component,
        binding_ports("rn"),
        frozenset((REQUESTER_NODE_ID,)),
    )
    home = ChiParticipantBinding(
        home_component.name,
        duts["hn"],
        home_component,
        binding_ports("hn"),
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
    return _GeneratedAssembly(
        system,
        elaborated,
        session,
        requester,
        home,
        routers,
        router_bindings,
        dict(adjacency),
        endpoints,
        request,
    )


def _ring_next_hop(current: str, target: str) -> str:
    order = ("r0", "r1", "r2", "r3")
    current_index = order.index(current)
    target_index = order.index(target)
    clockwise = (target_index - current_index) % len(order)
    counterclockwise = (current_index - target_index) % len(order)
    step = 1 if clockwise <= counterclockwise else -1
    return order[(current_index + step) % len(order)]


def _build_ring() -> _GeneratedAssembly:
    return _build_generated_network(
        "chi_generated_nonuniform_ring",
        adjacency={
            "r0": ("r1", "r3"),
            "r1": ("r0", "r2"),
            "r2": ("r1", "r3"),
            "r3": ("r2", "r0"),
        },
        endpoints=(
            _EndpointSpec("rn", REQUESTER_NODE_ID, "r0", REQ, DAT),
            _EndpointSpec(
                "leaf_a",
                FIRST_LEAF_NODE_ID,
                "r1",
                REQ_DAT,
                REQ_DAT,
            ),
            _EndpointSpec(
                "leaf_b",
                SECOND_LEAF_NODE_ID,
                "r1",
                REQ_DAT,
                REQ_DAT,
            ),
            _EndpointSpec("hn", HOME_NODE_ID, "r2", DAT, REQ),
        ),
        next_hop=_ring_next_hop,
    )


def _mesh_adjacency() -> dict[str, tuple[str, ...]]:
    adjacency: dict[str, tuple[str, ...]] = {}
    for x in range(4):
        for y in range(4):
            neighbors = []
            for next_x, next_y in (
                (x - 1, y),
                (x + 1, y),
                (x, y - 1),
                (x, y + 1),
            ):
                if 0 <= next_x < 4 and 0 <= next_y < 4:
                    neighbors.append(f"r{next_x}{next_y}")
            adjacency[f"r{x}{y}"] = tuple(neighbors)
    return adjacency


def _xy_next_hop(current: str, target: str) -> str:
    current_x, current_y = int(current[1]), int(current[2])
    target_x, target_y = int(target[1]), int(target[2])
    if current_x != target_x:
        step = 1 if target_x > current_x else -1
        return f"r{current_x + step}{current_y}"
    if current_y != target_y:
        step = 1 if target_y > current_y else -1
        return f"r{current_x}{current_y + step}"
    raise ValueError("XY next hop is undefined at the target router")


def _build_mesh() -> _GeneratedAssembly:
    return _build_generated_network(
        "chi_generated_four_by_four_mesh",
        adjacency=_mesh_adjacency(),
        endpoints=(
            _EndpointSpec("rn", REQUESTER_NODE_ID, "r00", REQ, DAT),
            _EndpointSpec(
                "corner_a",
                FIRST_LEAF_NODE_ID,
                "r03",
                REQ_DAT,
                REQ_DAT,
            ),
            _EndpointSpec(
                "corner_b",
                SECOND_LEAF_NODE_ID,
                "r30",
                REQ_DAT,
                REQ_DAT,
            ),
            _EndpointSpec("hn", HOME_NODE_ID, "r33", DAT, REQ),
        ),
        next_hop=_xy_next_hop,
    )


class ChiIssueHGeneratedTopologyTest(unittest.TestCase):
    def assert_topology_counts(
        self,
        assembly: _GeneratedAssembly,
        *,
        router_count: int,
        endpoint_count: int,
        backbone_count: int,
    ) -> None:
        plan = assembly.elaborated.transport_plan
        self.assertIsNotNone(plan)
        assert plan is not None
        router_names = set(assembly.routers)
        backbone = tuple(
            hop
            for hop in plan.hops
            if hop.transmitter.dut in router_names
            and hop.receiver.dut in router_names
        )
        local = tuple(
            hop
            for hop in plan.hops
            if hop not in backbone
        )
        self.assertEqual(len(assembly.routers), router_count)
        self.assertEqual(
            len(assembly.system.virtual_duts),
            router_count + endpoint_count,
        )
        self.assertEqual(len(backbone), backbone_count)
        self.assertEqual(len(local), endpoint_count * 2)
        self.assertEqual(
            len(plan.hops),
            backbone_count + endpoint_count * 2,
        )
        self.assertEqual(
            sum(len(router.routes) for router in assembly.routers.values()),
            router_count * endpoint_count,
        )

    def assert_exact_routes(
        self,
        assembly: _GeneratedAssembly,
        next_hop: Callable[[str, str], str],
    ) -> None:
        for router_name, router in assembly.routers.items():
            routes = {route.target_id: route for route in router.routes}
            self.assertEqual(
                set(routes),
                {endpoint.node_id for endpoint in assembly.endpoints},
            )
            for endpoint in assembly.endpoints:
                route = routes[endpoint.node_id]
                expected_egress = (
                    f"tx_local_{endpoint.name}"
                    if endpoint.router == router_name
                    else f"tx_{next_hop(router_name, endpoint.router)}"
                )
                self.assertEqual(route.egress_port, expected_egress)
                self.assertEqual(route.channels, endpoint.rx_channels)

    def execute_read(
        self,
        assembly: _GeneratedAssembly,
    ) -> None:
        submitted = assembly.session.step(
            assembly.session.initial_state(),
            ChiSubmitRead(assembly.requester.name, assembly.request),
        )
        self.assertIsNone(submitted.fault)
        self.assertIsNone(submitted.blocked)
        run = assembly.session.run_until_quiescent(
            submitted.state,
            max_steps=4096,
        )
        self.assertIs(run.verdict, Verdict.PASS)
        self.assertIsNone(run.blocked)
        self.assertEqual(len(run.final_state.requester.completed), 1)
        self.assertEqual(
            run.final_state.requester.completed[0].response.data,
            READ_VALUE,
        )
        self.assertTrue(assembly.session.is_quiescent(run.final_state))

    def test_nonuniform_ring_resolves_exact_routes(self) -> None:
        assembly = _build_ring()
        self.assert_topology_counts(
            assembly,
            router_count=4,
            endpoint_count=4,
            backbone_count=8,
        )
        self.assert_exact_routes(assembly, _ring_next_hop)

        r1_ports = set(
            assembly.elaborated.spec.virtual_duts["r1"].ports
        )
        self.assertTrue(
            {
                "rx_local_leaf_a",
                "tx_local_leaf_a",
                "rx_local_leaf_b",
                "tx_local_leaf_b",
            }
            <= r1_ports
        )
        r3_ports = assembly.elaborated.spec.virtual_duts["r3"].ports
        self.assertFalse(any("local" in name for name in r3_ports))
        self.assertEqual(
            assembly.session.request_route_connections,
            (
                "rn_to_r0",
                "r0_to_r1",
                "r1_to_r2",
                "r2_to_hn",
            ),
        )
        self.assertEqual(
            assembly.session.data_route_connections,
            (
                "hn_to_r2",
                "r2_to_r3",
                "r3_to_r0",
                "r0_to_rn",
            ),
        )
        self.execute_read(assembly)

    def test_generated_four_by_four_mesh_runs_corner_read(self) -> None:
        assembly = _build_mesh()
        self.assert_topology_counts(
            assembly,
            router_count=16,
            endpoint_count=4,
            backbone_count=48,
        )
        self.assert_exact_routes(assembly, _xy_next_hop)
        self.assertEqual(
            assembly.session.request_route_connections,
            (
                "rn_to_r00",
                "r00_to_r10",
                "r10_to_r20",
                "r20_to_r30",
                "r30_to_r31",
                "r31_to_r32",
                "r32_to_r33",
                "r33_to_hn",
            ),
        )
        self.assertEqual(
            assembly.session.data_route_connections,
            (
                "hn_to_r33",
                "r33_to_r23",
                "r23_to_r13",
                "r13_to_r03",
                "r03_to_r02",
                "r02_to_r01",
                "r01_to_r00",
                "r00_to_rn",
            ),
        )
        self.assertEqual(
            len(assembly.session.request_route_connections),
            8,
        )
        self.assertEqual(
            len(assembly.session.data_route_connections),
            8,
        )
        self.execute_read(assembly)


if __name__ == "__main__":
    unittest.main()

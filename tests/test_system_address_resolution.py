from __future__ import annotations

import unittest

from protocol_model.interface import InterfaceEventKind, InterfaceProtocol
from protocol_model.semantics import EventSchema
from protocol_model.semantics import SemanticFragment
from protocol_model.system import (
    AddressClaim,
    AddressRouterContract,
    AddressWindow,
    InterfaceConnection,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.system.protocol import InterfaceConnection as InterfaceFacadeConnection
from protocol_model.system.topology import InterfaceConnection as TopologyInterfaceConnection
from protocol_model.virtual_dut.boundary import DutBehaviorTag, InterfacePort, VirtualDut
from protocol_model.virtual_dut.backend.simple import NoOpBackend
from protocol_model.virtual_dut.fabric import (
    ADDRESS_ROUTER_PROJECTION,
    AddressRoute,
    AddressRouterBoundaryProjection,
)


class _ProjectedRouterBackend(NoOpBackend):
    def __init__(self, projection: AddressRouterBoundaryProjection) -> None:
        self.projection = projection

    def boundary_projections(self):
        return {ADDRESS_ROUTER_PROJECTION: self.projection}


def _address_link() -> InterfaceProtocol:
    request = EventSchema("REQUEST")
    response = EventSchema("RESPONSE")
    return InterfaceProtocol.define(
        "generic_address_link",
        roles=frozenset(("requester", "completer")),
        event_kinds={
            "request": InterfaceEventKind(
                "request", "requester", "completer", request
            ),
            "response": InterfaceEventKind(
                "response", "completer", "requester", response
            ),
        },
        fragments=(SemanticFragment.empty("generic_address_link.base"),),
    )


def _router_contract(
    routes: tuple[AddressRoute, ...] | None = None,
) -> AddressRouterContract:
    return AddressRouterContract(
        "main_map",
        "router",
        ("s0", "s1"),
        ("m0", "m1"),
        routes
        or (
            AddressRoute("target0", 0x1000, 0x100, "m0", 0),
            AddressRoute("target1", 0x2000, 0x100, "m1"),
        ),
    )


class SystemAddressResolutionTest(unittest.TestCase):
    def _system(
        self,
        *,
        contract: AddressRouterContract | None = None,
        claims: tuple[AddressClaim, ...] | None = None,
    ):
        protocol = _address_link()
        builder = SystemProtocolBuilder("two_by_two")
        managers = tuple(
            VirtualDut(
                f"manager{index}",
                {"bus": InterfacePort("bus", protocol, "requester")},
            )
            for index in range(2)
        )
        targets = tuple(
            VirtualDut(
                f"target{index}",
                {"bus": InterfacePort("bus", protocol, "completer")},
            )
            for index in range(2)
        )
        for dut in (*managers, *targets):
            builder.add_dut(dut)

        contract = contract or _router_contract()
        seen_contracts: list[AddressRouterContract] = []

        def factory(received: AddressRouterContract) -> VirtualDut:
            seen_contracts.append(received)
            ports = {
                name: InterfacePort(name, protocol, "completer")
                for name in received.ingress_ports
            }
            ports.update(
                {
                    name: InterfacePort(name, protocol, "requester")
                    for name in received.egress_ports
                }
            )
            return VirtualDut(
                received.router,
                ports,
                behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
                backend=_ProjectedRouterBackend(
                    AddressRouterBoundaryProjection(
                        received.ingress_ports,
                        received.egress_ports,
                        received.routes,
                    )
                ),
            )

        returned_builder = builder.construct_address_router(contract, factory)
        self.assertIs(builder, returned_builder)
        self.assertIs(contract, seen_contracts[0])

        for index in range(2):
            builder.connect(
                f"ingress{index}",
                protocol,
                {
                    "requester": VirtualDutPortRef(
                        f"manager{index}", "bus"
                    ),
                    "completer": VirtualDutPortRef("router", f"s{index}"),
                },
            )
            builder.connect(
                f"egress{index}",
                protocol,
                {
                    "requester": VirtualDutPortRef("router", f"m{index}"),
                    "completer": VirtualDutPortRef(
                        f"target{index}", "bus"
                    ),
                },
            )

        if claims is None:
            claims = (
                AddressClaim(
                    "target0_window",
                    VirtualDutPortRef("target0", "bus"),
                    AddressWindow(0, 0x100),
                ),
                AddressClaim(
                    "target1_window",
                    VirtualDutPortRef("target1", "bus"),
                    AddressWindow(0x2000, 0x100),
                ),
            )
        for claim in claims:
            builder.add_address_claim(claim)
        return builder.build()

    def test_two_by_two_routes_resolve_to_four_explicit_paths(self) -> None:
        elaborated = self._system().elaborate()

        self.assertIsNotNone(elaborated.address_plan)
        assert elaborated.address_plan is not None
        self.assertEqual(4, len(elaborated.address_plan.paths))
        self.assertEqual(
            {"ingress0", "ingress1"},
            {
                elaborated.owner_by_port[path.ingress].name
                for path in elaborated.address_plan.paths
            },
        )
        self.assertEqual(
            {"target0", "target1"},
            {path.receiver.dut for path in elaborated.address_plan.paths},
        )
        target0_paths = tuple(
            path
            for path in elaborated.address_plan.paths
            if path.route == "target0"
        )
        self.assertEqual(
            {AddressWindow(0, 0x100)},
            {path.output_window for path in target0_paths},
        )

    def test_topology_does_not_infer_router_behavior(self) -> None:
        system = self._system()
        without_contract = type(system)(
            system.name,
            system.virtual_duts,
            system.connections,
            system.boundary,
            system.semantics,
        )

        self.assertIsNone(without_contract.elaborate().address_plan)

    def test_route_requires_a_covering_direct_neighbor_claim(self) -> None:
        claims = (
            AddressClaim(
                "target0_too_small",
                VirtualDutPortRef("target0", "bus"),
                AddressWindow(0, 0x80),
            ),
            AddressClaim(
                "target1_window",
                VirtualDutPortRef("target1", "bus"),
                AddressWindow(0x2000, 0x100),
            ),
        )

        with self.assertRaisesRegex(ValueError, "no covering direct-neighbor"):
            self._system(claims=claims).elaborate()

    def test_claim_on_another_endpoint_does_not_close_the_route(self) -> None:
        claims = (
            AddressClaim(
                "target0_window",
                VirtualDutPortRef("target0", "bus"),
                AddressWindow(0, 0x100),
            ),
            AddressClaim(
                "misplaced_target1_window",
                VirtualDutPortRef("target0", "bus"),
                AddressWindow(0x2000, 0x100),
            ),
        )

        with self.assertRaisesRegex(ValueError, "no covering direct-neighbor"):
            self._system(claims=claims).elaborate()

    def test_router_contract_rejects_overlap_and_unused_egress(self) -> None:
        with self.assertRaisesRegex(ValueError, "overlap"):
            _router_contract(
                (
                    AddressRoute("first", 0x1000, 0x100, "m0"),
                    AddressRoute("second", 0x1080, 0x100, "m1"),
                )
            )
        with self.assertRaisesRegex(ValueError, "have no route"):
            _router_contract(
                (AddressRoute("first", 0x1000, 0x100, "m0"),)
            )

    def test_injected_router_factory_must_honor_contract_boundary(self) -> None:
        protocol = _address_link()
        builder = SystemProtocolBuilder("invalid_factory")

        def missing_egress(_contract: AddressRouterContract) -> VirtualDut:
            return VirtualDut(
                "router",
                {
                    "s0": InterfacePort("s0", protocol, "completer"),
                    "s1": InterfacePort("s1", protocol, "completer"),
                    "m0": InterfacePort("m0", protocol, "requester"),
                },
            )

        with self.assertRaisesRegex(ValueError, "omitted contract ports"):
            builder.construct_address_router(
                _router_contract(),
                missing_egress,
            )

    def test_constructed_router_projection_must_match_contract(self) -> None:
        protocol = _address_link()
        builder = SystemProtocolBuilder("mismatched_projection")

        def wrong_route(contract: AddressRouterContract) -> VirtualDut:
            ports = {
                name: InterfacePort(name, protocol, "completer")
                for name in contract.ingress_ports
            }
            ports.update(
                {
                    name: InterfacePort(name, protocol, "requester")
                    for name in contract.egress_ports
                }
            )
            routes = (
                AddressRoute("target0", 0x1000, 0x100, "m1", 0),
                AddressRoute("target1", 0x2000, 0x100, "m0"),
            )
            return VirtualDut(
                contract.router,
                ports,
                backend=_ProjectedRouterBackend(
                    AddressRouterBoundaryProjection(
                        contract.ingress_ports,
                        contract.egress_ports,
                        routes,
                    )
                ),
            )

        with self.assertRaisesRegex(ValueError, "projection disagrees"):
            builder.construct_address_router(_router_contract(), wrong_route)

    def test_topology_types_remain_reexported_from_the_public_facade(self) -> None:
        self.assertIs(TopologyInterfaceConnection, InterfaceFacadeConnection)
        self.assertIs(TopologyInterfaceConnection, InterfaceConnection)


if __name__ == "__main__":
    unittest.main()

"""Explicit construction of SystemProtocol declarations."""

from __future__ import annotations

from typing import Mapping, Protocol

from protocol_model.interface import InterfaceProtocol
from protocol_model.semantics import SemanticFragment
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.fabric.projection import (
    ADDRESS_ROUTER_PROJECTION,
    AddressRouterBoundaryProjection,
)

from ..contracts.address import (
    AddressClaim,
    AddressMapContract,
    AddressRouterContract,
)
from ..protocol import SystemConnection, SystemProtocol
from ..topology.model import InterfaceConnection, VirtualDutPortRef
from ..topology.transport import DirectedTransportConnection


class AddressRouterFactory(Protocol):
    """Injected, protocol-specific construction behind a generic boundary."""

    def __call__(self, contract: AddressRouterContract) -> VirtualDut:
        ...


class SystemProtocolBuilder:
    """Collect explicit topology and contracts without runtime insertion.

    The builder never infers crossbar behavior from an N-by-M shape.  A
    generated address router requires both an ``AddressRouterContract`` and an
    injected factory.  Protocol-family configuration remains captured by that
    factory and does not enter the SystemProtocol package.
    """

    def __init__(self, name: str) -> None:
        if not name:
            raise ValueError("SystemProtocolBuilder requires a name")
        self.name = name
        self._virtual_duts: dict[str, VirtualDut] = {}
        self._connections: dict[str, SystemConnection] = {}
        self._boundary: dict[str, VirtualDutPortRef] = {}
        self._semantics: SemanticFragment | None = None
        self._address_claims: dict[str, AddressClaim] = {}
        self._address_routers: dict[str, AddressRouterContract] = {}

    def add_dut(self, dut: VirtualDut) -> "SystemProtocolBuilder":
        if not isinstance(dut, VirtualDut):
            raise TypeError("SystemProtocolBuilder.add_dut requires VirtualDut")
        if dut.name in self._virtual_duts:
            raise ValueError(f"duplicate VirtualDut {dut.name!r}")
        self._virtual_duts[dut.name] = dut
        return self

    def add_connection(
        self, connection: SystemConnection
    ) -> "SystemProtocolBuilder":
        if not isinstance(
            connection, (InterfaceConnection, DirectedTransportConnection)
        ):
            raise TypeError(
                "SystemProtocolBuilder.add_connection requires "
                "InterfaceConnection or DirectedTransportConnection"
            )
        if connection.name in self._connections:
            raise ValueError(
                f"duplicate connection {connection.name!r}"
            )
        self._connections[connection.name] = connection
        return self

    def connect(
        self,
        name: str,
        protocol: InterfaceProtocol,
        endpoints: Mapping[str, VirtualDutPortRef],
        *,
        parameters: Mapping[str, object] | None = None,
    ) -> "SystemProtocolBuilder":
        """Add one interface connection with caller-supplied role bindings.

        Role names are deliberately explicit; this method does not guess
        requester/completer or any protocol-family convention.
        """

        return self.add_connection(
            InterfaceConnection(name, protocol, endpoints, parameters or {})
        )

    def connect_transport(
        self,
        name: str,
        transport_family: str,
        transmitter: VirtualDutPortRef,
        receiver: VirtualDutPortRef,
        *,
        profile: object | None = None,
    ) -> "SystemProtocolBuilder":
        """Add one explicit transmitter-to-receiver transport hop."""

        return self.add_connection(
            DirectedTransportConnection(
                name,
                transport_family,
                transmitter,
                receiver,
                profile,
            )
        )

    def expose(
        self,
        name: str,
        reference: VirtualDutPortRef,
    ) -> "SystemProtocolBuilder":
        if not name:
            raise ValueError("system boundary name must not be empty")
        if not isinstance(reference, VirtualDutPortRef):
            raise TypeError("system boundary requires VirtualDutPortRef")
        if name in self._boundary:
            raise ValueError(f"duplicate system boundary {name!r}")
        self._boundary[name] = reference
        return self

    def with_semantics(
        self,
        semantics: SemanticFragment,
    ) -> "SystemProtocolBuilder":
        if not isinstance(semantics, SemanticFragment):
            raise TypeError("system semantics require SemanticFragment")
        if self._semantics is not None:
            raise ValueError("system semantics are already configured")
        self._semantics = semantics
        return self

    def add_address_claim(
        self,
        claim: AddressClaim,
    ) -> "SystemProtocolBuilder":
        if not isinstance(claim, AddressClaim):
            raise TypeError("address claim requires AddressClaim")
        if claim.name in self._address_claims:
            raise ValueError(f"duplicate address claim {claim.name!r}")
        self._address_claims[claim.name] = claim
        return self

    def add_address_router(
        self,
        contract: AddressRouterContract,
    ) -> "SystemProtocolBuilder":
        """Register an asserted contract for an already supplied router.

        This path is suitable for an external or opaque DUT whose local route
        implementation cannot be inspected.  Generated routers should use
        ``construct_address_router()`` so their boundary projection is checked.
        """

        if not isinstance(contract, AddressRouterContract):
            raise TypeError("address router requires AddressRouterContract")
        if contract.name in self._address_routers:
            raise ValueError(
                f"duplicate address router contract {contract.name!r}"
            )
        if any(
            existing.router == contract.router
            for existing in self._address_routers.values()
        ):
            raise ValueError(
                f"VirtualDut {contract.router!r} already has an address "
                "router contract"
            )
        self._address_routers[contract.name] = contract
        return self

    def construct_address_router(
        self,
        contract: AddressRouterContract,
        factory: AddressRouterFactory,
    ) -> "SystemProtocolBuilder":
        """Construct and register one router from the same route authority.

        Queue depth, arbitration, attachments, and other local choices may be
        captured by ``factory``.  The returned backend must project its stable
        address boundary; construction compares that projection with the
        contract before either object is registered.  Only the returned
        VirtualDut and explicit address contract survive into SystemProtocol.
        """

        if not isinstance(contract, AddressRouterContract):
            raise TypeError("address router requires AddressRouterContract")
        if not callable(factory):
            raise TypeError("address router factory must be callable")
        if contract.router in self._virtual_duts:
            raise ValueError(f"duplicate VirtualDut {contract.router!r}")
        if contract.name in self._address_routers or any(
            existing.router == contract.router
            for existing in self._address_routers.values()
        ):
            raise ValueError(
                f"address router {contract.name!r} is already configured"
            )

        dut = factory(contract)
        if not isinstance(dut, VirtualDut):
            raise TypeError("address router factory must return VirtualDut")
        if dut.name != contract.router:
            raise ValueError(
                f"address router factory returned {dut.name!r}, expected "
                f"{contract.router!r}"
            )
        required_ports = set(contract.ingress_ports) | set(
            contract.egress_ports
        )
        missing_ports = required_ports - set(dut.ports)
        if missing_ports:
            raise ValueError(
                "address router factory omitted contract ports: "
                f"{sorted(missing_ports)!r}"
            )

        expected_projection = AddressRouterBoundaryProjection(
            contract.ingress_ports,
            contract.egress_ports,
            contract.routes,
        )
        projections = (
            {} if dut.backend is None else dict(dut.backend.boundary_projections())
        )
        observed_projection = projections.get(ADDRESS_ROUTER_PROJECTION)
        if observed_projection is None:
            raise ValueError(
                "constructed address router did not expose an address-router "
                "boundary projection; use add_dut() + add_address_router() "
                "when the contract is an external-DUT assumption"
            )
        if not isinstance(
            observed_projection, AddressRouterBoundaryProjection
        ):
            raise TypeError(
                "address-router boundary projection has an invalid type"
            )
        if observed_projection != expected_projection:
            raise ValueError(
                "constructed address router boundary projection disagrees "
                f"with contract {contract.name!r}"
            )

        self._virtual_duts[dut.name] = dut
        self._address_routers[contract.name] = contract
        return self

    def build(self) -> SystemProtocol:
        address_map = None
        if self._address_claims or self._address_routers:
            address_map = AddressMapContract(
                tuple(self._address_claims.values()),
                tuple(self._address_routers.values()),
            )
        return SystemProtocol(
            name=self.name,
            virtual_duts=self._virtual_duts,
            connections=self._connections,
            boundary=self._boundary,
            semantics=self._semantics,
            address_map=address_map,
        )


__all__ = ["AddressRouterFactory", "SystemProtocolBuilder"]

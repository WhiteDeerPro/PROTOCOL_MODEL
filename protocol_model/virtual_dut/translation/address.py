"""Typed translation boundaries and stages for address operations."""

from __future__ import annotations

from dataclasses import dataclass

from ..address.access import (
    AccessResult,
    AccessStatus,
    AddressAccess,
    AddressRead,
    AddressWrite,
)
from ..fabric.route import AddressRoute, validate_address_routes
from .contract import (
    SemanticEffect,
    SemanticEffectKind,
    StageContract,
)
from .signature import OperationSignature
from .stage import LocalCompletion, LoweredOne, UnaryTranslationStage


ADDRESS_ACCESS_SIGNATURE = OperationSignature(
    "address",
    "access",
    "1",
    (AddressRead, AddressWrite),
    (AccessResult,),
)


_ADDRESS_ROUTE_CONTRACT = StageContract(
    semantic_effects=(
        SemanticEffect(
            "address",
            SemanticEffectKind.REBIND,
            "select one address window and apply its configured remap",
            "address_route.window",
        ),
    ),
    completion_rule=(
        "a route hit returns the downstream access result; a route miss "
        "completes locally with DECODE_ERROR"
    ),
    provenance="virtual_dut.translation.address_route",
)


_ADDRESS_SHAPE_CONTRACT = StageContract(
    semantic_effects=(
        SemanticEffect(
            "transfer_shape",
            SemanticEffectKind.REJECT,
            "complete locally when the target transport cannot represent an access shape",
            "address_shape.target_profile",
        ),
    ),
    completion_rule=(
        "a supported shape returns the downstream access result; an unsupported "
        "shape completes locally with ACCESS_ERROR"
    ),
    provenance="virtual_dut.translation.address_shape",
)


@dataclass(frozen=True)
class AddressRouteStage(
    UnaryTranslationStage[
        AddressAccess,
        AccessResult,
        AddressAccess,
        AccessResult,
    ]
):
    """Select and remap one address access for a single bridge egress.

    Route miss is an ordinary locally produced address result.  The stage
    therefore does not issue a child operation for an unmapped access.
    """

    routes: tuple[AddressRoute, ...]
    name: str = "address_route"

    source = ADDRESS_ACCESS_SIGNATURE
    target = ADDRESS_ACCESS_SIGNATURE
    contract = _ADDRESS_ROUTE_CONTRACT

    def __post_init__(self) -> None:
        routes = tuple(self.routes)
        if any(not isinstance(route, AddressRoute) for route in routes):
            raise TypeError("address route stage requires AddressRoute values")
        egress_ports = {route.egress_port for route in routes}
        if len(egress_ports) > 1:
            raise ValueError(
                "address route stage requires every route to select one egress"
            )
        object.__setattr__(
            self,
            "routes",
            validate_address_routes(routes, egress_ports),
        )

    @property
    def egress_port(self) -> str:
        return self.routes[0].egress_port

    def lower(
        self, parent: AddressAccess
    ) -> LoweredOne[AddressAccess] | LocalCompletion[AccessResult]:
        route = next(
            (candidate for candidate in self.routes if candidate.contains(parent)),
            None,
        )
        if route is None:
            return LocalCompletion(
                AccessResult(status=AccessStatus.DECODE_ERROR),
                rule="address_route.decode_miss",
            )
        return LoweredOne(route.translate(parent))

    def lift(
        self, context: object | None, child_result: AccessResult
    ) -> AccessResult:
        return child_result


@dataclass(frozen=True)
class AddressShapeGuardStage(
    UnaryTranslationStage[
        AddressAccess,
        AccessResult,
        AddressAccess,
        AccessResult,
    ]
):
    """Admit only access geometry represented by one target attachment."""

    max_size: int
    exact_size: int | None = None
    require_power_of_two: bool = True
    require_alignment: bool = True
    require_full_write: bool = False
    address_limit: int | None = None
    name: str = "address_shape_guard"

    source = ADDRESS_ACCESS_SIGNATURE
    target = ADDRESS_ACCESS_SIGNATURE
    contract = _ADDRESS_SHAPE_CONTRACT

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_size, int)
            or isinstance(self.max_size, bool)
            or self.max_size <= 0
        ):
            raise ValueError("address shape maximum size must be positive")
        if self.exact_size is not None and (
            not isinstance(self.exact_size, int)
            or isinstance(self.exact_size, bool)
            or self.exact_size <= 0
            or self.exact_size > self.max_size
        ):
            raise ValueError(
                "address shape exact size must be positive and within the maximum"
            )
        if type(self.require_power_of_two) is not bool:
            raise TypeError("address shape power-of-two policy must be bool")
        if type(self.require_alignment) is not bool:
            raise TypeError("address shape alignment policy must be bool")
        if type(self.require_full_write) is not bool:
            raise TypeError("address shape full-write policy must be bool")
        if self.address_limit is not None and (
            not isinstance(self.address_limit, int)
            or isinstance(self.address_limit, bool)
            or self.address_limit <= 0
        ):
            raise ValueError("address shape address limit must be positive")

    def lower(
        self, parent: AddressAccess
    ) -> LoweredOne[AddressAccess] | LocalCompletion[AccessResult]:
        if not self.supports(parent):
            return LocalCompletion(
                AccessResult(status=AccessStatus.ACCESS_ERROR),
                rule="address_shape.target_profile",
            )
        return LoweredOne(parent)

    def supports(self, parent: AddressAccess) -> bool:
        """Return whether this target profile can encode one access."""

        supported = parent.size <= self.max_size
        if self.exact_size is not None:
            supported = supported and parent.size == self.exact_size
        if self.require_power_of_two:
            supported = supported and not (parent.size & (parent.size - 1))
        if self.require_alignment:
            supported = supported and parent.address % parent.size == 0
        if self.require_full_write and isinstance(parent, AddressWrite):
            supported = supported and (
                parent.effective_byte_enable == (1 << parent.size) - 1
            )
        if self.address_limit is not None:
            supported = supported and parent.address + parent.size <= self.address_limit
        return supported

    def lift(
        self, context: object | None, child_result: AccessResult
    ) -> AccessResult:
        return child_result


__all__ = [
    "ADDRESS_ACCESS_SIGNATURE",
    "AddressRouteStage",
    "AddressShapeGuardStage",
]

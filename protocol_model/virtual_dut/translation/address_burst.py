"""Typed fan-out from an address burst to ordered address accesses."""

from __future__ import annotations

from dataclasses import dataclass

from ..address.access import (
    AccessResult,
    AccessStatus,
    AddressAccess,
    AddressRead,
    AddressWrite,
)
from ..address.burst import AddressBurst, AddressBurstResult
from ..fabric.route import AddressRoute, validate_address_routes
from .address import ADDRESS_ACCESS_SIGNATURE
from .address import AddressShapeGuardStage
from .contract import SemanticEffect, SemanticEffectKind, StageContract
from .signature import OperationSignature
from .stage import (
    Expanded,
    FanoutTranslationStage,
    LocalCompletion,
    LoweredOne,
    UnaryTranslationStage,
)


ADDRESS_BURST_SIGNATURE = OperationSignature(
    "address",
    "burst",
    "1",
    (AddressBurst,),
    (AddressBurstResult,),
)


_BURST_TO_ACCESS_CONTRACT = StageContract(
    semantic_effects=(
        SemanticEffect(
            "address_work",
            SemanticEffectKind.SPLIT,
            "issue one ordered child operation for each address-burst beat",
            "address_burst.split",
        ),
        SemanticEffect(
            "address_results",
            SemanticEffectKind.AGGREGATE,
            "fold ordered child results into one address-burst result",
            "address_burst.aggregate",
        ),
    ),
    completion_rule="child results are folded in ascending beat index order",
    provenance="virtual_dut.translation.burst_to_access",
)


_BURST_ROUTE_CONTRACT = StageContract(
    semantic_effects=(
        SemanticEffect(
            "address",
            SemanticEffectKind.REBIND,
            "preflight one route for every beat and remap the complete burst",
            "address_burst_route.window",
        ),
    ),
    completion_rule=(
        "an entirely routed burst continues; a route miss completes every "
        "beat locally with DECODE_ERROR before any child is issued"
    ),
    provenance="virtual_dut.translation.address_burst_route",
)


_BURST_SHAPE_CONTRACT = StageContract(
    semantic_effects=(
        SemanticEffect(
            "transfer_shape",
            SemanticEffectKind.REJECT,
            "preflight every beat against the target access profile",
            "address_burst_shape.target_profile",
        ),
    ),
    completion_rule=(
        "a supported burst continues; an unsupported beat completes every "
        "beat with ACCESS_ERROR before any child is issued"
    ),
    provenance="virtual_dut.translation.address_burst_shape",
)


def _require_burst_signature(signature: OperationSignature) -> None:
    if signature.request_types != (AddressBurst,) or (
        signature.completion_types != (AddressBurstResult,)
    ):
        raise ValueError(
            "burst-to-access source must use AddressBurst and AddressBurstResult"
        )


def _require_access_signature(signature: OperationSignature) -> None:
    if set(signature.request_types) != {AddressRead, AddressWrite} or (
        signature.completion_types != (AccessResult,)
    ):
        raise ValueError(
            "burst-to-access target must use address read/write and AccessResult"
        )


@dataclass(frozen=True)
class AddressBurstRouteStage(
    UnaryTranslationStage[
        AddressBurst,
        AddressBurstResult,
        AddressBurst,
        AddressBurstResult,
    ]
):
    """Route and remap a complete burst before fan-out can cause effects."""

    routes: tuple[AddressRoute, ...]
    signature: OperationSignature = ADDRESS_BURST_SIGNATURE
    name: str = "address_burst_route"

    contract = _BURST_ROUTE_CONTRACT

    def __post_init__(self) -> None:
        _require_burst_signature(self.signature)
        routes = tuple(self.routes)
        if any(not isinstance(route, AddressRoute) for route in routes):
            raise TypeError(
                "address burst route stage requires AddressRoute values"
            )
        egress_ports = {route.egress_port for route in routes}
        if len(egress_ports) > 1:
            raise ValueError(
                "address burst route stage requires one selected egress"
            )
        object.__setattr__(
            self,
            "routes",
            validate_address_routes(routes, egress_ports),
        )

    @property
    def source(self) -> OperationSignature:
        return self.signature

    @property
    def target(self) -> OperationSignature:
        return self.signature

    @property
    def egress_port(self) -> str:
        return self.routes[0].egress_port

    def lower(
        self, parent: AddressBurst
    ) -> LoweredOne[AddressBurst] | LocalCompletion[AddressBurstResult]:
        route = next(
            (
                candidate
                for candidate in self.routes
                if all(candidate.contains(access) for access in parent.accesses)
            ),
            None,
        )
        if route is None:
            return LocalCompletion(
                AddressBurstResult(
                    tuple(
                        AccessResult(status=AccessStatus.DECODE_ERROR)
                        for _ in parent.accesses
                    )
                ),
                rule="address_burst_route.decode_miss",
            )
        return LoweredOne(
            AddressBurst(
                tuple(route.translate(access) for access in parent.accesses)
            )
        )

    def lift(
        self, context: object | None, child_result: AddressBurstResult
    ) -> AddressBurstResult:
        return child_result


@dataclass(frozen=True)
class AddressBurstShapeGuardStage(
    UnaryTranslationStage[
        AddressBurst,
        AddressBurstResult,
        AddressBurst,
        AddressBurstResult,
    ]
):
    """Preflight target geometry for every beat before burst fan-out."""

    access_guard: AddressShapeGuardStage
    signature: OperationSignature = ADDRESS_BURST_SIGNATURE
    name: str = "address_burst_shape_guard"

    contract = _BURST_SHAPE_CONTRACT

    def __post_init__(self) -> None:
        _require_burst_signature(self.signature)
        if not isinstance(self.access_guard, AddressShapeGuardStage):
            raise TypeError(
                "address burst shape guard requires an access shape guard"
            )

    @property
    def source(self) -> OperationSignature:
        return self.signature

    @property
    def target(self) -> OperationSignature:
        return self.signature

    def lower(
        self, parent: AddressBurst
    ) -> LoweredOne[AddressBurst] | LocalCompletion[AddressBurstResult]:
        if not all(
            self.access_guard.supports(access)
            for access in parent.accesses
        ):
            return LocalCompletion(
                AddressBurstResult(
                    tuple(
                        AccessResult(status=AccessStatus.ACCESS_ERROR)
                        for _ in parent.accesses
                    )
                ),
                rule="address_burst_shape.target_profile",
            )
        return LoweredOne(parent)

    def lift(
        self, context: object | None, child_result: AddressBurstResult
    ) -> AddressBurstResult:
        return child_result


@dataclass(frozen=True)
class BurstToAccessStage(
    FanoutTranslationStage[
        AddressBurst,
        AddressBurstResult,
        AddressAccess,
        AccessResult,
    ]
):
    """Lazily issue each stored beat and retain ordered completion results.

    ``source`` and ``target`` may carry integration-specific semantic
    identities while retaining the canonical runtime DTOs.  This lets an
    explicit attribute stage sit after fan-out without introducing a
    protocol-specific burst executor.
    """

    source: OperationSignature = ADDRESS_BURST_SIGNATURE
    target: OperationSignature = ADDRESS_ACCESS_SIGNATURE
    name: str = "burst_to_access"

    contract = _BURST_TO_ACCESS_CONTRACT

    def __post_init__(self) -> None:
        _require_burst_signature(self.source)
        _require_access_signature(self.target)

    def begin(self, parent: AddressBurst) -> Expanded:
        return Expanded(parent.beat_count, context=parent, fold_state=())

    def child_at(
        self, context: object | None, index: int
    ) -> AddressRead | AddressWrite:
        if not isinstance(context, AddressBurst):
            raise TypeError("burst-to-access lost its AddressBurst context")
        return context.accesses[index]

    def fold_one(
        self,
        context: object | None,
        fold_state: object | None,
        index: int,
        child_result: AccessResult,
    ) -> tuple[AccessResult, ...]:
        if not isinstance(context, AddressBurst):
            raise TypeError("burst-to-access lost its AddressBurst context")
        if not isinstance(fold_state, tuple) or any(
            not isinstance(result, AccessResult) for result in fold_state
        ):
            raise TypeError("burst-to-access fold state must contain results")
        if index != len(fold_state):
            raise ValueError("burst-to-access results must fold in beat order")
        if index >= context.beat_count:
            raise IndexError("burst-to-access result index exceeds beat count")
        if not isinstance(child_result, AccessResult):
            raise TypeError("burst-to-access child result must be AccessResult")
        return (*fold_state, child_result)

    def finish(
        self, context: object | None, fold_state: object | None
    ) -> AddressBurstResult:
        if not isinstance(context, AddressBurst):
            raise TypeError("burst-to-access lost its AddressBurst context")
        if not isinstance(fold_state, tuple) or (
            len(fold_state) != context.beat_count
        ):
            raise ValueError("burst-to-access result count does not match the burst")
        return AddressBurstResult(fold_state)


__all__ = [
    "ADDRESS_BURST_SIGNATURE",
    "AddressBurstRouteStage",
    "AddressBurstShapeGuardStage",
    "BurstToAccessStage",
]

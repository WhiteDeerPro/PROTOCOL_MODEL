"""Bounded, strictly serialized AXI4 subordinate to APB requester bridge."""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from protocol_model.link import LinkProtocol
from protocol_model.link.amba.apb import APB_FAMILY
from protocol_model.link.amba.axi.axi4 import AXI4_FAMILY
from protocol_model.semantics import ConstraintScope, SemanticFault
from protocol_model.virtual_dut.address.access import (
    AccessResult,
    AccessStatus,
    AddressAccess,
    AddressRead,
    AddressWrite,
    ByteOrder,
)
from protocol_model.virtual_dut.attachments.address import AddressRequest
from protocol_model.virtual_dut.backend.base import VirtualDutModel
from protocol_model.virtual_dut.backend.transition import (
    DutTransition,
    PortEmission,
    PortInput,
)
from protocol_model.virtual_dut.binding import (
    PortAttachmentBinding,
    VirtualDutBuilder,
)
from protocol_model.virtual_dut.boundary.module import DutFacet, VirtualDut
from protocol_model.virtual_dut.boundary.port import ProtocolPort
from protocol_model.virtual_dut.fabric.route import (
    AddressRoute,
    validate_address_routes,
)

from protocol_model.integrations.attachments.amba.apb import (
    ApbRequesterAttachment,
)
from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4AddressSpaceAttachment,
    Axi4BurstRequest,
    Axi4SubordinateState,
)


@dataclass(frozen=True)
class Axi4ToApbBridgeProfile:
    """Finite storage contract for the first AXI4-to-APB bridge profile.

    ``max_parent_transactions`` counts fully decoded AXI bursts in
    ``active + ready``.  AW descriptors and W data which have not yet formed
    such a burst use the three separate fragment limits.  The APB side always
    has at most one issued beat, as required by its requester attachment.

    Capacity exhaustion is currently reported as a VirtualDut fault.  A
    pin/cycle projection can later turn the same occupancy into AXI READY
    backpressure without changing this storage contract.
    """

    max_parent_transactions: int = 8
    max_pending_aw: int = 8
    max_pre_aw_w_bursts: int = 8
    max_buffered_w_beats: int = 256

    def __post_init__(self) -> None:
        for name in (
            "max_parent_transactions",
            "max_pending_aw",
            "max_pre_aw_w_bursts",
            "max_buffered_w_beats",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class Axi4ToApbActive:
    """One AXI parent burst being drained through the sole APB transfer."""

    request: Axi4BurstRequest
    results: tuple[AccessResult, ...] = ()
    pending_request_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request, Axi4BurstRequest):
            raise TypeError("active bridge request must be an AXI4 burst")
        if len(self.results) > len(self.request.accesses):
            raise ValueError("active bridge has more results than AXI beats")
        if self.pending_request_id is not None and (
            not isinstance(self.pending_request_id, int)
            or isinstance(self.pending_request_id, bool)
            or self.pending_request_id < 0
        ):
            raise ValueError("pending APB request id must be non-negative")
        if (
            self.pending_request_id is not None
            and len(self.results) == len(self.request.accesses)
        ):
            raise ValueError("completed AXI burst cannot own a pending APB beat")


@dataclass(frozen=True)
class Axi4ToApbBridgeState:
    """Immutable transport, queue, and correlation state of one bridge."""

    ingress_state: object
    egress_state: object
    ready: tuple[Axi4BurstRequest, ...] = ()
    active: Axi4ToApbActive | None = None
    next_request_id: int = 0

    def __post_init__(self) -> None:
        if any(not isinstance(item, Axi4BurstRequest) for item in self.ready):
            raise TypeError("bridge ready queue accepts AXI4 burst requests")
        if self.active is not None and not isinstance(
            self.active, Axi4ToApbActive
        ):
            raise TypeError("bridge active entry has the wrong type")
        if (
            not isinstance(self.next_request_id, int)
            or isinstance(self.next_request_id, bool)
            or self.next_request_id < 0
        ):
            raise ValueError("next APB request id must be non-negative")


class Axi4ToApbBridgeBackend(VirtualDutModel):
    """Split AXI bursts into APB beats under a strict FIFO parent policy.

    FIFO order is the order in which complete parent requests emerge from the
    AXI attachment.  AW and W are first joined by the AXI transport rule; the
    bridge does not invent an ordering between an incomplete write and an AR
    request on the independent read channel.
    """

    def __init__(
        self,
        ingress_binding: PortAttachmentBinding,
        egress_binding: PortAttachmentBinding,
        routes: tuple[AddressRoute, ...],
        profile: Axi4ToApbBridgeProfile,
    ) -> None:
        if not isinstance(ingress_binding, PortAttachmentBinding):
            raise TypeError("AXI bridge ingress requires an attachment binding")
        if not isinstance(egress_binding, PortAttachmentBinding):
            raise TypeError("APB bridge egress requires an attachment binding")
        if not isinstance(
            ingress_binding.attachment, Axi4AddressSpaceAttachment
        ):
            raise TypeError("AXI bridge ingress requires an AXI4 subordinate")
        if not isinstance(egress_binding.attachment, ApbRequesterAttachment):
            raise TypeError("APB bridge egress requires an APB requester")
        if ingress_binding.name == egress_binding.name:
            raise ValueError("bridge ingress and egress port names must differ")
        if not isinstance(profile, Axi4ToApbBridgeProfile):
            raise TypeError("bridge profile must be Axi4ToApbBridgeProfile")

        self.ingress_binding = ingress_binding
        self.egress_binding = egress_binding
        self.ingress_port = ingress_binding.name
        self.egress_port = egress_binding.name
        self.ingress_attachment = ingress_binding.attachment
        self.egress_attachment = egress_binding.attachment
        self.profile = profile
        self.bus_bytes = self.egress_attachment.bytes_per_transfer
        self.routes = validate_address_routes(routes, (self.egress_port,))
        self.bindings = MappingProxyType(
            {
                self.ingress_port: ingress_binding,
                self.egress_port: egress_binding,
            }
        )

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, PortAttachmentBinding]:
        return self.bindings

    def initial_state(self) -> Axi4ToApbBridgeState:
        return Axi4ToApbBridgeState(
            self.ingress_attachment.initial_state(),
            self.egress_attachment.initial_state(),
        )

    def accept(self, state: object, action: PortInput) -> DutTransition:
        if not isinstance(state, Axi4ToApbBridgeState):
            raise TypeError(
                "Axi4ToApbBridgeBackend requires Axi4ToApbBridgeState"
            )
        if action.port == self.ingress_port:
            return self._accept_axi(state, action)
        if action.port == self.egress_port:
            return self._accept_apb(state, action)
        return DutTransition(
            state,
            fault=self._fault(
                "unknown_port", f"bridge has no port {action.port!r}"
            ),
        )

    def _accept_axi(
        self, state: Axi4ToApbBridgeState, action: PortInput
    ) -> DutTransition:
        decoded = self.ingress_attachment.decode_request(
            state.ingress_state, action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)

        candidate = replace(state, ingress_state=decoded.state)
        fragment_fault = self._fragment_capacity_fault(candidate.ingress_state)
        if fragment_fault is not None:
            return DutTransition(state, fault=fragment_fault)
        if decoded.request is None:
            return DutTransition(candidate)

        occupied = len(candidate.ready) + (candidate.active is not None)
        if occupied >= self.profile.max_parent_transactions:
            return DutTransition(
                state,
                fault=self._fault(
                    "parent_capacity",
                    "AXI parent transaction capacity is full "
                    f"({self.profile.max_parent_transactions})",
                ),
            )
        candidate = replace(
            candidate, ready=candidate.ready + (decoded.request,)
        )
        return self._rollback_fault(state, self._drive(candidate))

    def _accept_apb(
        self, state: Axi4ToApbBridgeState, action: PortInput
    ) -> DutTransition:
        decoded = self.egress_attachment.decode_completion(
            state.egress_state, action.event
        )
        if decoded.fault is not None:
            return DutTransition(state, fault=decoded.fault)
        candidate = replace(state, egress_state=decoded.state)
        if decoded.completion is None:
            return DutTransition(candidate)

        active = candidate.active
        if active is None or active.pending_request_id is None:
            return DutTransition(
                state,
                fault=self._fault(
                    "orphan_completion",
                    "APB completion has no active AXI beat owner",
                ),
            )
        if decoded.completion.request_id != active.pending_request_id:
            return DutTransition(
                state,
                fault=self._fault(
                    "completion_owner",
                    f"APB completion {decoded.completion.request_id} does not "
                    f"belong to active request {active.pending_request_id}",
                ),
            )
        if decoded.completion.result.effects:
            return DutTransition(
                state,
                fault=self._fault(
                    "completion_effect",
                    "bridge completion boundary does not carry endpoint-local effects",
                ),
            )

        candidate = replace(
            candidate,
            active=Axi4ToApbActive(
                active.request,
                active.results + (decoded.completion.result,),
            ),
        )
        return self._rollback_fault(state, self._drive(candidate))

    def _drive(self, state: Axi4ToApbBridgeState) -> DutTransition:
        """Advance local zero-time work until one APB transfer is pending."""

        candidate = state
        emissions: list[PortEmission] = []
        while True:
            active = candidate.active
            if active is None:
                if not candidate.ready:
                    return DutTransition(candidate, tuple(emissions))
                active = Axi4ToApbActive(candidate.ready[0])
                candidate = replace(
                    candidate,
                    ready=candidate.ready[1:],
                    active=active,
                )

            if active.pending_request_id is not None:
                return DutTransition(candidate, tuple(emissions))

            index = len(active.results)
            if index == len(active.request.accesses):
                encoded = self.ingress_attachment.encode_completion(
                    candidate.ingress_state,
                    active.request,
                    active.results,
                )
                if encoded.fault is not None:
                    return DutTransition(candidate, fault=encoded.fault)
                candidate = replace(
                    candidate,
                    ingress_state=encoded.state,
                    active=None,
                )
                emissions.extend(
                    PortEmission(self.ingress_port, event)
                    for event in encoded.events
                )
                continue

            access = active.request.accesses[index]
            access_fault = self._access_profile_fault(access)
            if access_fault is not None:
                return DutTransition(candidate, fault=access_fault)
            route = next(
                (item for item in self.routes if item.contains(access)), None
            )
            if route is None:
                candidate = replace(
                    candidate,
                    active=replace(
                        active,
                        results=active.results
                        + (AccessResult(status=AccessStatus.DECODE_ERROR),),
                    ),
                )
                continue

            translated_access = route.translate(access)
            output_fault = self._access_profile_fault(translated_access)
            if output_fault is not None:
                return DutTransition(candidate, fault=output_fault)
            output_access = self._project_apb_access(translated_access)
            request_id = candidate.next_request_id
            encoded = self.egress_attachment.encode_request(
                candidate.egress_state,
                AddressRequest(request_id, output_access),
            )
            if encoded.fault is not None:
                return DutTransition(candidate, fault=encoded.fault)
            candidate = replace(
                candidate,
                egress_state=encoded.state,
                active=replace(active, pending_request_id=request_id),
                next_request_id=request_id + 1,
            )
            emissions.extend(
                PortEmission(self.egress_port, event)
                for event in encoded.events
            )
            return DutTransition(candidate, tuple(emissions))

    def _access_profile_fault(
        self, access: AddressAccess
    ) -> SemanticFault | None:
        if access.size != self.bus_bytes or access.address % self.bus_bytes:
            return self._fault(
                "access_shape",
                "current AXI4-to-APB profile requires aligned, full-width beats",
            )
        unsupported = {
            name: access.attributes[name]
            for name in ("cache", "qos", "region")
            if access.attributes.get(name, 0) != 0
        }
        if unsupported:
            return self._fault(
                "attributes",
                "current AXI4-to-APB profile cannot preserve non-zero "
                f"attributes {sorted(unsupported)!r}",
            )
        return None

    @staticmethod
    def _project_apb_access(access: AddressAccess) -> AddressAccess:
        attributes = {"prot": access.attributes.get("prot", 0)}
        if isinstance(access, AddressRead):
            return AddressRead(access.address, access.size, attributes)
        assert isinstance(access, AddressWrite)
        return AddressWrite(
            access.address,
            access.size,
            access.data,
            access.byte_enable,
            attributes,
        )

    def _fragment_capacity_fault(
        self, ingress_state: object
    ) -> SemanticFault | None:
        if not isinstance(ingress_state, Axi4SubordinateState):
            return self._fault(
                "ingress_state", "AXI attachment returned an unexpected state"
            )
        if len(ingress_state.pending_addresses) > self.profile.max_pending_aw:
            return self._fault(
                "pending_aw_capacity",
                "pending AXI AW capacity is full "
                f"({self.profile.max_pending_aw})",
            )
        if (
            len(ingress_state.completed_data)
            > self.profile.max_pre_aw_w_bursts
        ):
            return self._fault(
                "pre_aw_w_capacity",
                "complete pre-AW W burst capacity is full "
                f"({self.profile.max_pre_aw_w_bursts})",
            )
        buffered_w_beats = len(ingress_state.current_data) + sum(
            len(item) for item in ingress_state.completed_data
        )
        if buffered_w_beats > self.profile.max_buffered_w_beats:
            return self._fault(
                "w_beat_capacity",
                "buffered AXI W beat capacity is full "
                f"({self.profile.max_buffered_w_beats})",
            )
        return None

    def is_quiescent(self, state: object) -> bool:
        if not isinstance(state, Axi4ToApbBridgeState):
            return False
        return (
            state.active is None
            and not state.ready
            and self.ingress_attachment.is_quiescent(state.ingress_state)
            and self.egress_attachment.is_quiescent(state.egress_state)
        )

    @staticmethod
    def _rollback_fault(
        original: Axi4ToApbBridgeState, transition: DutTransition
    ) -> DutTransition:
        if transition.fault is None:
            return transition
        return DutTransition(original, fault=transition.fault)

    @staticmethod
    def _fault(suffix: str, message: str) -> SemanticFault:
        return SemanticFault(
            f"axi4_to_apb_bridge.{suffix}",
            message,
            ConstraintScope.VIRTUAL_DUT,
        )


def build_axi4_to_apb_bridge_vdut(
    name: str,
    axi_protocol: LinkProtocol,
    apb_protocol: LinkProtocol,
    routes: tuple[AddressRoute, ...],
    *,
    axi_port: str = "s_axi",
    apb_port: str = "m_apb",
    profile: Axi4ToApbBridgeProfile | None = None,
    capabilities: Mapping[str, object] | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
) -> VirtualDut:
    """Build an equal-width AXI4-to-APB bridge network node.

    The current execution profile expands each complete AXI burst into
    full-width APB transfers, keeps one APB transfer active, and completes AXI
    parents in strict decoded-request FIFO order.  PPROT and PSTRB are required
    so protection and partial write strobes can cross the boundary.
    """

    if axi_protocol.family != AXI4_FAMILY:
        raise ValueError("bridge ingress requires an AXI4 LinkProtocol")
    if apb_protocol.family != APB_FAMILY:
        raise ValueError("bridge egress requires an APB LinkProtocol")
    if int(axi_protocol.parameters["data_width"]) != int(
        apb_protocol.parameters["data_width"]
    ):
        raise ValueError("current AXI4-to-APB bridge requires equal data widths")
    request_fields = set(apb_protocol.channels["READ"].event.fields)
    if "prot" not in request_fields:
        raise ValueError("bridge APB profile must expose PPROT as canonical prot")
    if "strb" not in apb_protocol.channels["WRITE"].event.fields:
        raise ValueError("bridge APB profile must expose PSTRB as canonical strb")
    if not routes:
        raise ValueError("AXI4-to-APB bridge requires an address route")
    if {item.egress_port for item in routes} != {apb_port}:
        raise ValueError(
            f"all bridge routes must select the sole APB port {apb_port!r}"
        )

    axi_limit = 1 << int(axi_protocol.parameters["address_width"])
    apb_limit = 1 << int(apb_protocol.parameters["address_width"])
    for route in routes:
        if route.limit_address > axi_limit:
            raise ValueError(
                f"route {route.name!r} input window exceeds AXI4 address width"
            )
        output_base = (
            route.base_address
            if route.output_base_address is None
            else route.output_base_address
        )
        if output_base + route.size_bytes > apb_limit:
            raise ValueError(
                f"route {route.name!r} output window exceeds APB address width"
            )

    capability_by_port = dict(capabilities or {})
    unknown = set(capability_by_port) - {axi_port, apb_port}
    if unknown:
        raise ValueError(
            f"capabilities reference unknown bridge ports {sorted(unknown)!r}"
        )
    storage_profile = profile or Axi4ToApbBridgeProfile()
    if not isinstance(storage_profile, Axi4ToApbBridgeProfile):
        raise TypeError("profile must be Axi4ToApbBridgeProfile")

    ingress_attachment = Axi4AddressSpaceAttachment(
        axi_protocol, byte_order=byte_order
    )
    egress_attachment = ApbRequesterAttachment(apb_protocol)
    ingress = PortAttachmentBinding(
        ProtocolPort(
            axi_port,
            axi_protocol,
            ingress_attachment.role,
            capability=capability_by_port.get(axi_port),
        ),
        ingress_attachment,
    )
    egress = PortAttachmentBinding(
        ProtocolPort(
            apb_port,
            apb_protocol,
            egress_attachment.role,
            capability=capability_by_port.get(apb_port),
        ),
        egress_attachment,
    )
    backend = Axi4ToApbBridgeBackend(
        ingress, egress, routes, storage_profile
    )
    return (
        VirtualDutBuilder(name)
        .bind(ingress)
        .bind(egress)
        .with_model(backend)
        .with_facets(DutFacet.TRANSFORMING, DutFacet.ROUTING)
        .describe(
            "bounded serialized AXI4 subordinate to APB requester burst bridge"
        )
        .build()
    )


__all__ = [
    "Axi4ToApbActive",
    "Axi4ToApbBridgeBackend",
    "Axi4ToApbBridgeProfile",
    "Axi4ToApbBridgeState",
    "build_axi4_to_apb_bridge_vdut",
]

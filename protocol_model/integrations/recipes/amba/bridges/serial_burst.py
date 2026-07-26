"""Composable full-AXI burst to AMBA address bridge construction."""

from __future__ import annotations

from typing import Mapping

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.axi.axi4 import AXI4_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.binding import InterfaceAttachmentBinding
from protocol_model.virtual_dut.boundary import InterfacePort, VirtualDut
from protocol_model.virtual_dut.fabric import AddressRoute
from protocol_model.virtual_dut.recipes.address_translation import (
    build_address_operation_translation_vdut,
)
from protocol_model.virtual_dut.translation import (
    AddressBurstRouteStage,
    AddressBurstShapeGuardStage,
    TranslationProfile,
    BurstToAccessStage,
    SerialExecutorProfile,
    SerialTranslationExecutor,
    compile_translation_plan,
)

from protocol_model.integrations.attachments.amba.axi.axi4.burst_translation import (
    Axi4BurstAssemblyProfile,
    Axi4BurstTranslationAttachment,
)

from protocol_model.integrations.translations.amba.address_attributes import (
    DecodeAmbaProtectionStage,
    EncodeAmbaProtectionStage,
    amba_raw_address_signature,
)

from ._address_recipe import (
    AMBA_ADDRESS_EGRESS_FAMILIES,
    amba_address_requester_attachment,
    amba_target_shape_stage,
    validate_amba_route_address_widths,
)


def build_amba_serial_burst_bridge_vdut(
    name: str,
    ingress_protocol: InterfaceProtocol,
    egress_protocol: InterfaceProtocol,
    routes: tuple[AddressRoute, ...],
    *,
    ingress_port: str = "ingress",
    egress_port: str = "egress",
    parent_capacity: int = 8,
    assembly_profile: Axi4BurstAssemblyProfile | None = None,
    axi_wire_id: int = 0,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
    capabilities: Mapping[str, object] | None = None,
) -> VirtualDut:
    """Build a strict-serial AXI4 burst bridge from reusable typed stages.

    The ingress profile currently accepts full AXI4.  Every burst is routed,
    remapped, and checked against the target access geometry before the first
    child can produce a downstream effect.  Fan-out then emits ordered single
    accesses through any AMBA requester attachment supported by the common
    address integration.

    This profile does not split one beat by width or sparse byte enable.  An
    unrepresentable target shape completes the whole parent locally with an
    access error.  Downstream errors discovered after issue cannot roll back
    already completed children.
    """

    if not isinstance(ingress_protocol, InterfaceProtocol) or not isinstance(
        egress_protocol, InterfaceProtocol
    ):
        raise TypeError("AMBA burst bridge requires two InterfaceProtocol values")
    if ingress_protocol.interface_family != AXI4_FAMILY:
        raise ValueError(
            "the current AMBA burst ingress codec requires full AXI4"
        )
    if egress_protocol.interface_family not in AMBA_ADDRESS_EGRESS_FAMILIES:
        raise ValueError(
            "no AMBA address requester for family "
            f"{egress_protocol.interface_family!r}"
        )
    if ingress_port == egress_port:
        raise ValueError("AMBA burst bridge ports must differ")
    if (
        not isinstance(parent_capacity, int)
        or isinstance(parent_capacity, bool)
        or parent_capacity <= 0
    ):
        raise ValueError("AMBA burst bridge parent capacity must be positive")

    capability_by_port = dict(capabilities or {})
    unknown = set(capability_by_port) - {ingress_port, egress_port}
    if unknown:
        raise ValueError(
            f"capabilities reference unknown bridge ports {sorted(unknown)!r}"
        )
    normalized_order = (
        byte_order
        if isinstance(byte_order, ByteOrder)
        else ByteOrder(byte_order)
    )

    ingress_attachment = Axi4BurstTranslationAttachment(
        ingress_protocol,
        byte_order=normalized_order,
        assembly_profile=assembly_profile,
    )
    egress_attachment = amba_address_requester_attachment(
        egress_protocol,
        normalized_order,
        axi_wire_id=axi_wire_id,
    )
    ingress = InterfaceAttachmentBinding(
        InterfacePort(
            ingress_port,
            ingress_protocol,
            ingress_attachment.role,
            capability=capability_by_port.get(ingress_port),
        ),
        ingress_attachment,
    )
    egress = InterfaceAttachmentBinding(
        InterfacePort(
            egress_port,
            egress_protocol,
            egress_attachment.role,
            capability=capability_by_port.get(egress_port),
        ),
        egress_attachment,
    )

    raw_source_access = amba_raw_address_signature(ingress_protocol)
    raw_target_access = amba_raw_address_signature(egress_protocol)
    route_stage = AddressBurstRouteStage(
        tuple(routes), signature=ingress_attachment.operation_signature
    )
    if route_stage.egress_port != egress_port:
        raise ValueError(
            "AMBA burst routes must select the configured egress port"
        )
    validate_amba_route_address_widths(
        route_stage.routes, ingress_protocol, egress_protocol
    )
    target_shape = amba_target_shape_stage(
        egress_protocol, name=f"shape_for_{egress_port}"
    )
    prefix = (
        route_stage,
        AddressBurstShapeGuardStage(
            target_shape,
            signature=ingress_attachment.operation_signature,
        ),
    )
    expansion = BurstToAccessStage(
        source=ingress_attachment.operation_signature,
        target=raw_source_access,
    )
    suffix = (
        DecodeAmbaProtectionStage(ingress_protocol),
        EncodeAmbaProtectionStage(egress_protocol),
    )
    plan = compile_translation_plan(
        TranslationProfile(
            f"{ingress_protocol.interface_family}_to_{egress_protocol.interface_family}.serial_burst",
            ingress_attachment.operation_signature,
            raw_target_access,
            provenance="integrations.amba.serial_burst_bridge",
        ),
        prefix_stages=prefix,
        expansion=expansion,
        suffix_stages=suffix,
    )
    executor = SerialTranslationExecutor(
        plan,
        SerialExecutorProfile(
            parent_capacity=parent_capacity,
            egress_binding=egress_port,
            parent_pool_name=f"{name}.parents",
            egress_pool_name=f"{name}.egress",
        ),
    )
    return build_address_operation_translation_vdut(
        name,
        ingress,
        egress,
        executor,
        description=(
            f"serial {ingress_protocol.name} burst to "
            f"{egress_protocol.name} typed address bridge"
        ),
    )


__all__ = ["build_amba_serial_burst_bridge_vdut"]

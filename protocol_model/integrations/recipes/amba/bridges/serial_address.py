"""Composable single-access AMBA bridge construction."""

from __future__ import annotations

from typing import Mapping

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.ahb import AHB_FAMILY
from protocol_model.protocols.amba.apb import APB_FAMILY
from protocol_model.protocols.amba.axi.axi4 import AXI4_FAMILY
from protocol_model.protocols.amba.axi.axi4_lite import AXI4_LITE_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.binding import InterfaceAttachmentBinding
from protocol_model.virtual_dut.boundary import InterfacePort, VirtualDut
from protocol_model.virtual_dut.fabric import AddressRoute
from protocol_model.virtual_dut.recipes.address_translation import (
    build_address_translation_vdut,
)
from protocol_model.virtual_dut.translation import (
    TranslationProfile,
    SerialExecutorProfile,
    SerialTranslationExecutor,
    compile_translation_plan,
)
from protocol_model.virtual_dut.translation.address import (
    AddressRouteStage,
)

from protocol_model.integrations.attachments.amba.ahb import (
    AhbCompleterAttachment,
)
from protocol_model.integrations.attachments.amba.apb import (
    ApbCompleterAttachment,
)
from protocol_model.integrations.attachments.amba.axi.axi4_lite import (
    Axi4LiteCompleterAttachment,
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


_SINGLE_ACCESS_INGRESS_FAMILIES = frozenset(
    (AXI4_LITE_FAMILY, AHB_FAMILY, APB_FAMILY)
)


def _ingress_attachment(
    protocol: InterfaceProtocol, byte_order: ByteOrder
):
    if protocol.interface_family == AXI4_LITE_FAMILY:
        return Axi4LiteCompleterAttachment(protocol, byte_order=byte_order)
    if protocol.interface_family == AHB_FAMILY:
        return AhbCompleterAttachment(protocol, byte_order=byte_order)
    if protocol.interface_family == APB_FAMILY:
        return ApbCompleterAttachment(protocol)
    if protocol.interface_family == AXI4_FAMILY:
        raise ValueError(
            "full AXI4 ingress produces bursts; use the burst translation profile"
        )
    raise ValueError(
        f"no single-access AMBA completer for family {protocol.interface_family!r}"
    )


def build_amba_serial_address_bridge_vdut(
    name: str,
    ingress_protocol: InterfaceProtocol,
    egress_protocol: InterfaceProtocol,
    routes: tuple[AddressRoute, ...],
    *,
    ingress_port: str = "ingress",
    egress_port: str = "egress",
    parent_capacity: int = 8,
    axi_wire_id: int = 0,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
    capabilities: Mapping[str, object] | None = None,
) -> VirtualDut:
    """Build one serial bridge from family codecs and reusable stages.

    The current profile accepts one ``AddressAccess`` at a time.  Full AXI4
    burst ingress follows a separate fan-out profile; unequal data widths need
    an explicit width stage.  Unsupported transfer shapes complete locally
    with an access error rather than failing inside a target attachment.
    """

    if not isinstance(ingress_protocol, InterfaceProtocol) or not isinstance(
        egress_protocol, InterfaceProtocol
    ):
        raise TypeError("AMBA address bridge requires two InterfaceProtocol values")
    if ingress_protocol.interface_family not in _SINGLE_ACCESS_INGRESS_FAMILIES:
        if ingress_protocol.interface_family == AXI4_FAMILY:
            raise ValueError(
                "full AXI4 ingress produces bursts; use the burst translation "
                "profile"
            )
        raise ValueError(
            "no single-access AMBA completer for family "
            f"{ingress_protocol.interface_family!r}"
        )
    if egress_protocol.interface_family not in AMBA_ADDRESS_EGRESS_FAMILIES:
        raise ValueError(
            "no single-access AMBA requester for family "
            f"{egress_protocol.interface_family!r}"
        )
    if ingress_port == egress_port:
        raise ValueError("AMBA bridge ingress and egress ports must differ")
    normalized_order = (
        byte_order
        if isinstance(byte_order, ByteOrder)
        else ByteOrder(byte_order)
    )
    ingress_width = int(ingress_protocol.parameters["data_width"])
    egress_width = int(egress_protocol.parameters["data_width"])
    if ingress_width != egress_width:
        raise ValueError(
            "serial address bridge requires equal data widths until a width "
            "translation stage is selected"
        )

    capability_by_port = dict(capabilities or {})
    unknown = set(capability_by_port) - {ingress_port, egress_port}
    if unknown:
        raise ValueError(
            f"capabilities reference unknown bridge ports {sorted(unknown)!r}"
        )

    ingress_attachment = _ingress_attachment(
        ingress_protocol, normalized_order
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

    route_stage = AddressRouteStage(tuple(routes))
    if route_stage.egress_port != egress_port:
        raise ValueError(
            "address bridge routes must select the configured egress port"
        )
    validate_amba_route_address_widths(
        route_stage.routes, ingress_protocol, egress_protocol
    )
    source_signature = amba_raw_address_signature(ingress_protocol)
    target_signature = amba_raw_address_signature(egress_protocol)
    stages = (
        DecodeAmbaProtectionStage(ingress_protocol),
        route_stage,
        amba_target_shape_stage(
            egress_protocol, name=f"shape_for_{egress_port}"
        ),
        EncodeAmbaProtectionStage(egress_protocol),
    )
    plan = compile_translation_plan(
        TranslationProfile(
            f"{ingress_protocol.interface_family}_to_{egress_protocol.interface_family}.serial_address",
            source_signature,
            target_signature,
            provenance="integrations.amba.serial_address_bridge",
        ),
        prefix_stages=stages,
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
    return build_address_translation_vdut(
        name,
        ingress,
        egress,
        executor,
        description=(
            f"serial {ingress_protocol.name} to {egress_protocol.name} "
            "typed address bridge"
        ),
    )


__all__ = ["build_amba_serial_address_bridge_vdut"]

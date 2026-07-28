"""AMBA attachment selection for queued address responders."""

from __future__ import annotations

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.ahb import AHB_FAMILY
from protocol_model.protocols.amba.apb import APB_FAMILY
from protocol_model.protocols.amba.axi.axi4_lite import AXI4_LITE_FAMILY
from protocol_model.virtual_dut.address import AddressTarget, ByteOrder
from protocol_model.virtual_dut.backend.queued_address import (
    AddressDelayPolicy,
)
from protocol_model.virtual_dut.binding import InterfaceAttachmentBinding
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort
from protocol_model.virtual_dut.recipes.queued_address import (
    build_queued_address_responder_vdut,
)
from protocol_model.semantics import ResourceExhaustionPolicy

from protocol_model.integrations.attachments.amba.ahb import (
    AhbCompleterAttachment,
)
from protocol_model.integrations.attachments.amba.apb import (
    ApbCompleterAttachment,
)
from protocol_model.integrations.attachments.amba.axi.axi4_lite import (
    Axi4LiteCompleterAttachment,
)


def build_amba_queued_address_responder_vdut(
    name: str,
    protocol: InterfaceProtocol,
    handler: AddressTarget,
    *,
    capacity: int,
    delay_policy: AddressDelayPolicy,
    exhaustion_policy: ResourceExhaustionPolicy | str = (
        ResourceExhaustionPolicy.BLOCK
    ),
    port_name: str = "bus",
    capability: object | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
) -> VirtualDut:
    """Bind one single-access AMBA completer to the queued backend.

    Full AXI4 ingress is intentionally absent because it produces grouped
    ``AddressBurst`` operations.  Its buffering and delay policy require the
    typed address-operation backend rather than this single-access queue.
    """

    normalized_order = (
        byte_order
        if isinstance(byte_order, ByteOrder)
        else ByteOrder(byte_order)
    )
    if protocol.interface_family == AXI4_LITE_FAMILY:
        attachment = Axi4LiteCompleterAttachment(
            protocol, byte_order=normalized_order
        )
    elif protocol.interface_family == AHB_FAMILY:
        attachment = AhbCompleterAttachment(
            protocol, byte_order=normalized_order
        )
    elif protocol.interface_family == APB_FAMILY:
        attachment = ApbCompleterAttachment(protocol)
    else:
        raise ValueError(
            "queued AMBA responder supports AXI4-Lite, AHB, and APB "
            "single-access attachments"
        )

    binding = InterfaceAttachmentBinding(
        InterfacePort(
            port_name,
            protocol,
            attachment.role,
            capability=capability,
        ),
        attachment,
    )
    return build_queued_address_responder_vdut(
        name,
        handler,
        {port_name: binding},
        capacity=capacity,
        delay_policy=delay_policy,
        exhaustion_policy=exhaustion_policy,
        description=(
            f"queued {protocol.name} address responder with explicit advance"
        ),
    )


__all__ = ["build_amba_queued_address_responder_vdut"]

"""AMBA attachment selection for an address-visible sensor FIFO."""

from __future__ import annotations

from protocol_model.integrations.attachments.amba.ahb import (
    AhbCompleterAttachment,
)
from protocol_model.integrations.attachments.amba.apb import (
    ApbCompleterAttachment,
)
from protocol_model.integrations.attachments.amba.axi.axi4_lite import (
    Axi4LiteCompleterAttachment,
)
from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.ahb import AHB_FAMILY
from protocol_model.protocols.amba.apb import APB_FAMILY
from protocol_model.protocols.amba.axi.axi4_lite import AXI4_LITE_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.backend.sensor_fifo import (
    SensorFifoConfig,
    SensorSamplePolicy,
)
from protocol_model.virtual_dut.binding import InterfaceAttachmentBinding
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort
from protocol_model.virtual_dut.recipes.sensor_fifo import (
    build_sensor_fifo_vdut,
)


def build_amba_sensor_fifo_vdut(
    name: str,
    protocol: InterfaceProtocol,
    config: SensorFifoConfig,
    sample_policy: SensorSamplePolicy,
    *,
    port_name: str = "bus",
    capability: object | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
) -> VirtualDut:
    """Construct an AXI4-Lite, AHB, or APB sensor data endpoint."""

    if not isinstance(protocol, InterfaceProtocol):
        raise TypeError("AMBA sensor FIFO requires an InterfaceProtocol")
    if not isinstance(config, SensorFifoConfig):
        raise TypeError("AMBA sensor FIFO requires SensorFifoConfig")
    if protocol.interface_family not in {
        AXI4_LITE_FAMILY,
        AHB_FAMILY,
        APB_FAMILY,
    }:
        raise ValueError(
            "sensor FIFO supports AXI4-Lite, AHB, and APB completer "
            "attachments; full AXI4 is not part of this single-access recipe"
        )
    normalized_order = (
        byte_order
        if isinstance(byte_order, ByteOrder)
        else ByteOrder(byte_order)
    )
    bus_bytes = int(protocol.parameters.get("data_width", 0)) // 8
    address_width = int(protocol.parameters.get("address_width", 0))
    if address_width <= 0:
        raise ValueError("AMBA sensor FIFO requires a positive address width")
    if config.data_address + config.sample_bytes > 1 << address_width:
        raise ValueError(
            "sensor FIFO data register exceeds the protocol address space"
        )
    if protocol.interface_family == AXI4_LITE_FAMILY:
        if config.sample_bytes != bus_bytes:
            raise ValueError(
                "AXI4-Lite sensor sample size must equal the data bus width"
            )
        attachment = Axi4LiteCompleterAttachment(
            protocol, byte_order=normalized_order
        )
    elif protocol.interface_family == AHB_FAMILY:
        if config.sample_bytes > bus_bytes:
            raise ValueError(
                "AHB sensor sample size cannot exceed the data bus width"
            )
        attachment = AhbCompleterAttachment(
            protocol, byte_order=normalized_order
        )
    elif protocol.interface_family == APB_FAMILY:
        if config.sample_bytes != bus_bytes:
            raise ValueError(
                "APB sensor sample size must equal the data bus width"
            )
        attachment = ApbCompleterAttachment(protocol)
    else:
        raise ValueError("validated AMBA sensor family was lost")

    binding = InterfaceAttachmentBinding(
        InterfacePort(
            port_name,
            protocol,
            attachment.role,
            capability=capability,
        ),
        attachment,
    )
    return build_sensor_fifo_vdut(
        name,
        binding,
        config,
        sample_policy,
        description=f"{protocol.name} address-visible sensor FIFO",
    )


__all__ = ["build_amba_sensor_fifo_vdut"]

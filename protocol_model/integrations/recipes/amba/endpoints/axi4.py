"""AXI4-bound AddressSpace endpoint VirtualDut recipe."""

from __future__ import annotations

from typing import Hashable

from protocol_model.interface import InterfaceProtocol
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.address.space import AddressSpace
from protocol_model.virtual_dut.backend.stepped_emission import (
    SteppedEmissionBackend,
    SteppedEmissionProfile,
)
from protocol_model.virtual_dut.backend.transition import PortEmission
from protocol_model.virtual_dut.binding import InterfaceAttachmentBinding, VirtualDutBuilder
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort

from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4AddressSpaceAttachment,
)

from protocol_model.integrations.backends.amba.axi.axi4.address_space import (
    Axi4AddressSpaceBackend,
)


def _axi4_response_ordering_key(
    events: tuple[PortEmission, ...],
) -> Hashable:
    """Keep later same-ID AXI completions behind the earlier transaction."""

    first = events[0].event
    if first.kind not in {"R", "B"}:
        raise ValueError(
            "AXI4 stepped response backend only schedules R/B completions"
        )
    expected = (events[0].port, first.kind, first.key)
    if any(
        (item.port, item.event.kind, item.event.key) != expected
        for item in events
    ):
        raise ValueError(
            "one AXI4 response batch must retain one channel kind and ID"
        )
    return expected


def build_axi4_address_space_vdut(
    name: str,
    protocol: InterfaceProtocol,
    address_space: AddressSpace,
    *,
    port_name: str = "axi",
    capability: object | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
    response_profile: SteppedEmissionProfile | None = None,
) -> VirtualDut:
    """Construct one burst-aware normal-access AXI4 subordinate endpoint.

    With no ``response_profile``, the endpoint returns the abstract completion
    batch immediately.  A stepped profile places the R/B events in a finite
    output FIFO and releases at most one event per explicit advance.  This can
    express event-level response gaps without claiming an AXI pin/cycle driver.
    A round-robin stepped profile can interleave R beats from different IDs;
    the recipe supplies the AXI ordering key so same-ID bursts remain ordered.
    """

    attachment = Axi4AddressSpaceAttachment(
        protocol, byte_order=byte_order
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
    immediate_backend = Axi4AddressSpaceBackend(address_space, binding)
    backend = (
        immediate_backend
        if response_profile is None
        else SteppedEmissionBackend(
            immediate_backend,
            response_profile,
            batch_ordering_key=_axi4_response_ordering_key,
        )
    )
    return (
        VirtualDutBuilder(name)
        .bind(binding)
        .with_backend(backend)
        .describe(
            "burst-aware AXI4 AddressSpace endpoint"
            + (
                " with caller-stepped R/B emission"
                if response_profile is not None
                else ""
            )
        )
        .build()
    )

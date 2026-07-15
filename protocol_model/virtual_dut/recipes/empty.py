"""Protocol-independent recipes for explicitly empty endpoints."""

from __future__ import annotations

from protocol_model.link import LinkProtocol

from ..attachments.empty import EmptyEndpointAttachment, EmptyEndpointMode
from ..backend.simple import NoOpModel
from ..binding import PortAttachmentBinding, VirtualDutBuilder
from ..boundary.module import VirtualDut
from ..boundary.port import ProtocolPort


def _build_empty_endpoint(
    name: str,
    protocol: LinkProtocol,
    role: str,
    mode: EmptyEndpointMode,
    *,
    port_name: str,
    capability: object | None,
) -> VirtualDut:
    attachment = EmptyEndpointAttachment(protocol, role, mode)
    binding = PortAttachmentBinding(
        ProtocolPort(
            port_name,
            protocol,
            role,
            capability=capability,
        ),
        attachment,
    )
    description = (
        "idle source endpoint with no autonomous emissions"
        if mode is EmptyEndpointMode.IDLE_SOURCE
        else "blackhole sink that consumes input without completion"
    )
    return (
        VirtualDutBuilder(name)
        .bind(binding)
        .with_model(NoOpModel())
        .describe(description)
        .build()
    )


def build_idle_source_vdut(
    name: str,
    protocol: LinkProtocol,
    role: str,
    *,
    port_name: str = "link",
    capability: object | None = None,
) -> VirtualDut:
    """Build a source-side endpoint whose backend never initiates activity."""

    return _build_empty_endpoint(
        name,
        protocol,
        role,
        EmptyEndpointMode.IDLE_SOURCE,
        port_name=port_name,
        capability=capability,
    )


def build_blackhole_sink_vdut(
    name: str,
    protocol: LinkProtocol,
    role: str,
    *,
    port_name: str = "link",
    capability: object | None = None,
) -> VirtualDut:
    """Build a sink that intentionally consumes without producing completion."""

    return _build_empty_endpoint(
        name,
        protocol,
        role,
        EmptyEndpointMode.BLACKHOLE_SINK,
        port_name=port_name,
        capability=capability,
    )

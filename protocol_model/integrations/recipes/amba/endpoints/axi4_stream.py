"""AXI4-Stream-bound endpoint VirtualDut recipes."""

from __future__ import annotations

from protocol_model.link import LinkProtocol
from protocol_model.virtual_dut.backend.stream import StreamCaptureBackend
from protocol_model.virtual_dut.binding import PortAttachmentBinding, VirtualDutBuilder
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import ProtocolPort

from protocol_model.integrations.attachments.amba.axi.axi4_stream import (
    Axi4StreamReceiverAttachment,
)


def build_axi4_stream_capture_vdut(
    name: str,
    protocol: LinkProtocol,
    *,
    port_name: str = "stream",
    capability: object | None = None,
) -> VirtualDut:
    """Construct a receiver that retains normalized stream transfers."""

    attachment = Axi4StreamReceiverAttachment(protocol)
    binding = PortAttachmentBinding(
        ProtocolPort(
            port_name,
            protocol,
            attachment.role,
            capability=capability,
        ),
        attachment,
    )
    backend = StreamCaptureBackend({binding.name: binding})
    return (
        VirtualDutBuilder(name)
        .bind(binding)
        .with_model(backend)
        .describe("AXI4-Stream receiver capture endpoint")
        .build()
    )

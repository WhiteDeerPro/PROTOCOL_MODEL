"""Shared checks for AXI4-Stream VirtualDut attachments."""

from __future__ import annotations

from protocol_model.link import LinkProtocol
from protocol_model.link.amba.axi.axi4_stream import AXI4_STREAM_FAMILY


def require_axi4_stream_role(protocol: LinkProtocol, role: str) -> None:
    if protocol.family != AXI4_STREAM_FAMILY:
        raise ValueError(
            "AXI4-Stream attachment requires protocol family "
            f"{AXI4_STREAM_FAMILY!r}, got {protocol.family!r}"
        )
    if role not in protocol.roles:
        raise ValueError(
            f"AXI4-Stream protocol has no role {role!r}"
        )
    if set(protocol.channels) != {"T"}:
        raise ValueError("AXI4-Stream attachment requires one T channel")
    required = {
        "data_width",
        "id_width",
        "dest_width",
        "user_width",
        "use_keep",
        "use_strb",
        "use_last",
    }
    missing = required - set(protocol.parameters)
    if missing:
        raise ValueError(
            "AXI4-Stream protocol is missing parameters "
            f"{sorted(missing)!r}"
        )

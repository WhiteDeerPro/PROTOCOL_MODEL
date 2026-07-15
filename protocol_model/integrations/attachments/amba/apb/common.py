"""State and validation shared by APB address attachments."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import LinkProtocol
from protocol_model.link.amba.apb import APB_FAMILY


@dataclass(frozen=True)
class ApbAccessContext:
    request_kind: str


def require_apb_role(protocol: LinkProtocol, role: str) -> None:
    """Reject a non-APB transport or a role absent from its declaration."""

    if protocol.family != APB_FAMILY:
        raise ValueError("APB attachment requires an APB LinkProtocol family")
    if role not in protocol.roles:
        raise ValueError(f"APB protocol has no {role} role")

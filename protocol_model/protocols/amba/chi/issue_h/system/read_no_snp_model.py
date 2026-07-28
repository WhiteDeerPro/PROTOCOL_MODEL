"""Public actions, state, and evidence for the restricted CHI read runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from ..interface import (
    ChiReadNoSnpLedgerState,
    ChiReadNoSnpResult,
)
from ..participants import ChiDirectHomeState
from ..representation import ChiNetworkPacket, ChiReadNoSnpMessage
from .network import ChiNetworkEvent, ChiTransportNetworkState


@dataclass(frozen=True)
class ChiSubmitRead:
    """Submit one ReadNoSnp through a named requester participant."""

    requester: str
    request: ChiReadNoSnpMessage

    def __post_init__(self) -> None:
        if not isinstance(self.requester, str) or not self.requester:
            raise ValueError("CHI read submission requires a requester name")
        if not isinstance(self.request, ChiReadNoSnpMessage):
            raise TypeError("CHI read submission requires ChiReadNoSnpMessage")


@dataclass(frozen=True)
class ChiAdvanceReadNetwork:
    """Let the reference scheduler commit at most one internal microstep."""


ChiReadNoSnpSystemAction = ChiSubmitRead | ChiAdvanceReadNetwork


class ChiReadNoSnpSystemEventKind(str, Enum):
    ISSUE = "issue"
    NETWORK = "network"
    HOME_ACCEPT = "home_accept"
    HOME_SERVICE = "home_service"
    COMPLETE = "complete"
    HOME_RETRY_ACK = "home_retry_ack"
    HOME_PCREDIT_GRANT = "home_pcredit_grant"
    REQUESTER_RSP = "requester_rsp"
    RETRY = "retry"
    REQUESTER_PCREDIT_RETURN = "requester_pcredit_return"
    HOME_PCREDIT_RETURN = "home_pcredit_return"


@dataclass(frozen=True)
class ChiReadNoSnpSystemEvent:
    """One committed composite action or one underlying network action."""

    kind: ChiReadNoSnpSystemEventKind
    participant: str = ""
    connection: str = ""
    packet: ChiNetworkPacket | None = None
    lineage: tuple[str, ...] = ()
    result: ChiReadNoSnpResult | None = None
    detail: ChiNetworkEvent | None = None


@dataclass(frozen=True)
class ChiReadNoSnpSystemState:
    """Protocol, participant, network, and scheduler state for one session."""

    network: ChiTransportNetworkState
    requester: ChiReadNoSnpLedgerState
    home: ChiDirectHomeState
    home_lineage_by_request: Mapping[int, tuple[str, ...]] = field(
        default_factory=dict
    )
    scheduler_cursor: int = 0
    committed_microsteps: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "home_lineage_by_request",
            MappingProxyType(
                {
                    key: tuple(lineage)
                    for key, lineage in self.home_lineage_by_request.items()
                }
            ),
        )


__all__ = [
    "ChiAdvanceReadNetwork",
    "ChiReadNoSnpSystemAction",
    "ChiReadNoSnpSystemEvent",
    "ChiReadNoSnpSystemEventKind",
    "ChiReadNoSnpSystemState",
    "ChiSubmitRead",
]

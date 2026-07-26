"""Values describing the first directed CHI Issue H transport slice."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from protocol_model.system.topology.model import VirtualDutPortRef

from ..representation import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiChannelKind,
    ChiDatLCrdReturn,
    ChiIssueHReqProfile,
    ChiIssueHDatProfile,
    ChiIssueHRspProfile,
    ChiIssueHSnpProfile,
    ChiChannelClassification,
    ChiProtocolFlit,
    ChiReqLCrdReturn,
    ChiRspLCrdReturn,
    ChiSnpLCrdReturn,
)


CHI_ISSUE_H_TRANSPORT_FAMILY = "amba.chi.issue_h"


def _classify_channel_payload(
    payload: object,
    expected: ChiChannelKind,
) -> ChiChannelClassification:
    """Classify one flit and require the channel carried by this link lane."""

    classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(payload)
    if classification.channel is not expected:
        raise TypeError(
            f"{expected.name} link requires a {expected.name}-channel flit"
        )
    if classification.is_message:
        raise TypeError(
            "CHI protocol message must be packetized and wrapped as "
            "ChiProtocolFlit before it crosses a Link"
        )
    if classification.is_protocol_flit and not isinstance(
        payload, ChiProtocolFlit
    ):
        raise TypeError("CHI protocol Link carrier must be ChiProtocolFlit")
    return classification


ChiReqTransportFlit = ChiProtocolFlit | ChiReqLCrdReturn
ChiRspTransportFlit = ChiProtocolFlit | ChiRspLCrdReturn
ChiSnpTransportFlit = ChiProtocolFlit | ChiSnpLCrdReturn
ChiDatTransportFlit = ChiProtocolFlit | ChiDatLCrdReturn


class ChiLinkActivationPhase(str, Enum):
    """State encoded by LINKACTIVEREQ and LINKACTIVEACK."""

    STOP = "stop_00"
    ACTIVATE = "activate_10"
    RUN = "run_11"
    DEACTIVATE = "deactivate_01"

    @classmethod
    def from_signals(
        cls, request: bool, acknowledge: bool
    ) -> "ChiLinkActivationPhase":
        if type(request) is not bool or type(acknowledge) is not bool:
            raise TypeError("LINKACTIVEREQ and LINKACTIVEACK must be bool")
        return {
            (False, False): cls.STOP,
            (True, False): cls.ACTIVATE,
            (True, True): cls.RUN,
            (False, True): cls.DEACTIVATE,
        }[(request, acknowledge)]


@dataclass(frozen=True)
class ChiLinkActivationSignals:
    """One common-edge observation of the link-wide activation sideband.

    The first slice models a synchronous component-boundary observation.  It
    does not yet model the asynchronous propagation race in which a credit can
    reach a Transmitter before the corresponding LINKACTIVEACK observation.
    """

    request: bool
    acknowledge: bool

    def __post_init__(self) -> None:
        if type(self.request) is not bool or type(self.acknowledge) is not bool:
            raise TypeError("LINKACTIVEREQ and LINKACTIVEACK must be bool")

    @property
    def phase(self) -> ChiLinkActivationPhase:
        return ChiLinkActivationPhase.from_signals(
            self.request, self.acknowledge
        )


# CHI transport and SystemProtocol share one endpoint identity.  The family
# name remains as a readable public alias for link-local code.
ChiLinkEndpointRef = VirtualDutPortRef


@dataclass(frozen=True)
class ChiReqChannelProfile:
    """Capability of the dedicated-credit REQ channel in this slice."""

    representation: ChiIssueHReqProfile = field(
        default_factory=ChiIssueHReqProfile
    )
    credit_capacities: tuple[int, ...] = (1,)
    observation: str = "chi.req"

    def __post_init__(self) -> None:
        capacities = tuple(self.credit_capacities)
        if not 1 <= len(capacities) <= 8:
            raise ValueError("REQ Resource Plane count must be in 1..8")
        if any(
            not isinstance(item, int)
            or isinstance(item, bool)
            or not 1 <= item <= 15
            for item in capacities
        ):
            raise ValueError(
                "each dedicated REQ L-Credit capacity must be in 1..15"
            )
        if not self.observation:
            raise ValueError("REQ channel requires an observation name")
        object.__setattr__(self, "credit_capacities", capacities)

    @property
    def resource_planes(self) -> int:
        return len(self.credit_capacities)


@dataclass(frozen=True)
class ChiDatChannelProfile:
    """Capability of the dedicated-credit DAT channel in this slice."""

    representation: ChiIssueHDatProfile = field(
        default_factory=ChiIssueHDatProfile
    )
    credit_capacity: int = 1
    observation: str = "chi.dat"

    def __post_init__(self) -> None:
        if not isinstance(self.representation, ChiIssueHDatProfile):
            raise TypeError("DAT channel representation profile is invalid")
        if (
            not isinstance(self.credit_capacity, int)
            or isinstance(self.credit_capacity, bool)
            or not 1 <= self.credit_capacity <= 15
        ):
            raise ValueError("dedicated DAT L-Credit capacity must be in 1..15")
        if not self.observation:
            raise ValueError("DAT channel requires an observation name")


@dataclass(frozen=True)
class ChiRspChannelProfile:
    """Capability of the dedicated-credit RSP channel in this slice."""

    representation: ChiIssueHRspProfile = field(
        default_factory=ChiIssueHRspProfile
    )
    credit_capacity: int = 1
    observation: str = "chi.rsp"

    def __post_init__(self) -> None:
        if not isinstance(self.representation, ChiIssueHRspProfile):
            raise TypeError("RSP channel representation profile is invalid")
        if (
            not isinstance(self.credit_capacity, int)
            or isinstance(self.credit_capacity, bool)
            or not 1 <= self.credit_capacity <= 15
        ):
            raise ValueError("dedicated RSP L-Credit capacity must be in 1..15")
        if not self.observation:
            raise ValueError("RSP channel requires an observation name")


@dataclass(frozen=True)
class ChiSnpChannelProfile:
    """Capability of the dedicated-credit SNP channel in this slice."""

    representation: ChiIssueHSnpProfile = field(
        default_factory=ChiIssueHSnpProfile
    )
    credit_capacity: int = 1
    observation: str = "chi.snp"

    def __post_init__(self) -> None:
        if not isinstance(self.representation, ChiIssueHSnpProfile):
            raise TypeError("SNP channel representation profile is invalid")
        if (
            not isinstance(self.credit_capacity, int)
            or isinstance(self.credit_capacity, bool)
            or not 1 <= self.credit_capacity <= 15
        ):
            raise ValueError("dedicated SNP L-Credit capacity must be in 1..15")
        if not self.observation:
            raise ValueError("SNP channel requires an observation name")


@dataclass(frozen=True)
class ChiTransportLinkProfile:
    """Link-wide timing plus the channel capabilities currently implemented."""

    request: ChiReqChannelProfile | None = field(
        default_factory=ChiReqChannelProfile
    )
    data: ChiDatChannelProfile | None = None
    response: ChiRspChannelProfile | None = None
    snoop: ChiSnpChannelProfile | None = None
    clock: str = "clk"
    activation_observation: str = "chi.link"

    def __post_init__(self) -> None:
        if self.request is not None and not isinstance(
            self.request, ChiReqChannelProfile
        ):
            raise TypeError("CHI link request profile has an invalid type")
        if self.data is not None and not isinstance(
            self.data, ChiDatChannelProfile
        ):
            raise TypeError("CHI link data profile has an invalid type")
        if self.response is not None and not isinstance(
            self.response, ChiRspChannelProfile
        ):
            raise TypeError("CHI link response profile has an invalid type")
        if self.snoop is not None and not isinstance(
            self.snoop, ChiSnpChannelProfile
        ):
            raise TypeError("CHI link snoop profile has an invalid type")
        if (
            self.request is None
            and self.data is None
            and self.response is None
            and self.snoop is None
        ):
            raise ValueError("CHI link profile requires an implemented channel")
        if not self.clock or not self.activation_observation:
            raise ValueError("CHI link requires clock and activation observation")
        observations = [self.activation_observation]
        if self.request is not None:
            observations.append(self.request.observation)
        if self.data is not None:
            observations.append(self.data.observation)
        if self.response is not None:
            observations.append(self.response.observation)
        if self.snoop is not None:
            observations.append(self.snoop.observation)
        if len(set(observations)) != len(observations):
            raise ValueError("CHI link observation names must be distinct")


@dataclass(frozen=True)
class ChiReqChannelSignals:
    """One normalized, simultaneous sample of the REQ channel.

    A valid flit carries a typed value, while an invalid lane carries none.
    ``lcrdv_by_plane`` records dedicated credit grants observed in the same
    frame.  Link-wide activation is deliberately sampled separately.
    """

    flit_valid: bool = False
    flit: ChiReqTransportFlit | None = None
    resource_plane: int = 0
    lcrdv_by_plane: tuple[bool, ...] = (False,)

    def __post_init__(self) -> None:
        if type(self.flit_valid) is not bool:
            raise TypeError("flit_valid must be bool")
        grants = tuple(self.lcrdv_by_plane)
        if any(type(item) is not bool for item in grants):
            raise TypeError("lcrdv_by_plane entries must be bool")
        if not isinstance(self.resource_plane, int) or isinstance(
            self.resource_plane, bool
        ):
            raise TypeError("resource_plane must be an integer")
        if self.flit_valid != (self.flit is not None):
            raise ValueError("flit_valid must agree with presence of a typed flit")
        if self.flit is not None:
            _classify_channel_payload(self.flit, ChiChannelKind.REQ)
        object.__setattr__(self, "lcrdv_by_plane", grants)


@dataclass(frozen=True)
class ChiDatChannelSignals:
    """One normalized, simultaneous sample of the DAT channel."""

    flit_valid: bool = False
    flit: ChiDatTransportFlit | None = None
    lcrdv: bool = False

    def __post_init__(self) -> None:
        if type(self.flit_valid) is not bool or type(self.lcrdv) is not bool:
            raise TypeError("DAT FLITV and LCRDV must be bool")
        if self.flit_valid != (self.flit is not None):
            raise ValueError("flit_valid must agree with presence of a DAT flit")
        if self.flit is not None:
            _classify_channel_payload(self.flit, ChiChannelKind.DAT)


@dataclass(frozen=True)
class ChiRspChannelSignals:
    """One normalized, simultaneous sample of the RSP channel."""

    flit_valid: bool = False
    flit: ChiRspTransportFlit | None = None
    lcrdv: bool = False

    def __post_init__(self) -> None:
        if type(self.flit_valid) is not bool or type(self.lcrdv) is not bool:
            raise TypeError("RSP FLITV and LCRDV must be bool")
        if self.flit_valid != (self.flit is not None):
            raise ValueError("flit_valid must agree with presence of a RSP flit")
        if self.flit is not None:
            _classify_channel_payload(self.flit, ChiChannelKind.RSP)


@dataclass(frozen=True)
class ChiSnpChannelSignals:
    """One normalized, simultaneous sample of the SNP channel."""

    flit_valid: bool = False
    flit: ChiSnpTransportFlit | None = None
    lcrdv: bool = False

    def __post_init__(self) -> None:
        if type(self.flit_valid) is not bool or type(self.lcrdv) is not bool:
            raise TypeError("SNP FLITV and LCRDV must be bool")
        if self.flit_valid != (self.flit is not None):
            raise ValueError("flit_valid must agree with presence of a SNP flit")
        if self.flit is not None:
            _classify_channel_payload(self.flit, ChiChannelKind.SNP)


class ChiReqTransferKind(str, Enum):
    PROTOCOL = "protocol"
    LINK_CREDIT_RETURN = "link_credit_return"


@dataclass(frozen=True)
class ChiReqTransfer:
    """One REQ flit accepted by the adjacent receiver."""

    link: str
    flit: ChiReqTransportFlit
    resource_plane: int
    tick: int

    @property
    def kind(self) -> ChiReqTransferKind:
        classification = _classify_channel_payload(
            self.flit,
            ChiChannelKind.REQ,
        )
        if classification.is_link_maintenance:
            return ChiReqTransferKind.LINK_CREDIT_RETURN
        return ChiReqTransferKind.PROTOCOL


class ChiDatTransferKind(str, Enum):
    PROTOCOL = "protocol"
    LINK_CREDIT_RETURN = "link_credit_return"


@dataclass(frozen=True)
class ChiDatTransfer:
    """One DAT flit accepted by the adjacent receiver."""

    link: str
    flit: ChiDatTransportFlit
    tick: int

    @property
    def kind(self) -> ChiDatTransferKind:
        classification = _classify_channel_payload(
            self.flit,
            ChiChannelKind.DAT,
        )
        if classification.is_link_maintenance:
            return ChiDatTransferKind.LINK_CREDIT_RETURN
        return ChiDatTransferKind.PROTOCOL


class ChiRspTransferKind(str, Enum):
    PROTOCOL = "protocol"
    LINK_CREDIT_RETURN = "link_credit_return"


@dataclass(frozen=True)
class ChiRspTransfer:
    """One RSP flit accepted by the adjacent receiver."""

    link: str
    flit: ChiRspTransportFlit
    tick: int

    @property
    def kind(self) -> ChiRspTransferKind:
        classification = _classify_channel_payload(
            self.flit,
            ChiChannelKind.RSP,
        )
        if classification.is_link_maintenance:
            return ChiRspTransferKind.LINK_CREDIT_RETURN
        return ChiRspTransferKind.PROTOCOL


class ChiSnpTransferKind(str, Enum):
    PROTOCOL = "protocol"
    LINK_CREDIT_RETURN = "link_credit_return"


@dataclass(frozen=True)
class ChiSnpTransfer:
    """One SNP flit accepted by the adjacent receiver."""

    link: str
    flit: ChiSnpTransportFlit
    tick: int

    @property
    def kind(self) -> ChiSnpTransferKind:
        classification = _classify_channel_payload(
            self.flit,
            ChiChannelKind.SNP,
        )
        if classification.is_link_maintenance:
            return ChiSnpTransferKind.LINK_CREDIT_RETURN
        return ChiSnpTransferKind.PROTOCOL


ChiTransportTransfer = (
    ChiReqTransfer | ChiDatTransfer | ChiRspTransfer | ChiSnpTransfer
)


@dataclass(frozen=True)
class ChiTransportLink:
    """One directed TX-to-RX link with executable channel subsets.

    Activation belongs to this link rather than an individual channel.  REQ,
    RSP, SNP, and DAT state therefore share one atomic activation authority
    when they are configured on the same directed link.
    """

    name: str
    transmitter: ChiLinkEndpointRef
    receiver: ChiLinkEndpointRef
    profile: ChiTransportLinkProfile = field(
        default_factory=ChiTransportLinkProfile
    )

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("CHI transport link requires a name")
        if self.transmitter == self.receiver:
            raise ValueError("CHI transport link endpoints must be distinct")

    def open_session(self):
        from .session import ChiTransportLinkSession

        return ChiTransportLinkSession(self)


__all__ = [
    "CHI_ISSUE_H_TRANSPORT_FAMILY",
    "ChiLinkActivationPhase",
    "ChiLinkActivationSignals",
    "ChiLinkEndpointRef",
    "ChiDatChannelProfile",
    "ChiDatChannelSignals",
    "ChiDatTransfer",
    "ChiDatTransferKind",
    "ChiReqChannelProfile",
    "ChiReqChannelSignals",
    "ChiReqTransfer",
    "ChiReqTransferKind",
    "ChiRspChannelProfile",
    "ChiRspChannelSignals",
    "ChiRspTransfer",
    "ChiRspTransferKind",
    "ChiSnpChannelProfile",
    "ChiSnpChannelSignals",
    "ChiSnpTransfer",
    "ChiSnpTransferKind",
    "ChiTransportLink",
    "ChiTransportLinkProfile",
    "ChiTransportTransfer",
]

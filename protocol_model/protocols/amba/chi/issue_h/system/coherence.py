"""Packet-delivery composition for the executable CHI coherence profiles.

The transport network owns how a packet reaches its destination.  This module
starts at the next boundary: a delivered packet is dispatched to the Home or
Request Node that owns the corresponding protocol state.  Emitted packets can
then be passed back through any compatible ``ChiTransportNetworkSession``.

The profile is intentionally narrow.  It closes clean ``ReadShared`` and
``ReadUnique`` lifecycles, clean- and restricted shared-dirty-peer
``CleanUnique`` permission upgrades, the ``UD`` owner-transfer path for
``ReadUnique``, the MESI no-SharedDirty ``ReadNotSharedDirty`` downgrade path,
clean ``Evict``, explicit ``UD`` ``WriteBackFull``, a
``WriteEvictFull(CAH=0)`` transfer into Snoop-domain clean residency and its
pre-DBID invalidating-Snoop cancellation, the two Home-selected
``WriteEvictOrEvict(CAH=0)`` completion branches, one
successful clean ``ReadUnique`` or clean ``Evict`` Request-Retry cycle, a
pre-snoop ``ReadUnique`` NDERR completion, and their
narrow composition with an independent same-line Snoop while the Requester
waits for P-Credit.  The ``SD`` state exists only for the CleanUnique
memory-update slice; general shared-dirty behavior, post-snoop errors,
automatic victim selection, post-DBID CopyBack/Snoop composition, forwarding
snoops, and packed pin observations remain separate extensions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.system.contracts.address import AddressWindow

from ..interface.request_retry import ChiRequestRetryPhase
from ..participants.coherence import (
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiCoherentHomeState,
    ChiCoherentRnNode,
    ChiCoherentRnState,
    ChiHomeAcceptCleanUnique,
    ChiHomeAcceptCompAck,
    ChiHomeAcceptCopyBackData,
    ChiHomeAcceptCoherentRead,
    ChiHomeAcceptEvict,
    ChiHomeAcceptMakeUnique,
    ChiHomeAcceptSnoopResponse,
    ChiHomeAcceptWriteEvictFull,
    ChiHomeAcceptWriteEvictOrEvict,
    ChiHomeAcceptWriteBackFull,
    ChiHomeGrantPCredit,
    ChiHomeWriteEvictPending,
    ChiHomeWriteEvictOrEvictPending,
    ChiHomeCopyBackAdmission,
    ChiHomeWriteBackPending,
    ChiRnAcceptComp,
    ChiRnAcceptCompDBIDResp,
    ChiRnAcceptCompData,
    ChiRnAcceptPCrdGrant,
    ChiRnAcceptRetryAck,
    ChiRnAcceptSnoop,
    ChiRnIssueCleanUnique,
    ChiRnIssueCoherentRead,
    ChiRnIssueEvict,
    ChiRnIssueMakeUnique,
    ChiRnIssueWriteEvictFull,
    ChiRnIssueWriteEvictOrEvict,
    ChiRnIssueWriteBackFull,
    ChiRnRetryCoherentRequest,
    ChiRnCopyBackOutcome,
    ChiRnWriteEvictPending,
    ChiRnWriteEvictOrEvictPending,
    ChiRnWriteBackPending,
    ChiRnWriteCacheLine,
    ChiWriteEvictOrEvictDecision,
)
from ..participants.progress import chi_line_resource_name
from ..representation.dat import (
    ChiCompDataMessage,
    ChiCopyBackWrDataMessage,
    ChiSnpRespDataMessage,
)
from ..representation.packet import ChiNetworkPacket
from ..representation.req import (
    ChiCleanUniqueMessage,
    ChiEvictMessage,
    ChiMakeUniqueMessage,
    ChiReadNotSharedDirtyMessage,
    ChiReadSharedMessage,
    ChiReadUniqueMessage,
    ChiWriteBackFullMessage,
    ChiWriteEvictFullMessage,
    ChiWriteEvictOrEvictMessage,
)
from ..representation.response import ChiRespCode, ChiRespErr
from ..representation.rsp import (
    ChiCompAckMessage,
    ChiCompDBIDRespMessage,
    ChiCompMessage,
    ChiPCrdGrantMessage,
    ChiRetryAckMessage,
    ChiSnpRespMessage,
)
from ..representation.snp import (
    ChiSnpCleanInvalidMessage,
    ChiSnpMakeInvalidMessage,
    ChiSnpNotSharedDirtyMessage,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
)
from .capability import (
    CHI_FEATURE_CLEAN_EVICT,
    CHI_FEATURE_CLEAN_EVICT_RETRY,
    CHI_FEATURE_CLEAN_READ_SHARED,
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR,
    CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
    CHI_FEATURE_DIRTY_WRITEBACK,
    CHI_FEATURE_MAKE_UNIQUE,
    CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
    CHI_FEATURE_WRITE_EVICT_FULL,
    CHI_FEATURE_WRITE_EVICT_OR_EVICT,
    ChiFeatureKey,
)


_CLEAN_READ_FEATURES = frozenset(
    (
        CHI_FEATURE_CLEAN_READ_SHARED,
        CHI_FEATURE_CLEAN_READ_UNIQUE,
    )
)
_COHERENCE_FEATURES = frozenset(
    (
        *_CLEAN_READ_FEATURES,
        CHI_FEATURE_CLEAN_EVICT,
        CHI_FEATURE_CLEAN_EVICT_RETRY,
        CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
        CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR,
        CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
        CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
        CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
        CHI_FEATURE_DIRTY_WRITEBACK,
        CHI_FEATURE_MAKE_UNIQUE,
        CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
        CHI_FEATURE_WRITE_EVICT_FULL,
        CHI_FEATURE_WRITE_EVICT_OR_EVICT,
    )
)
_COHERENCE_RETRY_FEATURES = frozenset(
    (
        CHI_FEATURE_CLEAN_EVICT_RETRY,
        CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
    )
)
_COHERENCE_SNOOP_TYPES = (
    ChiSnpCleanInvalidMessage,
    ChiSnpMakeInvalidMessage,
    ChiSnpNotSharedDirtyMessage,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
)
_COHERENCE_SNOOP_RESPONSE_TYPES = (
    ChiSnpRespMessage,
    ChiSnpRespDataMessage,
)
_COHERENT_READ_TYPES = (
    ChiReadSharedMessage,
    ChiReadNotSharedDirtyMessage,
    ChiReadUniqueMessage,
)


@dataclass(frozen=True)
class ChiSubmitCoherentRead:
    """Ask one registered Request Node to issue a coherent read."""

    requester_node_id: int
    request: (
        ChiReadSharedMessage
        | ChiReadNotSharedDirtyMessage
        | ChiReadUniqueMessage
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requester_node_id, int)
            or isinstance(self.requester_node_id, bool)
            or self.requester_node_id < 0
        ):
            raise ValueError("CHI requester NodeID must be non-negative")
        if not isinstance(
            self.request,
            (
                ChiReadSharedMessage,
                ChiReadNotSharedDirtyMessage,
                ChiReadUniqueMessage,
            ),
        ):
            raise TypeError(
                "coherent read submission requires ReadShared, "
                "ReadNotSharedDirty, or ReadUnique"
            )


@dataclass(frozen=True)
class ChiSubmitCleanUnique:
    """Ask one registered Request Node to upgrade a resident ``SC`` line."""

    requester_node_id: int
    request: ChiCleanUniqueMessage

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requester_node_id, int)
            or isinstance(self.requester_node_id, bool)
            or self.requester_node_id < 0
        ):
            raise ValueError("CHI requester NodeID must be non-negative")
        if not isinstance(self.request, ChiCleanUniqueMessage):
            raise TypeError(
                "CleanUnique submission requires CleanUnique"
            )


@dataclass(frozen=True)
class ChiSubmitMakeUnique:
    """Issue MakeUnique with one RN-local full-line store intent."""

    requester_node_id: int
    request: ChiMakeUniqueMessage
    data: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requester_node_id, int)
            or isinstance(self.requester_node_id, bool)
            or self.requester_node_id < 0
        ):
            raise ValueError("CHI requester NodeID must be non-negative")
        if not isinstance(self.request, ChiMakeUniqueMessage):
            raise TypeError("MakeUnique submission requires MakeUnique")
        if (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or not 0 <= self.data < (1 << 512)
        ):
            raise ValueError(
                "MakeUnique store intent must fit one 512-bit cache line"
            )


@dataclass(frozen=True)
class ChiSubmitEvict:
    """Ask one Request Node to discard a clean line and notify Home."""

    requester_node_id: int
    request: ChiEvictMessage

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requester_node_id, int)
            or isinstance(self.requester_node_id, bool)
            or self.requester_node_id < 0
        ):
            raise ValueError("CHI requester NodeID must be non-negative")
        if not isinstance(self.request, ChiEvictMessage):
            raise TypeError("Evict submission requires Evict")


@dataclass(frozen=True)
class ChiDeliverCoherencePacket:
    """Deliver one packet after a transport/network runtime captured it."""

    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError("CHI coherence delivery requires a network packet")


@dataclass(frozen=True)
class ChiWriteUniqueCacheLine:
    """Apply one RN-local full-line write through the system composition."""

    request_node_id: int
    address: int
    data: int

    def __post_init__(self) -> None:
        for name, value in (
            ("request_node_id", self.request_node_id),
            ("address", self.address),
            ("data", self.data),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"CHI local write {name} must be non-negative")


@dataclass(frozen=True)
class ChiSubmitWriteBackFull:
    """Ask one registered Request Node to write a dirty line to Home."""

    requester_node_id: int
    request: ChiWriteBackFullMessage

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requester_node_id, int)
            or isinstance(self.requester_node_id, bool)
            or self.requester_node_id < 0
        ):
            raise ValueError("CHI writeback requester NodeID must be non-negative")
        if not isinstance(self.request, ChiWriteBackFullMessage):
            raise TypeError(
                "writeback submission requires WriteBackFull"
            )


@dataclass(frozen=True)
class ChiSubmitWriteEvictFull:
    """Ask one registered Request Node to offer a clean line downstream."""

    requester_node_id: int
    request: ChiWriteEvictFullMessage

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requester_node_id, int)
            or isinstance(self.requester_node_id, bool)
            or self.requester_node_id < 0
        ):
            raise ValueError(
                "CHI WriteEvict requester NodeID must be non-negative"
            )
        if not isinstance(self.request, ChiWriteEvictFullMessage):
            raise TypeError(
                "WriteEvict submission requires WriteEvictFull"
            )


@dataclass(frozen=True)
class ChiSubmitWriteEvictOrEvict:
    """Ask one Request Node to evict a clean UC or SC line."""

    requester_node_id: int
    request: ChiWriteEvictOrEvictMessage

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requester_node_id, int)
            or isinstance(self.requester_node_id, bool)
            or self.requester_node_id < 0
        ):
            raise ValueError(
                "CHI WriteEvictOrEvict requester NodeID must be non-negative"
            )
        if not isinstance(self.request, ChiWriteEvictOrEvictMessage):
            raise TypeError(
                "WriteEvictOrEvict submission requires "
                "WriteEvictOrEvict"
            )


@dataclass(frozen=True)
class ChiGrantCoherentHomePCredit:
    """Give the Home one opportunity to reserve a retry slot."""


@dataclass(frozen=True)
class ChiRetryCoherentRequest:
    """Ask one requester to consume credit and reissue a retained request."""

    requester_node_id: int
    transaction_id: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requester_node_id, int)
            or isinstance(self.requester_node_id, bool)
            or self.requester_node_id < 0
        ):
            raise ValueError("CHI retry requester NodeID must be non-negative")
        if (
            not isinstance(self.transaction_id, int)
            or isinstance(self.transaction_id, bool)
            or not 0 <= self.transaction_id < (1 << 12)
        ):
            raise ValueError("CHI retry transaction_id must be 12-bit")


ChiCoherenceAction = (
    ChiSubmitCoherentRead
    | ChiSubmitCleanUnique
    | ChiSubmitMakeUnique
    | ChiSubmitEvict
    | ChiSubmitWriteBackFull
    | ChiSubmitWriteEvictFull
    | ChiSubmitWriteEvictOrEvict
    | ChiDeliverCoherencePacket
    | ChiWriteUniqueCacheLine
    | ChiGrantCoherentHomePCredit
    | ChiRetryCoherentRequest
)


@dataclass(frozen=True)
class ChiCoherenceState:
    """Stable participant registries plus their current local states."""

    home: ChiCoherentHomeState
    request_nodes: Mapping[int, ChiCoherentRnState]
    expected_evict_completions: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)
    expected_clean_unique_completions: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)
    expected_make_unique_completions: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)
    expected_coherent_read_completions: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)
    expected_writeback_dbid_responses: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)
    expected_write_evict_dbid_responses: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)
    expected_write_evict_or_evict_responses: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)
    expected_copyback_data: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)
    expected_write_evict_or_evict_acks: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)
    expected_retry_acks: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)
    expected_pcredit_grants: tuple[ChiNetworkPacket, ...] = ()
    expected_snoop_deliveries: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)
    expected_snoop_responses: Mapping[
        tuple[int, int],
        ChiNetworkPacket,
    ] = field(default_factory=dict)

    def __post_init__(self) -> None:
        request_nodes = dict(self.request_nodes)
        object.__setattr__(
            self,
            "request_nodes",
            MappingProxyType(request_nodes),
        )
        expected = dict(self.expected_evict_completions)
        for key, completion_packet in expected.items():
            completion = (
                completion_packet.message
                if isinstance(completion_packet, ChiNetworkPacket)
                else None
            )
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 0
                    for value in key
                )
                or key[1] >= (1 << 12)
                or not isinstance(completion, ChiCompMessage)
                or completion_packet.target_id != key[0]
                or completion_packet.packet_index != 0
                or completion_packet.packet_count != 1
                or completion.transaction_id != key[1]
                or completion.response is not ChiRespCode.I
                or completion.response_error is not ChiRespErr.OK
                or completion.tag_operation != 0
                or key[0] not in request_nodes
                or not isinstance(
                    request_nodes[
                        key[0]
                    ].pending_transactions.get(key[1]),
                    ChiEvictMessage,
                )
            ):
                raise ValueError(
                    "expected Evict completions require one exact "
                    "(requester, TxnID)->Comp_I packet"
                )
        object.__setattr__(
            self,
            "expected_evict_completions",
            MappingProxyType(expected),
        )
        clean_unique_expected = dict(
            self.expected_clean_unique_completions
        )
        for key, completion_packet in clean_unique_expected.items():
            completion = (
                completion_packet.message
                if isinstance(completion_packet, ChiNetworkPacket)
                else None
            )
            valid_key = (
                isinstance(key, tuple)
                and len(key) == 2
                and all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in key
                )
                and key[1] < (1 << 12)
                and key[0] in request_nodes
            )
            pending_request = (
                request_nodes[key[0]].pending_transactions.get(key[1])
                if valid_key
                else None
            )
            matching_home_pending = (
                tuple(
                    pending
                    for pending in self.home.pending.values()
                    if (
                        pending.data_buffer_id
                        == completion.data_buffer_id
                        and pending.requester_id == key[0]
                        and isinstance(
                            pending.request,
                            ChiCleanUniqueMessage,
                        )
                        and pending.request == pending_request
                        and pending.request.transaction_id == key[1]
                        and pending.completion_sent
                    )
                )
                if (
                    valid_key
                    and isinstance(completion, ChiCompMessage)
                )
                else ()
            )
            if (
                not valid_key
                or not isinstance(completion, ChiCompMessage)
                or completion_packet.target_id != key[0]
                or completion_packet.packet_index != 0
                or completion_packet.packet_count != 1
                or completion.transaction_id != key[1]
                or completion.response is not ChiRespCode.UC
                or completion.response_error is not ChiRespErr.OK
                or completion.tag_operation != 0
                or not isinstance(
                    pending_request,
                    ChiCleanUniqueMessage,
                )
                or len(matching_home_pending) != 1
            ):
                raise ValueError(
                    "expected CleanUnique completions require one exact "
                    "(requester, TxnID)->Home Comp_UC packet and "
                    "reservation"
                )
        object.__setattr__(
            self,
            "expected_clean_unique_completions",
            MappingProxyType(clean_unique_expected),
        )
        required_clean_unique_completions = {
            (
                pending.requester_id,
                pending.request.transaction_id,
            )
            for pending in self.home.pending.values()
            if (
                isinstance(pending.request, ChiCleanUniqueMessage)
                and pending.completion_sent
                and pending.requester_id in request_nodes
                and request_nodes[
                    pending.requester_id
                ].pending_transactions.get(
                    pending.request.transaction_id
                )
                == pending.request
            )
        }
        if (
            set(clean_unique_expected)
            != required_clean_unique_completions
        ):
            raise ValueError(
                "Home-completed CleanUnique with a matching RN pending "
                "request requires exactly one expected Comp_UC"
            )

        make_unique_expected = dict(
            self.expected_make_unique_completions
        )
        for key, completion_packet in make_unique_expected.items():
            completion = (
                completion_packet.message
                if isinstance(completion_packet, ChiNetworkPacket)
                else None
            )
            if (
                not isinstance(key, tuple)
                or len(key) != 2
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 0
                    for value in key
                )
                or key[1] >= (1 << 12)
                or not isinstance(completion, ChiCompMessage)
                or completion_packet.target_id != key[0]
                or completion_packet.packet_index != 0
                or completion_packet.packet_count != 1
                or completion.transaction_id != key[1]
                or completion.response is not ChiRespCode.UC
                or completion.response_error is not ChiRespErr.OK
                or completion.tag_operation != 0
                or completion.trace_tag
                or key[0] not in request_nodes
                or not isinstance(
                    request_nodes[
                        key[0]
                    ].pending_transactions.get(key[1]),
                    ChiMakeUniqueMessage,
                )
                or len(
                    tuple(
                        pending
                        for pending in self.home.pending.values()
                        if (
                            pending.requester_id == key[0]
                            and isinstance(
                                pending.request,
                                ChiMakeUniqueMessage,
                            )
                            and pending.request.transaction_id == key[1]
                            and pending.data_buffer_id
                            == completion.data_buffer_id
                            and pending.completion_sent
                        )
                    )
                )
                != 1
            ):
                raise ValueError(
                    "expected MakeUnique completions require one exact "
                    "(requester, TxnID)->Home Comp_UC packet and reservation"
                )
        object.__setattr__(
            self,
            "expected_make_unique_completions",
            MappingProxyType(make_unique_expected),
        )
        required_make_unique_completions = {
            (
                pending.requester_id,
                pending.request.transaction_id,
            )
            for pending in self.home.pending.values()
            if (
                isinstance(pending.request, ChiMakeUniqueMessage)
                and pending.completion_sent
                and pending.requester_id in request_nodes
                and request_nodes[
                    pending.requester_id
                ].pending_transactions.get(
                    pending.request.transaction_id
                )
                == pending.request
            )
        }
        if set(make_unique_expected) != required_make_unique_completions:
            raise ValueError(
                "Home-completed MakeUnique with a matching RN pending "
                "request requires exactly one expected Comp_UC"
            )

        coherent_read_expected = dict(
            self.expected_coherent_read_completions
        )
        for key, completion_packet in coherent_read_expected.items():
            completion = (
                completion_packet.message
                if isinstance(completion_packet, ChiNetworkPacket)
                else None
            )
            valid_key = (
                isinstance(key, tuple)
                and len(key) == 2
                and all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in key
                )
                and key[1] < (1 << 12)
                and key[0] in request_nodes
            )
            pending_request = (
                request_nodes[key[0]].pending_transactions.get(key[1])
                if valid_key
                else None
            )
            matching_home_pending = (
                tuple(
                    pending
                    for pending in self.home.pending.values()
                    if (
                        pending.data_buffer_id
                        == completion.data_buffer_id
                        and pending.requester_id == key[0]
                        and isinstance(
                            pending.request,
                            _COHERENT_READ_TYPES,
                        )
                        and pending.request == pending_request
                        and pending.request.transaction_id == key[1]
                        and pending.completion_sent
                        and pending.completion_response_error
                        is completion.response_error
                    )
                )
                if (
                    valid_key
                    and isinstance(completion, ChiCompDataMessage)
                )
                else ()
            )
            if (
                not valid_key
                or not isinstance(completion, ChiCompDataMessage)
                or completion_packet.target_id != key[0]
                or completion_packet.packet_index != 0
                or completion_packet.packet_count != 1
                or completion.transaction_id != key[1]
                or completion.home_node_id
                != completion_packet.source_id
                or not isinstance(
                    pending_request,
                    _COHERENT_READ_TYPES,
                )
                or len(matching_home_pending) != 1
            ):
                raise ValueError(
                    "expected coherent-read completions require one exact "
                    "(requester, TxnID)->Home CompData packet and "
                    "reservation"
                )
        object.__setattr__(
            self,
            "expected_coherent_read_completions",
            MappingProxyType(coherent_read_expected),
        )
        required_coherent_read_completions = {
            (
                pending.requester_id,
                pending.request.transaction_id,
            )
            for pending in self.home.pending.values()
            if (
                isinstance(pending.request, _COHERENT_READ_TYPES)
                and pending.completion_sent
                and pending.requester_id in request_nodes
                and request_nodes[
                    pending.requester_id
                ].pending_transactions.get(
                    pending.request.transaction_id
                )
                == pending.request
            )
        }
        if (
            set(coherent_read_expected)
            != required_coherent_read_completions
        ):
            raise ValueError(
                "Home-completed coherent read with a matching RN pending "
                "request requires exactly one expected CompData"
            )

        writeback_dbid_responses = dict(
            self.expected_writeback_dbid_responses
        )
        for key, response_packet in writeback_dbid_responses.items():
            response = (
                response_packet.message
                if isinstance(response_packet, ChiNetworkPacket)
                else None
            )
            valid_key = (
                isinstance(key, tuple)
                and len(key) == 2
                and all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in key
                )
                and key[1] < (1 << 12)
                and key[0] in request_nodes
            )
            home_pending = (
                self.home.pending_copybacks.get(
                    response.data_buffer_id
                )
                if isinstance(response, ChiCompDBIDRespMessage)
                else None
            )
            rn_pending = (
                request_nodes[key[0]].pending_copybacks.get(key[1])
                if valid_key
                else None
            )
            if (
                not valid_key
                or not isinstance(response, ChiCompDBIDRespMessage)
                or response_packet.target_id != key[0]
                or response_packet.packet_index != 0
                or response_packet.packet_count != 1
                or response.transaction_id != key[1]
                or response.qos != 0
                or response.response_error is not ChiRespErr.OK
                or response.response != 0
                or response.completer_busy != 0
                or response.trace_tag
                or not isinstance(
                    home_pending, ChiHomeWriteBackPending
                )
                or home_pending.requester_id != key[0]
                or home_pending.request.transaction_id != key[1]
                or not isinstance(
                    rn_pending, ChiRnWriteBackPending
                )
                or rn_pending.request != home_pending.request
                or (
                    (
                        home_pending.admission
                        is ChiHomeCopyBackAdmission.SNOOP_CANCELED
                    )
                    != (
                        rn_pending.outcome
                        is ChiRnCopyBackOutcome.CANCELED_I
                    )
                )
            ):
                raise ValueError(
                    "expected CompDBIDResp requires one exact canonical "
                    "Home packet and matching Home/RN WriteBackFull state"
                )
        object.__setattr__(
            self,
            "expected_writeback_dbid_responses",
            MappingProxyType(writeback_dbid_responses),
        )

        write_evict_dbid_responses = dict(
            self.expected_write_evict_dbid_responses
        )
        for key, response_packet in write_evict_dbid_responses.items():
            response = (
                response_packet.message
                if isinstance(response_packet, ChiNetworkPacket)
                else None
            )
            valid_key = (
                isinstance(key, tuple)
                and len(key) == 2
                and all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in key
                )
                and key[1] < (1 << 12)
                and key[0] in request_nodes
            )
            home_pending = (
                self.home.pending_copybacks.get(
                    response.data_buffer_id
                )
                if isinstance(response, ChiCompDBIDRespMessage)
                else None
            )
            rn_pending = (
                request_nodes[key[0]].pending_copybacks.get(key[1])
                if valid_key
                else None
            )
            if (
                not valid_key
                or not isinstance(response, ChiCompDBIDRespMessage)
                or response_packet.target_id != key[0]
                or response_packet.packet_index != 0
                or response_packet.packet_count != 1
                or response.transaction_id != key[1]
                or response.qos != 0
                or response.response_error is not ChiRespErr.OK
                or response.response != 0
                or response.completer_busy != 0
                or response.trace_tag
                or not isinstance(
                    home_pending, ChiHomeWriteEvictPending
                )
                or home_pending.requester_id != key[0]
                or home_pending.request.transaction_id != key[1]
                or not isinstance(
                    rn_pending, ChiRnWriteEvictPending
                )
                or rn_pending.request != home_pending.request
                or (
                    (
                        home_pending.admission
                        is ChiHomeCopyBackAdmission.SNOOP_CANCELED
                    )
                    != (
                        rn_pending.outcome
                        is ChiRnCopyBackOutcome.CANCELED_I
                    )
                )
            ):
                raise ValueError(
                    "expected WriteEvict CompDBIDResp requires one exact "
                    "canonical Home packet and matching Home/RN state"
                )
        object.__setattr__(
            self,
            "expected_write_evict_dbid_responses",
            MappingProxyType(write_evict_dbid_responses),
        )

        write_evict_or_evict_responses = dict(
            self.expected_write_evict_or_evict_responses
        )
        for key, response_packet in (
            write_evict_or_evict_responses.items()
        ):
            response = (
                response_packet.message
                if isinstance(response_packet, ChiNetworkPacket)
                else None
            )
            valid_key = (
                isinstance(key, tuple)
                and len(key) == 2
                and all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in key
                )
                and key[1] < (1 << 12)
                and key[0] in request_nodes
            )
            data_buffer_id = (
                response.data_buffer_id
                if isinstance(
                    response,
                    (ChiCompMessage, ChiCompDBIDRespMessage),
                )
                else None
            )
            home_pending = (
                self.home.pending_copybacks.get(data_buffer_id)
                if data_buffer_id is not None
                else None
            )
            rn_pending = (
                request_nodes[key[0]].pending_copybacks.get(key[1])
                if valid_key
                else None
            )
            expects_data = (
                isinstance(
                    home_pending,
                    ChiHomeWriteEvictOrEvictPending,
                )
                and home_pending.decision
                is ChiWriteEvictOrEvictDecision.REQUEST_DATA
            )
            if (
                not valid_key
                or not isinstance(
                    response,
                    (ChiCompMessage, ChiCompDBIDRespMessage),
                )
                or response_packet.target_id != key[0]
                or response_packet.packet_index != 0
                or response_packet.packet_count != 1
                or response.transaction_id != key[1]
                or response.qos != 0
                or response.response_error is not ChiRespErr.OK
                or response.response != 0
                or response.completer_busy != 0
                or response.trace_tag
                or (
                    isinstance(response, ChiCompMessage)
                    and response.tag_operation != 0
                )
                or not isinstance(
                    home_pending,
                    ChiHomeWriteEvictOrEvictPending,
                )
                or home_pending.requester_id != key[0]
                or home_pending.request.transaction_id != key[1]
                or expects_data
                != isinstance(response, ChiCompDBIDRespMessage)
                or not isinstance(
                    rn_pending,
                    ChiRnWriteEvictOrEvictPending,
                )
                or rn_pending.request != home_pending.request
                or (
                    (
                        home_pending.admission
                        is ChiHomeCopyBackAdmission.SNOOP_CANCELED
                    )
                    != (
                        rn_pending.outcome
                        is ChiRnCopyBackOutcome.CANCELED_I
                    )
                )
            ):
                raise ValueError(
                    "expected WriteEvictOrEvict response requires one exact "
                    "Home-selected Comp or CompDBIDResp and matching Home/RN "
                    "state"
                )
        object.__setattr__(
            self,
            "expected_write_evict_or_evict_responses",
            MappingProxyType(write_evict_or_evict_responses),
        )
        response_key_sets = (
            set(writeback_dbid_responses),
            set(write_evict_dbid_responses),
            set(write_evict_or_evict_responses),
        )
        if (
            len(set().union(*response_key_sets))
            != sum(len(items) for items in response_key_sets)
        ):
            raise ValueError(
                "one Requester/TxnID cannot await multiple CopyBack response "
                "forms simultaneously"
            )

        copyback_data = dict(self.expected_copyback_data)
        for key, data_packet in copyback_data.items():
            message = (
                data_packet.message
                if isinstance(data_packet, ChiNetworkPacket)
                else None
            )
            valid_key = (
                isinstance(key, tuple)
                and len(key) == 2
                and all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in key
                )
                and key[1] < (1 << 12)
                and key[0] in request_nodes
            )
            home_pending = (
                self.home.pending_copybacks.get(key[1])
                if valid_key
                else None
            )
            canceled = (
                isinstance(
                    home_pending,
                    (
                        ChiHomeWriteBackPending,
                        ChiHomeWriteEvictPending,
                        ChiHomeWriteEvictOrEvictPending,
                    ),
                )
                and home_pending.admission
                is ChiHomeCopyBackAdmission.SNOOP_CANCELED
            )
            clean_evict = isinstance(
                home_pending,
                (
                    ChiHomeWriteEvictPending,
                    ChiHomeWriteEvictOrEvictPending,
                ),
            )
            clean_backing_line = (
                self.home.backing.line_at(
                    home_pending.request.address
                )
                if clean_evict
                else None
            )
            if (
                not valid_key
                or not isinstance(message, ChiCopyBackWrDataMessage)
                or data_packet.source_id != key[0]
                or data_packet.packet_index != 0
                or data_packet.packet_count != 1
                or message.transaction_id != key[1]
                or message.qos != 0
                or message.response_error is not ChiRespErr.OK
                or message.data_id != 0
                or message.data_source != 0
                or message.completer_busy != 0
                or message.critical_chunk_id != 0
                or message.trace_tag
                or home_pending is None
                or home_pending.requester_id != key[0]
                or (
                    isinstance(
                        home_pending,
                        ChiHomeWriteEvictOrEvictPending,
                    )
                    and home_pending.decision
                    is not ChiWriteEvictOrEvictDecision.REQUEST_DATA
                )
                or (
                    clean_evict
                    and not canceled
                    and (
                        message.response
                        is not (
                            ChiRespCode.SC
                            if isinstance(
                                home_pending,
                                ChiHomeWriteEvictOrEvictPending,
                            )
                            and home_pending.request.likely_shared
                            else ChiRespCode.UC
                        )
                        or not 0 <= message.data < (1 << 512)
                        or message.byte_enable != (1 << 64) - 1
                        or clean_backing_line is None
                        or message.data != clean_backing_line.data
                        or clean_backing_line.version
                        != home_pending.backing_version
                    )
                )
                or (
                    canceled
                    and (
                        message.response is not ChiRespCode.I
                        or message.data != 0
                        or message.byte_enable != 0
                    )
                )
                or (
                    not clean_evict
                    and not canceled
                    and (
                        message.response is not ChiRespCode.UD_PD
                        or not 0 <= message.data < (1 << 512)
                        or message.byte_enable != (1 << 64) - 1
                    )
                )
            ):
                raise ValueError(
                    "expected CopyBackWrData requires one exact canonical "
                    "RN packet and matching Home CopyBack reservation"
                )
        object.__setattr__(
            self,
            "expected_copyback_data",
            MappingProxyType(copyback_data),
        )

        write_evict_or_evict_acks = dict(
            self.expected_write_evict_or_evict_acks
        )
        for key, ack_packet in write_evict_or_evict_acks.items():
            ack = (
                ack_packet.message
                if isinstance(ack_packet, ChiNetworkPacket)
                else None
            )
            valid_key = (
                isinstance(key, tuple)
                and len(key) == 2
                and all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in key
                )
                and key[1] < (1 << 12)
                and key[0] in request_nodes
            )
            home_pending = (
                self.home.pending_copybacks.get(key[1])
                if valid_key
                else None
            )
            requester_state = (
                request_nodes[key[0]] if valid_key else None
            )
            requester_pending = (
                requester_state.pending_copybacks.get(
                    home_pending.request.transaction_id
                )
                if (
                    requester_state is not None
                    and isinstance(
                        home_pending,
                        ChiHomeWriteEvictOrEvictPending,
                    )
                )
                else None
            )
            line = (
                requester_state.line_at(home_pending.request.address)
                if (
                    requester_state is not None
                    and isinstance(
                        home_pending,
                        ChiHomeWriteEvictOrEvictPending,
                    )
                )
                else None
            )
            if (
                not valid_key
                or not isinstance(ack, ChiCompAckMessage)
                or ack_packet.source_id != key[0]
                or ack_packet.packet_index != 0
                or ack_packet.packet_count != 1
                or ack.transaction_id != key[1]
                or ack.qos != 0
                or ack.trace_tag
                or not isinstance(
                    home_pending,
                    ChiHomeWriteEvictOrEvictPending,
                )
                or home_pending.requester_id != key[0]
                or home_pending.decision
                is not ChiWriteEvictOrEvictDecision.COMPLETE_WITHOUT_DATA
                or ack.response
                != (
                    ChiRespCode.I
                    if home_pending.admission
                    is ChiHomeCopyBackAdmission.SNOOP_CANCELED
                    else (
                        ChiRespCode.SC
                        if home_pending.request.likely_shared
                        else ChiRespCode.UC
                    )
                )
                or requester_pending is not None
                or line is None
                or line.state is not ChiCacheState.I
                or line.data is not None
            ):
                raise ValueError(
                    "expected WriteEvictOrEvict CompAck requires one exact "
                    "RN-produced post-Snoop acknowledgement and matching "
                    "Home no-data reservation"
                )
        object.__setattr__(
            self,
            "expected_write_evict_or_evict_acks",
            MappingProxyType(write_evict_or_evict_acks),
        )

        for pending in self.home.pending_copybacks.values():
            if pending.requester_id not in request_nodes:
                raise ValueError(
                    "Home CopyBack reservation names an unknown RN"
                )
            response_key = (
                pending.requester_id,
                pending.request.transaction_id,
            )
            copyback_key = (
                pending.requester_id,
                pending.data_buffer_id,
            )
            response_evidence = (
                write_evict_or_evict_responses
                if isinstance(
                    pending,
                    ChiHomeWriteEvictOrEvictPending,
                )
                else (
                    write_evict_dbid_responses
                    if isinstance(pending, ChiHomeWriteEvictPending)
                    else writeback_dbid_responses
                )
            )
            response_packet = response_evidence.get(response_key)
            response_message = (
                response_packet.message
                if isinstance(response_packet, ChiNetworkPacket)
                else None
            )
            awaits_response = (
                isinstance(
                    response_message,
                    (ChiCompMessage, ChiCompDBIDRespMessage),
                )
                and response_message.data_buffer_id
                == pending.data_buffer_id
            )
            awaits_copyback = copyback_key in copyback_data
            awaits_ack = (
                copyback_key in write_evict_or_evict_acks
            )
            if sum((awaits_response, awaits_copyback, awaits_ack)) != 1:
                raise ValueError(
                    "one Home CopyBack reservation requires exactly "
                    "one response, data, or acknowledgement delivery phase"
                )
            if awaits_response:
                requester_pending = request_nodes[
                    pending.requester_id
                ].pending_copybacks.get(
                    pending.request.transaction_id
                )
                if (
                    requester_pending is None
                    or requester_pending.request != pending.request
                ):
                    raise ValueError(
                        "CompDBIDResp phase requires the matching retained "
                        "RN CopyBack request"
                    )
            else:
                requester_pending = request_nodes[
                    pending.requester_id
                ].pending_copybacks.get(
                    pending.request.transaction_id
                )
                if (
                    requester_pending is not None
                    and requester_pending.request == pending.request
                ):
                    raise ValueError(
                        "CopyBack data phase requires the RN to have consumed "
                        "the matching original request; the TxnID may name a "
                        "new request after CompDBIDResp"
                    )

        retry_acks = dict(self.expected_retry_acks)
        for key, retry_ack_packet in retry_acks.items():
            retry_ack = (
                retry_ack_packet.message
                if isinstance(retry_ack_packet, ChiNetworkPacket)
                else None
            )
            valid_key = (
                isinstance(key, tuple)
                and len(key) == 2
                and all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in key
                )
                and key[1] < (1 << 12)
                and key[0] in request_nodes
            )
            requester_state = (
                request_nodes[key[0]] if valid_key else None
            )
            pending_request = (
                requester_state.pending_transactions.get(key[1])
                if requester_state is not None
                else None
            )
            retry_entry = (
                requester_state.request_retry.entries.get(key[1])
                if requester_state is not None
                else None
            )
            if (
                not valid_key
                or not isinstance(retry_ack, ChiRetryAckMessage)
                or retry_ack_packet.target_id != key[0]
                or retry_ack_packet.packet_index != 0
                or retry_ack_packet.packet_count != 1
                or retry_ack.transaction_id != key[1]
                or not isinstance(
                    pending_request,
                    (ChiReadUniqueMessage, ChiEvictMessage),
                )
                or retry_entry is None
                or retry_entry.current_request != pending_request
                or retry_entry.phase
                is not ChiRequestRetryPhase.INITIAL_IN_FLIGHT
            ):
                raise ValueError(
                    "expected RetryAck requires one exact Home packet and "
                    "one initial retained retryable request"
                )
            matching_debt = any(
                debt.requester_id == key[0]
                and debt.transaction_id == key[1]
                and debt.protocol_credit_type
                == retry_ack.protocol_credit_type
                for debt in self.home.request_retry.retry_debts
            )
            matching_reservation = (
                self.home.request_retry.reservations.get(
                    (key[0], retry_ack.protocol_credit_type),
                    0,
                )
                > 0
            )
            if not matching_debt and not matching_reservation:
                raise ValueError(
                    "expected RetryAck has no matching Home debt or "
                    "granted reservation"
                )
        object.__setattr__(
            self,
            "expected_retry_acks",
            MappingProxyType(retry_acks),
        )

        pcredit_grants = tuple(self.expected_pcredit_grants)
        if any(
            not isinstance(packet, ChiNetworkPacket)
            or not isinstance(packet.message, ChiPCrdGrantMessage)
            or packet.target_id not in request_nodes
            or packet.packet_index != 0
            or packet.packet_count != 1
            for packet in pcredit_grants
        ):
            raise ValueError(
                "expected P-Credit grants require exact single-packet "
                "Home responses to registered Requesters"
            )
        expected_grants_by_key: dict[tuple[int, int], int] = {}
        for packet in pcredit_grants:
            key = (
                packet.target_id,
                packet.message.protocol_credit_type,
            )
            expected_grants_by_key[key] = (
                expected_grants_by_key.get(key, 0) + 1
            )
        if any(
            count
            > self.home.request_retry.reservations.get(key, 0)
            for key, count in expected_grants_by_key.items()
        ):
            raise ValueError(
                "expected P-Credit grant exceeds its Home reservation"
            )
        object.__setattr__(
            self,
            "expected_pcredit_grants",
            pcredit_grants,
        )

        snoop_deliveries = dict(self.expected_snoop_deliveries)
        snoop_responses = dict(self.expected_snoop_responses)

        def valid_snoop_key(key: object) -> bool:
            return (
                isinstance(key, tuple)
                and len(key) == 2
                and all(
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                    for value in key
                )
                and key[1] < (1 << 12)
            )

        def matching_pending(
            key: tuple[int, int],
            packet: ChiNetworkPacket,
        ):
            packet_address = getattr(packet.message, "address", None)
            return tuple(
                pending
                for pending in self.home.pending.values()
                if (
                    pending.snoop_transaction_id == key[1]
                    and key[0] in pending.snoop_targets
                    and (
                        packet_address is None
                        or pending.request.address == packet_address
                    )
                    and not pending.completion_sent
                )
            )

        if any(
            not valid_snoop_key(key)
            or not isinstance(packet, ChiNetworkPacket)
            or not isinstance(
                packet.message,
                _COHERENCE_SNOOP_TYPES,
            )
            or packet.target_id != key[0]
            or packet.message.transaction_id != key[1]
            or len(matching_pending(key, packet)) != 1
            or key[0]
            in matching_pending(key, packet)[0].snoop_results
            for key, packet in snoop_deliveries.items()
        ):
            raise ValueError(
                "expected Snoop delivery requires one exact unresolved "
                "Home-produced SNP target"
            )
        if any(
            not valid_snoop_key(key)
            or not isinstance(packet, ChiNetworkPacket)
            or not isinstance(
                packet.message,
                _COHERENCE_SNOOP_RESPONSE_TYPES,
            )
            or packet.source_id != key[0]
            or packet.message.transaction_id != key[1]
            or len(matching_pending(key, packet)) != 1
            or key[0]
            in matching_pending(key, packet)[0].snoop_results
            for key, packet in snoop_responses.items()
        ):
            raise ValueError(
                "expected Snoop response requires one exact unresolved "
                "RN-produced RSP or DAT packet"
            )
        if set(snoop_deliveries) & set(snoop_responses):
            raise ValueError(
                "one Snoop target cannot await delivery and response "
                "simultaneously"
            )
        unresolved_snoop_targets = {
            (target, pending.snoop_transaction_id)
            for pending in self.home.pending.values()
            if (
                pending.snoop_transaction_id is not None
                and not pending.completion_sent
            )
            for target in pending.snoop_targets
            if target not in pending.snoop_results
        }
        if (
            set(snoop_deliveries) | set(snoop_responses)
            != unresolved_snoop_targets
        ):
            raise ValueError(
                "every unresolved Home Snoop target requires exactly one "
                "delivery or response phase evidence"
            )
        object.__setattr__(
            self,
            "expected_snoop_deliveries",
            MappingProxyType(snoop_deliveries),
        )
        object.__setattr__(
            self,
            "expected_snoop_responses",
            MappingProxyType(snoop_responses),
        )


class ChiCoherenceInvariantMonitor:
    """Check directory/cache agreement at a quiescent reference point.

    In-flight coherence transactions intentionally create transient local
    differences, so this monitor is applied only when Home and Request Nodes
    have released their pending transaction records.  It consumes state and
    never generates participant output.
    """

    def explain(
        self,
        home: ChiCoherentHomeState,
        request_nodes: Mapping[int, ChiCoherentRnState],
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if home.pending or home.pending_copybacks:
            reasons.append(
                "stable coherence check requires an empty Home transaction table"
            )
        if (
            home.request_retry.retry_debts
            or home.request_retry.reservations
        ):
            reasons.append(
                "stable coherence check requires closed Home Retry/P-Credit "
                "obligations"
            )
        for node_id, state in request_nodes.items():
            if state.pending_transactions or state.pending_copybacks:
                reasons.append(
                    f"RN {node_id} still owns pending coherent transactions"
                )
            if (
                state.request_retry.entries
                or state.request_retry.protocol_credits
            ):
                reasons.append(
                    f"RN {node_id} still owns Retry/P-Credit state"
                )
        if reasons:
            return tuple(reasons)

        directory_addresses = set(home.directory)
        for address, entry in home.directory.items():
            backing_line = home.backing.line_at(address)
            assert backing_line is not None
            holders: dict[int, object] = {}
            for node_id, state in request_nodes.items():
                line = state.lines.get(address)
                if line is not None and line.state is not ChiCacheState.I:
                    holders[node_id] = line
            holder_states = tuple(
                (node_id, line.state.value)
                for node_id, line in sorted(holders.items())
            )

            if entry.unique_owner is not None:
                expected = {entry.unique_owner}
                if set(holders) != expected:
                    reasons.append(
                        f"line {address:#x} directory unique owner "
                        f"{entry.unique_owner} disagrees with RN holders "
                        f"{holder_states!r}"
                    )
                owner_line = holders.get(entry.unique_owner)
                if (
                    owner_line is not None
                    and owner_line.state
                    not in (
                        ChiCacheState.UC,
                        ChiCacheState.UCE,
                        ChiCacheState.UD,
                    )
                ):
                    reasons.append(
                        f"line {address:#x} unique owner is not in "
                        "UC, UCE, or UD state"
                    )
            else:
                expected = set(entry.sharers)
                if set(holders) != expected:
                    reasons.append(
                        f"line {address:#x} directory sharers "
                        f"{sorted(expected)!r} disagree with RN holders "
                        f"{sorted(holders)!r}"
                    )
                for node_id, line in holders.items():
                    expected_state = (
                        ChiCacheState.SD
                        if node_id == entry.shared_dirty_owner
                        else ChiCacheState.SC
                    )
                    if line.state is not expected_state:
                        reasons.append(
                            f"line {address:#x} shared holder {node_id} "
                            f"is not in {expected_state.value} state"
                        )

            if entry.shared_dirty_owner is not None:
                dirty_line = holders.get(entry.shared_dirty_owner)
                if dirty_line is not None:
                    for node_id, line in holders.items():
                        if line.data != dirty_line.data:
                            reasons.append(
                                f"line {address:#x} shared data at RN "
                                f"{node_id} differs from shared-dirty owner "
                                f"{entry.shared_dirty_owner}"
                            )
            else:
                for node_id, line in holders.items():
                    if (
                        line.state
                        not in (ChiCacheState.UCE, ChiCacheState.UD)
                        and line.data != backing_line.data
                    ):
                        reasons.append(
                            f"line {address:#x} data at RN {node_id} "
                            "differs from the authoritative Home backing copy"
                        )

        for node_id, state in request_nodes.items():
            for address, line in state.lines.items():
                if (
                    line.state is not ChiCacheState.I
                    and address not in directory_addresses
                ):
                    reasons.append(
                        f"RN {node_id} holds line {address:#x} without a "
                        "Home directory entry"
                    )
        return tuple(reasons)


class ChiCoherenceSession(
    SemanticComponent[
        ChiCoherenceAction,
        ChiCoherenceState,
        ChiNetworkPacket,
    ]
):
    """Compose one Home and a caller-selected set of coherent Request Nodes.

    ``step(ChiSubmitCoherentRead(...))`` creates the initial REQ packet.
    Thereafter the caller, scheduler, or transport runtime returns captured
    packets through ``ChiDeliverCoherencePacket``.  This keeps topology and
    cycle scheduling out of the coherence state machine while retaining an
    explicit packet boundary between every participant.
    """

    def __init__(
        self,
        name: str,
        home: ChiCoherentHomeNode,
        request_nodes: Mapping[int, ChiCoherentRnNode],
        *,
        monitor: ChiCoherenceInvariantMonitor | None = None,
        enabled_features: frozenset[ChiFeatureKey] | None = None,
        requester_node_ids: frozenset[int] | None = None,
        snoopee_node_ids: frozenset[int] | None = None,
        authority_window: AddressWindow | None = None,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("CHI coherence session requires a name")
        if not isinstance(home, ChiCoherentHomeNode):
            raise TypeError(
                "CHI coherence session requires a coherent Home"
            )
        nodes = dict(request_nodes)
        if not nodes:
            raise ValueError(
                "CHI coherence session requires Request Nodes"
            )
        for node_id, node in nodes.items():
            if not isinstance(node, ChiCoherentRnNode):
                raise TypeError("CHI Request Node registry has another component")
            if node_id != node.node_id:
                raise ValueError("CHI Request Node registry key must match NodeID")
            if node.home_node_id != home.node_id:
                raise ValueError(
                    "all Request Nodes in this profile must name the "
                    "registered Home"
                )
        participant_names = (
            home.name,
            *(node.name for node in nodes.values()),
        )
        if len(set(participant_names)) != len(participant_names):
            raise ValueError(
                "CHI coherence participant names must be unique"
            )
        if home.node_id in nodes:
            raise ValueError("CHI Home and Request Nodes must have distinct NodeIDs")
        features = (
            _CLEAN_READ_FEATURES
            if enabled_features is None
            else frozenset(enabled_features)
        )
        if not features or not features <= _COHERENCE_FEATURES:
            raise ValueError(
                "CHI coherence session has an unsupported feature"
            )
        if (
            CHI_FEATURE_DIRTY_UNIQUE_TRANSFER in features
            and CHI_FEATURE_CLEAN_READ_UNIQUE not in features
        ):
            raise ValueError(
                "dirty Unique transfer requires the ReadUnique base feature"
            )
        if (
            CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR in features
            and CHI_FEATURE_CLEAN_READ_UNIQUE not in features
        ):
            raise ValueError(
                "ReadUnique NDERR requires the clean ReadUnique base feature"
            )
        if (
            CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY in features
            and CHI_FEATURE_CLEAN_READ_UNIQUE not in features
        ):
            raise ValueError(
                "ReadUnique Retry requires the clean ReadUnique base feature"
            )
        if (
            CHI_FEATURE_CLEAN_EVICT_RETRY in features
            and CHI_FEATURE_CLEAN_EVICT not in features
        ):
            raise ValueError(
                "Evict Retry requires the clean Evict base feature"
            )
        if (
            home.read_unique_nderr_policy is not None
            and CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR not in features
        ):
            raise ValueError(
                "a configured coherent Home ReadUnique NDERR policy requires "
                "the ReadUnique NDERR feature"
            )
        if (
            CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR in features
            and home.read_unique_nderr_policy is None
        ):
            raise ValueError(
                "the ReadUnique NDERR feature requires a configured coherent "
                "Home NDERR policy"
            )
        if (
            home.retry_policy is not None
            and CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY not in features
        ):
            raise ValueError(
                "a configured coherent Home retry policy requires the "
                "ReadUnique Retry feature"
            )
        if (
            CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY in features
            and home.retry_policy is None
        ):
            raise ValueError(
                "the ReadUnique Retry feature requires a configured coherent "
                "Home retry policy"
            )
        if (
            home.evict_retry_policy is not None
            and CHI_FEATURE_CLEAN_EVICT_RETRY not in features
        ):
            raise ValueError(
                "a configured coherent Home Evict retry policy requires "
                "the Evict Retry feature"
            )
        if (
            CHI_FEATURE_CLEAN_EVICT_RETRY in features
            and home.evict_retry_policy is None
        ):
            raise ValueError(
                "the Evict Retry feature requires a configured coherent "
                "Home Evict retry policy"
            )
        if (
            CHI_FEATURE_DIRTY_UNIQUE_TRANSFER in features
            and not home.allow_dirty_data_transfer
        ):
            raise ValueError(
                "dirty Unique feature requires a Home configured to accept "
                "dirty snoop data"
            )
        if (
            CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY in features
            and not home.allow_dirty_data_transfer
        ):
            raise ValueError(
                "MESI ReadNotSharedDirty requires a Home configured to "
                "accept dirty snoop data"
            )
        if (
            CHI_FEATURE_DIRTY_WRITEBACK in features
            and not home.allow_dirty_data_transfer
        ):
            raise ValueError(
                "dirty writeback requires a Home configured to accept "
                "dirty copyback data"
            )
        if (
            CHI_FEATURE_WRITE_EVICT_FULL in features
            and home.clean_residency_core is None
        ):
            raise ValueError(
                "WriteEvictFull requires a Home Snoop-domain clean "
                "residency core"
            )
        if (
            CHI_FEATURE_WRITE_EVICT_OR_EVICT in features
            and home.clean_residency_core is None
        ):
            raise ValueError(
                "WriteEvictOrEvict requires a Home Snoop-domain clean "
                "residency core for its data-accepting outcome"
            )
        if (
            home.write_evict_or_evict_policy is not None
            and CHI_FEATURE_WRITE_EVICT_OR_EVICT not in features
        ):
            raise ValueError(
                "a configured Home WriteEvictOrEvict policy requires the "
                "WriteEvictOrEvict feature"
            )
        if (
            CHI_FEATURE_WRITE_EVICT_OR_EVICT in features
            and home.write_evict_or_evict_policy is None
        ):
            raise ValueError(
                "the WriteEvictOrEvict feature requires an explicit Home "
                "outcome policy"
            )
        if (
            CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER in features
            and CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS not in features
        ):
            raise ValueError(
                "shared-dirty CleanUnique requires the clean-peer base "
                "feature"
            )
        if (
            CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER in features
            and not home.allow_dirty_data_transfer
        ):
            raise ValueError(
                "shared-dirty CleanUnique requires a Home configured to "
                "accept PassDirty snoop data"
            )
        if (
            {
                CHI_FEATURE_MAKE_UNIQUE,
                CHI_FEATURE_CLEAN_READ_UNIQUE,
            }
            <= features
            and CHI_FEATURE_DIRTY_UNIQUE_TRANSFER not in features
        ):
            raise ValueError(
                "the current staged CHI profile combines MakeUnique and "
                "ReadUnique only with dirty Unique transfer enabled"
            )
        if (
            {
                CHI_FEATURE_MAKE_UNIQUE,
                CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
            }
            <= features
            and CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
            not in features
        ):
            raise ValueError(
                "the current staged CHI profile combines MakeUnique and "
                "CleanUnique only with shared-dirty peer handling enabled"
            )
        if (
            {
                CHI_FEATURE_MAKE_UNIQUE,
                CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
            }
            <= features
        ):
            raise ValueError(
                "the current staged CHI profile does not combine MakeUnique "
                "with MESI ReadNotSharedDirty until both same-line transient "
                "Snoop directions are implemented"
            )
        if (
            CHI_FEATURE_CLEAN_READ_SHARED in features
            and {
                CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
                CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
                CHI_FEATURE_DIRTY_WRITEBACK,
                CHI_FEATURE_MAKE_UNIQUE,
                CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
            }
            & features
        ):
            raise ValueError(
                "clean ReadShared cannot be combined with a dirty-owner "
                "feature until a dirty-shared policy is selected"
            )
        requesters = (
            frozenset(nodes)
            if requester_node_ids is None
            else frozenset(requester_node_ids)
        )
        snoopees = (
            frozenset(nodes)
            if snoopee_node_ids is None
            else frozenset(snoopee_node_ids)
        )
        for label, node_ids in (
            ("requester", requesters),
            ("Snoopee", snoopees),
        ):
            if any(
                not isinstance(node_id, int)
                or isinstance(node_id, bool)
                or node_id < 0
                for node_id in node_ids
            ):
                raise ValueError(
                    f"CHI {label} authority requires non-negative NodeIDs"
                )
        if not requesters:
            raise ValueError(
                "CHI coherence session requires an enabled requester"
            )
        if not requesters <= set(nodes) or not snoopees <= set(nodes):
            raise ValueError(
                "CHI requester and Snoopee authority must belong to the "
                "RN registry"
            )
        if authority_window is not None and not isinstance(
            authority_window, AddressWindow
        ):
            raise TypeError(
                "CHI coherence authority window requires AddressWindow"
            )
        self.name = name
        self.home = home
        self.request_nodes = MappingProxyType(nodes)
        self.monitor = monitor or ChiCoherenceInvariantMonitor()
        self.enabled_features = features
        self.requester_node_ids = requesters
        self.snoopee_node_ids = snoopees
        self.authority_window = authority_window

        initial = self._make_initial_state()
        profile_fault = self._profile_state_fault(initial)
        if profile_fault is not None:
            raise ValueError(profile_fault.reason)
        reasons = self.monitor.explain(initial.home, initial.request_nodes)
        if reasons:
            raise ValueError(
                "invalid initial coherent state: " + "; ".join(reasons)
            )

    @classmethod
    def from_resolved(
        cls,
        resolved: "ResolvedChiSystem",
        *,
        name: str | None = None,
        monitor: ChiCoherenceInvariantMonitor | None = None,
    ) -> "ChiCoherenceSession":
        """Bind coherence execution to closed roles and identities.

        The scalar ``requester`` is the only RN allowed to initiate through
        this construction.  ``snoopee`` contributes the finite peer registry;
        those peers can receive SNP and return RSP but do not inherit
        requester authority from being present in the session.
        """

        from .resolved import ResolvedChiSystem

        if not isinstance(resolved, ResolvedChiSystem):
            raise TypeError(
                "CHI resolved coherence construction requires "
                "ResolvedChiSystem"
            )
        resolved.require_closed()
        selected: set[ChiFeatureKey] = set()

        def add_feature(feature: ChiFeatureKey) -> None:
            if feature in selected:
                return
            selected.add(feature)
            definition = resolved.capabilities.catalog.definitions.get(
                feature
            )
            if definition is not None:
                for dependency in definition.dependencies:
                    add_feature(dependency)

        for required in resolved.feature_contract.required:
            add_feature(required)
        features = frozenset(selected & set(_COHERENCE_FEATURES))
        if not features:
            raise ValueError(
                "resolved CHI construction does not require a coherence "
                "feature"
            )
        for feature in features:
            resolved.capabilities.require(feature)

        requester_binding = resolved.role_binding("requester")
        authority = resolved.feature_authority
        home_binding = resolved.binding_by_name[authority.home]
        if authority.coherence_domain is None:
            snoopee_names: tuple[str, ...] = ()
        else:
            snoopee_names = resolved.authority_plan.eligible_snoopees(
                resolved.feature_address_claim,
                requester_binding.name,
            )
        snoopee_bindings = tuple(
            resolved.binding_by_name[item] for item in snoopee_names
        )
        effective_snoopees = (
            resolved.feature_contract.role_members("snoopee")
        )
        if effective_snoopees is not None and (
            tuple(sorted(effective_snoopees))
            != tuple(sorted(snoopee_names))
        ):
            raise ValueError(
                "resolved Snoopee feature role disagrees with its "
                "coherence domain"
            )
        if any(
            item.name == requester_binding.name
            for item in snoopee_bindings
        ):
            raise ValueError(
                "resolved Snoopee peer set must exclude its requester"
            )
        if not isinstance(requester_binding.component, ChiCoherentRnNode):
            raise TypeError(
                "resolved coherence requester requires ChiCoherentRnNode"
            )
        if not isinstance(home_binding.component, ChiCoherentHomeNode):
            raise TypeError(
                "resolved coherence Home requires ChiCoherentHomeNode"
            )
        peer_nodes: list[ChiCoherentRnNode] = []
        for binding in snoopee_bindings:
            if not isinstance(binding.component, ChiCoherentRnNode):
                raise TypeError(
                    "resolved coherence Snoopee requires ChiCoherentRnNode"
                )
            peer_nodes.append(binding.component)

        requester = requester_binding.component
        home = home_binding.component
        nodes = (requester, *peer_nodes)
        node_bindings = (
            (requester, requester_binding),
            *tuple(
                (binding.component, binding)
                for binding in snoopee_bindings
            ),
        )
        for node, binding in node_bindings:
            assert isinstance(node, ChiCoherentRnNode)
            if binding.node_ids != frozenset((node.node_id,)):
                raise ValueError(
                    f"resolved coherence participant {binding.name!r} must "
                    "offer exactly its component NodeID"
                )
            if node.home_node_id != home.node_id:
                raise ValueError(
                    f"CHI RN {binding.name!r} names another Home NodeID"
                )
        if authority.home_node_id != home.node_id:
            raise ValueError(
                "resolved Home authority disagrees with its component NodeID"
            )
        if home_binding.node_ids != frozenset((home.node_id,)):
            raise ValueError(
                "resolved coherence Home must offer exactly its component NodeID"
            )
        registry = {node.node_id: node for node in nodes}
        if len(registry) != len(nodes):
            raise ValueError(
                "resolved coherence RN roles contain duplicate component "
                "NodeIDs"
            )
        allowed_holders = set(registry)
        for entry in home.initial_directory:
            line_window = AddressWindow(entry.address, 64)
            if not authority.address_claim.window.contains(line_window):
                continue
            holders = set(entry.sharers)
            if entry.unique_owner is not None:
                holders.add(entry.unique_owner)
            outside = holders - allowed_holders
            if outside:
                raise ValueError(
                    f"Home directory line {entry.address:#x} names holders "
                    "outside the resolved coherence domain: "
                    f"{sorted(outside)!r}"
                )
        session_name = (
            f"{resolved.system.spec.name}.coherence"
            if name is None
            else name
        )
        return cls(
            session_name,
            home,
            registry,
            monitor=monitor,
            enabled_features=features,
            requester_node_ids=frozenset((requester.node_id,)),
            snoopee_node_ids=frozenset(
                node.node_id for node in peer_nodes
            ),
            authority_window=authority.address_claim.window,
        )

    def _make_initial_state(self) -> ChiCoherenceState:
        return ChiCoherenceState(
            home=self.home.initial_state(),
            request_nodes={
                node_id: node.initial_state()
                for node_id, node in self.request_nodes.items()
            },
        )

    def initial_state(self) -> ChiCoherenceState:
        return self._make_initial_state()

    def is_quiescent(self, state: ChiCoherenceState) -> bool:
        if not isinstance(state, ChiCoherenceState):
            return False
        return (
            self.home.is_quiescent(state.home)
            and all(
                self.request_nodes[node_id].is_quiescent(item)
                for node_id, item in state.request_nodes.items()
            )
            and not state.expected_evict_completions
            and not state.expected_clean_unique_completions
            and not state.expected_make_unique_completions
            and not state.expected_coherent_read_completions
            and not state.expected_writeback_dbid_responses
            and not state.expected_write_evict_dbid_responses
            and not state.expected_write_evict_or_evict_responses
            and not state.expected_copyback_data
            and not state.expected_write_evict_or_evict_acks
            and not state.expected_retry_acks
            and not state.expected_pcredit_grants
            and not state.expected_snoop_deliveries
            and not state.expected_snoop_responses
        )

    def step(
        self,
        state: ChiCoherenceState,
        action: ChiCoherenceAction,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        if not isinstance(state, ChiCoherenceState):
            raise TypeError(
                "CHI coherence session requires its own state"
            )
        profile_fault = self._profile_state_fault(state)
        if profile_fault is not None:
            return SemanticStep(state, fault=profile_fault)
        if isinstance(action, ChiSubmitCoherentRead):
            return self._issue(state, action)
        if isinstance(action, ChiSubmitCleanUnique):
            return self._issue_clean_unique(state, action)
        if isinstance(action, ChiSubmitMakeUnique):
            return self._issue_make_unique(state, action)
        if isinstance(action, ChiSubmitEvict):
            return self._issue_evict(state, action)
        if isinstance(action, ChiSubmitWriteBackFull):
            return self._issue_writeback(state, action)
        if isinstance(action, ChiSubmitWriteEvictFull):
            return self._issue_write_evict(state, action)
        if isinstance(action, ChiSubmitWriteEvictOrEvict):
            return self._issue_write_evict_or_evict(state, action)
        if isinstance(action, ChiDeliverCoherencePacket):
            return self._deliver(state, action.packet)
        if isinstance(action, ChiWriteUniqueCacheLine):
            return self._write_unique_cache_line(state, action)
        if isinstance(action, ChiGrantCoherentHomePCredit):
            return self._grant_pcredit(state)
        if isinstance(action, ChiRetryCoherentRequest):
            return self._retry_request(state, action)
        raise TypeError("unknown CHI coherence system action")

    def _profile_state_fault(
        self,
        state: ChiCoherenceState,
    ) -> SemanticFault | None:
        if any(
            packet.source_id != self.home.node_id
            or packet.target_id not in self.requester_node_ids
            for packet in (
                *state.expected_evict_completions.values(),
                *state.expected_clean_unique_completions.values(),
                *state.expected_make_unique_completions.values(),
                *state.expected_coherent_read_completions.values(),
                *state.expected_writeback_dbid_responses.values(),
                *state.expected_write_evict_dbid_responses.values(),
                *state.expected_write_evict_or_evict_responses.values(),
                *state.expected_retry_acks.values(),
                *state.expected_pcredit_grants,
            )
        ):
            return SemanticFault(
                f"{self.name}.completion_endpoint",
                "expected completion has another Home or Requester "
                "endpoint",
                ConstraintScope.SYSTEM,
                self.name,
            )
        if any(
            packet.source_id not in self.requester_node_ids
            or packet.target_id != self.home.node_id
            for packet in (
                *state.expected_copyback_data.values(),
                *state.expected_write_evict_or_evict_acks.values(),
            )
        ):
            return SemanticFault(
                f"{self.name}.copyback_endpoint",
                "expected CopyBackWrData has another Requester or Home "
                "endpoint",
                ConstraintScope.SYSTEM,
                self.name,
            )
        if any(
            packet.source_id != self.home.node_id
            or packet.target_id not in self.snoopee_node_ids
            for packet in state.expected_snoop_deliveries.values()
        ):
            return SemanticFault(
                f"{self.name}.snoop_delivery_endpoint",
                "expected Snoop delivery has another Home or Snoopee "
                "endpoint",
                ConstraintScope.SYSTEM,
                self.name,
            )
        if any(
            packet.target_id != self.home.node_id
            or packet.source_id not in self.snoopee_node_ids
            for packet in state.expected_snoop_responses.values()
        ):
            return SemanticFault(
                f"{self.name}.snoop_response_endpoint",
                "expected Snoop response has another Snoopee or Home "
                "endpoint",
                ConstraintScope.SYSTEM,
                self.name,
            )
        allows_unique_dirty = bool(
            {
                CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
                CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
                CHI_FEATURE_DIRTY_WRITEBACK,
                CHI_FEATURE_MAKE_UNIQUE,
                CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
            }
            & self.enabled_features
        )
        allows_shared_dirty = bool(
            {
                CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
                CHI_FEATURE_MAKE_UNIQUE,
            }
            & self.enabled_features
        )
        allows_empty_unique = (
            bool(
                {
                    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
                    CHI_FEATURE_CLEAN_EVICT,
                    CHI_FEATURE_MAKE_UNIQUE,
                }
                & self.enabled_features
            )
        )
        for node_id, node_state in state.request_nodes.items():
            for address, line in node_state.lines.items():
                if (
                    line.state is ChiCacheState.UD
                    and not allows_unique_dirty
                ):
                    return SemanticFault(
                        f"{self.name}.dirty_state_profile",
                        (
                            f"RN {node_id} line {address:#x} is UD but the "
                            "selected coherence features cannot consume a "
                            "dirty owner"
                        ),
                        ConstraintScope.SYSTEM,
                        self.name,
                    )
                if (
                    line.state is ChiCacheState.SD
                    and not allows_shared_dirty
                ):
                    return SemanticFault(
                        f"{self.name}.shared_dirty_state_profile",
                        (
                            f"RN {node_id} line {address:#x} is SD but the "
                            "selected coherence features cannot consume a "
                            "shared-dirty owner"
                        ),
                        ConstraintScope.SYSTEM,
                        self.name,
                    )
                if (
                    line.state is ChiCacheState.UCE
                    and not allows_empty_unique
                ):
                    return SemanticFault(
                        f"{self.name}.empty_unique_state_profile",
                        (
                            f"RN {node_id} line {address:#x} is UCE but the "
                            "selected coherence features cannot create or "
                            "consume empty Unique ownership"
                        ),
                        ConstraintScope.SYSTEM,
                        self.name,
                    )
        return None

    def _grant_pcredit(
        self,
        state: ChiCoherenceState,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        if (
            not self.enabled_features & _COHERENCE_RETRY_FEATURES
        ):
            return self._fault(
                state,
                "retry_feature",
                "no coherent Request-Retry modifier is enabled by the "
                "feature contract",
            )
        transition = self.home.step(
            state.home,
            ChiHomeGrantPCredit(),
        )
        expected_pcredit_grants = state.expected_pcredit_grants
        if (
            transition.fault is None
            and transition.blocked is None
        ):
            if (
                len(transition.emissions) != 1
                or not isinstance(
                    transition.emissions[0].message,
                    ChiPCrdGrantMessage,
                )
            ):
                return self._fault(
                    state,
                    "pcredit_grant_shape",
                    "Home P-Credit grant must emit exactly one PCrdGrant",
                )
            expected_pcredit_grants = (
                *state.expected_pcredit_grants,
                transition.emissions[0],
            )
        candidate = ChiCoherenceState(
            home=transition.state,
            request_nodes=state.request_nodes,
            expected_evict_completions=(
                state.expected_evict_completions
            ),
            expected_clean_unique_completions=(
                state.expected_clean_unique_completions
            ),
            expected_make_unique_completions=(
                state.expected_make_unique_completions
            ),
            expected_coherent_read_completions=(
                state.expected_coherent_read_completions
            ),
            expected_writeback_dbid_responses=(
                state.expected_writeback_dbid_responses
            ),
            expected_write_evict_dbid_responses=(
                state.expected_write_evict_dbid_responses
            ),
            expected_write_evict_or_evict_responses=(
                state.expected_write_evict_or_evict_responses
            ),
            expected_copyback_data=state.expected_copyback_data,
            expected_write_evict_or_evict_acks=(
                state.expected_write_evict_or_evict_acks
            ),
            expected_retry_acks=state.expected_retry_acks,
            expected_pcredit_grants=expected_pcredit_grants,
            expected_snoop_deliveries=(
                state.expected_snoop_deliveries
            ),
            expected_snoop_responses=state.expected_snoop_responses,
        )
        return self._finish(candidate, transition)

    def _retry_request(
        self,
        state: ChiCoherenceState,
        action: ChiRetryCoherentRequest,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        node = self.request_nodes.get(action.requester_node_id)
        if node is None:
            return self._fault(
                state,
                "retry_requester",
                f"NodeID {action.requester_node_id} is not a registered RN",
            )
        if action.requester_node_id not in self.requester_node_ids:
            return self._fault(
                state,
                "requester_authority",
                f"NodeID {action.requester_node_id} cannot retry requests "
                "in this construction",
            )
        retained_request = state.request_nodes[
            action.requester_node_id
        ].pending_transactions.get(action.transaction_id)
        retry_feature = self._retry_feature(retained_request)
        if (
            retry_feature is None
            or retry_feature not in self.enabled_features
        ):
            return self._fault(
                state,
                "retry_feature",
                "the retained request opcode is not enabled by its "
                "Request-Retry modifier",
            )
        transition = node.step(
            state.request_nodes[action.requester_node_id],
            ChiRnRetryCoherentRequest(action.transaction_id),
        )
        return self._replace_request_node(
            state,
            action.requester_node_id,
            transition,
        )

    def _write_unique_cache_line(
        self,
        state: ChiCoherenceState,
        action: ChiWriteUniqueCacheLine,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        authority_fault = self._address_authority_fault(
            action.address,
            64,
        )
        if authority_fault is not None:
            return SemanticStep(state, fault=authority_fault)
        node = self.request_nodes.get(action.request_node_id)
        if node is None:
            return self._fault(
                state,
                "local_write_identity",
                f"NodeID {action.request_node_id} is not a registered RN",
            )
        if not {
            CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
            CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
            CHI_FEATURE_DIRTY_WRITEBACK,
            CHI_FEATURE_MAKE_UNIQUE,
        } & self.enabled_features:
            return self._fault(
                state,
                "local_write_feature",
                "local dirtying requires an enabled dirty-owner lifecycle",
            )
        if any(
            pending.request.address == action.address
            for pending in state.home.pending.values()
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    chi_line_resource_name(
                        self.home.name, action.address
                    ),
                    ConstraintScope.SYSTEM,
                    available=0,
                    capacity=1,
                    reason=(
                        "local write waits for the same-line Home "
                        "transaction"
                    ),
                    location=self.name,
                ),
            )
        transition = node.step(
            state.request_nodes[action.request_node_id],
            ChiRnWriteCacheLine(action.address, action.data),
        )
        return self._replace_request_node(
            state,
            action.request_node_id,
            transition,
        )

    def _issue_writeback(
        self,
        state: ChiCoherenceState,
        action: ChiSubmitWriteBackFull,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        authority_fault = self._address_authority_fault(
            action.request.address,
            1 << action.request.size,
        )
        if authority_fault is not None:
            return SemanticStep(state, fault=authority_fault)
        node = self.request_nodes.get(action.requester_node_id)
        if node is None:
            return self._fault(
                state,
                "writeback_identity",
                f"NodeID {action.requester_node_id} is not a registered RN",
            )
        if action.requester_node_id not in self.requester_node_ids:
            return self._fault(
                state,
                "requester_authority",
                f"NodeID {action.requester_node_id} cannot issue writeback "
                "in this construction",
            )
        if CHI_FEATURE_DIRTY_WRITEBACK not in self.enabled_features:
            return self._fault(
                state,
                "writeback_feature",
                "WriteBackFull is not enabled by the feature contract",
            )
        if any(
            pending.request.address == action.request.address
            for pending in state.home.pending.values()
        ) or any(
            pending.request.address == action.request.address
            for pending in state.home.pending_copybacks.values()
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    chi_line_resource_name(
                        self.home.name, action.request.address
                    ),
                    ConstraintScope.SYSTEM,
                    available=0,
                    capacity=1,
                    reason=(
                        "writeback waits for the same-line Home transaction"
                    ),
                    location=self.name,
                ),
            )
        transition = node.step(
            state.request_nodes[action.requester_node_id],
            ChiRnIssueWriteBackFull(action.request),
        )
        return self._replace_request_node(
            state,
            action.requester_node_id,
            transition,
        )

    def _issue_write_evict(
        self,
        state: ChiCoherenceState,
        action: ChiSubmitWriteEvictFull,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        authority_fault = self._address_authority_fault(
            action.request.address,
            1 << action.request.size,
        )
        if authority_fault is not None:
            return SemanticStep(state, fault=authority_fault)
        node = self.request_nodes.get(action.requester_node_id)
        if node is None:
            return self._fault(
                state,
                "write_evict_identity",
                f"NodeID {action.requester_node_id} is not a registered RN",
            )
        if action.requester_node_id not in self.requester_node_ids:
            return self._fault(
                state,
                "requester_authority",
                f"NodeID {action.requester_node_id} cannot issue "
                "WriteEvictFull in this construction",
            )
        if CHI_FEATURE_WRITE_EVICT_FULL not in self.enabled_features:
            return self._fault(
                state,
                "write_evict_feature",
                "WriteEvictFull is not enabled by the feature contract",
            )
        if any(
            pending.request.address == action.request.address
            for pending in state.home.pending.values()
        ) or any(
            pending.request.address == action.request.address
            for pending in state.home.pending_copybacks.values()
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    chi_line_resource_name(
                        self.home.name, action.request.address
                    ),
                    ConstraintScope.SYSTEM,
                    available=0,
                    capacity=1,
                    reason=(
                        "WriteEvictFull waits for the same-line Home "
                        "transaction"
                    ),
                    location=self.name,
                ),
            )
        transition = node.step(
            state.request_nodes[action.requester_node_id],
            ChiRnIssueWriteEvictFull(action.request),
        )
        return self._replace_request_node(
            state,
            action.requester_node_id,
            transition,
        )

    def _issue_write_evict_or_evict(
        self,
        state: ChiCoherenceState,
        action: ChiSubmitWriteEvictOrEvict,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        authority_fault = self._address_authority_fault(
            action.request.address,
            1 << action.request.size,
        )
        if authority_fault is not None:
            return SemanticStep(state, fault=authority_fault)
        node = self.request_nodes.get(action.requester_node_id)
        if node is None:
            return self._fault(
                state,
                "write_evict_or_evict_identity",
                f"NodeID {action.requester_node_id} is not a registered RN",
            )
        if action.requester_node_id not in self.requester_node_ids:
            return self._fault(
                state,
                "requester_authority",
                f"NodeID {action.requester_node_id} cannot issue "
                "WriteEvictOrEvict in this construction",
            )
        if (
            CHI_FEATURE_WRITE_EVICT_OR_EVICT
            not in self.enabled_features
        ):
            return self._fault(
                state,
                "write_evict_or_evict_feature",
                "WriteEvictOrEvict is not enabled by the feature contract",
            )
        if any(
            pending.request.address == action.request.address
            for pending in state.home.pending.values()
        ) or any(
            pending.request.address == action.request.address
            for pending in state.home.pending_copybacks.values()
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    chi_line_resource_name(
                        self.home.name,
                        action.request.address,
                    ),
                    ConstraintScope.SYSTEM,
                    available=0,
                    capacity=1,
                    reason=(
                        "WriteEvictOrEvict waits for the same-line Home "
                        "transaction"
                    ),
                    location=self.name,
                ),
            )
        transition = node.step(
            state.request_nodes[action.requester_node_id],
            ChiRnIssueWriteEvictOrEvict(action.request),
        )
        return self._replace_request_node(
            state,
            action.requester_node_id,
            transition,
        )

    def _issue_clean_unique(
        self,
        state: ChiCoherenceState,
        action: ChiSubmitCleanUnique,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        authority_fault = self._address_authority_fault(
            action.request.address,
            1 << action.request.size,
        )
        if authority_fault is not None:
            return SemanticStep(state, fault=authority_fault)
        node = self.request_nodes.get(action.requester_node_id)
        if node is None:
            return self._fault(
                state,
                "requester_identity",
                f"NodeID {action.requester_node_id} is not a registered RN",
            )
        if action.requester_node_id not in self.requester_node_ids:
            return self._fault(
                state,
                "requester_authority",
                f"NodeID {action.requester_node_id} is registered only as "
                "a Snoopee in this construction",
            )
        if (
            CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
            not in self.enabled_features
        ):
            return self._fault(
                state,
                "feature_enablement",
                "CleanUnique is not enabled by the resolved feature contract",
            )
        entry = state.home.directory.get(action.request.address)
        if entry is not None:
            if entry.unique_owner is not None:
                owner = state.request_nodes.get(entry.unique_owner)
                owner_line = None if owner is None else owner.line_at(
                    action.request.address
                )
                if (
                    owner_line is not None
                    and owner_line.state is ChiCacheState.UD
                    and CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
                    not in self.enabled_features
                ):
                    return self._fault(
                        state,
                        "clean_unique_dirty_peer",
                        "CleanUnique against a dirty Unique owner requires "
                        "the Snoopee-to-Home DAT feature",
                    )
            if (
                entry.shared_dirty_owner is not None
                and CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
                not in self.enabled_features
            ):
                return self._fault(
                    state,
                    "clean_unique_shared_dirty_feature",
                    "the selected CleanUnique feature has no Snoopee-to-Home "
                    "DAT flow for the directory shared-dirty owner",
                )
            for peer_id in entry.sharers - {action.requester_node_id}:
                peer = state.request_nodes.get(peer_id)
                line = None if peer is None else peer.line_at(
                    action.request.address
                )
                if line is not None and line.state is ChiCacheState.UD:
                    return self._fault(
                        state,
                        "clean_unique_dirty_peer",
                        f"RN {peer_id} is UD beside a shared requester; "
                        "this is not a legal stable shared-dirty state",
                    )
        transition = node.step(
            state.request_nodes[action.requester_node_id],
            ChiRnIssueCleanUnique(action.request),
        )
        return self._replace_request_node(
            state,
            action.requester_node_id,
            transition,
        )

    def _issue_make_unique(
        self,
        state: ChiCoherenceState,
        action: ChiSubmitMakeUnique,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        authority_fault = self._address_authority_fault(
            action.request.address,
            1 << action.request.size,
        )
        if authority_fault is not None:
            return SemanticStep(state, fault=authority_fault)
        node = self.request_nodes.get(action.requester_node_id)
        if node is None:
            return self._fault(
                state,
                "requester_identity",
                f"NodeID {action.requester_node_id} is not a registered RN",
            )
        if action.requester_node_id not in self.requester_node_ids:
            return self._fault(
                state,
                "requester_authority",
                f"NodeID {action.requester_node_id} is registered only as "
                "a Snoopee in this construction",
            )
        if CHI_FEATURE_MAKE_UNIQUE not in self.enabled_features:
            return self._fault(
                state,
                "feature_enablement",
                "MakeUnique is not enabled by the resolved feature contract",
            )
        transition = node.step(
            state.request_nodes[action.requester_node_id],
            ChiRnIssueMakeUnique(action.request, action.data),
        )
        return self._replace_request_node(
            state,
            action.requester_node_id,
            transition,
        )

    def _issue_evict(
        self,
        state: ChiCoherenceState,
        action: ChiSubmitEvict,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        authority_fault = self._address_authority_fault(
            action.request.address,
            1 << action.request.size,
        )
        if authority_fault is not None:
            return SemanticStep(state, fault=authority_fault)
        node = self.request_nodes.get(action.requester_node_id)
        if node is None:
            return self._fault(
                state,
                "requester_identity",
                f"NodeID {action.requester_node_id} is not a registered RN",
            )
        if action.requester_node_id not in self.requester_node_ids:
            return self._fault(
                state,
                "requester_authority",
                f"NodeID {action.requester_node_id} is registered only as "
                "a Snoopee in this construction",
            )
        if CHI_FEATURE_CLEAN_EVICT not in self.enabled_features:
            return self._fault(
                state,
                "feature_enablement",
                "clean Evict is not enabled by the resolved feature contract",
            )
        transition = node.step(
            state.request_nodes[action.requester_node_id],
            ChiRnIssueEvict(action.request),
        )
        return self._replace_request_node(
            state,
            action.requester_node_id,
            transition,
        )

    def _issue(
        self,
        state: ChiCoherenceState,
        action: ChiSubmitCoherentRead,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        authority_fault = self._address_authority_fault(
            action.request.address,
            1 << action.request.size,
        )
        if authority_fault is not None:
            return SemanticStep(state, fault=authority_fault)
        node = self.request_nodes.get(action.requester_node_id)
        if node is None:
            return self._fault(
                state,
                "requester_identity",
                f"NodeID {action.requester_node_id} is not a registered RN",
            )
        if action.requester_node_id not in self.requester_node_ids:
            return self._fault(
                state,
                "requester_authority",
                f"NodeID {action.requester_node_id} is registered only as "
                "a Snoopee in this construction",
            )
        feature = self._request_feature(action.request)
        if feature not in self.enabled_features:
            return self._fault(
                state,
                "feature_enablement",
                f"{type(action.request).__name__} is not enabled by the "
                "resolved feature contract",
            )
        transition = node.step(
            state.request_nodes[action.requester_node_id],
            ChiRnIssueCoherentRead(action.request),
        )
        return self._replace_request_node(
            state,
            action.requester_node_id,
            transition,
        )

    def _deliver(
        self,
        state: ChiCoherenceState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        message = packet.message
        address = getattr(message, "address", None)
        if isinstance(address, int) and not isinstance(address, bool):
            size = getattr(message, "size", 6)
            size_bytes = (
                1 << size
                if isinstance(size, int)
                and not isinstance(size, bool)
                and 0 <= size <= 63
                else 64
            )
            authority_fault = self._address_authority_fault(
                address,
                size_bytes,
            )
            if authority_fault is not None:
                return SemanticStep(state, fault=authority_fault)
        if packet.target_id == self.home.node_id:
            consumed_snoop_response_key: tuple[int, int] | None = None
            if isinstance(message, ChiEvictMessage):
                if packet.source_id not in self.requester_node_ids:
                    return self._fault(
                        state,
                        "requester_authority",
                        f"NodeID {packet.source_id} is not the requester "
                        "of this construction",
                    )
                if CHI_FEATURE_CLEAN_EVICT not in self.enabled_features:
                    return self._fault(
                        state,
                        "feature_enablement",
                        "clean Evict is not enabled by the resolved feature "
                        "contract",
                    )
                if (
                    not message.allow_retry
                    and CHI_FEATURE_CLEAN_EVICT_RETRY
                    not in self.enabled_features
                ):
                    return self._fault(
                        state,
                        "retry_feature",
                        "credited Evict is not enabled by the feature "
                        "contract",
                    )
                requester_state = state.request_nodes[packet.source_id]
                retry_fault = self._retry_request_delivery_fault(
                    state,
                    packet,
                    message,
                )
                if retry_fault is not None:
                    return SemanticStep(state, fault=retry_fault)
                pending_request = requester_state.pending_transactions.get(
                    message.transaction_id
                )
                line = requester_state.line_at(message.address)
                if (
                    pending_request != message
                    or line is None
                    or line.state is not ChiCacheState.I
                    or line.data is not None
                ):
                    return self._fault(
                        state,
                        "evict_admission_evidence",
                        "Evict lacks the issuing RN's matching pending "
                        "clean-to-I transition",
                    )
                completion_key = (
                    packet.source_id,
                    message.transaction_id,
                )
                if completion_key in state.expected_evict_completions:
                    return self._fault(
                        state,
                        "duplicate_evict_request",
                        "this Evict request already produced its completion",
                    )
                action = ChiHomeAcceptEvict(packet)
            elif isinstance(message, ChiMakeUniqueMessage):
                if packet.source_id not in self.requester_node_ids:
                    return self._fault(
                        state,
                        "requester_authority",
                        f"NodeID {packet.source_id} is not the requester "
                        "of this construction",
                    )
                if CHI_FEATURE_MAKE_UNIQUE not in self.enabled_features:
                    return self._fault(
                        state,
                        "feature_enablement",
                        "MakeUnique is not enabled by the resolved feature "
                        "contract",
                    )
                requester_state = state.request_nodes[packet.source_id]
                pending_request = (
                    requester_state.pending_transactions.get(
                        message.transaction_id
                    )
                )
                if (
                    pending_request != message
                    or message.transaction_id
                    not in requester_state.make_unique_store_intents
                ):
                    return self._fault(
                        state,
                        "make_unique_admission_evidence",
                        "MakeUnique lacks the issuing RN's matching pending "
                        "request and 512-bit store intent",
                    )
                action = ChiHomeAcceptMakeUnique(packet)
            elif isinstance(message, ChiCleanUniqueMessage):
                if packet.source_id not in self.requester_node_ids:
                    return self._fault(
                        state,
                        "requester_authority",
                        f"NodeID {packet.source_id} is not the requester "
                        "of this construction",
                    )
                if (
                    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
                    not in self.enabled_features
                ):
                    return self._fault(
                        state,
                        "feature_enablement",
                        "CleanUnique is not enabled by the resolved feature "
                        "contract",
                    )
                action = ChiHomeAcceptCleanUnique(packet)
            elif isinstance(
                message,
                (
                    ChiReadSharedMessage,
                    ChiReadNotSharedDirtyMessage,
                    ChiReadUniqueMessage,
                ),
            ):
                if packet.source_id not in self.requester_node_ids:
                    return self._fault(
                        state,
                        "requester_authority",
                        f"NodeID {packet.source_id} is not the requester "
                        "of this construction",
                    )
                if self._request_feature(message) not in self.enabled_features:
                    return self._fault(
                        state,
                        "feature_enablement",
                        f"{type(message).__name__} is not enabled by the "
                        "resolved feature contract",
                    )
                if (
                    isinstance(message, ChiReadUniqueMessage)
                    and not message.allow_retry
                    and CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY
                    not in self.enabled_features
                ):
                    return self._fault(
                        state,
                        "retry_feature",
                        "credited ReadUnique is not enabled by the feature "
                        "contract",
                    )
                if isinstance(message, ChiReadUniqueMessage):
                    retry_fault = self._retry_request_delivery_fault(
                        state,
                        packet,
                        message,
                    )
                    if retry_fault is not None:
                        return SemanticStep(state, fault=retry_fault)
                action = ChiHomeAcceptCoherentRead(packet)
            elif isinstance(message, ChiWriteEvictOrEvictMessage):
                if packet.source_id not in self.requester_node_ids:
                    return self._fault(
                        state,
                        "requester_authority",
                        f"NodeID {packet.source_id} cannot issue "
                        "WriteEvictOrEvict in this construction",
                    )
                if (
                    CHI_FEATURE_WRITE_EVICT_OR_EVICT
                    not in self.enabled_features
                ):
                    return self._fault(
                        state,
                        "feature_enablement",
                        "WriteEvictOrEvict is not enabled by the resolved "
                        "feature contract",
                    )
                response_key = (
                    packet.source_id,
                    message.transaction_id,
                )
                if (
                    response_key
                    in state.expected_write_evict_or_evict_responses
                ):
                    return self._fault(
                        state,
                        "write_evict_or_evict_request_replay",
                        "WriteEvictOrEvict already selected a Home outcome "
                        "for this Requester/TxnID",
                    )
                requester_state = state.request_nodes[packet.source_id]
                pending_write_evict_or_evict = (
                    requester_state.pending_copybacks.get(
                        message.transaction_id
                    )
                )
                entry = state.home.directory.get(message.address)
                line = requester_state.line_at(message.address)
                expected_state = (
                    ChiCacheState.SC
                    if message.likely_shared
                    else ChiCacheState.UC
                )
                authority_matches = (
                    entry is not None
                    and (
                        packet.source_id in entry.sharers
                        and entry.shared_dirty_owner
                        != packet.source_id
                        if message.likely_shared
                        else entry.unique_owner == packet.source_id
                    )
                )
                if (
                    packet.packet_index != 0
                    or packet.packet_count != 1
                    or not isinstance(
                        pending_write_evict_or_evict,
                        ChiRnWriteEvictOrEvictPending,
                    )
                    or pending_write_evict_or_evict.request != message
                ):
                    return self._fault(
                        state,
                        "write_evict_or_evict_admission_evidence",
                        "WriteEvictOrEvict does not match one canonical "
                        "RN-produced request",
                    )
                admission = ChiHomeCopyBackAdmission.CURRENT_OWNER
                canceled = (
                    pending_write_evict_or_evict.outcome
                    is ChiRnCopyBackOutcome.CANCELED_I
                )
                if canceled and not authority_matches:
                    if (
                        line is None
                        or line.state is not ChiCacheState.I
                        or line.data is not None
                        or entry is None
                        or packet.source_id in entry.sharers
                        or entry.shared_dirty_owner == packet.source_id
                        or entry.unique_owner == packet.source_id
                    ):
                        return self._fault(
                            state,
                            "write_evict_or_evict_cancellation_evidence",
                            "non-holder WriteEvictOrEvict lacks one matching "
                            "Snoop-canceled RN outcome",
                        )
                    admission = ChiHomeCopyBackAdmission.SNOOP_CANCELED
                elif (
                    canceled
                    and not any(
                        item.request.address == message.address
                        for item in state.home.pending.values()
                    )
                    and not any(
                        item.request.address == message.address
                        for item in state.home.pending_copybacks.values()
                    )
                ):
                    return self._fault(
                        state,
                        "write_evict_or_evict_admission_evidence",
                        "Snoop-canceled WriteEvictOrEvict cannot be "
                        "admitted as a live current-holder request",
                    )
                elif (
                    not canceled
                    and (
                        line is None
                        or line.state is not expected_state
                        or line.data is None
                        or not authority_matches
                    )
                ):
                    return self._fault(
                        state,
                        "write_evict_or_evict_admission_evidence",
                        "live WriteEvictOrEvict lacks its encoded UC/SC "
                        "line and Home authority",
                    )
                action = ChiHomeAcceptWriteEvictOrEvict(
                    packet,
                    admission,
                )
            elif isinstance(message, ChiWriteEvictFullMessage):
                if packet.source_id not in self.requester_node_ids:
                    return self._fault(
                        state,
                        "requester_authority",
                        f"NodeID {packet.source_id} cannot issue "
                        "WriteEvictFull in this construction",
                    )
                if (
                    CHI_FEATURE_WRITE_EVICT_FULL
                    not in self.enabled_features
                ):
                    return self._fault(
                        state,
                        "feature_enablement",
                        "WriteEvictFull is not enabled by the resolved "
                        "feature contract",
                    )
                requester_state = state.request_nodes[packet.source_id]
                pending_write_evict = (
                    requester_state.pending_copybacks.get(
                        message.transaction_id
                    )
                )
                if (
                    packet.packet_index != 0
                    or packet.packet_count != 1
                    or not isinstance(
                        pending_write_evict, ChiRnWriteEvictPending
                    )
                    or pending_write_evict.request != message
                ):
                    return self._fault(
                        state,
                        "write_evict_admission_evidence",
                        "WriteEvictFull does not match one canonical "
                        "RN-produced request",
                    )
                admission = ChiHomeCopyBackAdmission.CURRENT_OWNER
                entry = state.home.directory.get(message.address)
                line = requester_state.line_at(message.address)
                if (
                    entry is not None
                    and entry.unique_owner != packet.source_id
                ):
                    if (
                        pending_write_evict.outcome
                        is not ChiRnCopyBackOutcome.CANCELED_I
                        or line is None
                        or line.state is not ChiCacheState.I
                        or line.data is not None
                        or packet.source_id in entry.sharers
                        or entry.shared_dirty_owner == packet.source_id
                    ):
                        return self._fault(
                            state,
                            "write_evict_cancellation_evidence",
                            "non-owner WriteEvictFull lacks a matching "
                            "Snoop-canceled RN pending outcome",
                        )
                    admission = (
                        ChiHomeCopyBackAdmission.SNOOP_CANCELED
                    )
                elif (
                    pending_write_evict.outcome
                    is ChiRnCopyBackOutcome.CANCELED_I
                    and not any(
                        item.request.address == message.address
                        for item in state.home.pending.values()
                    )
                    and not any(
                        item.request.address == message.address
                        for item in state.home.pending_copybacks.values()
                    )
                ):
                    return self._fault(
                        state,
                        "write_evict_admission_evidence",
                        "Snoop-canceled WriteEvictFull cannot be admitted "
                        "as a live current-owner request",
                    )
                elif (
                    pending_write_evict.outcome
                    is ChiRnCopyBackOutcome.LIVE_UC
                    and (
                        line is None
                        or line.state is not ChiCacheState.UC
                        or line.data is None
                    )
                ):
                    return self._fault(
                        state,
                        "write_evict_admission_evidence",
                        "live WriteEvictFull lacks its retained UC line",
                    )
                action = ChiHomeAcceptWriteEvictFull(
                    packet,
                    admission,
                )
            elif isinstance(message, ChiWriteBackFullMessage):
                if packet.source_id not in self.requester_node_ids:
                    return self._fault(
                        state,
                        "requester_authority",
                        f"NodeID {packet.source_id} cannot issue "
                        "WriteBackFull in this construction",
                    )
                if CHI_FEATURE_DIRTY_WRITEBACK not in self.enabled_features:
                    return self._fault(
                        state,
                        "feature_enablement",
                        "WriteBackFull is not enabled by the resolved "
                        "feature contract",
                    )
                requester_state = state.request_nodes[packet.source_id]
                pending_writeback = (
                    requester_state.pending_copybacks.get(
                        message.transaction_id
                    )
                )
                if (
                    packet.packet_index != 0
                    or packet.packet_count != 1
                    or pending_writeback is None
                    or pending_writeback.request != message
                ):
                    return self._fault(
                        state,
                        "writeback_admission_evidence",
                        "WriteBackFull does not match one canonical "
                        "RN-produced request",
                    )
                admission = ChiHomeCopyBackAdmission.CURRENT_OWNER
                entry = state.home.directory.get(message.address)
                if (
                    entry is not None
                    and entry.unique_owner != packet.source_id
                ):
                    line = requester_state.line_at(message.address)
                    if (
                        pending_writeback.outcome
                        is not ChiRnCopyBackOutcome.CANCELED_I
                        or line is None
                        or line.state is not ChiCacheState.I
                        or line.data is not None
                        or packet.source_id in entry.sharers
                        or entry.shared_dirty_owner == packet.source_id
                    ):
                        return self._fault(
                            state,
                            "writeback_cancellation_evidence",
                            "non-owner WriteBackFull lacks a matching "
                            "Snoop-canceled RN pending outcome",
                        )
                    admission = (
                        ChiHomeCopyBackAdmission.SNOOP_CANCELED
                    )
                elif (
                    pending_writeback.outcome
                    is ChiRnCopyBackOutcome.CANCELED_I
                    and not any(
                        item.request.address == message.address
                        for item in state.home.pending.values()
                    )
                    and not any(
                        item.request.address == message.address
                        for item in state.home.pending_copybacks.values()
                    )
                ):
                    return self._fault(
                        state,
                        "writeback_admission_evidence",
                        "Snoop-canceled WriteBackFull cannot be admitted "
                        "as a live current-owner request",
                    )
                action = ChiHomeAcceptWriteBackFull(
                    packet,
                    admission,
                )
            elif isinstance(
                message,
                (ChiSnpRespMessage, ChiSnpRespDataMessage),
            ):
                if packet.source_id not in self.snoopee_node_ids:
                    return self._fault(
                        state,
                        "snoopee_authority",
                        f"NodeID {packet.source_id} is not a Snoopee "
                        "of this construction",
                    )
                if isinstance(message, ChiSnpRespDataMessage):
                    matches = tuple(
                        pending
                        for pending in state.home.pending.values()
                        if (
                            pending.snoop_transaction_id
                            == message.transaction_id
                            and packet.source_id in pending.snoop_targets
                        )
                    )
                    if (
                        len(matches) == 1
                        and isinstance(
                            matches[0].request,
                            ChiMakeUniqueMessage,
                        )
                    ):
                        return self._fault(
                            state,
                            "make_unique_snoop_data",
                            "MakeUnique SnpMakeInvalid accepts only a "
                            "data-less SnpResp_I",
                        )
                    if (
                        len(matches) == 1
                        and isinstance(
                            matches[0].request,
                            ChiCleanUniqueMessage,
                        )
                        and CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
                        not in self.enabled_features
                    ):
                        return self._fault(
                            state,
                            "clean_unique_shared_dirty_feature",
                            "CleanUnique SnpRespData requires the "
                            "shared-dirty peer feature",
                        )
                response_key = (
                    packet.source_id,
                    message.transaction_id,
                )
                if (
                    state.expected_snoop_responses.get(response_key)
                    != packet
                ):
                    return self._fault(
                        state,
                        "snoop_response_correlation",
                        "Snoop response does not exactly match one "
                        "RN-produced response after SNP delivery",
                    )
                consumed_snoop_response_key = response_key
                action = ChiHomeAcceptSnoopResponse(packet)
            elif isinstance(message, ChiCompAckMessage):
                if packet.source_id not in self.requester_node_ids:
                    return self._fault(
                        state,
                        "requester_authority",
                        f"NodeID {packet.source_id} cannot return CompAck "
                        "in this construction",
                    )
                pending = state.home.pending.get(
                    message.transaction_id
                )
                write_evict_or_evict_pending = (
                    state.home.pending_copybacks.get(
                        message.transaction_id
                    )
                )
                if (
                    pending is None
                    and not isinstance(
                        write_evict_or_evict_pending,
                        ChiHomeWriteEvictOrEvictPending,
                    )
                ):
                    return self._fault(
                        state,
                        "completion_ack_correlation",
                        "CompAck does not select one retained Home "
                        "completion or WriteEvictOrEvict acknowledgement",
                    )
                if isinstance(
                    write_evict_or_evict_pending,
                    ChiHomeWriteEvictOrEvictPending,
                ):
                    if (
                        CHI_FEATURE_WRITE_EVICT_OR_EVICT
                        not in self.enabled_features
                        or write_evict_or_evict_pending.decision
                        is not (
                            ChiWriteEvictOrEvictDecision
                            .COMPLETE_WITHOUT_DATA
                        )
                        or state.expected_write_evict_or_evict_acks.get(
                            (packet.source_id, message.transaction_id)
                        )
                        != packet
                    ):
                        return self._fault(
                            state,
                            "write_evict_or_evict_ack_correlation",
                            "CompAck does not exactly match one Home "
                            "no-data WriteEvictOrEvict outcome",
                        )
                if (
                    pending is not None
                    and isinstance(
                        pending.request,
                        ChiCleanUniqueMessage,
                    )
                ):
                    key = (
                        pending.requester_id,
                        pending.request.transaction_id,
                    )
                    requester_state = state.request_nodes[
                        pending.requester_id
                    ]
                    if (
                        packet.source_id != pending.requester_id
                        or key
                        in state.expected_clean_unique_completions
                        or (
                            requester_state.pending_transactions.get(
                                pending.request.transaction_id
                            )
                            == pending.request
                        )
                    ):
                        return self._fault(
                            state,
                            "clean_unique_completion_ack_sequence",
                            "CleanUnique CompAck requires the retained Home "
                            "reservation and a completed RN Comp_UC",
                        )
                if (
                    pending is not None
                    and isinstance(
                        pending.request,
                        _COHERENT_READ_TYPES,
                    )
                ):
                    key = (
                        pending.requester_id,
                        pending.request.transaction_id,
                    )
                    requester_state = state.request_nodes[
                        pending.requester_id
                    ]
                    if (
                        packet.source_id != pending.requester_id
                        or key
                        in state.expected_coherent_read_completions
                        or (
                            requester_state.pending_transactions.get(
                                pending.request.transaction_id
                            )
                            == pending.request
                        )
                    ):
                        return self._fault(
                            state,
                            "coherent_read_completion_ack_sequence",
                            "coherent-read CompAck requires the retained "
                            "Home reservation and a completed RN CompData",
                        )
                if (
                    pending is not None
                    and isinstance(
                        pending.request,
                        ChiMakeUniqueMessage,
                    )
                ):
                    key = (
                        pending.requester_id,
                        pending.request.transaction_id,
                    )
                    requester_state = state.request_nodes[
                        pending.requester_id
                    ]
                    line = requester_state.line_at(
                        pending.request.address
                    )
                    if (
                        packet.source_id != pending.requester_id
                        or key
                        in state.expected_make_unique_completions
                        or isinstance(
                            requester_state.pending_transactions.get(
                                pending.request.transaction_id
                            ),
                            ChiMakeUniqueMessage,
                        )
                        or line is None
                        or line.state is not ChiCacheState.UD
                        or line.data is None
                    ):
                        return self._fault(
                            state,
                            "make_unique_completion_ack_sequence",
                            "MakeUnique CompAck requires the retained Home "
                            "reservation and a completed RN Comp_UC store",
                        )
                action = ChiHomeAcceptCompAck(packet)
            elif isinstance(message, ChiCopyBackWrDataMessage):
                if packet.source_id not in self.requester_node_ids:
                    return self._fault(
                        state,
                        "requester_authority",
                        f"NodeID {packet.source_id} cannot return copyback "
                        "data in this construction",
                    )
                if (
                    state.expected_copyback_data.get(
                        (packet.source_id, message.transaction_id)
                    )
                    != packet
                ):
                    return self._fault(
                        state,
                        "copyback_correlation",
                        "CopyBackWrData does not exactly match one "
                        "RN-produced packet",
                    )
                home_pending = state.home.pending_copybacks.get(
                    message.transaction_id
                )
                copyback_feature = (
                    CHI_FEATURE_WRITE_EVICT_OR_EVICT
                    if isinstance(
                        home_pending,
                        ChiHomeWriteEvictOrEvictPending,
                    )
                    else (
                        CHI_FEATURE_WRITE_EVICT_FULL
                        if isinstance(
                            home_pending,
                            ChiHomeWriteEvictPending,
                        )
                        else CHI_FEATURE_DIRTY_WRITEBACK
                    )
                )
                if copyback_feature not in self.enabled_features:
                    return self._fault(
                        state,
                        "feature_enablement",
                        "CopyBackWrData is not enabled by the resolved "
                        "feature contract",
                    )
                action = ChiHomeAcceptCopyBackData(packet)
            else:
                return self._fault(
                    state,
                    "home_dispatch",
                    f"Home cannot consume {type(message).__name__}",
                )
            transition = self.home.step(state.home, action)
            expected_evict_completions = (
                state.expected_evict_completions
            )
            expected_clean_unique_completions = (
                state.expected_clean_unique_completions
            )
            expected_make_unique_completions = (
                state.expected_make_unique_completions
            )
            expected_coherent_read_completions = (
                state.expected_coherent_read_completions
            )
            expected_writeback_dbid_responses = (
                state.expected_writeback_dbid_responses
            )
            expected_write_evict_dbid_responses = (
                state.expected_write_evict_dbid_responses
            )
            expected_write_evict_or_evict_responses = (
                state.expected_write_evict_or_evict_responses
            )
            expected_copyback_data = state.expected_copyback_data
            expected_write_evict_or_evict_acks = (
                state.expected_write_evict_or_evict_acks
            )
            expected_retry_acks = state.expected_retry_acks
            expected_pcredit_grants = state.expected_pcredit_grants
            expected_snoop_deliveries = (
                state.expected_snoop_deliveries
            )
            expected_snoop_responses = state.expected_snoop_responses
            if (
                isinstance(message, ChiEvictMessage)
                and transition.fault is None
                and transition.blocked is None
            ):
                if (
                    len(transition.emissions) != 1
                ):
                    return self._fault(
                        state,
                        "evict_completion_shape",
                        "Home Evict acceptance must emit exactly one "
                        "RetryAck or Comp",
                    )
                evict_response = transition.emissions[0]
                if isinstance(evict_response.message, ChiCompMessage):
                    expected = dict(state.expected_evict_completions)
                    expected[
                        (packet.source_id, message.transaction_id)
                    ] = evict_response
                    expected_evict_completions = expected
                elif isinstance(
                    evict_response.message,
                    ChiRetryAckMessage,
                ):
                    if (
                        CHI_FEATURE_CLEAN_EVICT_RETRY
                        not in self.enabled_features
                        or not message.allow_retry
                    ):
                        return self._fault(
                            state,
                            "evict_retry_feature",
                            "Home cannot retry Evict without the "
                            "opcode-specific modifier on an initial request",
                        )
                else:
                    return self._fault(
                        state,
                        "evict_completion_shape",
                        "Home Evict acceptance must emit exactly one "
                        "RetryAck or Comp",
                    )
            if (
                transition.fault is None
                and transition.blocked is None
            ):
                if isinstance(message, ChiWriteEvictOrEvictMessage):
                    if (
                        len(transition.emissions) != 1
                        or not isinstance(
                            transition.emissions[0].message,
                            (ChiCompMessage, ChiCompDBIDRespMessage),
                        )
                    ):
                        return self._fault(
                            state,
                            "write_evict_or_evict_response_shape",
                            "Home WriteEvictOrEvict acceptance must emit "
                            "exactly one Comp or CompDBIDResp",
                        )
                    response_packet = transition.emissions[0]
                    response = response_packet.message
                    pending = transition.state.pending_copybacks.get(
                        response.data_buffer_id
                    )
                    key = (
                        response_packet.target_id,
                        response.transaction_id,
                    )
                    if (
                        response_packet.source_id != self.home.node_id
                        or response_packet.target_id != packet.source_id
                        or response_packet.packet_index != 0
                        or response_packet.packet_count != 1
                        or response.transaction_id
                        != message.transaction_id
                        or not isinstance(
                            pending,
                            ChiHomeWriteEvictOrEvictPending,
                        )
                        or pending.requester_id != packet.source_id
                        or pending.request != message
                        or (
                            pending.decision
                            is ChiWriteEvictOrEvictDecision.REQUEST_DATA
                        )
                        != isinstance(response, ChiCompDBIDRespMessage)
                        or key
                        in state.expected_write_evict_or_evict_responses
                    ):
                        return self._fault(
                            state,
                            "write_evict_or_evict_response_evidence",
                            "Home response does not select one new "
                            "WriteEvictOrEvict reservation and outcome",
                        )
                    responses = dict(
                        state.expected_write_evict_or_evict_responses
                    )
                    responses[key] = response_packet
                    expected_write_evict_or_evict_responses = responses
                elif isinstance(
                    message,
                    (ChiWriteBackFullMessage, ChiWriteEvictFullMessage),
                ):
                    is_write_evict = isinstance(
                        message, ChiWriteEvictFullMessage
                    )
                    operation_name = (
                        "WriteEvictFull"
                        if is_write_evict
                        else "WriteBackFull"
                    )
                    if (
                        len(transition.emissions) != 1
                        or not isinstance(
                            transition.emissions[0].message,
                            ChiCompDBIDRespMessage,
                        )
                    ):
                        return self._fault(
                            state,
                            "copyback_dbid_response_shape",
                            f"Home {operation_name} acceptance must emit "
                            "exactly one CompDBIDResp",
                        )
                    response_packet = transition.emissions[0]
                    response = response_packet.message
                    pending = transition.state.pending_copybacks.get(
                        response.data_buffer_id
                    )
                    key = (
                        response_packet.target_id,
                        response.transaction_id,
                    )
                    if (
                        response_packet.source_id != self.home.node_id
                        or response_packet.target_id != packet.source_id
                        or response_packet.packet_index != 0
                        or response_packet.packet_count != 1
                        or response.transaction_id
                        != message.transaction_id
                        or not isinstance(
                            pending,
                            (
                                ChiHomeWriteEvictPending
                                if is_write_evict
                                else ChiHomeWriteBackPending
                            ),
                        )
                        or pending.requester_id != packet.source_id
                        or pending.request != message
                        or key
                        in (
                            state.expected_write_evict_dbid_responses
                            if is_write_evict
                            else state.expected_writeback_dbid_responses
                        )
                    ):
                        return self._fault(
                            state,
                            "copyback_dbid_response_evidence",
                            "Home CompDBIDResp does not select one new "
                            f"{operation_name} reservation",
                        )
                    responses = dict(
                        state.expected_write_evict_dbid_responses
                        if is_write_evict
                        else state.expected_writeback_dbid_responses
                    )
                    responses[key] = response_packet
                    if is_write_evict:
                        expected_write_evict_dbid_responses = responses
                    else:
                        expected_writeback_dbid_responses = responses
                elif isinstance(message, ChiCopyBackWrDataMessage):
                    copyback = dict(state.expected_copyback_data)
                    del copyback[
                        (packet.source_id, message.transaction_id)
                    ]
                    expected_copyback_data = copyback
                elif isinstance(message, ChiCompAckMessage):
                    key = (packet.source_id, message.transaction_id)
                    if key in state.expected_write_evict_or_evict_acks:
                        acks = dict(
                            state.expected_write_evict_or_evict_acks
                        )
                        del acks[key]
                        expected_write_evict_or_evict_acks = acks
                retry_ack_emissions = tuple(
                    emission
                    for emission in transition.emissions
                    if isinstance(
                        emission.message,
                        ChiRetryAckMessage,
                    )
                )
                if len(retry_ack_emissions) > 1:
                    return self._fault(
                        state,
                        "retry_ack_shape",
                        "one Home transition emitted multiple RetryAck "
                        "packets",
                    )
                if retry_ack_emissions:
                    retry_ack_packet = retry_ack_emissions[0]
                    retry_ack = retry_ack_packet.message
                    retained_request = state.request_nodes[
                        retry_ack_packet.target_id
                    ].pending_transactions.get(
                        retry_ack.transaction_id
                    ) if (
                        retry_ack_packet.target_id
                        in state.request_nodes
                    ) else None
                    retry_feature = self._retry_feature(retained_request)
                    key = (
                        retry_ack_packet.target_id,
                        retry_ack.transaction_id,
                    )
                    if (
                        retry_ack_packet.source_id != self.home.node_id
                        or retry_ack_packet.target_id
                        not in self.requester_node_ids
                        or retry_feature is None
                        or retry_feature not in self.enabled_features
                        or key in state.expected_retry_acks
                    ):
                        return self._fault(
                            state,
                            "retry_ack_evidence",
                            "Home RetryAck does not select one new retained "
                            "request with its opcode-specific modifier",
                        )
                    retry_acks = dict(state.expected_retry_acks)
                    retry_acks[key] = retry_ack_packet
                    expected_retry_acks = retry_acks
                if consumed_snoop_response_key is not None:
                    responses = dict(state.expected_snoop_responses)
                    del responses[consumed_snoop_response_key]
                    expected_snoop_responses = responses
                snoop_emissions = tuple(
                    emission
                    for emission in transition.emissions
                    if isinstance(
                        emission.message,
                        _COHERENCE_SNOOP_TYPES,
                    )
                )
                if snoop_emissions:
                    deliveries = dict(
                        state.expected_snoop_deliveries
                    )
                    for emission in snoop_emissions:
                        snoop = emission.message
                        key = (
                            emission.target_id,
                            snoop.transaction_id,
                        )
                        matches = tuple(
                            pending
                            for pending in transition.state.pending.values()
                            if (
                                pending.snoop_transaction_id
                                == snoop.transaction_id
                                and emission.target_id
                                in pending.snoop_targets
                                and pending.request.address
                                == snoop.address
                                and not pending.completion_sent
                                and emission.target_id
                                not in pending.snoop_results
                            )
                        )
                        if (
                            emission.source_id != self.home.node_id
                            or emission.target_id
                            not in self.snoopee_node_ids
                            or len(matches) != 1
                            or key in deliveries
                            or key in expected_snoop_responses
                        ):
                            return self._fault(
                                state,
                                "snoop_emission_evidence",
                                "Home SNP emission does not select one new "
                                "unresolved Snoopee target",
                            )
                        deliveries[key] = emission
                    expected_snoop_deliveries = deliveries
                make_unique_completions = tuple(
                    emission
                    for emission in transition.emissions
                    if isinstance(emission.message, ChiCompMessage)
                    and emission.source_id == self.home.node_id
                    and (
                        pending := transition.state.pending.get(
                            emission.message.data_buffer_id
                        )
                    )
                    is not None
                    and isinstance(
                        pending.request,
                        ChiMakeUniqueMessage,
                    )
                    and pending.completion_sent
                    and pending.requester_id == emission.target_id
                    and pending.request.transaction_id
                    == emission.message.transaction_id
                )
                if len(make_unique_completions) > 1:
                    return self._fault(
                        state,
                        "make_unique_completion_shape",
                        "one Home transition emitted multiple MakeUnique "
                        "completions",
                    )
                if make_unique_completions:
                    completion_packet = make_unique_completions[0]
                    completion = completion_packet.message
                    assert isinstance(completion, ChiCompMessage)
                    key = (
                        completion_packet.target_id,
                        completion.transaction_id,
                    )
                    if key in expected_make_unique_completions:
                        return self._fault(
                            state,
                            "duplicate_make_unique_completion",
                            "Home produced a second completion for one "
                            "MakeUnique transaction",
                        )
                    expected = dict(
                        state.expected_make_unique_completions
                    )
                    expected[key] = completion_packet
                    expected_make_unique_completions = expected
                clean_unique_completions = tuple(
                    emission
                    for emission in transition.emissions
                    if isinstance(emission.message, ChiCompMessage)
                    and emission.source_id == self.home.node_id
                    and (
                        pending := transition.state.pending.get(
                            emission.message.data_buffer_id
                        )
                    )
                    is not None
                    and isinstance(
                        pending.request,
                        ChiCleanUniqueMessage,
                    )
                    and pending.completion_sent
                    and pending.requester_id == emission.target_id
                    and pending.request.transaction_id
                    == emission.message.transaction_id
                )
                if len(clean_unique_completions) > 1:
                    return self._fault(
                        state,
                        "clean_unique_completion_shape",
                        "one Home transition emitted multiple CleanUnique "
                        "completions",
                    )
                if clean_unique_completions:
                    completion_packet = clean_unique_completions[0]
                    completion = completion_packet.message
                    assert isinstance(completion, ChiCompMessage)
                    key = (
                        completion_packet.target_id,
                        completion.transaction_id,
                    )
                    if key in expected_clean_unique_completions:
                        return self._fault(
                            state,
                            "duplicate_clean_unique_completion",
                            "Home produced a second completion for one "
                            "CleanUnique transaction",
                        )
                    expected = dict(
                        state.expected_clean_unique_completions
                    )
                    expected[key] = completion_packet
                    expected_clean_unique_completions = expected
                coherent_read_completions = tuple(
                    emission
                    for emission in transition.emissions
                    if isinstance(
                        emission.message,
                        ChiCompDataMessage,
                    )
                )
                if len(coherent_read_completions) > 1:
                    return self._fault(
                        state,
                        "coherent_read_completion_shape",
                        "one Home transition emitted multiple coherent-read "
                        "completions",
                    )
                if coherent_read_completions:
                    completion_packet = coherent_read_completions[0]
                    completion = completion_packet.message
                    assert isinstance(completion, ChiCompDataMessage)
                    pending = transition.state.pending.get(
                        completion.data_buffer_id
                    )
                    if (
                        completion_packet.source_id != self.home.node_id
                        or completion_packet.target_id
                        not in self.requester_node_ids
                        or pending is None
                        or not isinstance(
                            pending.request,
                            _COHERENT_READ_TYPES,
                        )
                        or not pending.completion_sent
                        or pending.requester_id
                        != completion_packet.target_id
                        or pending.request.transaction_id
                        != completion.transaction_id
                        or pending.completion_response_error
                        is not completion.response_error
                    ):
                        return self._fault(
                            state,
                            "coherent_read_completion_evidence",
                            "Home CompData emission does not select one "
                            "completed coherent-read reservation",
                        )
                    key = (
                        completion_packet.target_id,
                        completion.transaction_id,
                    )
                    if key in expected_coherent_read_completions:
                        return self._fault(
                            state,
                            "duplicate_coherent_read_completion",
                            "Home produced a second completion for one "
                            "coherent-read transaction",
                        )
                    expected = dict(
                        state.expected_coherent_read_completions
                    )
                    expected[key] = completion_packet
                    expected_coherent_read_completions = expected
            candidate = ChiCoherenceState(
                home=transition.state,
                request_nodes=state.request_nodes,
                expected_evict_completions=(
                    expected_evict_completions
                ),
                expected_clean_unique_completions=(
                    expected_clean_unique_completions
                ),
                expected_make_unique_completions=(
                    expected_make_unique_completions
                ),
                expected_coherent_read_completions=(
                    expected_coherent_read_completions
                ),
                expected_writeback_dbid_responses=(
                    expected_writeback_dbid_responses
                ),
                expected_write_evict_dbid_responses=(
                    expected_write_evict_dbid_responses
                ),
                expected_write_evict_or_evict_responses=(
                    expected_write_evict_or_evict_responses
                ),
                expected_copyback_data=expected_copyback_data,
                expected_write_evict_or_evict_acks=(
                    expected_write_evict_or_evict_acks
                ),
                expected_retry_acks=expected_retry_acks,
                expected_pcredit_grants=expected_pcredit_grants,
                expected_snoop_deliveries=(
                    expected_snoop_deliveries
                ),
                expected_snoop_responses=(
                    expected_snoop_responses
                ),
            )
            return self._finish(candidate, transition)

        node = self.request_nodes.get(packet.target_id)
        if node is None:
            return self._fault(
                state,
                "target_identity",
                f"packet targets unknown NodeID {packet.target_id}",
            )
        if isinstance(
            message,
            (
                ChiSnpCleanInvalidMessage,
                ChiSnpMakeInvalidMessage,
                ChiSnpSharedMessage,
                ChiSnpNotSharedDirtyMessage,
                ChiSnpUniqueMessage,
            ),
        ):
            if packet.target_id not in self.snoopee_node_ids:
                return self._fault(
                    state,
                    "snoopee_authority",
                    f"NodeID {packet.target_id} is not a Snoopee "
                    "of this construction",
                )
            if self._snoop_feature(message) not in self.enabled_features:
                return self._fault(
                    state,
                    "feature_enablement",
                    f"{type(message).__name__} is not enabled by the "
                    "resolved feature contract",
                )
            matches = tuple(
                pending
                for pending in state.home.pending.values()
                if (
                    pending.snoop_transaction_id
                    == message.transaction_id
                    and packet.target_id in pending.snoop_targets
                    and pending.request.address == message.address
                    and not pending.completion_sent
                    and packet.target_id
                    not in pending.snoop_results
                )
            )
            snoop_key = (
                packet.target_id,
                message.transaction_id,
            )
            if (
                len(matches) != 1
                or state.expected_snoop_deliveries.get(snoop_key)
                != packet
            ):
                return self._fault(
                    state,
                    "snoop_delivery_correlation",
                    "Snoop packet does not exactly match one pending "
                    "Home-issued target delivery",
                )
            transition = node.step(
                state.request_nodes[packet.target_id],
                ChiRnAcceptSnoop(packet),
            )
            deliveries = state.expected_snoop_deliveries
            responses = state.expected_snoop_responses
            if (
                transition.fault is None
                and transition.blocked is None
            ):
                if (
                    len(transition.emissions) != 1
                    or not isinstance(
                        transition.emissions[0].message,
                        _COHERENCE_SNOOP_RESPONSE_TYPES,
                    )
                    or transition.emissions[0].source_id
                    != packet.target_id
                    or transition.emissions[0].target_id
                    != self.home.node_id
                    or transition.emissions[0].message.transaction_id
                    != message.transaction_id
                ):
                    return self._fault(
                        state,
                        "snoop_response_emission",
                        "RN Snoop acceptance must emit one exactly "
                        "correlated RSP or DAT packet",
                    )
                updated_deliveries = dict(
                    state.expected_snoop_deliveries
                )
                del updated_deliveries[snoop_key]
                updated_responses = dict(
                    state.expected_snoop_responses
                )
                if snoop_key in updated_responses:
                    return self._fault(
                        state,
                        "duplicate_snoop_response",
                        "Snoopee already has an expected response for "
                        "this Snoop identity",
                    )
                updated_responses[snoop_key] = transition.emissions[0]
                deliveries = updated_deliveries
                responses = updated_responses
            states = dict(state.request_nodes)
            states[packet.target_id] = transition.state
            candidate = ChiCoherenceState(
                home=state.home,
                request_nodes=states,
                expected_evict_completions=(
                    state.expected_evict_completions
                ),
                expected_clean_unique_completions=(
                    state.expected_clean_unique_completions
                ),
                expected_make_unique_completions=(
                    state.expected_make_unique_completions
                ),
                expected_coherent_read_completions=(
                    state.expected_coherent_read_completions
                ),
                expected_writeback_dbid_responses=(
                    state.expected_writeback_dbid_responses
                ),
                expected_write_evict_dbid_responses=(
                    state.expected_write_evict_dbid_responses
                ),
                expected_write_evict_or_evict_responses=(
                    state.expected_write_evict_or_evict_responses
                ),
                expected_copyback_data=state.expected_copyback_data,
                expected_write_evict_or_evict_acks=(
                    state.expected_write_evict_or_evict_acks
                ),
                expected_retry_acks=state.expected_retry_acks,
                expected_pcredit_grants=(
                    state.expected_pcredit_grants
                ),
                expected_snoop_deliveries=deliveries,
                expected_snoop_responses=responses,
            )
            return self._finish(candidate, transition)
        elif isinstance(message, ChiRetryAckMessage):
            if packet.target_id not in self.requester_node_ids:
                return self._fault(
                    state,
                    "requester_authority",
                    f"NodeID {packet.target_id} cannot receive RetryAck "
                    "in this construction",
                )
            retained_request = state.request_nodes[
                packet.target_id
            ].pending_transactions.get(message.transaction_id)
            retry_feature = self._retry_feature(retained_request)
            if (
                retry_feature is None
                or retry_feature not in self.enabled_features
            ):
                return self._fault(
                    state,
                    "retry_feature",
                    "RetryAck does not match a retained request whose "
                    "opcode-specific Retry modifier is enabled",
                )
            if packet.source_id != self.home.node_id:
                return self._fault(
                    state,
                    "retry_home",
                    "RetryAck does not come from the selected Home",
                )
            if (
                state.expected_retry_acks.get(
                    (packet.target_id, message.transaction_id)
                )
                != packet
            ):
                return self._fault(
                    state,
                    "retry_ack_correlation",
                    "RetryAck does not exactly match a Home-produced "
                    "response",
                )
            action = ChiRnAcceptRetryAck(packet)
        elif isinstance(message, ChiPCrdGrantMessage):
            if packet.target_id not in self.requester_node_ids:
                return self._fault(
                    state,
                    "requester_authority",
                    f"NodeID {packet.target_id} cannot receive PCrdGrant "
                    "in this construction",
                )
            if (
                not self.enabled_features & _COHERENCE_RETRY_FEATURES
            ):
                return self._fault(
                    state,
                    "retry_feature",
                    "PCrdGrant is not enabled by an opcode-specific "
                    "Request-Retry modifier",
                )
            if packet.source_id != self.home.node_id:
                return self._fault(
                    state,
                    "retry_home",
                    "PCrdGrant does not come from the selected Home",
                )
            if packet not in state.expected_pcredit_grants:
                return self._fault(
                    state,
                    "pcredit_grant_correlation",
                    "PCrdGrant does not exactly match a Home-produced grant",
                )
            action = ChiRnAcceptPCrdGrant(packet)
        elif isinstance(message, ChiCompMessage):
            if packet.target_id not in self.requester_node_ids:
                return self._fault(
                    state,
                    "requester_authority",
                    f"NodeID {packet.target_id} cannot receive Comp "
                    "in this construction",
                )
            write_evict_or_evict_pending = state.request_nodes[
                packet.target_id
            ].pending_copybacks.get(message.transaction_id)
            home_write_evict_or_evict_pending = (
                state.home.pending_copybacks.get(
                    message.data_buffer_id
                )
            )
            if isinstance(
                write_evict_or_evict_pending,
                ChiRnWriteEvictOrEvictPending,
            ):
                response_key = (
                    packet.target_id,
                    message.transaction_id,
                )
                if (
                    CHI_FEATURE_WRITE_EVICT_OR_EVICT
                    not in self.enabled_features
                    or packet.source_id != self.home.node_id
                    or state.expected_write_evict_or_evict_responses.get(
                        response_key
                    )
                    != packet
                ):
                    return self._fault(
                        state,
                        "write_evict_or_evict_completion_correlation",
                        "Comp does not exactly match one Home-produced "
                        "WriteEvictOrEvict no-data outcome",
                    )
                transition = node.step(
                    state.request_nodes[packet.target_id],
                    ChiRnAcceptComp(packet),
                )
                responses = dict(
                    state.expected_write_evict_or_evict_responses
                )
                acks = dict(
                    state.expected_write_evict_or_evict_acks
                )
                if (
                    transition.fault is None
                    and transition.blocked is None
                ):
                    if (
                        len(transition.emissions) != 1
                        or not isinstance(
                            transition.emissions[0].message,
                            ChiCompAckMessage,
                        )
                    ):
                        return self._fault(
                            state,
                            "write_evict_or_evict_ack_shape",
                            "RN no-data completion must emit exactly one "
                            "CompAck",
                        )
                    ack_packet = transition.emissions[0]
                    ack = ack_packet.message
                    ack_key = (
                        ack_packet.source_id,
                        ack.transaction_id,
                    )
                    if (
                        ack_packet.source_id != packet.target_id
                        or ack_packet.target_id != self.home.node_id
                        or ack_packet.packet_index != 0
                        or ack_packet.packet_count != 1
                        or ack.transaction_id != message.data_buffer_id
                        or ack.response
                        != (
                            ChiRespCode.I
                            if write_evict_or_evict_pending.outcome
                            is ChiRnCopyBackOutcome.CANCELED_I
                            else (
                                ChiRespCode.SC
                                if write_evict_or_evict_pending
                                .request.likely_shared
                                else ChiRespCode.UC
                            )
                        )
                        or ack_key in acks
                    ):
                        return self._fault(
                            state,
                            "write_evict_or_evict_ack_evidence",
                            "RN CompAck does not select the consumed Home "
                            "DBID and post-Snoop outcome",
                        )
                    del responses[response_key]
                    acks[ack_key] = ack_packet
                states = dict(state.request_nodes)
                states[packet.target_id] = transition.state
                candidate = ChiCoherenceState(
                    home=state.home,
                    request_nodes=states,
                    expected_evict_completions=(
                        state.expected_evict_completions
                    ),
                    expected_clean_unique_completions=(
                        state.expected_clean_unique_completions
                    ),
                    expected_make_unique_completions=(
                        state.expected_make_unique_completions
                    ),
                    expected_coherent_read_completions=(
                        state.expected_coherent_read_completions
                    ),
                    expected_writeback_dbid_responses=(
                        state.expected_writeback_dbid_responses
                    ),
                    expected_write_evict_dbid_responses=(
                        state.expected_write_evict_dbid_responses
                    ),
                    expected_write_evict_or_evict_responses=responses,
                    expected_copyback_data=state.expected_copyback_data,
                    expected_write_evict_or_evict_acks=acks,
                    expected_retry_acks=state.expected_retry_acks,
                    expected_pcredit_grants=(
                        state.expected_pcredit_grants
                    ),
                    expected_snoop_deliveries=(
                        state.expected_snoop_deliveries
                    ),
                    expected_snoop_responses=(
                        state.expected_snoop_responses
                    ),
                )
                return self._finish(candidate, transition)
            if isinstance(
                home_write_evict_or_evict_pending,
                ChiHomeWriteEvictOrEvictPending,
            ) and (
                home_write_evict_or_evict_pending.requester_id
                == packet.target_id
                and home_write_evict_or_evict_pending.request.transaction_id
                == message.transaction_id
            ):
                return self._fault(
                    state,
                    "write_evict_or_evict_completion_correlation",
                    "Comp replays a Home WriteEvictOrEvict outcome whose "
                    "Requester response phase already completed",
                )
            pending_request = state.request_nodes[
                packet.target_id
            ].pending_transactions.get(message.transaction_id)
            if isinstance(pending_request, ChiEvictMessage):
                if CHI_FEATURE_CLEAN_EVICT not in self.enabled_features:
                    return self._fault(
                        state,
                        "feature_enablement",
                        "Comp_I is not enabled by the clean Evict feature",
                    )
                expected = state.expected_evict_completions.get(
                    (packet.target_id, message.transaction_id)
                )
                if (
                    packet.source_id != self.home.node_id
                    or expected != packet
                ):
                    return self._fault(
                        state,
                        "evict_completion_correlation",
                        "Comp_I does not match a Home-produced Evict "
                        "completion",
                    )
                action = ChiRnAcceptComp(packet)
                transition = node.step(
                    state.request_nodes[packet.target_id],
                    action,
                )
                states = dict(state.request_nodes)
                states[packet.target_id] = transition.state
                completions = dict(state.expected_evict_completions)
                if (
                    transition.fault is None
                    and transition.blocked is None
                ):
                    del completions[
                        (packet.target_id, message.transaction_id)
                    ]
                candidate = ChiCoherenceState(
                    home=state.home,
                    request_nodes=states,
                    expected_evict_completions=completions,
                    expected_clean_unique_completions=(
                        state.expected_clean_unique_completions
                    ),
                    expected_make_unique_completions=(
                        state.expected_make_unique_completions
                    ),
                    expected_coherent_read_completions=(
                        state.expected_coherent_read_completions
                    ),
                    expected_writeback_dbid_responses=(
                        state.expected_writeback_dbid_responses
                    ),
                    expected_write_evict_dbid_responses=(
                        state.expected_write_evict_dbid_responses
                    ),
                    expected_write_evict_or_evict_responses=(
                        state.expected_write_evict_or_evict_responses
                    ),
                    expected_copyback_data=state.expected_copyback_data,
                    expected_write_evict_or_evict_acks=(
                        state.expected_write_evict_or_evict_acks
                    ),
                    expected_retry_acks=state.expected_retry_acks,
                    expected_pcredit_grants=(
                        state.expected_pcredit_grants
                    ),
                    expected_snoop_deliveries=(
                        state.expected_snoop_deliveries
                    ),
                    expected_snoop_responses=(
                        state.expected_snoop_responses
                    ),
                )
                return self._finish(candidate, transition)
            if isinstance(pending_request, ChiMakeUniqueMessage):
                if CHI_FEATURE_MAKE_UNIQUE not in self.enabled_features:
                    return self._fault(
                        state,
                        "feature_enablement",
                        "MakeUnique Comp_UC is not enabled by the resolved "
                        "feature contract",
                    )
                expected = state.expected_make_unique_completions.get(
                    (packet.target_id, message.transaction_id)
                )
                if (
                    packet.source_id != self.home.node_id
                    or expected != packet
                ):
                    return self._fault(
                        state,
                        "make_unique_completion_correlation",
                        "Comp_UC does not exactly match the Home-produced "
                        "MakeUnique completion",
                    )
                transition = node.step(
                    state.request_nodes[packet.target_id],
                    ChiRnAcceptComp(packet),
                )
                states = dict(state.request_nodes)
                states[packet.target_id] = transition.state
                completions = dict(
                    state.expected_make_unique_completions
                )
                if (
                    transition.fault is None
                    and transition.blocked is None
                ):
                    del completions[
                        (packet.target_id, message.transaction_id)
                    ]
                candidate = ChiCoherenceState(
                    home=state.home,
                    request_nodes=states,
                    expected_evict_completions=(
                        state.expected_evict_completions
                    ),
                    expected_clean_unique_completions=(
                        state.expected_clean_unique_completions
                    ),
                    expected_make_unique_completions=completions,
                    expected_coherent_read_completions=(
                        state.expected_coherent_read_completions
                    ),
                    expected_writeback_dbid_responses=(
                        state.expected_writeback_dbid_responses
                    ),
                    expected_write_evict_dbid_responses=(
                        state.expected_write_evict_dbid_responses
                    ),
                    expected_write_evict_or_evict_responses=(
                        state.expected_write_evict_or_evict_responses
                    ),
                    expected_copyback_data=state.expected_copyback_data,
                    expected_write_evict_or_evict_acks=(
                        state.expected_write_evict_or_evict_acks
                    ),
                    expected_retry_acks=state.expected_retry_acks,
                    expected_pcredit_grants=(
                        state.expected_pcredit_grants
                    ),
                    expected_snoop_deliveries=(
                        state.expected_snoop_deliveries
                    ),
                    expected_snoop_responses=(
                        state.expected_snoop_responses
                    ),
                )
                return self._finish(candidate, transition)
            if not isinstance(pending_request, ChiCleanUniqueMessage):
                return self._fault(
                    state,
                    "dataless_completion_correlation",
                    "Comp does not match an outstanding dataless request",
                )
            if (
                CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
                not in self.enabled_features
            ):
                return self._fault(
                    state,
                    "feature_enablement",
                    "Comp_UC is not enabled by the resolved feature contract",
                )
            expected = state.expected_clean_unique_completions.get(
                (packet.target_id, message.transaction_id)
            )
            if (
                packet.source_id != self.home.node_id
                or expected != packet
            ):
                return self._fault(
                    state,
                    "clean_unique_completion_correlation",
                    "Comp_UC does not exactly match the Home-produced "
                    "CleanUnique completion",
                )
            transition = node.step(
                state.request_nodes[packet.target_id],
                ChiRnAcceptComp(packet),
            )
            states = dict(state.request_nodes)
            states[packet.target_id] = transition.state
            completions = dict(
                state.expected_clean_unique_completions
            )
            if (
                transition.fault is None
                and transition.blocked is None
            ):
                del completions[
                    (packet.target_id, message.transaction_id)
                ]
            candidate = ChiCoherenceState(
                home=state.home,
                request_nodes=states,
                expected_evict_completions=(
                    state.expected_evict_completions
                ),
                expected_clean_unique_completions=completions,
                expected_make_unique_completions=(
                    state.expected_make_unique_completions
                ),
                expected_coherent_read_completions=(
                    state.expected_coherent_read_completions
                ),
                expected_writeback_dbid_responses=(
                    state.expected_writeback_dbid_responses
                ),
                expected_write_evict_dbid_responses=(
                    state.expected_write_evict_dbid_responses
                ),
                expected_write_evict_or_evict_responses=(
                    state.expected_write_evict_or_evict_responses
                ),
                expected_copyback_data=state.expected_copyback_data,
                expected_write_evict_or_evict_acks=(
                    state.expected_write_evict_or_evict_acks
                ),
                expected_retry_acks=state.expected_retry_acks,
                expected_pcredit_grants=(
                    state.expected_pcredit_grants
                ),
                expected_snoop_deliveries=(
                    state.expected_snoop_deliveries
                ),
                expected_snoop_responses=(
                    state.expected_snoop_responses
                ),
            )
            return self._finish(candidate, transition)
        elif isinstance(message, ChiCompDataMessage):
            if packet.target_id not in self.requester_node_ids:
                return self._fault(
                    state,
                    "requester_authority",
                    f"NodeID {packet.target_id} cannot receive CompData "
                    "in this construction",
                )
            pending_request = state.request_nodes[
                packet.target_id
            ].pending_transactions.get(message.transaction_id)
            if isinstance(pending_request, ChiMakeUniqueMessage):
                return self._fault(
                    state,
                    "make_unique_completion_data",
                    "MakeUnique is Dataless and cannot complete on DAT",
                )
            if (
                message.response_error is ChiRespErr.NDERR
                and CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR
                not in self.enabled_features
            ):
                return self._fault(
                    state,
                    "read_unique_nderr_feature",
                    "ReadUnique NDERR completion is not enabled by the "
                    "resolved feature contract",
                )
            expected = state.expected_coherent_read_completions.get(
                (packet.target_id, message.transaction_id)
            )
            if (
                packet.source_id != self.home.node_id
                or not isinstance(
                    pending_request,
                    _COHERENT_READ_TYPES,
                )
                or expected != packet
            ):
                return self._fault(
                    state,
                    "completion_correlation",
                    "CompData does not exactly match one Home-produced "
                    "Requester/TxnID/DBID/RespErr completion packet",
                )
            transition = node.step(
                state.request_nodes[packet.target_id],
                ChiRnAcceptCompData(packet),
            )
            states = dict(state.request_nodes)
            states[packet.target_id] = transition.state
            completions = dict(
                state.expected_coherent_read_completions
            )
            if (
                transition.fault is None
                and transition.blocked is None
            ):
                del completions[
                    (packet.target_id, message.transaction_id)
                ]
            candidate = ChiCoherenceState(
                home=state.home,
                request_nodes=states,
                expected_evict_completions=(
                    state.expected_evict_completions
                ),
                expected_clean_unique_completions=(
                    state.expected_clean_unique_completions
                ),
                expected_make_unique_completions=(
                    state.expected_make_unique_completions
                ),
                expected_coherent_read_completions=completions,
                expected_writeback_dbid_responses=(
                    state.expected_writeback_dbid_responses
                ),
                expected_write_evict_dbid_responses=(
                    state.expected_write_evict_dbid_responses
                ),
                expected_write_evict_or_evict_responses=(
                    state.expected_write_evict_or_evict_responses
                ),
                expected_copyback_data=state.expected_copyback_data,
                expected_write_evict_or_evict_acks=(
                    state.expected_write_evict_or_evict_acks
                ),
                expected_retry_acks=state.expected_retry_acks,
                expected_pcredit_grants=(
                    state.expected_pcredit_grants
                ),
                expected_snoop_deliveries=(
                    state.expected_snoop_deliveries
                ),
                expected_snoop_responses=(
                    state.expected_snoop_responses
                ),
            )
            return self._finish(candidate, transition)
        elif isinstance(message, ChiCompDBIDRespMessage):
            if packet.target_id not in self.requester_node_ids:
                return self._fault(
                    state,
                    "requester_authority",
                    f"NodeID {packet.target_id} cannot receive "
                    "CompDBIDResp in this construction",
                )
            response_key = (
                packet.target_id,
                message.transaction_id,
            )
            write_evict_key = (
                response_key
                in state.expected_write_evict_dbid_responses
            )
            writeback_key = (
                response_key
                in state.expected_writeback_dbid_responses
            )
            write_evict_or_evict_key = (
                response_key
                in state.expected_write_evict_or_evict_responses
            )
            response_kinds = (
                write_evict_key,
                writeback_key,
                write_evict_or_evict_key,
            )
            requester_copyback = state.request_nodes[
                packet.target_id
            ].pending_copybacks.get(message.transaction_id)
            home_copyback = state.home.pending_copybacks.get(
                message.data_buffer_id
            )
            enabled_copyback_features = self.enabled_features & {
                CHI_FEATURE_DIRTY_WRITEBACK,
                CHI_FEATURE_WRITE_EVICT_FULL,
                CHI_FEATURE_WRITE_EVICT_OR_EVICT,
            }
            sole_copyback_feature = (
                next(iter(enabled_copyback_features))
                if len(enabled_copyback_features) == 1
                else None
            )
            correlation_rule = (
                "write_evict_or_evict_response_correlation"
                if (
                    write_evict_or_evict_key
                    or isinstance(
                        requester_copyback,
                        ChiRnWriteEvictOrEvictPending,
                    )
                    or isinstance(
                        home_copyback,
                        ChiHomeWriteEvictOrEvictPending,
                    )
                    and sole_copyback_feature
                    is CHI_FEATURE_WRITE_EVICT_OR_EVICT
                )
                else (
                    "write_evict_dbid_response_correlation"
                    if (
                        write_evict_key
                        or isinstance(
                            requester_copyback,
                            ChiRnWriteEvictPending,
                        )
                        or isinstance(
                            home_copyback,
                            ChiHomeWriteEvictPending,
                        )
                        and sole_copyback_feature
                        is CHI_FEATURE_WRITE_EVICT_FULL
                    )
                    else (
                        "writeback_dbid_response_correlation"
                        if (
                            writeback_key
                            or isinstance(
                                requester_copyback,
                                ChiRnWriteBackPending,
                            )
                            or isinstance(
                                home_copyback,
                                ChiHomeWriteBackPending,
                            )
                            and sole_copyback_feature
                            is CHI_FEATURE_DIRTY_WRITEBACK
                        )
                        else "copyback_dbid_response_correlation"
                    )
                )
            )
            if sum(response_kinds) != 1:
                return self._fault(
                    state,
                    correlation_rule,
                    "CompDBIDResp does not select exactly one pending "
                    "CopyBack response class",
                )
            if write_evict_or_evict_key:
                expected_response = (
                    state.expected_write_evict_or_evict_responses[
                        response_key
                    ]
                )
                response_feature = CHI_FEATURE_WRITE_EVICT_OR_EVICT
            elif write_evict_key:
                expected_response = (
                    state.expected_write_evict_dbid_responses[
                        response_key
                    ]
                )
                response_feature = CHI_FEATURE_WRITE_EVICT_FULL
            else:
                expected_response = (
                    state.expected_writeback_dbid_responses[response_key]
                )
                response_feature = CHI_FEATURE_DIRTY_WRITEBACK
            if expected_response != packet:
                return self._fault(
                    state,
                    correlation_rule,
                    "CompDBIDResp does not exactly match the Home-produced "
                    "response",
                )
            if response_feature not in self.enabled_features:
                return self._fault(
                    state,
                    "feature_enablement",
                    "CompDBIDResp is not enabled by the resolved feature "
                    "contract",
                )
            action = ChiRnAcceptCompDBIDResp(packet)
        else:
            return self._fault(
                state,
                "rn_dispatch",
                f"Request Node cannot consume {type(message).__name__}",
            )
        transition = node.step(state.request_nodes[packet.target_id], action)
        expected_writeback_dbid_responses = (
            state.expected_writeback_dbid_responses
        )
        expected_write_evict_dbid_responses = (
            state.expected_write_evict_dbid_responses
        )
        expected_write_evict_or_evict_responses = (
            state.expected_write_evict_or_evict_responses
        )
        expected_copyback_data = state.expected_copyback_data
        expected_write_evict_or_evict_acks = (
            state.expected_write_evict_or_evict_acks
        )
        expected_retry_acks = state.expected_retry_acks
        expected_pcredit_grants = state.expected_pcredit_grants
        if (
            transition.fault is None
            and transition.blocked is None
            and isinstance(message, ChiCompDBIDRespMessage)
        ):
            if (
                len(transition.emissions) != 1
                or not isinstance(
                    transition.emissions[0].message,
                    ChiCopyBackWrDataMessage,
                )
            ):
                return self._fault(
                    state,
                    "copyback_emission_shape",
                    "RN CompDBIDResp acceptance must emit exactly one "
                    "CopyBackWrData",
                )
            data_packet = transition.emissions[0]
            data_message = data_packet.message
            key = (data_packet.source_id, data_message.transaction_id)
            if (
                data_packet.source_id != packet.target_id
                or data_packet.target_id != self.home.node_id
                or data_packet.packet_index != 0
                or data_packet.packet_count != 1
                or data_message.transaction_id
                != message.data_buffer_id
                or key in state.expected_copyback_data
            ):
                return self._fault(
                    state,
                    "copyback_emission_evidence",
                    "RN CopyBackWrData does not select the consumed Home "
                    "DBID response",
                )
            if write_evict_or_evict_key:
                dbid_responses = dict(
                    state.expected_write_evict_or_evict_responses
                )
            elif write_evict_key:
                dbid_responses = dict(
                    state.expected_write_evict_dbid_responses
                )
            else:
                dbid_responses = dict(
                    state.expected_writeback_dbid_responses
                )
            del dbid_responses[response_key]
            if write_evict_or_evict_key:
                expected_write_evict_or_evict_responses = dbid_responses
            elif write_evict_key:
                expected_write_evict_dbid_responses = dbid_responses
            else:
                expected_writeback_dbid_responses = dbid_responses
            copyback = dict(state.expected_copyback_data)
            copyback[key] = data_packet
            expected_copyback_data = copyback
        elif (
            transition.fault is None
            and transition.blocked is None
            and isinstance(message, ChiRetryAckMessage)
        ):
            retry_acks = dict(state.expected_retry_acks)
            del retry_acks[(packet.target_id, message.transaction_id)]
            expected_retry_acks = retry_acks
        elif (
            transition.fault is None
            and transition.blocked is None
            and isinstance(message, ChiPCrdGrantMessage)
        ):
            grants = list(state.expected_pcredit_grants)
            grants.remove(packet)
            expected_pcredit_grants = tuple(grants)
        if isinstance(
            message,
            (
                ChiCompDBIDRespMessage,
                ChiRetryAckMessage,
                ChiPCrdGrantMessage,
            ),
        ):
            states = dict(state.request_nodes)
            states[packet.target_id] = transition.state
            candidate = ChiCoherenceState(
                home=state.home,
                request_nodes=states,
                expected_evict_completions=(
                    state.expected_evict_completions
                ),
                expected_clean_unique_completions=(
                    state.expected_clean_unique_completions
                ),
                expected_make_unique_completions=(
                    state.expected_make_unique_completions
                ),
                expected_coherent_read_completions=(
                    state.expected_coherent_read_completions
                ),
                expected_writeback_dbid_responses=(
                    expected_writeback_dbid_responses
                ),
                expected_write_evict_dbid_responses=(
                    expected_write_evict_dbid_responses
                ),
                expected_write_evict_or_evict_responses=(
                    expected_write_evict_or_evict_responses
                ),
                expected_copyback_data=expected_copyback_data,
                expected_write_evict_or_evict_acks=(
                    expected_write_evict_or_evict_acks
                ),
                expected_retry_acks=expected_retry_acks,
                expected_pcredit_grants=expected_pcredit_grants,
                expected_snoop_deliveries=(
                    state.expected_snoop_deliveries
                ),
                expected_snoop_responses=(
                    state.expected_snoop_responses
                ),
            )
            return self._finish(candidate, transition)
        return self._replace_request_node(state, packet.target_id, transition)

    def _address_authority_fault(
        self,
        address: int,
        size_bytes: int,
    ) -> SemanticFault | None:
        """Reject traffic outside this resolved feature address scope."""

        if self.authority_window is None:
            return None
        transfer = AddressWindow(address, size_bytes)
        if self.authority_window.contains(transfer):
            return None
        return SemanticFault(
            f"{self.name}.address_authority",
            (
                f"address range {address:#x}+{size_bytes:#x} is outside "
                "the Home authority selected for this construction"
            ),
            ConstraintScope.SYSTEM,
            self.name,
        )

    @staticmethod
    def _request_feature(
        request: (
            ChiMakeUniqueMessage
            | ChiReadSharedMessage
            | ChiReadNotSharedDirtyMessage
            | ChiReadUniqueMessage
        ),
    ) -> ChiFeatureKey:
        if isinstance(request, ChiMakeUniqueMessage):
            return CHI_FEATURE_MAKE_UNIQUE
        if isinstance(request, ChiReadUniqueMessage):
            return CHI_FEATURE_CLEAN_READ_UNIQUE
        if isinstance(request, ChiReadNotSharedDirtyMessage):
            return CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY
        return CHI_FEATURE_CLEAN_READ_SHARED

    @staticmethod
    def _retry_feature(request: object) -> ChiFeatureKey | None:
        if isinstance(request, ChiReadUniqueMessage):
            return CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY
        if isinstance(request, ChiEvictMessage):
            return CHI_FEATURE_CLEAN_EVICT_RETRY
        return None

    def _retry_request_delivery_fault(
        self,
        state: ChiCoherenceState,
        packet: ChiNetworkPacket,
        request: ChiReadUniqueMessage | ChiEvictMessage,
    ) -> SemanticFault | None:
        requester_state = state.request_nodes[packet.source_id]
        entry = requester_state.request_retry.entries.get(
            request.transaction_id
        )
        expected_phase = (
            ChiRequestRetryPhase.INITIAL_IN_FLIGHT
            if request.allow_retry
            else ChiRequestRetryPhase.RETRIED_IN_FLIGHT
        )
        if (
            entry is None
            or entry.home_node_id != self.home.node_id
            or entry.current_request != request
            or entry.phase is not expected_phase
        ):
            return SemanticFault(
                f"{self.name}.retry_request_delivery",
                (
                    f"{type(request).__name__} does not match the retained "
                    f"Requester form in {expected_phase.value}"
                ),
                ConstraintScope.SYSTEM,
                self.name,
            )
        if (
            request.allow_retry
            and (
                packet.source_id,
                request.transaction_id,
            )
            in state.expected_retry_acks
        ):
            return SemanticFault(
                f"{self.name}.retry_request_replay",
                (
                    f"initial {type(request).__name__} already produced an "
                    "undelivered RetryAck"
                ),
                ConstraintScope.SYSTEM,
                self.name,
            )
        return None

    @staticmethod
    def _snoop_feature(
        snoop: (
            ChiSnpCleanInvalidMessage
            | ChiSnpMakeInvalidMessage
            | ChiSnpSharedMessage
            | ChiSnpNotSharedDirtyMessage
            | ChiSnpUniqueMessage
        ),
    ) -> ChiFeatureKey:
        if isinstance(snoop, ChiSnpMakeInvalidMessage):
            return CHI_FEATURE_MAKE_UNIQUE
        if isinstance(snoop, ChiSnpCleanInvalidMessage):
            return CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS
        if isinstance(snoop, ChiSnpUniqueMessage):
            return CHI_FEATURE_CLEAN_READ_UNIQUE
        if isinstance(snoop, ChiSnpNotSharedDirtyMessage):
            return CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY
        return CHI_FEATURE_CLEAN_READ_SHARED

    def _replace_request_node(
        self,
        state: ChiCoherenceState,
        node_id: int,
        transition: SemanticStep[ChiCoherentRnState, ChiNetworkPacket],
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        states = dict(state.request_nodes)
        states[node_id] = transition.state
        candidate = ChiCoherenceState(
            home=state.home,
            request_nodes=states,
            expected_evict_completions=(
                state.expected_evict_completions
            ),
            expected_clean_unique_completions=(
                state.expected_clean_unique_completions
            ),
            expected_make_unique_completions=(
                state.expected_make_unique_completions
            ),
            expected_coherent_read_completions=(
                state.expected_coherent_read_completions
            ),
            expected_writeback_dbid_responses=(
                state.expected_writeback_dbid_responses
            ),
            expected_write_evict_dbid_responses=(
                state.expected_write_evict_dbid_responses
            ),
            expected_write_evict_or_evict_responses=(
                state.expected_write_evict_or_evict_responses
            ),
            expected_copyback_data=state.expected_copyback_data,
            expected_write_evict_or_evict_acks=(
                state.expected_write_evict_or_evict_acks
            ),
            expected_retry_acks=state.expected_retry_acks,
            expected_pcredit_grants=state.expected_pcredit_grants,
            expected_snoop_deliveries=(
                state.expected_snoop_deliveries
            ),
            expected_snoop_responses=state.expected_snoop_responses,
        )
        return self._finish(candidate, transition)

    def _finish(
        self,
        candidate: ChiCoherenceState,
        transition: SemanticStep[object, ChiNetworkPacket],
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        if transition.fault is not None or transition.blocked is not None:
            return SemanticStep(
                candidate,
                transition.emissions,
                transition.fault,
                transition.causal_predecessors,
                transition.blocked,
            )
        if self.is_quiescent(candidate):
            reasons = self.monitor.explain(
                candidate.home,
                candidate.request_nodes,
            )
            if reasons:
                return self._fault(
                    candidate,
                    "stable_coherence",
                    "; ".join(reasons),
                )
        return SemanticStep(
            candidate,
            transition.emissions,
            causal_predecessors=transition.causal_predecessors,
        )

    def _fault(
        self,
        state: ChiCoherenceState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiCoherenceState, ChiNetworkPacket]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                ConstraintScope.SYSTEM,
                self.name,
            ),
        )


__all__ = [
    "ChiCoherenceAction",
    "ChiCoherenceInvariantMonitor",
    "ChiCoherenceSession",
    "ChiCoherenceState",
    "ChiDeliverCoherencePacket",
    "ChiGrantCoherentHomePCredit",
    "ChiRetryCoherentRequest",
    "ChiSubmitCleanUnique",
    "ChiSubmitCoherentRead",
    "ChiSubmitEvict",
    "ChiSubmitMakeUnique",
    "ChiSubmitWriteEvictFull",
    "ChiSubmitWriteBackFull",
    "ChiWriteUniqueCacheLine",
]

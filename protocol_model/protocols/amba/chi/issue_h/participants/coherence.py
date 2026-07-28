"""Finite RN/Home behaviors for the executable coherent CHI lifecycle.

The components operate at a delivered-Network-packet boundary.  RN behavior
uses an injected protocol-neutral cache core and owns CHI permission and
transaction state.  Home behavior uses an injected protocol-neutral full-line
backing core and separately owns directory and transaction state.  ``SD`` is
present only as the minimum shared-dirty authority needed by dirty-peer
CleanUnique, while ``UCE`` records data-less Unique permission after an
invalid/absent-line CleanUnique completion.  This is not a general MOESI
profile.  Neither participant decides how a packet crosses a topology; output
is another explicit ``ChiNetworkPacket`` that a transport runtime can enqueue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.virtual_dut.backend.backing import (
    BackingCommitConflict,
    FullLineBackingCore,
    LineBackingState,
    PreparedBackingWrite,
)
from protocol_model.virtual_dut.backend.cache import (
    CacheCore,
    CacheLinePayload,
    CacheLineStoreState,
)

from ..interface import (
    ChiRequestRetryContract,
    ChiRequestRetryContractError,
    ChiRequestRetryHomeState,
    ChiRequestRetryPhase,
    ChiRequestRetryRequesterState,
)
from ..representation.dat import (
    ChiCompDataMessage,
    ChiCopyBackWrDataMessage,
    ChiSnpRespDataMessage,
)
from ..representation.packet import ChiNetworkPacket
from ..representation.req import (
    ChiCleanUniqueMessage,
    ChiReadNotSharedDirtyMessage,
    ChiReadSharedMessage,
    ChiReadUniqueMessage,
    ChiWriteBackFullMessage,
)
from ..representation.response import ChiRespCode, ChiRespErr
from ..representation.rsp import (
    ChiCompMessage,
    ChiCompAckMessage,
    ChiCompDBIDRespMessage,
    ChiPCrdGrantMessage,
    ChiRetryAckMessage,
    ChiSnpRespMessage,
)
from ..representation.snp import (
    ChiSnpCleanInvalidMessage,
    ChiSnpNotSharedDirtyMessage,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
)
from .progress import chi_line_resource_name


_CACHE_LINE_BYTES = 64
_CACHE_LINE_DATA_LIMIT = 1 << (_CACHE_LINE_BYTES * 8)
_TRANSACTION_ID_LIMIT = 1 << 12


def _require_node_id(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative NodeID")


def _require_line_address(address: int) -> None:
    if (
        not isinstance(address, int)
        or isinstance(address, bool)
        or address < 0
        or address % _CACHE_LINE_BYTES
    ):
        raise ValueError("coherent line address must be 64-byte aligned")


class ChiCacheState(str, Enum):
    """Stable cache states supported by the restricted coherence profiles."""

    I = "I"
    SC = "SC"
    SD = "SD"
    UC = "UC"
    UCE = "UCE"
    UD = "UD"


@dataclass(frozen=True)
class ChiCacheLine:
    """One RN-local cache line in the restricted reference model."""

    address: int
    state: ChiCacheState
    data: int | None = None

    def __post_init__(self) -> None:
        _require_line_address(self.address)
        object.__setattr__(self, "state", ChiCacheState(self.state))
        if self.data is not None and (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or not 0 <= self.data < _CACHE_LINE_DATA_LIMIT
        ):
            raise ValueError("cache-line data must fit one 512-bit line")
        if self.state in (ChiCacheState.I, ChiCacheState.UCE):
            if self.data is not None:
                raise ValueError(
                    "I and UCE cache states must not carry valid line data"
                )
        elif self.data is None:
            raise ValueError("a full valid cache line requires data")


class ChiRnWriteBackOutcome(str, Enum):
    """Post-Snoop outcome retained while an RN waits for a CopyBack DBID."""

    LIVE_UD = "live_ud"
    CANCELED_I = "canceled_i"


@dataclass(frozen=True)
class ChiRnWriteBackPending:
    """Requester correlation plus the post-Snoop CopyBack outcome."""

    request: ChiWriteBackFullMessage
    outcome: ChiRnWriteBackOutcome = ChiRnWriteBackOutcome.LIVE_UD

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChiWriteBackFullMessage):
            raise TypeError(
                "RN writeback pending record requires WriteBackFull"
            )
        object.__setattr__(
            self,
            "outcome",
            ChiRnWriteBackOutcome(self.outcome),
        )

    @property
    def transaction_id(self) -> int:
        return self.request.transaction_id

    @property
    def address(self) -> int:
        return self.request.address


ChiCoherentReadMessage = (
    ChiReadSharedMessage
    | ChiReadNotSharedDirtyMessage
    | ChiReadUniqueMessage
)
ChiCoherenceRequestMessage = (
    ChiCoherentReadMessage
    | ChiCleanUniqueMessage
)
ChiCoherentSnoopMessage = (
    ChiSnpCleanInvalidMessage
    | ChiSnpSharedMessage
    | ChiSnpNotSharedDirtyMessage
    | ChiSnpUniqueMessage
)


@dataclass(frozen=True)
class ChiRnIssueCoherentRead:
    request: ChiCoherentReadMessage

    def __post_init__(self) -> None:
        if not isinstance(
            self.request,
            (
                ChiReadSharedMessage,
                ChiReadNotSharedDirtyMessage,
                ChiReadUniqueMessage,
            ),
        ):
            raise TypeError(
                "RN coherent issue requires ReadShared, "
                "ReadNotSharedDirty, or ReadUnique"
            )


@dataclass(frozen=True)
class ChiRnIssueCleanUnique:
    """Request Unique permission without transferring cache-line data."""

    request: ChiCleanUniqueMessage

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChiCleanUniqueMessage):
            raise TypeError("RN CleanUnique issue requires CleanUnique")


@dataclass(frozen=True)
class ChiRnAcceptSnoop:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message,
            (
                ChiSnpCleanInvalidMessage,
                ChiSnpSharedMessage,
                ChiSnpNotSharedDirtyMessage,
                ChiSnpUniqueMessage,
            ),
        ):
            raise TypeError(
                "RN snoop action requires a supported clean Snoop packet"
            )


@dataclass(frozen=True)
class ChiRnAcceptComp:
    """Accept one data-less completion from the configured Home."""

    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message, ChiCompMessage
        ):
            raise TypeError("RN data-less completion action requires Comp")


@dataclass(frozen=True)
class ChiRnAcceptCompData:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message, ChiCompDataMessage
        ):
            raise TypeError("RN completion action requires a CompData packet")


@dataclass(frozen=True)
class ChiRnAcceptRetryAck:
    """Correlate a Home RetryAck with one retained ReadUnique."""

    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message, ChiRetryAckMessage
        ):
            raise TypeError("RN retry action requires a RetryAck packet")


@dataclass(frozen=True)
class ChiRnAcceptPCrdGrant:
    """Pool one transaction-independent Home protocol credit."""

    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message, ChiPCrdGrantMessage
        ):
            raise TypeError("RN P-Credit action requires a PCrdGrant packet")


@dataclass(frozen=True)
class ChiRnRetryCoherentRequest:
    """Consume a matching P-Credit and reissue a retained ReadUnique."""

    transaction_id: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.transaction_id, int)
            or isinstance(self.transaction_id, bool)
            or not 0 <= self.transaction_id < _TRANSACTION_ID_LIMIT
        ):
            raise ValueError("RN retry transaction_id must be 12-bit")


@dataclass(frozen=True)
class ChiRnWriteCacheLine:
    """Apply one local write after the RN already owns Unique permission.

    The action is internal Request-Node behavior, not a CHI wire message.
    It changes ``UC`` to ``UD`` (or updates an existing ``UD`` line) and
    therefore makes the RN responsible for eventually passing or writing
    back the latest data.
    """

    address: int
    data: int

    def __post_init__(self) -> None:
        _require_line_address(self.address)
        if (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or not 0 <= self.data < _CACHE_LINE_DATA_LIMIT
        ):
            raise ValueError("local cache-line write must fit 512 bits")


@dataclass(frozen=True)
class ChiRnIssueWriteBackFull:
    """Start writing one resident dirty Unique line back to its Home."""

    request: ChiWriteBackFullMessage

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChiWriteBackFullMessage):
            raise TypeError("RN writeback issue requires WriteBackFull")


@dataclass(frozen=True)
class ChiRnAcceptCompDBIDResp:
    """Accept the Home DBID allocation for one pending writeback."""

    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message, ChiCompDBIDRespMessage
        ):
            raise TypeError(
                "RN writeback response requires CompDBIDResp packet"
            )


ChiCoherentRnAction = (
    ChiRnIssueCoherentRead
    | ChiRnIssueCleanUnique
    | ChiRnAcceptSnoop
    | ChiRnAcceptComp
    | ChiRnAcceptCompData
    | ChiRnAcceptRetryAck
    | ChiRnAcceptPCrdGrant
    | ChiRnRetryCoherentRequest
    | ChiRnWriteCacheLine
    | ChiRnIssueWriteBackFull
    | ChiRnAcceptCompDBIDResp
)


@dataclass(frozen=True)
class ChiCoherentRnState:
    """Cache storage state plus CHI-specific permissions and transactions.

    ``cache`` is the only owner of resident line data.  ``permissions`` is a
    CHI facet projection and can retain an ``I`` tombstone after invalidation
    or a data-less ``UCE`` permission.  The ``lines`` property is a
    compatibility/readout view assembled from those two facts; it is not
    another mutable store.
    """

    cache: CacheLineStoreState[CacheLinePayload] = field(
        default_factory=CacheLineStoreState
    )
    permissions: Mapping[int, ChiCacheState] = field(default_factory=dict)
    pending_transactions: Mapping[int, ChiCoherenceRequestMessage] = field(
        default_factory=dict
    )
    pending_writebacks: Mapping[int, ChiRnWriteBackPending] = field(
        default_factory=dict
    )
    request_retry: ChiRequestRetryRequesterState[
        ChiReadUniqueMessage
    ] = field(default_factory=ChiRequestRetryRequesterState)

    def __post_init__(self) -> None:
        if not isinstance(self.cache, CacheLineStoreState):
            raise TypeError("RN cache state requires CacheLineStoreState")
        if any(
            not isinstance(item, CacheLinePayload)
            or address != item.address
            for address, item in self.cache.lines.items()
        ):
            raise ValueError(
                "RN cache storage requires CacheLinePayload records"
            )
        permissions: dict[int, ChiCacheState] = {}
        for address, permission in dict(self.permissions).items():
            _require_line_address(address)
            permissions[address] = ChiCacheState(permission)
        resident = set(self.cache.lines)
        payload_permissions = {
            address
            for address, permission in permissions.items()
            if permission not in (ChiCacheState.I, ChiCacheState.UCE)
        }
        if resident != payload_permissions:
            raise ValueError(
                "resident cache data must have exactly one full-data CHI "
                "permission; I and UCE do not own payload"
            )
        pending = dict(self.pending_transactions)
        if any(
            not isinstance(
                item,
                (
                    ChiCleanUniqueMessage,
                    ChiReadSharedMessage,
                    ChiReadNotSharedDirtyMessage,
                    ChiReadUniqueMessage,
                ),
            )
            or transaction_id != item.transaction_id
            for transaction_id, item in pending.items()
        ):
            raise ValueError(
                "RN pending-transaction mapping key must match request TxnID"
            )
        object.__setattr__(
            self,
            "permissions",
            MappingProxyType(permissions),
        )
        object.__setattr__(
            self,
            "pending_transactions",
            MappingProxyType(pending),
        )
        writebacks = dict(self.pending_writebacks)
        if any(
            not isinstance(item, ChiRnWriteBackPending)
            or transaction_id != item.transaction_id
            for transaction_id, item in writebacks.items()
        ):
            raise ValueError(
                "RN pending-writeback mapping key must match request TxnID"
            )
        if set(pending) & set(writebacks):
            raise ValueError(
                "RN coherence and writeback transactions share one TxnID space"
            )
        reserved_addresses = tuple(
            request.address for request in pending.values()
        ) + tuple(
            request.address for request in writebacks.values()
        )
        for address in reserved_addresses:
            _require_line_address(address)
        if len(set(reserved_addresses)) != len(reserved_addresses):
            raise ValueError(
                "RN coherent transactions must reserve distinct cache lines"
            )
        for pending_writeback in writebacks.values():
            address = pending_writeback.address
            if (
                pending_writeback.outcome
                is ChiRnWriteBackOutcome.LIVE_UD
            ):
                if (
                    address not in resident
                    or permissions.get(address) is not ChiCacheState.UD
                ):
                    raise ValueError(
                        "live RN WriteBackFull requires a resident UD line"
                    )
            elif (
                address in resident
                or permissions.get(address) is not ChiCacheState.I
            ):
                raise ValueError(
                    "Snoop-canceled RN WriteBackFull requires I without "
                    "resident payload"
                )
        if any(
            permissions.get(request.address, ChiCacheState.I)
            not in (ChiCacheState.I, ChiCacheState.SC)
            for request in pending.values()
            if isinstance(request, ChiCleanUniqueMessage)
        ):
            raise ValueError(
                "RN pending CleanUnique requires an I or SC line state"
            )
        if not isinstance(
            self.request_retry,
            ChiRequestRetryRequesterState,
        ):
            raise TypeError(
                "RN Request-Retry facet requires requester retry state"
            )
        retry_entries = self.request_retry.entries
        read_unique_ids = {
            transaction_id
            for transaction_id, request in pending.items()
            if isinstance(request, ChiReadUniqueMessage)
        }
        if set(retry_entries) != read_unique_ids or any(
            not isinstance(entry.current_request, ChiReadUniqueMessage)
            or pending.get(transaction_id) != entry.current_request
            for transaction_id, entry in retry_entries.items()
        ):
            raise ValueError(
                "RN Request-Retry entries must project retained ReadUnique "
                "transactions"
            )
        object.__setattr__(
            self,
            "pending_writebacks",
            MappingProxyType(writebacks),
        )

    @property
    def lines(self) -> Mapping[int, ChiCacheLine]:
        """Return the protocol-facing line-state projection."""

        return MappingProxyType(
            {
                address: ChiCacheLine(
                    address,
                    permission,
                    (
                        None
                        if permission in (
                            ChiCacheState.I,
                            ChiCacheState.UCE,
                        )
                        else self.cache.lines[address].data
                    ),
                )
                for address, permission in self.permissions.items()
            }
        )

    def line_at(self, address: int) -> ChiCacheLine | None:
        _require_line_address(address)
        return self.lines.get(address)

    def pending_for_address(
        self,
        address: int,
    ) -> tuple[
        ChiCoherenceRequestMessage | ChiWriteBackFullMessage,
        ...,
    ]:
        """Return local coherent transactions reserving one cache line."""

        _require_line_address(address)
        return tuple(
            request
            for request in self.pending_transactions.values()
            if request.address == address
        ) + tuple(
            pending.request
            for pending in self.pending_writebacks.values()
            if pending.address == address
        )

    def retryable_transaction_ids(self) -> tuple[int, ...]:
        """Return retained requests that can consume a matching P-Credit."""

        return self.request_retry.retryable_transaction_ids()


class ChiCoherentRnNode(
    SemanticComponent[
        ChiCoherentRnAction,
        ChiCoherentRnState,
        ChiNetworkPacket,
    ]
):
    """Restricted RN-F behavior for coherent requests and Unique dirtying."""

    def __init__(
        self,
        name: str,
        node_id: int,
        home_node_id: int,
        *,
        cache_core: CacheCore[CacheLinePayload],
        initial_permissions: Mapping[int, ChiCacheState],
        outstanding_capacity: int = 4,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("coherent RN requires a name")
        _require_node_id("RN node_id", node_id)
        _require_node_id("RN home_node_id", home_node_id)
        if node_id == home_node_id:
            raise ValueError("RN and Home NodeIDs must be distinct")
        if (
            not isinstance(outstanding_capacity, int)
            or isinstance(outstanding_capacity, bool)
            or outstanding_capacity <= 0
        ):
            raise ValueError("RN outstanding capacity must be positive")
        if not isinstance(cache_core, CacheCore):
            raise TypeError("RN cache_core requires CacheCore")
        cache_store = cache_core.line_store
        if cache_store.line_bytes != _CACHE_LINE_BYTES:
            raise ValueError(
                "CHI Issue H cache profile requires 64-byte cache lines"
            )
        initial_cache = cache_core.initial_state()
        if any(
            not isinstance(item, CacheLinePayload)
            for item in initial_cache.lines.values()
        ):
            raise TypeError(
                "CHI RN cache core requires CacheLinePayload records"
            )
        permissions = {
            address: ChiCacheState(permission)
            for address, permission in dict(initial_permissions).items()
        }
        payload_permissions = {
            address
            for address, permission in permissions.items()
            if permission not in (ChiCacheState.I, ChiCacheState.UCE)
        }
        if set(initial_cache.lines) != payload_permissions:
            raise ValueError(
                "initial full-data CHI permissions must cover exactly the "
                "resident cache payloads; I and UCE carry no payload"
            )
        self.name = name
        self.node_id = node_id
        self.home_node_id = home_node_id
        self.cache_core = cache_core
        self.cache_store = cache_store
        self.initial_permissions = MappingProxyType(permissions)
        self.outstanding_capacity = outstanding_capacity

    def initial_state(self) -> ChiCoherentRnState:
        return ChiCoherentRnState(
            self.cache_store.initial_state(),
            self.initial_permissions,
        )

    def is_quiescent(self, state: ChiCoherentRnState) -> bool:
        return (
            isinstance(state, ChiCoherentRnState)
            and not state.pending_transactions
            and not state.pending_writebacks
            and not state.request_retry.entries
            and not state.request_retry.protocol_credits
        )

    def step(
        self,
        state: ChiCoherentRnState,
        action: ChiCoherentRnAction,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        if not isinstance(state, ChiCoherentRnState):
            raise TypeError("coherent RN requires ChiCoherentRnState")
        if isinstance(action, ChiRnIssueCoherentRead):
            return self._issue(state, action.request)
        if isinstance(action, ChiRnIssueCleanUnique):
            return self._issue_clean_unique(state, action.request)
        if isinstance(action, ChiRnAcceptSnoop):
            return self._accept_snoop(state, action.packet)
        if isinstance(action, ChiRnAcceptComp):
            return self._accept_comp(state, action.packet)
        if isinstance(action, ChiRnAcceptCompData):
            return self._accept_comp_data(state, action.packet)
        if isinstance(action, ChiRnAcceptRetryAck):
            return self._accept_retry_ack(state, action.packet)
        if isinstance(action, ChiRnAcceptPCrdGrant):
            return self._accept_pcredit_grant(state, action.packet)
        if isinstance(action, ChiRnRetryCoherentRequest):
            return self._retry_coherent_request(
                state,
                action.transaction_id,
            )
        if isinstance(action, ChiRnWriteCacheLine):
            return self._write_cache_line(
                state,
                action.address,
                action.data,
            )
        if isinstance(action, ChiRnIssueWriteBackFull):
            return self._issue_writeback(state, action.request)
        if isinstance(action, ChiRnAcceptCompDBIDResp):
            return self._accept_comp_dbid_resp(state, action.packet)
        raise TypeError("unknown coherent RN action")

    def _write_cache_line(
        self,
        state: ChiCoherentRnState,
        address: int,
        data: int,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        if state.pending_for_address(address):
            return self._fault(
                state,
                "local_write_hazard",
                "local write conflicts with an RN-local coherent transaction",
            )
        line = state.line_at(address)
        if line is None or line.state is ChiCacheState.I:
            return self._fault(
                state,
                "local_write_permission",
                "local write requires an installed Unique cache line",
            )
        if line.state not in (
            ChiCacheState.UC,
            ChiCacheState.UCE,
            ChiCacheState.UD,
        ):
            return self._fault(
                state,
                "local_write_upgrade",
                "writing Shared state requires a separate permission upgrade",
            )
        cache = self.cache_store.install(
            state.cache,
            CacheLinePayload(address, data),
        ).state
        permissions = dict(state.permissions)
        permissions[address] = ChiCacheState.UD
        return SemanticStep(
            ChiCoherentRnState(
                cache,
                permissions,
                state.pending_transactions,
                state.pending_writebacks,
                state.request_retry,
            )
        )

    def _issue(
        self,
        state: ChiCoherentRnState,
        request: ChiCoherentReadMessage,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        if request.size != 6 or request.address % _CACHE_LINE_BYTES:
            return self._fault(
                state,
                "read_shape",
                "first coherent RN profile requires one aligned 64-byte read",
            )
        unsupported = tuple(
            name
            for name, enabled in (
                ("non-snoopable", not request.snoop_attribute),
                ("exclusive", request.exclusive),
                ("ordered", request.order != 0),
                ("tag operation", request.tag_operation != 0),
                ("trace tag", request.trace_tag),
            )
            if enabled
        )
        if unsupported:
            return self._fault(
                state,
                "read_attributes",
                "coherent-read profile does not implement "
                + ", ".join(unsupported),
            )
        if not request.expect_completion_ack:
            return self._fault(
                state,
                "completion_ack",
                "coherent reads in this RN-F profile require ExpCompAck",
            )
        if (
            not request.allow_retry
            or request.protocol_credit_type != 0
        ):
            return self._fault(
                state,
                "coherent_read_retry_shape",
                "an initial coherent read requires AllowRetry=1 and "
                "PCrdType=0",
            )
        if (
            request.transaction_id in state.pending_transactions
            or request.transaction_id in state.pending_writebacks
        ):
            return self._fault(
                state,
                "duplicate_transaction",
                "RN already owns this coherent-read TxnID",
            )
        if state.pending_for_address(request.address):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    chi_line_resource_name(self.name, request.address),
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=1,
                    reason=(
                        "another RN-local coherent transaction reserves "
                        "this cache line"
                    ),
                    location=self.name,
                ),
            )
        if (
            len(state.pending_transactions) + len(state.pending_writebacks)
            >= self.outstanding_capacity
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.coherent_read_slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.outstanding_capacity,
                    reason="RN coherent-read table is full",
                    location=self.name,
                ),
            )
        line = state.line_at(request.address)
        is_shared_to_unique_upgrade = (
            isinstance(request, ChiReadUniqueMessage)
            and line is not None
            and line.state is ChiCacheState.SC
        )
        if (
            line is not None
            and line.state is not ChiCacheState.I
            and not is_shared_to_unique_upgrade
        ):
            return self._fault(
                state,
                "local_hit",
                "the current coherent-read profile issues from I, or uses "
                "ReadUnique to upgrade an existing SC line",
            )
        pending = dict(state.pending_transactions)
        pending[request.transaction_id] = request
        request_retry = state.request_retry
        if isinstance(request, ChiReadUniqueMessage):
            try:
                request_retry = ChiRequestRetryContract.retain_initial(
                    request_retry,
                    request,
                    home_node_id=self.home_node_id,
                )
            except ChiRequestRetryContractError as error:
                return self._fault(state, error.code, error.reason)
        candidate = ChiCoherentRnState(
            state.cache,
            state.permissions,
            pending,
            state.pending_writebacks,
            request_retry,
        )
        packet = ChiNetworkPacket.request(
            request,
            source_id=self.node_id,
            target_id=self.home_node_id,
        )
        return SemanticStep(candidate, (packet,))

    def _issue_clean_unique(
        self,
        state: ChiCoherentRnState,
        request: ChiCleanUniqueMessage,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        """Reserve an invalid/absent or Shared line for a Unique upgrade."""

        if request.size != 6 or request.address % _CACHE_LINE_BYTES:
            return self._fault(
                state,
                "clean_unique_shape",
                "CleanUnique requires one aligned 64-byte cache line",
            )
        if (
            not request.allow_retry
            or request.protocol_credit_type != 0
            or not request.expect_completion_ack
            or request.memory_attributes not in (0b0101, 0b1101)
        ):
            return self._fault(
                state,
                "clean_unique_attributes",
                "initial CleanUnique requires Normal-memory attributes, "
                "AllowRetry=1, PCrdType=0, and ExpCompAck=1",
            )
        unsupported = tuple(
            name
            for name, enabled in (
                ("likely shared", request.likely_shared),
                ("non-snoopable", not request.snoop_attribute),
                ("exclusive", request.exclusive),
                ("ordered", request.order != 0),
                ("tag operation", request.tag_operation != 0),
                ("trace tag", request.trace_tag),
            )
            if enabled
        )
        if unsupported:
            return self._fault(
                state,
                "clean_unique_attributes",
                "first CleanUnique profile does not implement "
                + ", ".join(unsupported),
            )
        if (
            request.transaction_id in state.pending_transactions
            or request.transaction_id in state.pending_writebacks
        ):
            return self._fault(
                state,
                "duplicate_transaction",
                "RN already owns this coherence TxnID",
            )
        if state.pending_for_address(request.address):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    chi_line_resource_name(self.name, request.address),
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=1,
                    reason=(
                        "another RN-local coherent transaction reserves "
                        "this cache line"
                    ),
                    location=self.name,
                ),
            )
        if (
            len(state.pending_transactions) + len(state.pending_writebacks)
            >= self.outstanding_capacity
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.coherence_transaction_slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.outstanding_capacity,
                    reason="RN coherence transaction table is full",
                    location=self.name,
                ),
            )
        line = state.line_at(request.address)
        if line is not None and line.state is ChiCacheState.UD:
            return self._fault(
                state,
                "clean_unique_dirty_requester",
                "the clean-only CleanUnique slice rejects a dirty requester",
            )
        if (
            line is not None
            and line.state not in (ChiCacheState.I, ChiCacheState.SC)
        ):
            return self._fault(
                state,
                "clean_unique_permission",
                "CleanUnique requires I or a resident SC line at the requester",
            )
        pending = dict(state.pending_transactions)
        pending[request.transaction_id] = request
        candidate = ChiCoherentRnState(
            state.cache,
            state.permissions,
            pending,
            state.pending_writebacks,
            state.request_retry,
        )
        return SemanticStep(
            candidate,
            (
                ChiNetworkPacket.request(
                    request,
                    source_id=self.node_id,
                    target_id=self.home_node_id,
                ),
            ),
        )

    def _accept_retry_ack(
        self,
        state: ChiCoherentRnState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "retry_ack_target",
                "RetryAck packet targets another Request Node",
            )
        if packet.source_id != self.home_node_id:
            return self._fault(
                state,
                "retry_ack_home",
                "RetryAck does not come from the configured Home",
            )
        response = packet.message
        assert isinstance(response, ChiRetryAckMessage)
        request = state.pending_transactions.get(response.transaction_id)
        if not isinstance(request, ChiReadUniqueMessage):
            return self._fault(
                state,
                "retry_ack_identity",
                "RetryAck does not match a retained ReadUnique",
            )
        try:
            request_retry = ChiRequestRetryContract.observe_retry_ack(
                state.request_retry,
                response,
                home_node_id=self.home_node_id,
            )
        except ChiRequestRetryContractError as error:
            return self._fault(state, error.code, error.reason)
        return SemanticStep(
            ChiCoherentRnState(
                state.cache,
                state.permissions,
                state.pending_transactions,
                state.pending_writebacks,
                request_retry,
            )
        )

    def _accept_pcredit_grant(
        self,
        state: ChiCoherentRnState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "pcredit_target",
                "PCrdGrant packet targets another Request Node",
            )
        if packet.source_id != self.home_node_id:
            return self._fault(
                state,
                "pcredit_home",
                "PCrdGrant does not come from the configured Home",
            )
        response = packet.message
        assert isinstance(response, ChiPCrdGrantMessage)
        request_retry = ChiRequestRetryContract.observe_pcredit(
            state.request_retry,
            response,
            home_node_id=self.home_node_id,
        )
        return SemanticStep(
            ChiCoherentRnState(
                state.cache,
                state.permissions,
                state.pending_transactions,
                state.pending_writebacks,
                request_retry,
            )
        )

    def _retry_coherent_request(
        self,
        state: ChiCoherentRnState,
        transaction_id: int,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        try:
            request_retry, request = (
                ChiRequestRetryContract.credited_reissue(
                    state.request_retry,
                    transaction_id,
                )
            )
        except ChiRequestRetryContractError as error:
            return self._fault(state, error.code, error.reason)
        if not isinstance(request, ChiReadUniqueMessage):
            return self._fault(
                state,
                "retry_opcode",
                "the coherent retry slice supports only ReadUnique",
            )
        pending = dict(state.pending_transactions)
        if not isinstance(
            pending.get(transaction_id),
            ChiReadUniqueMessage,
        ):
            return self._fault(
                state,
                "retry_identity",
                "retry no longer matches an RN pending ReadUnique",
            )
        pending[transaction_id] = request
        candidate = ChiCoherentRnState(
            state.cache,
            state.permissions,
            pending,
            state.pending_writebacks,
            request_retry,
        )
        return SemanticStep(
            candidate,
            (
                ChiNetworkPacket.request(
                    request,
                    source_id=self.node_id,
                    target_id=self.home_node_id,
                ),
            ),
        )

    def _accept_snoop(
        self,
        state: ChiCoherentRnState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "snoop_target",
                "Snoop packet targets another NodeID",
            )
        if packet.source_id != self.home_node_id:
            return self._fault(
                state,
                "snoop_source",
                "first profile accepts snoops only from its configured Home",
            )
        snoop = packet.message
        assert isinstance(
            snoop,
            (
                ChiSnpCleanInvalidMessage,
                ChiSnpSharedMessage,
                ChiSnpNotSharedDirtyMessage,
                ChiSnpUniqueMessage,
            ),
        )
        if snoop.address % _CACHE_LINE_BYTES:
            return self._fault(
                state,
                "snoop_shape",
                "first coherent RN profile requires a line-aligned snoop",
            )
        same_line = state.pending_for_address(snoop.address)
        read_unique_overlap = (
            isinstance(snoop, ChiSnpUniqueMessage)
            and same_line
            and all(
                isinstance(request, ChiReadUniqueMessage)
                for request in same_line
            )
        )
        clean_unique_overlap = (
            isinstance(
                snoop,
                (ChiSnpCleanInvalidMessage, ChiSnpUniqueMessage),
            )
            and same_line
            and all(
                isinstance(request, ChiCleanUniqueMessage)
                for request in same_line
            )
        )
        writeback_overlap = (
            isinstance(
                snoop,
                (ChiSnpCleanInvalidMessage, ChiSnpUniqueMessage),
            )
            and same_line
            and all(
                isinstance(request, ChiWriteBackFullMessage)
                for request in same_line
            )
        )
        if same_line and not (
            read_unique_overlap
            or clean_unique_overlap
            or writeback_overlap
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    chi_line_resource_name(self.name, snoop.address),
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=1,
                    reason=(
                        "the staged transient policy defers the Snoop because "
                        "an RN-local transaction reserves this cache line; "
                        "only ReadUnique/SnpUnique and CleanUnique/"
                        "invalidating-Snoop and WriteBackFull/"
                        "invalidating-Snoop same-line transients are implemented"
                    ),
                    location=self.name,
                ),
            )
        if isinstance(
            snoop,
            (ChiSnpCleanInvalidMessage, ChiSnpUniqueMessage),
        ):
            if not snoop.do_not_go_to_shared_dirty:
                return self._fault(
                    state,
                    "snoop_profile",
                    "invalidating Snoop requires DoNotGoToSD",
                )
        if (
            isinstance(snoop, ChiSnpCleanInvalidMessage)
            and snoop.return_to_source
        ):
            return self._fault(
                state,
                "snoop_profile",
                "SnpCleanInvalid requires RetToSrc=0",
            )
        cache = state.cache
        permissions = dict(state.permissions)
        line = state.line_at(snoop.address)
        response_message: (
            ChiSnpRespMessage | ChiSnpRespDataMessage | None
        ) = None
        if isinstance(
            snoop,
            (ChiSnpCleanInvalidMessage, ChiSnpUniqueMessage),
        ):
            response = ChiRespCode.I
            if line is not None and line.state is not ChiCacheState.I:
                if line.state is ChiCacheState.UCE:
                    response_message = ChiSnpRespMessage(
                        transaction_id=snoop.transaction_id,
                        response=response,
                    )
                elif line.state in (ChiCacheState.SD, ChiCacheState.UD):
                    if (
                        line.state is ChiCacheState.SD
                        and not isinstance(snoop, ChiSnpCleanInvalidMessage)
                    ):
                        return self._fault(
                            state,
                            "shared_dirty_snoop_profile",
                            "the restricted SD profile is consumed only by "
                            "SnpCleanInvalid",
                        )
                    assert line.data is not None
                    response_message = ChiSnpRespDataMessage(
                        transaction_id=snoop.transaction_id,
                        data=line.data,
                        response=ChiRespCode.I_PD,
                    )
                else:
                    if (
                        isinstance(snoop, ChiSnpUniqueMessage)
                        and snoop.return_to_source
                    ):
                        assert line.data is not None
                        response_message = ChiSnpRespDataMessage(
                            transaction_id=snoop.transaction_id,
                            data=line.data,
                            response=ChiRespCode.I,
                        )
                    else:
                        response_message = ChiSnpRespMessage(
                            transaction_id=snoop.transaction_id,
                            response=response,
                        )
                if line.state is not ChiCacheState.UCE:
                    cache = self.cache_store.remove(
                        cache,
                        snoop.address,
                    ).state
                permissions[snoop.address] = ChiCacheState.I
            else:
                response_message = ChiSnpRespMessage(
                    transaction_id=snoop.transaction_id,
                    response=response,
                )
        else:
            if line is None or line.state is ChiCacheState.I:
                response = ChiRespCode.I
            elif line.state is ChiCacheState.UC:
                response = ChiRespCode.SC
                permissions[snoop.address] = ChiCacheState.SC
                if snoop.return_to_source:
                    assert line.data is not None
                    response_message = ChiSnpRespDataMessage(
                        transaction_id=snoop.transaction_id,
                        data=line.data,
                        response=response,
                    )
            elif line.state is ChiCacheState.SC:
                response = ChiRespCode.SC
            elif line.state is ChiCacheState.UCE:
                response = ChiRespCode.I
                permissions[snoop.address] = ChiCacheState.I
            elif line.state is ChiCacheState.SD:
                return self._fault(
                    state,
                    "shared_dirty_snoop_profile",
                    "the restricted SD profile is consumed only by "
                    "SnpCleanInvalid",
                )
            elif line.state is ChiCacheState.UD:
                if isinstance(snoop, ChiSnpSharedMessage):
                    return self._fault(
                        state,
                        "dirty_shared_policy",
                        "SnpShared against a UD line requires an explicit "
                        "dirty-shared policy; the current MESI path uses "
                        "SnpNotSharedDirty",
                    )
                assert line.data is not None
                response = ChiRespCode.SC_PD
                response_message = ChiSnpRespDataMessage(
                    transaction_id=snoop.transaction_id,
                    data=line.data,
                    response=response,
                )
                permissions[snoop.address] = ChiCacheState.SC
            if response_message is None:
                response_message = ChiSnpRespMessage(
                    transaction_id=snoop.transaction_id,
                    response=response,
                )
        assert response_message is not None
        response_packet = (
            ChiNetworkPacket.data(
                response_message,
                source_id=self.node_id,
                target_id=packet.source_id,
            )
            if isinstance(response_message, ChiSnpRespDataMessage)
            else ChiNetworkPacket.response(
                response_message,
                source_id=self.node_id,
                target_id=packet.source_id,
            )
        )
        pending_writebacks = state.pending_writebacks
        if writeback_overlap:
            updated_writebacks = dict(state.pending_writebacks)
            for transaction_id, pending_writeback in tuple(
                updated_writebacks.items()
            ):
                if pending_writeback.address == snoop.address:
                    updated_writebacks[transaction_id] = (
                        ChiRnWriteBackPending(
                            pending_writeback.request,
                            ChiRnWriteBackOutcome.CANCELED_I,
                        )
                    )
            pending_writebacks = updated_writebacks
        return SemanticStep(
            ChiCoherentRnState(
                cache,
                permissions,
                state.pending_transactions,
                pending_writebacks,
                state.request_retry,
            ),
            (response_packet,),
        )

    def _accept_comp(
        self,
        state: ChiCoherentRnState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        """Install ``UC``/``UCE`` and acknowledge the Home-owned DBID."""

        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "clean_unique_completion_target",
                "Comp packet targets another Request Node",
            )
        if packet.source_id != self.home_node_id:
            return self._fault(
                state,
                "clean_unique_completion_home",
                "Comp does not come from the configured Home",
            )
        response = packet.message
        assert isinstance(response, ChiCompMessage)
        request = state.pending_transactions.get(response.transaction_id)
        if not isinstance(request, ChiCleanUniqueMessage):
            return self._fault(
                state,
                "clean_unique_completion_identity",
                "Comp does not match an outstanding CleanUnique TxnID",
            )
        if (
            response.response_error != 0
            or response.response is not ChiRespCode.UC
            or response.tag_operation != 0
        ):
            return self._fault(
                state,
                "clean_unique_completion_state",
                "the CleanUnique completion must be Comp_UC without error "
                "or tag operation",
            )
        line = state.line_at(request.address)
        if line is not None and line.state not in (
            ChiCacheState.I,
            ChiCacheState.SC,
        ):
            return self._fault(
                state,
                "clean_unique_reserved_line",
                "the reserved CleanUnique line is neither I nor resident SC",
            )
        permissions = dict(state.permissions)
        permissions[request.address] = (
            ChiCacheState.UCE
            if line is None or line.state is ChiCacheState.I
            else ChiCacheState.UC
        )
        pending = dict(state.pending_transactions)
        del pending[request.transaction_id]
        ack = ChiNetworkPacket.response(
            ChiCompAckMessage(transaction_id=response.data_buffer_id),
            source_id=self.node_id,
            target_id=self.home_node_id,
        )
        return SemanticStep(
            ChiCoherentRnState(
                state.cache,
                permissions,
                pending,
                state.pending_writebacks,
                state.request_retry,
            ),
            (ack,),
        )

    def _accept_comp_data(
        self,
        state: ChiCoherentRnState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "completion_target",
                "CompData packet targets another NodeID",
            )
        response = packet.message
        assert isinstance(response, ChiCompDataMessage)
        request = state.pending_transactions.get(response.transaction_id)
        if request is None or isinstance(request, ChiCleanUniqueMessage):
            return self._fault(
                state,
                "completion_identity",
                "CompData does not match an outstanding coherent-read TxnID",
            )
        if (
            packet.source_id != self.home_node_id
            or response.home_node_id != self.home_node_id
        ):
            return self._fault(
                state,
                "completion_home",
                "CompData does not identify the configured Home",
            )
        if response.response_error is ChiRespErr.NDERR:
            if (
                not isinstance(request, ChiReadUniqueMessage)
                or response.response != ChiRespCode.I
                or response.data_id != 0
                or response.trace_tag
            ):
                return self._fault(
                    state,
                    "read_unique_nderr_completion",
                    "ReadUnique NDERR requires CompData_I with DataID=0 "
                    "and TraceTag=0",
                )
            try:
                request_retry = ChiRequestRetryContract.retire(
                    state.request_retry,
                    response.transaction_id,
                )
            except ChiRequestRetryContractError as error:
                return self._fault(state, error.code, error.reason)
            pending = dict(state.pending_transactions)
            del pending[response.transaction_id]
            ack = ChiNetworkPacket.response(
                ChiCompAckMessage(
                    transaction_id=response.data_buffer_id,
                ),
                source_id=self.node_id,
                target_id=response.home_node_id,
            )
            return SemanticStep(
                ChiCoherentRnState(
                    state.cache,
                    state.permissions,
                    pending,
                    state.pending_writebacks,
                    request_retry,
                ),
                (ack,),
            )
        allowed_responses = (
            (ChiRespCode.UC, ChiRespCode.UD_PD)
            if isinstance(request, ChiReadUniqueMessage)
            else (
                (ChiRespCode.UC, ChiRespCode.UD_PD, ChiRespCode.SC)
                if isinstance(request, ChiReadNotSharedDirtyMessage)
                else (ChiRespCode.SC,)
            )
        )
        if response.response_error != 0 or response.response not in (
            allowed_responses
        ):
            return self._fault(
                state,
                "completion_state",
                "coherent-read completion has an unsupported cache state",
            )
        installed_state = (
            ChiCacheState.UD
            if response.passes_dirty
            else (
                ChiCacheState.UC
                if response.response is ChiRespCode.UC
                else ChiCacheState.SC
            )
        )
        cache = self.cache_store.install(
            state.cache,
            CacheLinePayload(request.address, response.data),
        ).state
        permissions = dict(state.permissions)
        permissions[request.address] = installed_state
        pending = dict(state.pending_transactions)
        del pending[response.transaction_id]
        request_retry = state.request_retry
        if isinstance(request, ChiReadUniqueMessage):
            try:
                request_retry = ChiRequestRetryContract.retire(
                    request_retry,
                    response.transaction_id,
                )
            except ChiRequestRetryContractError as error:
                return self._fault(state, error.code, error.reason)
        ack = ChiNetworkPacket.response(
            ChiCompAckMessage(
                transaction_id=response.data_buffer_id,
            ),
            source_id=self.node_id,
            target_id=response.home_node_id,
        )
        return SemanticStep(
            ChiCoherentRnState(
                cache,
                permissions,
                pending,
                state.pending_writebacks,
                request_retry,
            ),
            (ack,),
        )

    def _issue_writeback(
        self,
        state: ChiCoherentRnState,
        request: ChiWriteBackFullMessage,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        """Reserve a dirty line while Home allocates the copyback DBID."""

        if request.size != 6 or request.address % _CACHE_LINE_BYTES:
            return self._fault(
                state,
                "writeback_shape",
                "first writeback profile requires one aligned 64-byte line",
            )
        if (
            not request.allow_retry
            or request.protocol_credit_type != 0
            or request.expect_completion_ack
            or request.memory_attributes not in (0b0101, 0b1101)
        ):
            return self._fault(
                state,
                "writeback_request_attributes",
                "initial WriteBackFull requires Normal-memory attributes, "
                "AllowRetry=1, PCrdType=0, and ExpCompAck=0",
            )
        unsupported = tuple(
            name
            for name, enabled in (
                ("likely shared", request.likely_shared),
                ("non-snoopable", not request.snoop_attribute),
                ("exclusive", request.exclusive),
                ("ordered", request.order != 0),
                ("tag operation", request.tag_operation != 0),
                ("trace tag", request.trace_tag),
            )
            if enabled
        )
        if unsupported:
            return self._fault(
                state,
                "writeback_request_attributes",
                "first WriteBackFull profile does not implement "
                + ", ".join(unsupported),
            )
        if (
            request.transaction_id in state.pending_transactions
            or request.transaction_id in state.pending_writebacks
        ):
            return self._fault(
                state,
                "duplicate_transaction",
                "RN already owns this read/writeback TxnID",
            )
        if state.pending_for_address(request.address):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    chi_line_resource_name(self.name, request.address),
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=1,
                    reason=(
                        "another RN-local coherent transaction reserves "
                        "this cache line"
                    ),
                    location=self.name,
                ),
            )
        if (
            len(state.pending_transactions) + len(state.pending_writebacks)
            >= self.outstanding_capacity
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.coherence_transaction_slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.outstanding_capacity,
                    reason="RN coherent transaction table is full",
                    location=self.name,
                ),
            )
        line = state.line_at(request.address)
        if line is None or line.state is not ChiCacheState.UD:
            return self._fault(
                state,
                "writeback_permission",
                "WriteBackFull requires a resident UD line",
            )
        pending = dict(state.pending_writebacks)
        pending[request.transaction_id] = ChiRnWriteBackPending(request)
        candidate = ChiCoherentRnState(
            state.cache,
            state.permissions,
            state.pending_transactions,
            pending,
            state.request_retry,
        )
        return SemanticStep(
            candidate,
            (
                ChiNetworkPacket.request(
                    request,
                    source_id=self.node_id,
                    target_id=self.home_node_id,
                ),
            ),
        )

    def _accept_comp_dbid_resp(
        self,
        state: ChiCoherentRnState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        """Complete a live or Snoop-canceled CopyBack under Home's DBID."""

        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "writeback_response_target",
                "CompDBIDResp packet targets another Request Node",
            )
        if packet.source_id != self.home_node_id:
            return self._fault(
                state,
                "writeback_response_home",
                "CompDBIDResp does not come from the configured Home",
            )
        response = packet.message
        assert isinstance(response, ChiCompDBIDRespMessage)
        pending_writeback = state.pending_writebacks.get(
            response.transaction_id
        )
        if pending_writeback is None:
            return self._fault(
                state,
                "writeback_response_identity",
                "CompDBIDResp does not match an outstanding WriteBackFull",
            )
        if response.response_error != 0 or response.response != 0:
            return self._fault(
                state,
                "writeback_response_status",
                "first writeback profile accepts only a normal DBID response",
            )
        request = pending_writeback.request
        line = state.line_at(request.address)
        cache = state.cache
        permissions = dict(state.permissions)
        if (
            pending_writeback.outcome
            is ChiRnWriteBackOutcome.LIVE_UD
        ):
            if (
                line is None
                or line.state is not ChiCacheState.UD
                or line.data is None
            ):
                return self._fault(
                    state,
                    "writeback_reserved_line",
                    "live writeback line is no longer resident in UD",
                )
            copyback = ChiCopyBackWrDataMessage(
                transaction_id=response.data_buffer_id,
                data=line.data,
                response=ChiRespCode.UD_PD,
                data_id=0,
                byte_enable=(1 << _CACHE_LINE_BYTES) - 1,
            )
            cache = self.cache_store.remove(
                state.cache,
                request.address,
            ).state
            permissions[request.address] = ChiCacheState.I
        else:
            if (
                line is None
                or line.state is not ChiCacheState.I
                or request.address in state.cache.lines
            ):
                return self._fault(
                    state,
                    "writeback_canceled_line",
                    "Snoop-canceled writeback must remain I without payload",
                )
            copyback = ChiCopyBackWrDataMessage(
                transaction_id=response.data_buffer_id,
                data=0,
                response=ChiRespCode.I,
                data_id=0,
                byte_enable=0,
            )
        pending = dict(state.pending_writebacks)
        del pending[request.transaction_id]
        return SemanticStep(
            ChiCoherentRnState(
                cache,
                permissions,
                state.pending_transactions,
                pending,
                state.request_retry,
            ),
            (
                ChiNetworkPacket.data(
                    copyback,
                    source_id=self.node_id,
                    target_id=self.home_node_id,
                ),
            ),
        )

    def _fault(
        self,
        state: ChiCoherentRnState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiCoherentRnState, ChiNetworkPacket]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                ConstraintScope.VIRTUAL_DUT,
                self.name,
            ),
        )


@dataclass(frozen=True)
class ChiHomeDirectoryEntry:
    """Stable holder authority for one line.

    ``shared_dirty_owner`` is a deliberately narrow authority needed by the
    dirty-peer CleanUnique profile.  It does not claim general MOESI/Owned,
    forwarding, or shared-dirty replacement behavior.

    Line payload is deliberately absent.  The injected protocol-neutral
    backing core is the sole Home-local owner of the reference copy.
    """

    address: int
    sharers: frozenset[int] = frozenset()
    unique_owner: int | None = None
    shared_dirty_owner: int | None = None

    def __post_init__(self) -> None:
        _require_line_address(self.address)
        sharers = frozenset(self.sharers)
        for node_id in sharers:
            _require_node_id("directory sharer", node_id)
        if self.unique_owner is not None:
            _require_node_id("directory unique owner", self.unique_owner)
            if sharers:
                raise ValueError(
                    "unique owner and shared holders are exclusive states"
                )
        if self.shared_dirty_owner is not None:
            _require_node_id(
                "directory shared-dirty owner",
                self.shared_dirty_owner,
            )
            if self.unique_owner is not None:
                raise ValueError(
                    "unique and shared-dirty owners are exclusive states"
                )
            if self.shared_dirty_owner not in sharers:
                raise ValueError(
                    "shared-dirty owner must belong to directory sharers"
                )
        object.__setattr__(self, "sharers", sharers)


@dataclass(frozen=True)
class ChiSnoopResult:
    """One normalized Home observation of either RSP or DAT snoop response."""

    response: ChiRespCode
    data: int | None = None

    def __post_init__(self) -> None:
        response = ChiRespCode(self.response)
        if self.data is not None and (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or not 0 <= self.data < _CACHE_LINE_DATA_LIMIT
        ):
            raise ValueError("snoop-result data must fit one 512-bit line")
        if bool(int(response) & 0b100) and self.data is None:
            raise ValueError(
                "PassDirty snoop result requires the transferred data"
            )
        object.__setattr__(self, "response", response)

    @property
    def passes_dirty(self) -> bool:
        return bool(int(self.response) & 0b100)


@dataclass(frozen=True)
class ChiCoherentTransactionPending:
    """Home-private coherent transaction; grouping is not a wire field."""

    requester_id: int
    request: ChiCoherenceRequestMessage
    snoop_transaction_id: int | None
    data_buffer_id: int
    snoop_targets: frozenset[int]
    snoop_results: Mapping[int, ChiSnoopResult] = field(default_factory=dict)
    completion_sent: bool = False
    prepared_backing_write: PreparedBackingWrite | None = None
    completion_response_error: ChiRespErr | int = ChiRespErr.OK

    def __post_init__(self) -> None:
        _require_node_id("pending requester", self.requester_id)
        if not isinstance(
            self.request,
            (
                ChiCleanUniqueMessage,
                ChiReadSharedMessage,
                ChiReadNotSharedDirtyMessage,
                ChiReadUniqueMessage,
            ),
        ):
            raise TypeError(
                "Home pending transaction requires a coherent request"
            )
        snoop_transaction_id = self.snoop_transaction_id
        if snoop_transaction_id is not None and (
            not isinstance(snoop_transaction_id, int)
            or isinstance(snoop_transaction_id, bool)
            or not 0 <= snoop_transaction_id < _TRANSACTION_ID_LIMIT
        ):
            raise ValueError(
                "snoop_transaction_id must be a 12-bit identifier or None"
            )
        if (
            not isinstance(self.data_buffer_id, int)
            or isinstance(self.data_buffer_id, bool)
            or not 0 <= self.data_buffer_id < _TRANSACTION_ID_LIMIT
        ):
            raise ValueError("data_buffer_id must be a 12-bit identifier")
        try:
            completion_response_error = ChiRespErr(
                self.completion_response_error
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Home pending completion has an unknown RespErr"
            ) from error
        if completion_response_error not in (
            ChiRespErr.OK,
            ChiRespErr.NDERR,
        ):
            raise ValueError(
                "coherent Home pending supports only OK or NDERR completion"
            )
        targets = frozenset(self.snoop_targets)
        for node_id in targets:
            _require_node_id("snoop target", node_id)
        results = {
            node_id: (
                result
                if isinstance(result, ChiSnoopResult)
                else ChiSnoopResult(result)
            )
            for node_id, result in self.snoop_results.items()
        }
        if not set(results) <= set(targets):
            raise ValueError("snoop response source is not an expected target")
        if sum(result.passes_dirty for result in results.values()) > 1:
            raise ValueError(
                "one coherent transaction cannot collect two dirty owners"
            )
        if type(self.completion_sent) is not bool:
            raise TypeError("completion_sent must be bool")
        prepared = self.prepared_backing_write
        if completion_response_error is ChiRespErr.NDERR:
            if (
                not isinstance(self.request, ChiReadUniqueMessage)
                or snoop_transaction_id is not None
                or targets
                or results
                or not self.completion_sent
                or prepared is not None
            ):
                raise ValueError(
                    "pre-snoop ReadUnique NDERR must have no Snoop identity, "
                    "targets, results, or prepared backing write and must "
                    "already have emitted its completion"
                )
        elif snoop_transaction_id is None:
            raise ValueError(
                "successful coherent pending requires a Snoop identity"
            )
        if prepared is not None:
            if not isinstance(prepared, PreparedBackingWrite):
                raise TypeError(
                    "Home prepared backing write requires "
                    "PreparedBackingWrite"
                )
            dirty = tuple(
                result for result in results.values() if result.passes_dirty
            )
            if (
                not self.completion_sent
                or set(results) != set(targets)
                or len(dirty) != 1
                or not isinstance(
                    self.request,
                    (
                        ChiCleanUniqueMessage,
                        ChiReadNotSharedDirtyMessage,
                    ),
                )
                or prepared.address != self.request.address
                or prepared.data != dirty[0].data
            ):
                raise ValueError(
                    "prepared backing write must match one completed "
                    "dirty-data absorption lifecycle"
                )
        object.__setattr__(self, "snoop_targets", targets)
        object.__setattr__(
            self,
            "snoop_results",
            MappingProxyType(results),
        )
        object.__setattr__(
            self,
            "completion_response_error",
            completion_response_error,
        )

    @property
    def all_snoops_complete(self) -> bool:
        return set(self.snoop_results) == set(self.snoop_targets)

    @property
    def dirty_result(self) -> ChiSnoopResult | None:
        results = tuple(
            result
            for result in self.snoop_results.values()
            if result.passes_dirty
        )
        return results[0] if results else None

    @property
    def memory_update_data(self) -> int | None:
        """Latest line retained by Home for a prepared backing update.

        A non-``None`` value is an explicit reference-backing obligation
        owned by this pending transaction.  It remains live after ``Comp``
        and is closed together with directory authority when ``CompAck`` is
        accepted.  It is not evidence of a downstream SN or physical-media
        commit.
        """

        if self.prepared_backing_write is None:
            return None
        return self.prepared_backing_write.data


class ChiHomeWriteBackAdmission(str, Enum):
    """System-validated authority mode for one Home WriteBack admission."""

    CURRENT_OWNER = "current_owner"
    SNOOP_CANCELED = "snoop_canceled"


@dataclass(frozen=True)
class ChiHomeWriteBackPending:
    """Home reservation plus immutable authority evidence for CopyBack."""

    requester_id: int
    request: ChiWriteBackFullMessage
    data_buffer_id: int
    directory_snapshot: ChiHomeDirectoryEntry
    backing_version: int
    admission: ChiHomeWriteBackAdmission = (
        ChiHomeWriteBackAdmission.CURRENT_OWNER
    )

    def __post_init__(self) -> None:
        _require_node_id("writeback requester", self.requester_id)
        if not isinstance(self.request, ChiWriteBackFullMessage):
            raise TypeError(
                "Home writeback pending record requires WriteBackFull"
            )
        if (
            not isinstance(self.data_buffer_id, int)
            or isinstance(self.data_buffer_id, bool)
            or not 0 <= self.data_buffer_id < _TRANSACTION_ID_LIMIT
        ):
            raise ValueError("writeback data_buffer_id must be 12-bit")
        if (
            not isinstance(
                self.directory_snapshot,
                ChiHomeDirectoryEntry,
            )
            or self.directory_snapshot.address != self.request.address
        ):
            raise ValueError(
                "writeback directory snapshot must match the request line"
            )
        if (
            not isinstance(self.backing_version, int)
            or isinstance(self.backing_version, bool)
            or self.backing_version < 0
        ):
            raise ValueError(
                "writeback backing version must be a non-negative integer"
            )
        object.__setattr__(
            self,
            "admission",
            ChiHomeWriteBackAdmission(self.admission),
        )


@dataclass(frozen=True)
class ChiHomeAcceptCoherentRead:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message,
            (
                ChiReadSharedMessage,
                ChiReadNotSharedDirtyMessage,
                ChiReadUniqueMessage,
            ),
        ):
            raise TypeError(
                "Home read action requires a supported coherent Read"
            )


@dataclass(frozen=True)
class ChiHomeAcceptCleanUnique:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message, ChiCleanUniqueMessage
        ):
            raise TypeError(
                "Home CleanUnique action requires a CleanUnique packet"
            )


@dataclass(frozen=True)
class ChiHomeAcceptSnoopResponse:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message,
            (ChiSnpRespMessage, ChiSnpRespDataMessage),
        ):
            raise TypeError(
                "Home snoop response action requires SnpResp or SnpRespData"
            )


@dataclass(frozen=True)
class ChiHomeAcceptCompAck:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message, ChiCompAckMessage
        ):
            raise TypeError("Home completion action requires CompAck")


@dataclass(frozen=True)
class ChiHomeAcceptWriteBackFull:
    packet: ChiNetworkPacket
    admission: ChiHomeWriteBackAdmission = (
        ChiHomeWriteBackAdmission.CURRENT_OWNER
    )

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message, ChiWriteBackFullMessage
        ):
            raise TypeError(
                "Home writeback action requires WriteBackFull packet"
            )
        object.__setattr__(
            self,
            "admission",
            ChiHomeWriteBackAdmission(self.admission),
        )


@dataclass(frozen=True)
class ChiHomeAcceptCopyBackData:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message, ChiCopyBackWrDataMessage
        ):
            raise TypeError(
                "Home copyback action requires CopyBackWrData packet"
            )


@dataclass(frozen=True)
class ChiHomeGrantPCredit:
    """Reserve one real Home transaction slot for the oldest retry debt."""


ChiCoherentHomeAction = (
    ChiHomeAcceptCoherentRead
    | ChiHomeAcceptCleanUnique
    | ChiHomeAcceptSnoopResponse
    | ChiHomeAcceptCompAck
    | ChiHomeAcceptWriteBackFull
    | ChiHomeAcceptCopyBackData
    | ChiHomeGrantPCredit
)


@dataclass(frozen=True)
class ChiCoherentHomeState:
    directory: Mapping[int, ChiHomeDirectoryEntry]
    backing: LineBackingState
    pending: Mapping[int, ChiCoherentTransactionPending] = field(
        default_factory=dict
    )
    next_snoop_transaction_id: int = 0x100
    next_data_buffer_id: int = 0x200
    pending_writebacks: Mapping[int, ChiHomeWriteBackPending] = field(
        default_factory=dict
    )
    request_retry: ChiRequestRetryHomeState = field(
        default_factory=ChiRequestRetryHomeState
    )

    def __post_init__(self) -> None:
        if not isinstance(self.backing, LineBackingState):
            raise TypeError(
                "coherent Home backing requires LineBackingState"
            )
        directory = dict(self.directory)
        if any(
            not isinstance(entry, ChiHomeDirectoryEntry)
            or address != entry.address
            for address, entry in directory.items()
        ):
            raise ValueError(
                "Home directory mapping key must match entry address"
            )
        missing_backing = set(directory) - set(self.backing.lines)
        if missing_backing:
            raise ValueError(
                "Home directory addresses require backing lines: "
                f"{sorted(missing_backing)!r}"
            )
        pending = dict(self.pending)
        if any(
            not isinstance(item, ChiCoherentTransactionPending)
            or data_buffer_id != item.data_buffer_id
            for data_buffer_id, item in pending.items()
        ):
            raise ValueError("Home pending mapping key must match DBID")
        for name, value in (
            ("next_snoop_transaction_id", self.next_snoop_transaction_id),
            ("next_data_buffer_id", self.next_data_buffer_id),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value < _TRANSACTION_ID_LIMIT
            ):
                raise ValueError(f"{name} must be a 12-bit identifier")
        object.__setattr__(
            self,
            "directory",
            MappingProxyType(directory),
        )
        object.__setattr__(self, "pending", MappingProxyType(pending))
        writebacks = dict(self.pending_writebacks)
        if any(
            not isinstance(item, ChiHomeWriteBackPending)
            or data_buffer_id != item.data_buffer_id
            for data_buffer_id, item in writebacks.items()
        ):
            raise ValueError(
                "Home pending-writeback mapping key must match DBID"
            )
        if set(pending) & set(writebacks):
            raise ValueError(
                "Home coherence and writebacks share one DBID allocation space"
            )
        reserved_addresses = tuple(
            item.request.address for item in pending.values()
        ) + tuple(
            item.request.address for item in writebacks.values()
        )
        for address in reserved_addresses:
            _require_line_address(address)
        if len(set(reserved_addresses)) != len(reserved_addresses):
            raise ValueError(
                "Home coherent transactions must reserve distinct lines"
            )
        if any(address not in directory for address in reserved_addresses):
            raise ValueError(
                "Home pending transaction requires a directory entry"
            )
        for item in writebacks.values():
            entry = directory[item.request.address]
            if (
                item.admission
                is ChiHomeWriteBackAdmission.CURRENT_OWNER
                and entry.unique_owner != item.requester_id
            ):
                raise ValueError(
                    "normal Home writeback requester must remain Unique owner"
                )
            if (
                item.admission
                is ChiHomeWriteBackAdmission.SNOOP_CANCELED
                and (
                    entry.unique_owner == item.requester_id
                    or item.requester_id in entry.sharers
                    or entry.shared_dirty_owner == item.requester_id
                )
            ):
                raise ValueError(
                    "Snoop-canceled Home writeback requester must no longer "
                    "hold directory authority"
                )
        requester_transactions = tuple(
            (item.requester_id, item.request.transaction_id)
            for item in pending.values()
        ) + tuple(
            (item.requester_id, item.request.transaction_id)
            for item in writebacks.values()
        )
        if len(set(requester_transactions)) != len(
            requester_transactions
        ):
            raise ValueError(
                "Home pending transactions must have distinct "
                "Requester/TxnID identities"
            )
        object.__setattr__(
            self,
            "pending_writebacks",
            MappingProxyType(writebacks),
        )
        if not isinstance(self.request_retry, ChiRequestRetryHomeState):
            raise TypeError(
                "Home Request-Retry facet requires Home retry state"
            )


ChiCoherentRetryAdmissionPolicy = Callable[
    [ChiReadUniqueMessage, ChiCoherentHomeState],
    int | None,
]
ChiReadUniqueNderrPolicy = Callable[
    [ChiReadUniqueMessage, ChiCoherentHomeState],
    bool,
]


class ChiCoherentHomeNode(
    SemanticComponent[
        ChiCoherentHomeAction,
        ChiCoherentHomeState,
        ChiNetworkPacket,
    ]
):
    """Restricted directory and coherence transactions over one backing core.

    Until DAT fragmentation is implemented, the emitted full-line CompData
    requires a 512-bit DAT representation profile.
    """

    def __init__(
        self,
        name: str,
        node_id: int,
        *,
        backing_core: FullLineBackingCore,
        initial_directory: tuple[ChiHomeDirectoryEntry, ...],
        transaction_capacity: int = 4,
        initial_snoop_transaction_id: int = 0x100,
        initial_data_buffer_id: int = 0x200,
        allow_dirty_data_transfer: bool = False,
        default_protocol_credit_type: int = 0,
        retry_policy: ChiCoherentRetryAdmissionPolicy | None = None,
        read_unique_nderr_policy: ChiReadUniqueNderrPolicy | None = None,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("coherent Home requires a name")
        _require_node_id("Home node_id", node_id)
        if not isinstance(backing_core, FullLineBackingCore):
            raise TypeError(
                "coherent Home requires FullLineBackingCore"
            )
        if backing_core.line_bytes != _CACHE_LINE_BYTES:
            raise ValueError(
                "CHI Issue H coherent Home requires 64-byte backing lines"
            )
        entries = tuple(initial_directory)
        if any(not isinstance(item, ChiHomeDirectoryEntry) for item in entries):
            raise TypeError(
                "Home initial directory requires ChiHomeDirectoryEntry"
            )
        if len({item.address for item in entries}) != len(entries):
            raise ValueError("Home initial directory addresses must be unique")
        initial_backing = backing_core.initial_state()
        missing_backing = {
            item.address for item in entries
        } - set(initial_backing.lines)
        if missing_backing:
            raise ValueError(
                "Home initial directory requires matching backing lines: "
                f"{sorted(missing_backing)!r}"
            )
        if (
            not isinstance(transaction_capacity, int)
            or isinstance(transaction_capacity, bool)
            or not 0 < transaction_capacity <= _TRANSACTION_ID_LIMIT
        ):
            raise ValueError(
                "Home transaction capacity must be in 1..4096"
            )
        for name_, value in (
            ("initial_snoop_transaction_id", initial_snoop_transaction_id),
            ("initial_data_buffer_id", initial_data_buffer_id),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value < _TRANSACTION_ID_LIMIT
            ):
                raise ValueError(f"{name_} must be a 12-bit identifier")
        if type(allow_dirty_data_transfer) is not bool:
            raise TypeError("allow_dirty_data_transfer must be bool")
        if (
            not isinstance(default_protocol_credit_type, int)
            or isinstance(default_protocol_credit_type, bool)
            or not 0 <= default_protocol_credit_type < 16
        ):
            raise ValueError("default protocol-credit type must be in 0..15")
        if retry_policy is not None and not callable(retry_policy):
            raise TypeError("coherent Home retry_policy must be callable")
        if (
            read_unique_nderr_policy is not None
            and not callable(read_unique_nderr_policy)
        ):
            raise TypeError(
                "coherent Home read_unique_nderr_policy must be callable"
            )
        self.name = name
        self.node_id = node_id
        self.backing_core = backing_core
        self.initial_directory = entries
        self.transaction_capacity = transaction_capacity
        self.initial_snoop_transaction_id = initial_snoop_transaction_id
        self.initial_data_buffer_id = initial_data_buffer_id
        self.allow_dirty_data_transfer = allow_dirty_data_transfer
        self.default_protocol_credit_type = default_protocol_credit_type
        self.retry_policy = retry_policy
        self.read_unique_nderr_policy = read_unique_nderr_policy

    def initial_state(self) -> ChiCoherentHomeState:
        return ChiCoherentHomeState(
            directory={
                entry.address: entry
                for entry in self.initial_directory
            },
            backing=self.backing_core.initial_state(),
            next_snoop_transaction_id=self.initial_snoop_transaction_id,
            next_data_buffer_id=self.initial_data_buffer_id,
        )

    def is_quiescent(self, state: ChiCoherentHomeState) -> bool:
        return (
            isinstance(state, ChiCoherentHomeState)
            and not state.pending
            and not state.pending_writebacks
            and not state.request_retry.retry_debts
            and not state.request_retry.reservations
        )

    def step(
        self,
        state: ChiCoherentHomeState,
        action: ChiCoherentHomeAction,
    ) -> SemanticStep[ChiCoherentHomeState, ChiNetworkPacket]:
        if not isinstance(state, ChiCoherentHomeState):
            raise TypeError("coherent Home requires ChiCoherentHomeState")
        active_count = len(state.pending) + len(state.pending_writebacks)
        if (
            active_count + state.request_retry.reserved_count
            > self.transaction_capacity
        ):
            return self._fault(
                state,
                "retry_capacity_invariant",
                "active transactions plus P-Credit reservations exceed "
                "Home capacity",
            )
        if isinstance(action, ChiHomeAcceptCoherentRead):
            return self._accept_coherence_request(state, action.packet)
        if isinstance(action, ChiHomeAcceptCleanUnique):
            return self._accept_coherence_request(state, action.packet)
        if isinstance(action, ChiHomeAcceptSnoopResponse):
            return self._accept_snoop_response(state, action.packet)
        if isinstance(action, ChiHomeAcceptCompAck):
            return self._accept_comp_ack(state, action.packet)
        if isinstance(action, ChiHomeAcceptWriteBackFull):
            return self._accept_writeback_full(
                state,
                action.packet,
                action.admission,
            )
        if isinstance(action, ChiHomeAcceptCopyBackData):
            return self._accept_copyback_data(state, action.packet)
        if isinstance(action, ChiHomeGrantPCredit):
            return self._grant_pcredit(state)
        raise TypeError("unknown coherent Home action")

    def _accept_coherence_request(
        self,
        state: ChiCoherentHomeState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherentHomeState, ChiNetworkPacket]:
        request = packet.message
        assert isinstance(
            request,
            (
                ChiCleanUniqueMessage,
                ChiReadSharedMessage,
                ChiReadNotSharedDirtyMessage,
                ChiReadUniqueMessage,
            ),
        )
        active_count = len(state.pending) + len(state.pending_writebacks)
        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "request_target",
                "coherent request packet targets another Home",
            )
        if (
            request.size != 6
            or request.address % _CACHE_LINE_BYTES
            or not request.expect_completion_ack
        ):
            return self._fault(
                state,
                "request_profile",
                "coherent Home profile requires an aligned 64-byte request "
                "with ExpCompAck",
            )
        if isinstance(request, ChiCleanUniqueMessage) and (
            not request.allow_retry
            or request.protocol_credit_type != 0
            or request.memory_attributes not in (0b0101, 0b1101)
            or request.likely_shared
        ):
            return self._fault(
                state,
                "clean_unique_profile",
                "initial CleanUnique requires Normal-memory attributes, "
                "AllowRetry=1, PCrdType=0, and LikelyShared=0",
            )
        if isinstance(request, ChiReadUniqueMessage):
            if request.allow_retry and request.protocol_credit_type != 0:
                return self._fault(
                    state,
                    "read_unique_initial_credit_type",
                    "initial ReadUnique requires PCrdType=0",
                )
            if (
                not request.allow_retry
                and request.protocol_credit_type not in range(16)
            ):
                return self._fault(
                    state,
                    "read_unique_retry_credit_type",
                    "credited ReadUnique requires a 4-bit PCrdType",
                )
        elif not isinstance(request, ChiCleanUniqueMessage) and (
            not request.allow_retry
            or request.protocol_credit_type != 0
        ):
            return self._fault(
                state,
                "coherent_read_initial_retry_shape",
                "the current non-ReadUnique coherent reads accept only "
                "initial AllowRetry=1, PCrdType=0 requests",
            )
        unsupported = tuple(
            name
            for name, enabled in (
                ("non-snoopable", not request.snoop_attribute),
                ("exclusive", request.exclusive),
                ("ordered", request.order != 0),
                ("tag operation", request.tag_operation != 0),
                ("trace tag", request.trace_tag),
            )
            if enabled
        )
        if unsupported:
            return self._fault(
                state,
                "request_attributes",
                "coherent Home does not implement "
                + ", ".join(unsupported),
            )
        entry = state.directory.get(request.address)
        if entry is None:
            return self._fault(
                state,
                "address_home",
                "Home has no backing entry for this address",
            )
        if (
            isinstance(request, ChiCleanUniqueMessage)
            and entry.shared_dirty_owner is not None
            and not self.allow_dirty_data_transfer
        ):
            return self._fault(
                state,
                "clean_unique_shared_dirty_disabled",
                "shared-dirty CleanUnique requires a Home configured "
                "to accept PassDirty snoop data",
            )
        if any(
            item.request.address == request.address
            for item in state.pending.values()
        ) or any(
            item.request.address == request.address
            for item in state.pending_writebacks.values()
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    chi_line_resource_name(self.name, request.address),
                    ConstraintScope.SYSTEM,
                    available=0,
                    capacity=1,
                    reason="same-line coherent transaction is in progress",
                    location=self.name,
                ),
            )
        if any(
            item.requester_id == packet.source_id
            and item.request.transaction_id == request.transaction_id
            for item in state.pending.values()
        ) or any(
            item.requester_id == packet.source_id
            and item.request.transaction_id == request.transaction_id
            for item in state.pending_writebacks.values()
        ):
            return self._fault(
                state,
                "duplicate_request",
                "Home already owns this Requester/TxnID",
            )
        request_retry = state.request_retry
        if isinstance(request, ChiReadUniqueMessage):
            if request.allow_retry:
                credit_type = (
                    None
                    if self.retry_policy is None
                    else self.retry_policy(request, state)
                )
                if credit_type is not None and (
                    not isinstance(credit_type, int)
                    or isinstance(credit_type, bool)
                    or not 0 <= credit_type < 16
                ):
                    return self._fault(
                        state,
                        "retry_policy",
                        "retry policy returned a P-Credit type outside 0..15",
                    )
                no_unreserved_slot = (
                    active_count + request_retry.reserved_count
                    >= self.transaction_capacity
                )
                if credit_type is not None or (
                    self.retry_policy is not None and no_unreserved_slot
                ):
                    if credit_type is None:
                        credit_type = self.default_protocol_credit_type
                    try:
                        request_retry, response = (
                            ChiRequestRetryContract.record_retry(
                                request_retry,
                                requester_id=packet.source_id,
                                transaction_id=request.transaction_id,
                                protocol_credit_type=credit_type,
                            )
                        )
                    except ChiRequestRetryContractError as error:
                        return self._fault(
                            state,
                            error.code,
                            error.reason,
                        )
                    candidate = ChiCoherentHomeState(
                        directory=state.directory,
                        backing=state.backing,
                        pending=state.pending,
                        next_snoop_transaction_id=(
                            state.next_snoop_transaction_id
                        ),
                        next_data_buffer_id=state.next_data_buffer_id,
                        pending_writebacks=state.pending_writebacks,
                        request_retry=request_retry,
                    )
                    return SemanticStep(
                        candidate,
                        (
                            ChiNetworkPacket.response(
                                response,
                                source_id=self.node_id,
                                target_id=packet.source_id,
                            ),
                        ),
                    )
            else:
                try:
                    request_retry = (
                        ChiRequestRetryContract.consume_reservation(
                            request_retry,
                            requester_id=packet.source_id,
                            protocol_credit_type=(
                                request.protocol_credit_type
                            ),
                        )
                    )
                except ChiRequestRetryContractError as error:
                    return self._fault(state, error.code, error.reason)

        if (
            request.allow_retry
            and active_count + request_retry.reserved_count
            >= self.transaction_capacity
        ) or (
            not request.allow_retry
            and active_count >= self.transaction_capacity
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.coherence_transaction_slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.transaction_capacity,
                    reason="Home coherence transaction table is full",
                    location=self.name,
                ),
            )

        complete_with_nderr = False
        if (
            isinstance(request, ChiReadUniqueMessage)
            and self.read_unique_nderr_policy is not None
        ):
            complete_with_nderr = self.read_unique_nderr_policy(
                request,
                state,
            )
            if type(complete_with_nderr) is not bool:
                return self._fault(
                    state,
                    "read_unique_nderr_policy",
                    "ReadUnique NDERR policy must return bool",
                )
        data_buffer_id = self._allocate_identifier(
            state.next_data_buffer_id,
            set(state.pending) | set(state.pending_writebacks),
        )
        if complete_with_nderr:
            pending_item = ChiCoherentTransactionPending(
                packet.source_id,
                request,
                None,
                data_buffer_id,
                frozenset(),
                completion_sent=True,
                completion_response_error=ChiRespErr.NDERR,
            )
            pending = dict(state.pending)
            pending[data_buffer_id] = pending_item
            candidate = ChiCoherentHomeState(
                directory=state.directory,
                backing=state.backing,
                pending=pending,
                next_snoop_transaction_id=(
                    state.next_snoop_transaction_id
                ),
                next_data_buffer_id=(
                    (data_buffer_id + 1) % _TRANSACTION_ID_LIMIT
                ),
                pending_writebacks=state.pending_writebacks,
                request_retry=request_retry,
            )
            return SemanticStep(
                candidate,
                (self._completion_packet(state, pending_item),),
            )

        targets = set(entry.sharers)
        if entry.unique_owner is not None:
            targets.add(entry.unique_owner)
        targets.discard(packet.source_id)
        snoop_id = self._allocate_identifier(
            state.next_snoop_transaction_id,
            {
                item.snoop_transaction_id
                for item in state.pending.values()
                if item.snoop_transaction_id is not None
            },
        )
        pending_item = ChiCoherentTransactionPending(
            packet.source_id,
            request,
            snoop_id,
            data_buffer_id,
            frozenset(targets),
            completion_sent=not targets,
        )
        pending = dict(state.pending)
        pending[data_buffer_id] = pending_item
        emissions: tuple[ChiNetworkPacket, ...]
        if targets:
            if isinstance(request, ChiCleanUniqueMessage):
                snoop: ChiCoherentSnoopMessage = (
                    ChiSnpCleanInvalidMessage(
                        transaction_id=snoop_id,
                        address=request.address,
                        qos=request.qos,
                        pas=request.pas,
                        do_not_go_to_shared_dirty=True,
                        return_to_source=False,
                    )
                )
            elif isinstance(request, ChiReadUniqueMessage):
                snoop = ChiSnpUniqueMessage(
                    transaction_id=snoop_id,
                    address=request.address,
                    qos=request.qos,
                    pas=request.pas,
                    do_not_go_to_shared_dirty=True,
                    return_to_source=(
                        self.allow_dirty_data_transfer
                        and entry.unique_owner is not None
                        and entry.unique_owner in targets
                    ),
                )
            elif isinstance(request, ChiReadNotSharedDirtyMessage):
                snoop = ChiSnpNotSharedDirtyMessage(
                    transaction_id=snoop_id,
                    address=request.address,
                    qos=request.qos,
                    pas=request.pas,
                    do_not_go_to_shared_dirty=True,
                    return_to_source=(
                        self.allow_dirty_data_transfer
                        and entry.unique_owner is not None
                        and entry.unique_owner in targets
                    ),
                )
            else:
                snoop = ChiSnpSharedMessage(
                    transaction_id=snoop_id,
                    address=request.address,
                    qos=request.qos,
                    pas=request.pas,
                    return_to_source=False,
                )
            emissions = tuple(
                ChiNetworkPacket.snoop(
                    snoop,
                    source_id=self.node_id,
                    target_id=target,
                )
                for target in sorted(targets)
            )
        else:
            emissions = (self._completion_packet(state, pending_item),)
        candidate = ChiCoherentHomeState(
            directory=state.directory,
            backing=state.backing,
            pending=pending,
            next_snoop_transaction_id=(
                (snoop_id + 1) % _TRANSACTION_ID_LIMIT
            ),
            next_data_buffer_id=(
                (data_buffer_id + 1) % _TRANSACTION_ID_LIMIT
            ),
            pending_writebacks=state.pending_writebacks,
            request_retry=request_retry,
        )
        return SemanticStep(candidate, emissions)

    def _grant_pcredit(
        self,
        state: ChiCoherentHomeState,
    ) -> SemanticStep[ChiCoherentHomeState, ChiNetworkPacket]:
        if not state.request_retry.retry_debts:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.retry_debt",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    reason="Home has no RetryAck awaiting P-Credit",
                    location=self.name,
                ),
            )
        active_count = len(state.pending) + len(state.pending_writebacks)
        if (
            active_count + state.request_retry.reserved_count
            >= self.transaction_capacity
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.retry_reservation_slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.transaction_capacity,
                    reason="Home has no real transaction slot for P-Credit",
                    location=self.name,
                ),
            )
        request_retry, debt, grant = (
            ChiRequestRetryContract.grant_oldest(state.request_retry)
        )
        candidate = ChiCoherentHomeState(
            directory=state.directory,
            backing=state.backing,
            pending=state.pending,
            next_snoop_transaction_id=state.next_snoop_transaction_id,
            next_data_buffer_id=state.next_data_buffer_id,
            pending_writebacks=state.pending_writebacks,
            request_retry=request_retry,
        )
        return SemanticStep(
            candidate,
            (
                ChiNetworkPacket.response(
                    grant,
                    source_id=self.node_id,
                    target_id=debt.requester_id,
                ),
            ),
        )

    def _accept_snoop_response(
        self,
        state: ChiCoherentHomeState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherentHomeState, ChiNetworkPacket]:
        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "snoop_response_target",
                "SnpResp packet targets another Home",
            )
        response = packet.message
        assert isinstance(
            response,
            (ChiSnpRespMessage, ChiSnpRespDataMessage),
        )
        matches = tuple(
            item
            for item in state.pending.values()
            if item.snoop_transaction_id == response.transaction_id
            and packet.source_id in item.snoop_targets
        )
        if len(matches) != 1:
            return self._fault(
                state,
                "snoop_response_identity",
                "SnpResp does not select one pending snoop copy",
            )
        pending_item = matches[0]
        if pending_item.completion_sent:
            return self._fault(
                state,
                "late_snoop_response",
                "SnpResp arrived after completion was released",
            )
        if packet.source_id in pending_item.snoop_results:
            return self._fault(
                state,
                "duplicate_snoop_response",
                "Home already consumed this Snoopee RSP or DAT result",
            )
        is_data = isinstance(response, ChiSnpRespDataMessage)
        if is_data and not self.allow_dirty_data_transfer:
            return self._fault(
                state,
                "snoop_data_profile",
                "Home dirty-data transfer profile is not enabled",
            )
        if (
            is_data
            and response.response is ChiRespCode.I_PD
            and pending_item.dirty_result is not None
        ):
            return self._fault(
                state,
                "multiple_dirty_owners",
                "two Snoopees attempted to pass dirty responsibility",
            )
        if isinstance(pending_item.request, ChiCleanUniqueMessage):
            entry = state.directory[pending_item.request.address]
            requires_dirty_data = (
                packet.source_id == entry.shared_dirty_owner
            )
            permits_dirty_data = (
                requires_dirty_data
                or packet.source_id == entry.unique_owner
            )
            if requires_dirty_data and not is_data:
                return self._fault(
                    state,
                    "clean_unique_shared_dirty_response",
                    "the directory shared-dirty owner must return "
                    "SnpRespData_I_PD",
                )
            if is_data and not permits_dirty_data:
                return self._fault(
                    state,
                    "clean_unique_dirty_response_source",
                    "only the directory dirty owner can return "
                    "SnpRespData_I_PD for CleanUnique",
                )
            allowed_responses = (
                (ChiRespCode.I_PD,)
                if is_data
                else (ChiRespCode.I,)
            )
        elif isinstance(pending_item.request, ChiReadUniqueMessage):
            allowed_responses = (
                (ChiRespCode.I, ChiRespCode.I_PD)
                if is_data
                else (ChiRespCode.I,)
            )
        elif isinstance(
            pending_item.request,
            ChiReadNotSharedDirtyMessage,
        ):
            allowed_responses = (
                (ChiRespCode.SC, ChiRespCode.SC_PD)
                if is_data
                else (ChiRespCode.I, ChiRespCode.SC)
            )
        else:
            allowed_responses = (
                ()
                if is_data
                else (ChiRespCode.I, ChiRespCode.SC)
            )
        if (
            response.response_error != 0
            or response.response not in allowed_responses
        ):
            return self._fault(
                state,
                "snoop_response_state",
                "snoop response form/state is incompatible with its "
                "coherence-request profile",
            )
        result = ChiSnoopResult(
            response.response,
            response.data if is_data else None,
        )
        if result.passes_dirty and pending_item.dirty_result is not None:
            return self._fault(
                state,
                "multiple_dirty_owners",
                "two Snoopees attempted to pass dirty responsibility",
            )
        results = dict(pending_item.snoop_results)
        results[packet.source_id] = result
        all_snoops_complete = set(results) == set(
            pending_item.snoop_targets
        )
        prepared_backing_write: PreparedBackingWrite | None = None
        if all_snoops_complete and isinstance(
            pending_item.request,
            (
                ChiCleanUniqueMessage,
                ChiReadNotSharedDirtyMessage,
            ),
        ):
            dirty_results = tuple(
                item for item in results.values() if item.passes_dirty
            )
            if dirty_results:
                dirty_data = dirty_results[0].data
                assert dirty_data is not None
                try:
                    prepared_backing_write = (
                        self.backing_core.prepare_write(
                            state.backing,
                            pending_item.request.address,
                            dirty_data,
                        )
                    )
                except (KeyError, ValueError) as error:
                    return self._fault(
                        state,
                        "backing_prepare",
                        "Home could not prepare the absorbed dirty line: "
                        f"{error}",
                    )
        updated = ChiCoherentTransactionPending(
            pending_item.requester_id,
            pending_item.request,
            pending_item.snoop_transaction_id,
            pending_item.data_buffer_id,
            pending_item.snoop_targets,
            results,
            completion_sent=all_snoops_complete,
            completion_response_error=(
                pending_item.completion_response_error
            ),
            prepared_backing_write=prepared_backing_write,
        )
        pending = dict(state.pending)
        pending[updated.data_buffer_id] = updated
        emissions: tuple[ChiNetworkPacket, ...] = ()
        if updated.completion_sent:
            emissions = (self._completion_packet(state, updated),)
        return SemanticStep(
            ChiCoherentHomeState(
                directory=state.directory,
                backing=state.backing,
                pending=pending,
                next_snoop_transaction_id=(
                    state.next_snoop_transaction_id
                ),
                next_data_buffer_id=state.next_data_buffer_id,
                pending_writebacks=state.pending_writebacks,
                request_retry=state.request_retry,
            ),
            emissions,
        )

    def _accept_comp_ack(
        self,
        state: ChiCoherentHomeState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherentHomeState, ChiNetworkPacket]:
        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "completion_ack_target",
                "CompAck packet targets another Home",
            )
        ack = packet.message
        assert isinstance(ack, ChiCompAckMessage)
        pending_item = state.pending.get(ack.transaction_id)
        if (
            pending_item is None
            or packet.source_id != pending_item.requester_id
        ):
            return self._fault(
                state,
                "completion_ack_identity",
                "CompAck does not match the Home DBID/requester pair",
            )
        if not pending_item.completion_sent:
            return self._fault(
                state,
                "early_completion_ack",
                "CompAck arrived before all selected snoops completed",
            )
        if pending_item.completion_response_error is ChiRespErr.NDERR:
            if ack.response != 0 or ack.trace_tag:
                return self._fault(
                    state,
                    "read_unique_nderr_completion_ack_state",
                    "the ReadUnique NDERR profile requires CompAck Resp=0 "
                    "and TraceTag=0",
                )
            pending = dict(state.pending)
            del pending[pending_item.data_buffer_id]
            return SemanticStep(
                ChiCoherentHomeState(
                    directory=state.directory,
                    backing=state.backing,
                    pending=pending,
                    next_snoop_transaction_id=(
                        state.next_snoop_transaction_id
                    ),
                    next_data_buffer_id=state.next_data_buffer_id,
                    pending_writebacks=state.pending_writebacks,
                    request_retry=state.request_retry,
                )
            )
        if (
            isinstance(pending_item.request, ChiCleanUniqueMessage)
            and (ack.response != 0 or ack.trace_tag)
        ):
            return self._fault(
                state,
                "clean_unique_completion_ack_state",
                "the CleanUnique profile requires CompAck Resp=0 and "
                "TraceTag=0",
            )
        entry = state.directory[pending_item.request.address]
        backing = state.backing
        if pending_item.prepared_backing_write is not None:
            try:
                backing = self.backing_core.commit_write(
                    state.backing,
                    pending_item.prepared_backing_write,
                ).state
            except (BackingCommitConflict, ValueError) as error:
                return self._fault(
                    state,
                    "backing_commit_conflict",
                    "Home backing changed after completion preparation: "
                    f"{error}",
                )
        directory = dict(state.directory)
        if isinstance(
            pending_item.request,
            (ChiCleanUniqueMessage, ChiReadUniqueMessage),
        ):
            directory[entry.address] = self._commit_unique_directory(
                entry,
                pending_item,
            )
        else:
            sharers = set(entry.sharers)
            if entry.unique_owner is not None:
                sharers.add(entry.unique_owner)
            sharers.difference_update(pending_item.snoop_targets)
            sharers.update(
                node_id
                for node_id, result in
                pending_item.snoop_results.items()
                if result.response
                in (ChiRespCode.SC, ChiRespCode.SC_PD)
            )
            sharers.add(pending_item.requester_id)
            directory[entry.address] = ChiHomeDirectoryEntry(
                entry.address,
                sharers=frozenset(sharers),
                unique_owner=None,
            )
        pending = dict(state.pending)
        del pending[pending_item.data_buffer_id]
        return SemanticStep(
            ChiCoherentHomeState(
                directory=directory,
                backing=backing,
                pending=pending,
                next_snoop_transaction_id=(
                    state.next_snoop_transaction_id
                ),
                next_data_buffer_id=state.next_data_buffer_id,
                pending_writebacks=state.pending_writebacks,
                request_retry=state.request_retry,
            )
        )

    def _accept_writeback_full(
        self,
        state: ChiCoherentHomeState,
        packet: ChiNetworkPacket,
        admission: ChiHomeWriteBackAdmission,
    ) -> SemanticStep[ChiCoherentHomeState, ChiNetworkPacket]:
        """Allocate a Home DBID without changing directory/backing state."""

        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "writeback_target",
                "WriteBackFull packet targets another Home",
            )
        if not self.allow_dirty_data_transfer:
            return self._fault(
                state,
                "writeback_disabled",
                "Home profile does not enable dirty-data transfer",
            )
        request = packet.message
        assert isinstance(request, ChiWriteBackFullMessage)
        if (
            request.size != 6
            or request.address % _CACHE_LINE_BYTES
            or not request.allow_retry
            or request.protocol_credit_type != 0
            or request.memory_attributes not in (0b0101, 0b1101)
            or request.expect_completion_ack
        ):
            return self._fault(
                state,
                "writeback_profile",
                "first WriteBackFull profile requires an aligned 64-byte "
                "Normal-memory first attempt without CompAck",
            )
        unsupported = tuple(
            name
            for name, enabled in (
                ("likely shared", request.likely_shared),
                ("non-snoopable", not request.snoop_attribute),
                ("exclusive", request.exclusive),
                ("ordered", request.order != 0),
                ("tag operation", request.tag_operation != 0),
                ("trace tag", request.trace_tag),
            )
            if enabled
        )
        if unsupported:
            return self._fault(
                state,
                "writeback_attributes",
                "coherent Home does not implement "
                + ", ".join(unsupported),
            )
        entry = state.directory.get(request.address)
        if entry is None:
            return self._fault(
                state,
                "writeback_address_home",
                "Home has no directory/backing entry for this address",
            )
        if (
            admission is ChiHomeWriteBackAdmission.CURRENT_OWNER
            and entry.unique_owner != packet.source_id
        ):
            return self._fault(
                state,
                "writeback_owner",
                "WriteBackFull source is not the directory Unique owner",
            )
        if (
            admission is ChiHomeWriteBackAdmission.SNOOP_CANCELED
            and (
                entry.unique_owner == packet.source_id
                or packet.source_id in entry.sharers
                or entry.shared_dirty_owner == packet.source_id
            )
        ):
            return self._fault(
                state,
                "writeback_cancellation_authority",
                "Snoop-canceled WriteBack source still holds directory "
                "authority",
            )
        if any(
            item.request.address == request.address
            for item in state.pending.values()
        ) or any(
            item.request.address == request.address
            for item in state.pending_writebacks.values()
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    chi_line_resource_name(self.name, request.address),
                    ConstraintScope.SYSTEM,
                    available=0,
                    capacity=1,
                    reason="same-line coherent transaction is in progress",
                    location=self.name,
                ),
            )
        if any(
            item.requester_id == packet.source_id
            and item.request.transaction_id == request.transaction_id
            for item in state.pending.values()
        ) or any(
            item.requester_id == packet.source_id
            and item.request.transaction_id == request.transaction_id
            for item in state.pending_writebacks.values()
        ):
            return self._fault(
                state,
                "duplicate_writeback",
                "Home already owns this Requester/TxnID",
            )
        if (
            len(state.pending)
            + len(state.pending_writebacks)
            + state.request_retry.reserved_count
            >= self.transaction_capacity
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.coherence_transaction_slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.transaction_capacity,
                    reason="Home coherence transaction table is full",
                    location=self.name,
                ),
            )
        data_buffer_id = self._allocate_identifier(
            state.next_data_buffer_id,
            set(state.pending) | set(state.pending_writebacks),
        )
        writebacks = dict(state.pending_writebacks)
        writebacks[data_buffer_id] = ChiHomeWriteBackPending(
            packet.source_id,
            request,
            data_buffer_id,
            entry,
            state.backing.line_at(request.address).version,
            admission,
        )
        response = ChiNetworkPacket.response(
            ChiCompDBIDRespMessage(
                transaction_id=request.transaction_id,
                data_buffer_id=data_buffer_id,
            ),
            source_id=self.node_id,
            target_id=packet.source_id,
        )
        return SemanticStep(
            ChiCoherentHomeState(
                directory=state.directory,
                backing=state.backing,
                pending=state.pending,
                next_snoop_transaction_id=(
                    state.next_snoop_transaction_id
                ),
                next_data_buffer_id=(
                    (data_buffer_id + 1) % _TRANSACTION_ID_LIMIT
                ),
                pending_writebacks=writebacks,
                request_retry=state.request_retry,
            ),
            (response,),
        )

    def _accept_copyback_data(
        self,
        state: ChiCoherentHomeState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherentHomeState, ChiNetworkPacket]:
        """Commit CopyBack data, then release owner authority and the DBID."""

        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "copyback_target",
                "CopyBackWrData packet targets another Home",
            )
        if not self.allow_dirty_data_transfer:
            return self._fault(
                state,
                "copyback_disabled",
                "Home profile does not enable dirty-data transfer",
            )
        message = packet.message
        assert isinstance(message, ChiCopyBackWrDataMessage)
        pending = state.pending_writebacks.get(message.transaction_id)
        if pending is None or pending.requester_id != packet.source_id:
            return self._fault(
                state,
                "copyback_identity",
                "CopyBackWrData does not match the Home DBID/requester pair",
            )
        entry = state.directory[pending.request.address]
        backing_line = state.backing.line_at(pending.request.address)
        if (
            entry != pending.directory_snapshot
            or backing_line.version != pending.backing_version
        ):
            return self._fault(
                state,
                "copyback_reservation_changed",
                "directory or backing authority changed after the Home "
                "admitted WriteBackFull",
            )
        writebacks = dict(state.pending_writebacks)
        del writebacks[pending.data_buffer_id]
        if (
            pending.admission
            is ChiHomeWriteBackAdmission.SNOOP_CANCELED
        ):
            if (
                message.response is not ChiRespCode.I
                or message.response_error != 0
                or message.data_id != 0
                or message.byte_enable != 0
                or message.data != 0
            ):
                return self._fault(
                    state,
                    "copyback_cancellation_profile",
                    "Snoop-canceled WriteBackFull requires "
                    "CopyBackWrData_I with zero data and byte enables",
                )
            return SemanticStep(
                ChiCoherentHomeState(
                    directory=state.directory,
                    backing=state.backing,
                    pending=state.pending,
                    next_snoop_transaction_id=(
                        state.next_snoop_transaction_id
                    ),
                    next_data_buffer_id=state.next_data_buffer_id,
                    pending_writebacks=writebacks,
                    request_retry=state.request_retry,
                )
            )
        if (
            message.response is not ChiRespCode.UD_PD
            or message.response_error != 0
            or message.data_id != 0
            or message.byte_enable != (1 << _CACHE_LINE_BYTES) - 1
            or message.data >= _CACHE_LINE_DATA_LIMIT
        ):
            return self._fault(
                state,
                "copyback_profile",
                "normal WriteBackFull requires one full-line "
                "CopyBackWrData_UD_PD packet",
            )
        if entry.unique_owner != pending.requester_id:
            return self._fault(
                state,
                "copyback_owner",
                "directory owner changed before CopyBackWrData arrived",
            )
        try:
            prepared = self.backing_core.prepare_write(
                state.backing,
                entry.address,
                message.data,
            )
            backing = self.backing_core.commit_write(
                state.backing,
                prepared,
            ).state
        except (BackingCommitConflict, KeyError, ValueError) as error:
            return self._fault(
                state,
                "copyback_backing_commit",
                "Home could not atomically commit CopyBack data: "
                f"{error}",
            )
        directory = dict(state.directory)
        directory[entry.address] = ChiHomeDirectoryEntry(
            entry.address,
            unique_owner=None,
        )
        return SemanticStep(
            ChiCoherentHomeState(
                directory=directory,
                backing=backing,
                pending=state.pending,
                next_snoop_transaction_id=(
                    state.next_snoop_transaction_id
                ),
                next_data_buffer_id=state.next_data_buffer_id,
                pending_writebacks=writebacks,
                request_retry=state.request_retry,
            )
        )

    def _completion_packet(
        self,
        state: ChiCoherentHomeState,
        pending: ChiCoherentTransactionPending,
    ) -> ChiNetworkPacket:
        if pending.completion_response_error is ChiRespErr.NDERR:
            assert isinstance(pending.request, ChiReadUniqueMessage)
            return ChiNetworkPacket.data(
                ChiCompDataMessage(
                    transaction_id=pending.request.transaction_id,
                    data=0,
                    data_id=0,
                    home_node_id=self.node_id,
                    response_error=ChiRespErr.NDERR,
                    response=ChiRespCode.I,
                    data_buffer_id=pending.data_buffer_id,
                ),
                source_id=self.node_id,
                target_id=pending.requester_id,
            )
        if isinstance(pending.request, ChiCleanUniqueMessage):
            return ChiNetworkPacket.response(
                ChiCompMessage(
                    transaction_id=pending.request.transaction_id,
                    data_buffer_id=pending.data_buffer_id,
                    response=ChiRespCode.UC,
                ),
                source_id=self.node_id,
                target_id=pending.requester_id,
            )
        data_results = tuple(
            result
            for result in pending.snoop_results.values()
            if result.data is not None
        )
        dirty_result = pending.dirty_result
        completion_data = (
            dirty_result.data
            if dirty_result is not None
            else (
                data_results[0].data
                if data_results
                else self.backing_core.read_line(
                    state.backing,
                    pending.request.address,
                )
            )
        )
        assert completion_data is not None
        return ChiNetworkPacket.data(
            ChiCompDataMessage(
                transaction_id=pending.request.transaction_id,
                data=completion_data,
                data_id=0,
                home_node_id=self.node_id,
                response_error=0,
                response=(
                    (
                        ChiRespCode.UD_PD
                        if dirty_result is not None
                        else ChiRespCode.UC
                    )
                    if isinstance(pending.request, ChiReadUniqueMessage)
                    else ChiRespCode.SC
                ),
                data_buffer_id=pending.data_buffer_id,
            ),
            source_id=self.node_id,
            target_id=pending.requester_id,
        )

    @staticmethod
    def _commit_unique_directory(
        entry: ChiHomeDirectoryEntry,
        pending: ChiCoherentTransactionPending,
    ) -> ChiHomeDirectoryEntry:
        """Commit the holder-authority half of one Unique lifecycle.

        A prepared backing write, when present, is committed separately before
        this candidate is installed in the same immutable Home-state step.
        ``ReadUnique`` has no such write because dirty responsibility passes to
        the requester.
        """

        return ChiHomeDirectoryEntry(
            entry.address,
            unique_owner=pending.requester_id,
        )

    @staticmethod
    def _allocate_identifier(start: int, used: set[int]) -> int:
        """Choose the next free value in one 12-bit correlation namespace."""

        for offset in range(_TRANSACTION_ID_LIMIT):
            candidate = (start + offset) % _TRANSACTION_ID_LIMIT
            if candidate not in used:
                return candidate
        raise RuntimeError("12-bit CHI transaction identifier space exhausted")

    def _fault(
        self,
        state: ChiCoherentHomeState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiCoherentHomeState, ChiNetworkPacket]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                ConstraintScope.VIRTUAL_DUT,
                self.name,
            ),
        )


__all__ = [
    "ChiCacheLine",
    "ChiCacheState",
    "ChiCoherentTransactionPending",
    "ChiCoherenceRequestMessage",
    "ChiHomeWriteBackAdmission",
    "ChiHomeWriteBackPending",
    "ChiCoherentHomeAction",
    "ChiCoherentHomeNode",
    "ChiCoherentHomeState",
    "ChiCoherentReadMessage",
    "ChiCoherentRnAction",
    "ChiCoherentRnNode",
    "ChiCoherentRnState",
    "ChiCoherentRetryAdmissionPolicy",
    "ChiReadUniqueNderrPolicy",
    "ChiHomeAcceptCompAck",
    "ChiHomeAcceptCleanUnique",
    "ChiHomeAcceptCopyBackData",
    "ChiHomeAcceptCoherentRead",
    "ChiHomeAcceptSnoopResponse",
    "ChiHomeAcceptWriteBackFull",
    "ChiHomeGrantPCredit",
    "ChiHomeDirectoryEntry",
    "ChiRnAcceptComp",
    "ChiRnAcceptCompData",
    "ChiRnAcceptCompDBIDResp",
    "ChiRnAcceptPCrdGrant",
    "ChiRnAcceptRetryAck",
    "ChiRnAcceptSnoop",
    "ChiRnIssueCleanUnique",
    "ChiRnIssueCoherentRead",
    "ChiRnIssueWriteBackFull",
    "ChiRnRetryCoherentRequest",
    "ChiRnWriteBackOutcome",
    "ChiRnWriteBackPending",
    "ChiRnWriteCacheLine",
    "ChiSnoopResult",
]

"""Finite RN/Home behaviors for the executable coherent CHI lifecycle.

The components operate at a delivered-Network-packet boundary.  RN behavior
uses an injected protocol-neutral cache core and owns CHI permission and
transaction state.  Home behavior owns directory and transaction state in the
current slice.  Neither decides how a packet crosses a topology; output is
another explicit ``ChiNetworkPacket`` that a transport runtime can enqueue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.virtual_dut.backend.cache import (
    CacheCore,
    CacheLinePayload,
    CacheLineStoreState,
)

from ..representation.dat import (
    ChiCompDataMessage,
    ChiCopyBackWrDataMessage,
    ChiSnpRespDataMessage,
)
from ..representation.packet import ChiNetworkPacket
from ..representation.req import (
    ChiReadNotSharedDirtyMessage,
    ChiReadSharedMessage,
    ChiReadUniqueMessage,
    ChiWriteBackFullMessage,
)
from ..representation.response import ChiRespCode
from ..representation.rsp import (
    ChiCompAckMessage,
    ChiCompDBIDRespMessage,
    ChiSnpRespMessage,
)
from ..representation.snp import (
    ChiSnpNotSharedDirtyMessage,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
)


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
    """Stable cache states supported by the current MESI-like profile."""

    I = "I"
    SC = "SC"
    UC = "UC"
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
        if self.state is not ChiCacheState.I and self.data is None:
            raise ValueError("a valid clean cache line requires data")


ChiCoherentReadMessage = (
    ChiReadSharedMessage
    | ChiReadNotSharedDirtyMessage
    | ChiReadUniqueMessage
)
ChiCoherentSnoopMessage = (
    ChiSnpSharedMessage
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
class ChiRnAcceptSnoop:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message,
            (
                ChiSnpSharedMessage,
                ChiSnpNotSharedDirtyMessage,
                ChiSnpUniqueMessage,
            ),
        ):
            raise TypeError(
                "RN snoop action requires a supported clean Snoop packet"
            )


@dataclass(frozen=True)
class ChiRnAcceptCompData:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message, ChiCompDataMessage
        ):
            raise TypeError("RN completion action requires a CompData packet")


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
    | ChiRnAcceptSnoop
    | ChiRnAcceptCompData
    | ChiRnWriteCacheLine
    | ChiRnIssueWriteBackFull
    | ChiRnAcceptCompDBIDResp
)


@dataclass(frozen=True)
class ChiCoherentRnState:
    """Cache storage state plus CHI-specific permissions and transactions.

    ``cache`` is the only owner of resident line data.  ``permissions`` is a
    CHI facet projection and can retain an ``I`` tombstone after invalidation.
    The ``lines`` property is a compatibility/readout view assembled from
    those two facts; it is not another mutable store.
    """

    cache: CacheLineStoreState[CacheLinePayload] = field(
        default_factory=CacheLineStoreState
    )
    permissions: Mapping[int, ChiCacheState] = field(default_factory=dict)
    pending_reads: Mapping[int, ChiCoherentReadMessage] = field(
        default_factory=dict
    )
    pending_writebacks: Mapping[int, ChiWriteBackFullMessage] = field(
        default_factory=dict
    )

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
        valid_permissions = {
            address
            for address, permission in permissions.items()
            if permission is not ChiCacheState.I
        }
        if resident != valid_permissions:
            raise ValueError(
                "resident cache data must have exactly one non-I CHI "
                "permission"
            )
        pending = dict(self.pending_reads)
        if any(
            not isinstance(
                item,
                (
                    ChiReadSharedMessage,
                    ChiReadNotSharedDirtyMessage,
                    ChiReadUniqueMessage,
                ),
            )
            or transaction_id != item.transaction_id
            for transaction_id, item in pending.items()
        ):
            raise ValueError(
                "RN pending-read mapping key must match request TxnID"
            )
        object.__setattr__(
            self,
            "permissions",
            MappingProxyType(permissions),
        )
        object.__setattr__(
            self,
            "pending_reads",
            MappingProxyType(pending),
        )
        writebacks = dict(self.pending_writebacks)
        if any(
            not isinstance(item, ChiWriteBackFullMessage)
            or transaction_id != item.transaction_id
            for transaction_id, item in writebacks.items()
        ):
            raise ValueError(
                "RN pending-writeback mapping key must match request TxnID"
            )
        if set(pending) & set(writebacks):
            raise ValueError(
                "RN read and writeback transactions share one TxnID space"
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
        if any(
            request.address not in resident
            or permissions.get(request.address) is not ChiCacheState.UD
            for request in writebacks.values()
        ):
            raise ValueError(
                "RN pending WriteBackFull requires a resident UD line"
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
                        if permission is ChiCacheState.I
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
        ChiCoherentReadMessage | ChiWriteBackFullMessage,
        ...,
    ]:
        """Return local coherent transactions reserving one cache line."""

        _require_line_address(address)
        return tuple(
            request
            for request in self.pending_reads.values()
            if request.address == address
        ) + tuple(
            request
            for request in self.pending_writebacks.values()
            if request.address == address
        )


class ChiCoherentRnNode(
    SemanticComponent[
        ChiCoherentRnAction,
        ChiCoherentRnState,
        ChiNetworkPacket,
    ]
):
    """Restricted RN-F behavior for coherent reads and Unique dirtying."""

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
        valid_permissions = {
            address
            for address, permission in permissions.items()
            if permission is not ChiCacheState.I
        }
        if set(initial_cache.lines) != valid_permissions:
            raise ValueError(
                "initial CHI permissions must cover exactly the resident "
                "cache payloads"
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
            and not state.pending_reads
            and not state.pending_writebacks
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
        if isinstance(action, ChiRnAcceptSnoop):
            return self._accept_snoop(state, action.packet)
        if isinstance(action, ChiRnAcceptCompData):
            return self._accept_comp_data(state, action.packet)
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
                "local write conflicts with an RN-local coherent read",
            )
        line = state.line_at(address)
        if line is None or line.state is ChiCacheState.I:
            return self._fault(
                state,
                "local_write_permission",
                "local write requires an installed Unique cache line",
            )
        if line.state not in (ChiCacheState.UC, ChiCacheState.UD):
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
                state.pending_reads,
                state.pending_writebacks,
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
            request.transaction_id in state.pending_reads
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
                    f"{self.name}.line[{request.address:#x}]",
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
            len(state.pending_reads) + len(state.pending_writebacks)
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
        pending = dict(state.pending_reads)
        pending[request.transaction_id] = request
        candidate = ChiCoherentRnState(
            state.cache,
            state.permissions,
            pending,
            state.pending_writebacks,
        )
        packet = ChiNetworkPacket.request(
            request,
            source_id=self.node_id,
            target_id=self.home_node_id,
        )
        return SemanticStep(candidate, (packet,))

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
        if state.pending_for_address(snoop.address):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.line[{snoop.address:#x}]",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=1,
                    reason=(
                        "an RN-local coherent transaction reserves this "
                        "cache line; the first transient policy defers "
                        "the Snoop"
                    ),
                    location=self.name,
                ),
            )
        if isinstance(snoop, ChiSnpUniqueMessage):
            if not snoop.do_not_go_to_shared_dirty:
                return self._fault(
                    state,
                    "snoop_profile",
                    "SnpUnique requires DoNotGoToSD",
                )
        cache = state.cache
        permissions = dict(state.permissions)
        line = state.line_at(snoop.address)
        response_message: (
            ChiSnpRespMessage | ChiSnpRespDataMessage | None
        ) = None
        if isinstance(snoop, ChiSnpUniqueMessage):
            response = ChiRespCode.I
            if line is not None and line.state is not ChiCacheState.I:
                if line.state is ChiCacheState.UD:
                    assert line.data is not None
                    response_message = ChiSnpRespDataMessage(
                        transaction_id=snoop.transaction_id,
                        data=line.data,
                        response=ChiRespCode.I_PD,
                    )
                else:
                    if snoop.return_to_source:
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
        return SemanticStep(
            ChiCoherentRnState(
                cache,
                permissions,
                state.pending_reads,
                state.pending_writebacks,
            ),
            (response_packet,),
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
        request = state.pending_reads.get(response.transaction_id)
        if request is None:
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
        pending = dict(state.pending_reads)
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
                cache,
                permissions,
                pending,
                state.pending_writebacks,
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
            request.transaction_id in state.pending_reads
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
                    f"{self.name}.line[{request.address:#x}]",
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
            len(state.pending_reads) + len(state.pending_writebacks)
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
        pending[request.transaction_id] = request
        candidate = ChiCoherentRnState(
            state.cache,
            state.permissions,
            state.pending_reads,
            pending,
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
        """Invalidate the RN line and emit its latest data under Home's DBID."""

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
        request = state.pending_writebacks.get(response.transaction_id)
        if request is None:
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
        line = state.line_at(request.address)
        if (
            line is None
            or line.state is not ChiCacheState.UD
            or line.data is None
        ):
            return self._fault(
                state,
                "writeback_reserved_line",
                "reserved writeback line is no longer resident in UD",
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
        permissions = dict(state.permissions)
        permissions[request.address] = ChiCacheState.I
        pending = dict(state.pending_writebacks)
        del pending[request.transaction_id]
        return SemanticStep(
            ChiCoherentRnState(
                cache,
                permissions,
                state.pending_reads,
                pending,
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
    """Stable holder authority plus the Home backing copy for one line.

    ``data`` is current for clean holders.  It can be stale while the unique
    owner is in ``UD``; the latest value then travels with PassDirty.
    """

    address: int
    data: int
    sharers: frozenset[int] = frozenset()
    unique_owner: int | None = None

    def __post_init__(self) -> None:
        _require_line_address(self.address)
        if (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or not 0 <= self.data < _CACHE_LINE_DATA_LIMIT
        ):
            raise ValueError("Home backing data must fit one 512-bit line")
        sharers = frozenset(self.sharers)
        for node_id in sharers:
            _require_node_id("directory sharer", node_id)
        if self.unique_owner is not None:
            _require_node_id("directory unique owner", self.unique_owner)
            if sharers:
                raise ValueError(
                    "unique owner and shared holders are exclusive states"
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
class ChiCoherentReadPending:
    """Home-private transaction record; none of its grouping is a wire field."""

    requester_id: int
    request: ChiCoherentReadMessage
    snoop_transaction_id: int
    data_buffer_id: int
    snoop_targets: frozenset[int]
    snoop_results: Mapping[int, ChiSnoopResult] = field(default_factory=dict)
    completion_sent: bool = False

    def __post_init__(self) -> None:
        _require_node_id("pending requester", self.requester_id)
        if not isinstance(
            self.request,
            (
                ChiReadSharedMessage,
                ChiReadNotSharedDirtyMessage,
                ChiReadUniqueMessage,
            ),
        ):
            raise TypeError(
                "Home pending transaction requires a coherent Read"
            )
        for name, value in (
            ("snoop_transaction_id", self.snoop_transaction_id),
            ("data_buffer_id", self.data_buffer_id),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value < _TRANSACTION_ID_LIMIT
            ):
                raise ValueError(f"{name} must be a 12-bit identifier")
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
        object.__setattr__(self, "snoop_targets", targets)
        object.__setattr__(
            self,
            "snoop_results",
            MappingProxyType(results),
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


@dataclass(frozen=True)
class ChiHomeWriteBackPending:
    """Home reservation between WriteBackFull and CopyBackWrData."""

    requester_id: int
    request: ChiWriteBackFullMessage
    data_buffer_id: int

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

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket) or not isinstance(
            self.packet.message, ChiWriteBackFullMessage
        ):
            raise TypeError(
                "Home writeback action requires WriteBackFull packet"
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


ChiCoherentHomeAction = (
    ChiHomeAcceptCoherentRead
    | ChiHomeAcceptSnoopResponse
    | ChiHomeAcceptCompAck
    | ChiHomeAcceptWriteBackFull
    | ChiHomeAcceptCopyBackData
)


@dataclass(frozen=True)
class ChiCoherentHomeState:
    directory: Mapping[int, ChiHomeDirectoryEntry]
    pending: Mapping[int, ChiCoherentReadPending] = field(
        default_factory=dict
    )
    next_snoop_transaction_id: int = 0x100
    next_data_buffer_id: int = 0x200
    pending_writebacks: Mapping[int, ChiHomeWriteBackPending] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        directory = dict(self.directory)
        if any(
            not isinstance(entry, ChiHomeDirectoryEntry)
            or address != entry.address
            for address, entry in directory.items()
        ):
            raise ValueError(
                "Home directory mapping key must match entry address"
            )
        pending = dict(self.pending)
        if any(
            not isinstance(item, ChiCoherentReadPending)
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
                "Home reads and writebacks share one DBID allocation space"
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
        if any(
            directory[item.request.address].unique_owner
            != item.requester_id
            for item in writebacks.values()
        ):
            raise ValueError(
                "Home pending writeback requester must remain Unique owner"
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


class ChiCoherentHomeNode(
    SemanticComponent[
        ChiCoherentHomeAction,
        ChiCoherentHomeState,
        ChiNetworkPacket,
    ]
):
    """Restricted backing state, directory, and coherence transaction tables.

    Until DAT fragmentation is implemented, the emitted full-line CompData
    requires a 512-bit DAT representation profile.
    """

    def __init__(
        self,
        name: str,
        node_id: int,
        *,
        initial_directory: tuple[ChiHomeDirectoryEntry, ...],
        transaction_capacity: int = 4,
        initial_snoop_transaction_id: int = 0x100,
        initial_data_buffer_id: int = 0x200,
        allow_dirty_data_transfer: bool = False,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("coherent Home requires a name")
        _require_node_id("Home node_id", node_id)
        entries = tuple(initial_directory)
        if any(not isinstance(item, ChiHomeDirectoryEntry) for item in entries):
            raise TypeError(
                "Home initial directory requires ChiHomeDirectoryEntry"
            )
        if len({item.address for item in entries}) != len(entries):
            raise ValueError("Home initial directory addresses must be unique")
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
        self.name = name
        self.node_id = node_id
        self.initial_directory = entries
        self.transaction_capacity = transaction_capacity
        self.initial_snoop_transaction_id = initial_snoop_transaction_id
        self.initial_data_buffer_id = initial_data_buffer_id
        self.allow_dirty_data_transfer = allow_dirty_data_transfer

    def initial_state(self) -> ChiCoherentHomeState:
        return ChiCoherentHomeState(
            {
                entry.address: entry
                for entry in self.initial_directory
            },
            next_snoop_transaction_id=self.initial_snoop_transaction_id,
            next_data_buffer_id=self.initial_data_buffer_id,
        )

    def is_quiescent(self, state: ChiCoherentHomeState) -> bool:
        return (
            isinstance(state, ChiCoherentHomeState)
            and not state.pending
            and not state.pending_writebacks
        )

    def step(
        self,
        state: ChiCoherentHomeState,
        action: ChiCoherentHomeAction,
    ) -> SemanticStep[ChiCoherentHomeState, ChiNetworkPacket]:
        if not isinstance(state, ChiCoherentHomeState):
            raise TypeError("coherent Home requires ChiCoherentHomeState")
        if isinstance(action, ChiHomeAcceptCoherentRead):
            return self._accept_read(state, action.packet)
        if isinstance(action, ChiHomeAcceptSnoopResponse):
            return self._accept_snoop_response(state, action.packet)
        if isinstance(action, ChiHomeAcceptCompAck):
            return self._accept_comp_ack(state, action.packet)
        if isinstance(action, ChiHomeAcceptWriteBackFull):
            return self._accept_writeback_full(state, action.packet)
        if isinstance(action, ChiHomeAcceptCopyBackData):
            return self._accept_copyback_data(state, action.packet)
        raise TypeError("unknown coherent Home action")

    def _accept_read(
        self,
        state: ChiCoherentHomeState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[ChiCoherentHomeState, ChiNetworkPacket]:
        request = packet.message
        assert isinstance(
            request,
            (
                ChiReadSharedMessage,
                ChiReadNotSharedDirtyMessage,
                ChiReadUniqueMessage,
            ),
        )
        if packet.target_id != self.node_id:
            return self._fault(
                state,
                "request_target",
                "coherent Read packet targets another Home",
            )
        if (
            request.size != 6
            or request.address % _CACHE_LINE_BYTES
            or not request.expect_completion_ack
        ):
            return self._fault(
                state,
                "request_profile",
                "coherent Home profile requires an aligned 64-byte read "
                "with ExpCompAck",
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
                    f"{self.name}.line[{request.address:#x}]",
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
        if (
            len(state.pending) + len(state.pending_writebacks)
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

        targets = set(entry.sharers)
        if entry.unique_owner is not None:
            targets.add(entry.unique_owner)
        targets.discard(packet.source_id)
        snoop_id = self._allocate_identifier(
            state.next_snoop_transaction_id,
            {
                item.snoop_transaction_id
                for item in state.pending.values()
            },
        )
        data_buffer_id = self._allocate_identifier(
            state.next_data_buffer_id,
            set(state.pending) | set(state.pending_writebacks),
        )
        pending_item = ChiCoherentReadPending(
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
            if isinstance(request, ChiReadUniqueMessage):
                snoop: ChiCoherentSnoopMessage = ChiSnpUniqueMessage(
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
            emissions = (self._completion_packet(entry, pending_item),)
        candidate = ChiCoherentHomeState(
            state.directory,
            pending,
            (snoop_id + 1) % _TRANSACTION_ID_LIMIT,
            (data_buffer_id + 1) % _TRANSACTION_ID_LIMIT,
            state.pending_writebacks,
        )
        return SemanticStep(candidate, emissions)

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
        if isinstance(pending_item.request, ChiReadUniqueMessage):
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
                "coherent Read profile",
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
        updated = ChiCoherentReadPending(
            pending_item.requester_id,
            pending_item.request,
            pending_item.snoop_transaction_id,
            pending_item.data_buffer_id,
            pending_item.snoop_targets,
            results,
            completion_sent=(
                set(results) == set(pending_item.snoop_targets)
            ),
        )
        pending = dict(state.pending)
        pending[updated.data_buffer_id] = updated
        emissions: tuple[ChiNetworkPacket, ...] = ()
        if updated.completion_sent:
            entry = state.directory[updated.request.address]
            emissions = (self._completion_packet(entry, updated),)
        return SemanticStep(
            ChiCoherentHomeState(
                state.directory,
                pending,
                state.next_snoop_transaction_id,
                state.next_data_buffer_id,
                state.pending_writebacks,
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
        entry = state.directory[pending_item.request.address]
        directory = dict(state.directory)
        if isinstance(pending_item.request, ChiReadUniqueMessage):
            directory[entry.address] = ChiHomeDirectoryEntry(
                entry.address,
                entry.data,
                unique_owner=pending_item.requester_id,
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
                (
                    pending_item.dirty_result.data
                    if pending_item.dirty_result is not None
                    else entry.data
                ),
                frozenset(sharers),
                unique_owner=None,
            )
        pending = dict(state.pending)
        del pending[pending_item.data_buffer_id]
        return SemanticStep(
            ChiCoherentHomeState(
                directory,
                pending,
                state.next_snoop_transaction_id,
                state.next_data_buffer_id,
                state.pending_writebacks,
            )
        )

    def _accept_writeback_full(
        self,
        state: ChiCoherentHomeState,
        packet: ChiNetworkPacket,
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
        if entry.unique_owner != packet.source_id:
            return self._fault(
                state,
                "writeback_owner",
                "WriteBackFull source is not the directory Unique owner",
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
                    f"{self.name}.line[{request.address:#x}]",
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
            len(state.pending) + len(state.pending_writebacks)
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
                state.directory,
                state.pending,
                state.next_snoop_transaction_id,
                (data_buffer_id + 1) % _TRANSACTION_ID_LIMIT,
                writebacks,
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
                "first WriteBackFull profile requires one full-line "
                "CopyBackWrData_UD_PD packet",
            )
        entry = state.directory[pending.request.address]
        if entry.unique_owner != pending.requester_id:
            return self._fault(
                state,
                "copyback_owner",
                "directory owner changed before CopyBackWrData arrived",
            )
        directory = dict(state.directory)
        directory[entry.address] = ChiHomeDirectoryEntry(
            entry.address,
            message.data,
            unique_owner=None,
        )
        writebacks = dict(state.pending_writebacks)
        del writebacks[pending.data_buffer_id]
        return SemanticStep(
            ChiCoherentHomeState(
                directory,
                state.pending,
                state.next_snoop_transaction_id,
                state.next_data_buffer_id,
                writebacks,
            )
        )

    def _completion_packet(
        self,
        entry: ChiHomeDirectoryEntry,
        pending: ChiCoherentReadPending,
    ) -> ChiNetworkPacket:
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
                else entry.data
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
    "ChiCoherentReadPending",
    "ChiHomeWriteBackPending",
    "ChiCoherentHomeAction",
    "ChiCoherentHomeNode",
    "ChiCoherentHomeState",
    "ChiCoherentReadMessage",
    "ChiCoherentRnAction",
    "ChiCoherentRnNode",
    "ChiCoherentRnState",
    "ChiHomeAcceptCompAck",
    "ChiHomeAcceptCopyBackData",
    "ChiHomeAcceptCoherentRead",
    "ChiHomeAcceptSnoopResponse",
    "ChiHomeAcceptWriteBackFull",
    "ChiHomeDirectoryEntry",
    "ChiRnAcceptCompData",
    "ChiRnAcceptCompDBIDResp",
    "ChiRnAcceptSnoop",
    "ChiRnIssueCoherentRead",
    "ChiRnIssueWriteBackFull",
    "ChiRnWriteCacheLine",
    "ChiSnoopResult",
]

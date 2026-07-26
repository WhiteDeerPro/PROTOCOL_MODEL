"""Packet-delivery composition for the executable CHI coherence profiles.

The transport network owns how a packet reaches its destination.  This module
starts at the next boundary: a delivered packet is dispatched to the Home or
Request Node that owns the corresponding protocol state.  Emitted packets can
then be passed back through any compatible ``ChiTransportNetworkSession``.

The profile is intentionally narrow.  It closes clean ``ReadShared`` and
``ReadUnique`` lifecycles, clean- and restricted shared-dirty-peer
``CleanUnique`` permission upgrades, the ``UD`` owner-transfer path for
``ReadUnique``, the MESI no-SharedDirty ``ReadNotSharedDirty`` downgrade path,
and explicit ``UD`` ``WriteBackFull``.  The ``SD`` state exists only for the
CleanUnique memory-update slice; general shared-dirty behavior, Retry,
automatic victim selection, forwarding snoops, and packed pin observations
remain separate extensions.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    ChiHomeAcceptSnoopResponse,
    ChiHomeAcceptWriteBackFull,
    ChiRnAcceptComp,
    ChiRnAcceptCompDBIDResp,
    ChiRnAcceptCompData,
    ChiRnAcceptSnoop,
    ChiRnIssueCleanUnique,
    ChiRnIssueCoherentRead,
    ChiRnIssueWriteBackFull,
    ChiRnWriteCacheLine,
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
from ..representation.rsp import (
    ChiCompAckMessage,
    ChiCompDBIDRespMessage,
    ChiCompMessage,
    ChiSnpRespMessage,
)
from ..representation.snp import (
    ChiSnpCleanInvalidMessage,
    ChiSnpNotSharedDirtyMessage,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
)
from .capability import (
    CHI_FEATURE_CLEAN_READ_SHARED,
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
    CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
    CHI_FEATURE_DIRTY_WRITEBACK,
    CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
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
        CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS,
        CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
        CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
        CHI_FEATURE_DIRTY_WRITEBACK,
        CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
    )
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


ChiCoherenceAction = (
    ChiSubmitCoherentRead
    | ChiSubmitCleanUnique
    | ChiSubmitWriteBackFull
    | ChiDeliverCoherencePacket
    | ChiWriteUniqueCacheLine
)


@dataclass(frozen=True)
class ChiCoherenceState:
    """Stable participant registries plus their current local states."""

    home: ChiCoherentHomeState
    request_nodes: Mapping[int, ChiCoherentRnState]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_nodes",
            MappingProxyType(dict(self.request_nodes)),
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
        if home.pending or home.pending_writebacks:
            reasons.append(
                "stable coherence check requires an empty Home transaction table"
            )
        for node_id, state in request_nodes.items():
            if state.pending_transactions or state.pending_writebacks:
                reasons.append(
                    f"RN {node_id} still owns pending coherent transactions"
                )
        if reasons:
            return tuple(reasons)

        directory_addresses = set(home.directory)
        for address, entry in home.directory.items():
            holders: dict[int, object] = {}
            for node_id, state in request_nodes.items():
                line = state.lines.get(address)
                if line is not None and line.state is not ChiCacheState.I:
                    holders[node_id] = line

            if entry.unique_owner is not None:
                expected = {entry.unique_owner}
                if set(holders) != expected:
                    reasons.append(
                        f"line {address:#x} directory unique owner "
                        f"{entry.unique_owner} disagrees with RN holders "
                        f"{sorted(holders)!r}"
                    )
                owner_line = holders.get(entry.unique_owner)
                if (
                    owner_line is not None
                    and owner_line.state
                    not in (ChiCacheState.UC, ChiCacheState.UD)
                ):
                    reasons.append(
                        f"line {address:#x} unique owner is not in "
                        "UC or UD state"
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
                        line.state is not ChiCacheState.UD
                        and line.data != entry.data
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
            CHI_FEATURE_CLEAN_READ_SHARED in features
            and {
                CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER,
                CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
                CHI_FEATURE_DIRTY_WRITEBACK,
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
            self.home.initial_state(),
            {
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
            not state.home.pending
            and not state.home.pending_writebacks
            and all(
                not item.pending_transactions
                and not item.pending_writebacks
                for item in state.request_nodes.values()
            )
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
        if isinstance(action, ChiSubmitWriteBackFull):
            return self._issue_writeback(state, action)
        if isinstance(action, ChiDeliverCoherencePacket):
            return self._deliver(state, action.packet)
        if isinstance(action, ChiWriteUniqueCacheLine):
            return self._write_unique_cache_line(state, action)
        raise TypeError("unknown CHI coherence system action")

    def _profile_state_fault(
        self,
        state: ChiCoherenceState,
    ) -> SemanticFault | None:
        allows_unique_dirty = bool(
            {
                CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
                CHI_FEATURE_DIRTY_WRITEBACK,
                CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY,
            }
            & self.enabled_features
        )
        allows_shared_dirty = (
            CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER
            in self.enabled_features
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
                            "shared-dirty CleanUnique feature is not enabled"
                        ),
                        ConstraintScope.SYSTEM,
                        self.name,
                    )
        return None

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
            CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
            CHI_FEATURE_DIRTY_WRITEBACK,
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
                    f"{self.name}.line[{action.address:#x}]",
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
            for pending in state.home.pending_writebacks.values()
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.line[{action.request.address:#x}]",
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
                return self._fault(
                    state,
                    "clean_unique_dirty_peer",
                    "CleanUnique requires shared directory state without a "
                    "Unique owner",
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
            if isinstance(message, ChiCleanUniqueMessage):
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
                action = ChiHomeAcceptCoherentRead(packet)
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
                action = ChiHomeAcceptWriteBackFull(packet)
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
                action = ChiHomeAcceptSnoopResponse(packet)
            elif isinstance(message, ChiCompAckMessage):
                if packet.source_id not in self.requester_node_ids:
                    return self._fault(
                        state,
                        "requester_authority",
                        f"NodeID {packet.source_id} cannot return CompAck "
                        "in this construction",
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
                if CHI_FEATURE_DIRTY_WRITEBACK not in self.enabled_features:
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
            candidate = ChiCoherenceState(
                transition.state,
                state.request_nodes,
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
                )
            )
            if len(matches) != 1:
                return self._fault(
                    state,
                    "snoop_correlation",
                    "Snoop packet does not match one Home-issued target",
                )
            action = ChiRnAcceptSnoop(packet)
        elif isinstance(message, ChiCompMessage):
            if packet.target_id not in self.requester_node_ids:
                return self._fault(
                    state,
                    "requester_authority",
                    f"NodeID {packet.target_id} cannot receive Comp "
                    "in this construction",
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
            action = ChiRnAcceptComp(packet)
        elif isinstance(message, ChiCompDataMessage):
            if packet.target_id not in self.requester_node_ids:
                return self._fault(
                    state,
                    "requester_authority",
                    f"NodeID {packet.target_id} cannot receive CompData "
                    "in this construction",
                )
            action = ChiRnAcceptCompData(packet)
        elif isinstance(message, ChiCompDBIDRespMessage):
            if packet.target_id not in self.requester_node_ids:
                return self._fault(
                    state,
                    "requester_authority",
                    f"NodeID {packet.target_id} cannot receive "
                    "CompDBIDResp in this construction",
                )
            if CHI_FEATURE_DIRTY_WRITEBACK not in self.enabled_features:
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
            ChiReadSharedMessage
            | ChiReadNotSharedDirtyMessage
            | ChiReadUniqueMessage
        ),
    ) -> ChiFeatureKey:
        if isinstance(request, ChiReadUniqueMessage):
            return CHI_FEATURE_CLEAN_READ_UNIQUE
        if isinstance(request, ChiReadNotSharedDirtyMessage):
            return CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY
        return CHI_FEATURE_CLEAN_READ_SHARED

    @staticmethod
    def _snoop_feature(
        snoop: (
            ChiSnpCleanInvalidMessage
            | ChiSnpSharedMessage
            | ChiSnpNotSharedDirtyMessage
            | ChiSnpUniqueMessage
        ),
    ) -> ChiFeatureKey:
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
        candidate = ChiCoherenceState(state.home, states)
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
    "ChiSubmitCleanUnique",
    "ChiSubmitCoherentRead",
    "ChiSubmitWriteBackFull",
    "ChiWriteUniqueCacheLine",
]

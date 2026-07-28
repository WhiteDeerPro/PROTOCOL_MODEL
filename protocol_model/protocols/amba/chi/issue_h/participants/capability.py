"""Explicit CHI participant capability claims.

These values describe behavior already supplied by a participant component.
They do not install that behavior and deliberately remain separate from
``ChiParticipantBinding`` so the first capability-closure slice does not
change existing executable sessions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class ChiCapabilityKey:
    """Stable, extensible name for one atomic CHI capability."""

    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.startswith("chi."):
            raise ValueError(
                "CHI capability keys require a non-empty 'chi.' name"
            )

    def __str__(self) -> str:
        return self.name


CHI_REQUESTER_READ_NO_SNP_ISSUE = ChiCapabilityKey(
    "chi.requester.read_no_snp.issue"
)
CHI_REQUESTER_COMP_DATA_ACCEPT = ChiCapabilityKey(
    "chi.requester.comp_data.accept"
)
CHI_HOME_READ_NO_SNP_ACCEPT = ChiCapabilityKey(
    "chi.home.read_no_snp.accept"
)
CHI_HOME_COMP_DATA_PRODUCE = ChiCapabilityKey(
    "chi.home.comp_data.produce"
)
CHI_REQUESTER_READ_NO_SNP_NDERR_ACCEPT = ChiCapabilityKey(
    "chi.requester.read_no_snp.nderr.accept"
)
CHI_HOME_READ_NO_SNP_NDERR_PRODUCE = ChiCapabilityKey(
    "chi.home.read_no_snp.nderr.produce"
)

CHI_REQUESTER_RETRY_ACK_ACCEPT = ChiCapabilityKey(
    "chi.requester.retry_ack.accept"
)
CHI_REQUESTER_PCREDIT_CONSUME = ChiCapabilityKey(
    "chi.requester.pcredit.consume"
)
CHI_REQUESTER_PCREDIT_RETURN = ChiCapabilityKey(
    "chi.requester.pcredit.return"
)
CHI_HOME_RETRY_ACK_PRODUCE = ChiCapabilityKey(
    "chi.home.retry_ack.produce"
)
CHI_HOME_PCREDIT_GRANT = ChiCapabilityKey(
    "chi.home.pcredit.grant"
)
CHI_HOME_PCREDIT_RECLAIM = ChiCapabilityKey(
    "chi.home.pcredit.reclaim"
)

CHI_REQUESTER_READ_SHARED_ISSUE = ChiCapabilityKey(
    "chi.requester.read_shared.issue"
)
CHI_REQUESTER_SHARED_COMP_DATA_ACCEPT = ChiCapabilityKey(
    "chi.requester.comp_data.shared.accept"
)
CHI_REQUESTER_COMP_ACK_PRODUCE = ChiCapabilityKey(
    "chi.requester.comp_ack.produce"
)
CHI_HOME_READ_SHARED_ACCEPT = ChiCapabilityKey(
    "chi.home.read_shared.accept"
)
CHI_HOME_CLEAN_SNOOP_COORDINATE = ChiCapabilityKey(
    "chi.home.clean_snoop.coordinate"
)
CHI_HOME_SHARED_COMP_DATA_PRODUCE = ChiCapabilityKey(
    "chi.home.comp_data.shared.produce"
)
CHI_HOME_COMP_ACK_ACCEPT = ChiCapabilityKey(
    "chi.home.comp_ack.accept"
)
CHI_SNOOPEE_SNP_SHARED_ACCEPT = ChiCapabilityKey(
    "chi.snoopee.snp_shared.accept"
)
CHI_SNOOPEE_CLEAN_SNP_RESP_PRODUCE = ChiCapabilityKey(
    "chi.snoopee.snp_resp.clean.produce"
)
CHI_REQUESTER_READ_UNIQUE_ISSUE = ChiCapabilityKey(
    "chi.requester.read_unique.issue"
)
CHI_REQUESTER_UNIQUE_COMP_DATA_ACCEPT = ChiCapabilityKey(
    "chi.requester.comp_data.unique.accept"
)
CHI_HOME_READ_UNIQUE_ACCEPT = ChiCapabilityKey(
    "chi.home.read_unique.accept"
)
CHI_HOME_UNIQUE_COMP_DATA_PRODUCE = ChiCapabilityKey(
    "chi.home.comp_data.unique.produce"
)
CHI_REQUESTER_READ_UNIQUE_NDERR_ACCEPT = ChiCapabilityKey(
    "chi.requester.read_unique.nderr.accept"
)
CHI_HOME_READ_UNIQUE_NDERR_PRODUCE = ChiCapabilityKey(
    "chi.home.read_unique.nderr.produce"
)
CHI_SNOOPEE_SNP_UNIQUE_ACCEPT = ChiCapabilityKey(
    "chi.snoopee.snp_unique.accept"
)
CHI_SNOOPEE_READ_UNIQUE_PENDING_SNP_UNIQUE_ACCEPT = ChiCapabilityKey(
    "chi.snoopee.snp_unique.read_unique_pending.accept"
)
CHI_SNOOPEE_CLEAN_UNIQUE_PENDING_INVALIDATING_SNP_ACCEPT = ChiCapabilityKey(
    "chi.snoopee.invalidating_snp.clean_unique_pending.accept"
)
CHI_REQUEST_NODE_UNIQUE_LOCAL_WRITE = ChiCapabilityKey(
    "chi.request_node.unique_local_write"
)
CHI_REQUESTER_DIRTY_COMP_DATA_ACCEPT = ChiCapabilityKey(
    "chi.requester.comp_data.dirty.accept"
)
CHI_HOME_DIRTY_SNP_DATA_ACCEPT = ChiCapabilityKey(
    "chi.home.snp_resp_data.dirty.accept"
)
CHI_HOME_PASS_DIRTY_MEMORY_UPDATE = ChiCapabilityKey(
    "chi.home.pass_dirty.memory_update"
)
CHI_HOME_DIRTY_COMP_DATA_PRODUCE = ChiCapabilityKey(
    "chi.home.comp_data.dirty.produce"
)
CHI_SNOOPEE_DIRTY_SNP_DATA_PRODUCE = ChiCapabilityKey(
    "chi.snoopee.snp_resp_data.dirty.produce"
)
CHI_HOME_DIRTY_TO_CLEAN_SHARED_COMMIT = ChiCapabilityKey(
    "chi.home.dirty_to_clean_shared.commit"
)
CHI_SNOOPEE_DIRTY_TO_CLEAN_SHARED_DOWNGRADE = ChiCapabilityKey(
    "chi.snoopee.dirty_to_clean_shared.downgrade"
)
CHI_REQUESTER_READ_NOT_SHARED_DIRTY_ISSUE = ChiCapabilityKey(
    "chi.requester.read_not_shared_dirty.issue"
)
CHI_HOME_READ_NOT_SHARED_DIRTY_ACCEPT = ChiCapabilityKey(
    "chi.home.read_not_shared_dirty.accept"
)
CHI_SNOOPEE_SNP_NOT_SHARED_DIRTY_ACCEPT = ChiCapabilityKey(
    "chi.snoopee.snp_not_shared_dirty.accept"
)
CHI_REQUESTER_WRITEBACK_FULL_ISSUE = ChiCapabilityKey(
    "chi.requester.writeback_full.issue"
)
CHI_REQUESTER_COPYBACK_WR_DATA_PRODUCE = ChiCapabilityKey(
    "chi.requester.copyback_wr_data.produce"
)
CHI_SNOOPEE_WRITEBACK_PENDING_INVALIDATING_SNP_ACCEPT = ChiCapabilityKey(
    "chi.snoopee.invalidating_snp.writeback_pending.accept"
)
CHI_SNOOPEE_WRITE_EVICT_PENDING_INVALIDATING_SNP_ACCEPT = ChiCapabilityKey(
    "chi.snoopee.invalidating_snp.write_evict_pending.accept"
)
CHI_SNOOPEE_WRITE_EVICT_OR_EVICT_PENDING_INVALIDATING_SNP_ACCEPT = (
    ChiCapabilityKey(
        "chi.snoopee.invalidating_snp.write_evict_or_evict_pending.accept"
    )
)
CHI_REQUESTER_COPYBACK_CANCEL_PRODUCE = ChiCapabilityKey(
    "chi.requester.copyback_cancel.produce"
)
CHI_HOME_WRITEBACK_FULL_ACCEPT = ChiCapabilityKey(
    "chi.home.writeback_full.accept"
)
CHI_HOME_COMP_DBID_RESP_PRODUCE = ChiCapabilityKey(
    "chi.home.comp_dbid_resp.produce"
)
CHI_REQUESTER_COMP_DBID_RESP_ACCEPT = ChiCapabilityKey(
    "chi.requester.comp_dbid_resp.accept"
)
CHI_HOME_COPYBACK_WR_DATA_ACCEPT = ChiCapabilityKey(
    "chi.home.copyback_wr_data.accept"
)
CHI_HOME_COPYBACK_CANCEL_ACCEPT = ChiCapabilityKey(
    "chi.home.copyback_cancel.accept"
)
CHI_REQUESTER_WRITE_EVICT_FULL_ISSUE = ChiCapabilityKey(
    "chi.requester.write_evict_full.issue"
)
CHI_REQUESTER_CLEAN_COPYBACK_WR_DATA_PRODUCE = ChiCapabilityKey(
    "chi.requester.copyback_wr_data.clean.produce"
)
CHI_HOME_WRITE_EVICT_FULL_ACCEPT = ChiCapabilityKey(
    "chi.home.write_evict_full.accept"
)
CHI_HOME_CLEAN_COPYBACK_WR_DATA_ACCEPT = ChiCapabilityKey(
    "chi.home.copyback_wr_data.clean.accept"
)
CHI_HOME_CLEAN_RESIDENCY_RETAIN = ChiCapabilityKey(
    "chi.home.clean_residency.retain"
)
CHI_REQUESTER_COPY_AT_HOME_PROVENANCE_CACHE = ChiCapabilityKey(
    "chi.requester.copy_at_home.provenance.cache"
)
CHI_REQUESTER_WRITE_EVICT_FULL_COPY_AT_HOME_ISSUE = ChiCapabilityKey(
    "chi.requester.write_evict_full.copy_at_home.issue"
)
CHI_REQUESTER_WRITE_EVICT_FULL_COMP_ACCEPT = ChiCapabilityKey(
    "chi.requester.write_evict_full.comp.accept"
)
CHI_HOME_COPY_AT_HOME_COMP_DATA_PRODUCE = ChiCapabilityKey(
    "chi.home.copy_at_home.comp_data.produce"
)
CHI_HOME_WRITE_EVICT_FULL_COPY_AT_HOME_ACCEPT = ChiCapabilityKey(
    "chi.home.write_evict_full.copy_at_home.accept"
)
CHI_HOME_WRITE_EVICT_FULL_COMP_PRODUCE = ChiCapabilityKey(
    "chi.home.write_evict_full.comp.produce"
)
CHI_REQUESTER_WRITE_EVICT_OR_EVICT_ISSUE = ChiCapabilityKey(
    "chi.requester.write_evict_or_evict.issue"
)
CHI_REQUESTER_WRITE_EVICT_OR_EVICT_COMP_ACCEPT = ChiCapabilityKey(
    "chi.requester.write_evict_or_evict.comp.accept"
)
CHI_HOME_WRITE_EVICT_OR_EVICT_ACCEPT = ChiCapabilityKey(
    "chi.home.write_evict_or_evict.accept"
)
CHI_HOME_WRITE_EVICT_OR_EVICT_COMP_PRODUCE = ChiCapabilityKey(
    "chi.home.write_evict_or_evict.comp.produce"
)
CHI_REQUESTER_CLEAN_UNIQUE_ISSUE = ChiCapabilityKey(
    "chi.requester.clean_unique.issue"
)
CHI_REQUESTER_COMP_UC_ACCEPT = ChiCapabilityKey(
    "chi.requester.comp_uc.accept"
)
CHI_HOME_CLEAN_UNIQUE_ACCEPT = ChiCapabilityKey(
    "chi.home.clean_unique.accept"
)
CHI_HOME_COMP_UC_PRODUCE = ChiCapabilityKey(
    "chi.home.comp_uc.produce"
)
CHI_SNOOPEE_SNP_CLEAN_INVALID_ACCEPT = ChiCapabilityKey(
    "chi.snoopee.snp_clean_invalid.accept"
)
CHI_REQUESTER_MAKE_UNIQUE_ISSUE = ChiCapabilityKey(
    "chi.requester.make_unique.issue"
)
CHI_HOME_MAKE_UNIQUE_ACCEPT = ChiCapabilityKey(
    "chi.home.make_unique.accept"
)
CHI_SNOOPEE_SNP_MAKE_INVALID_ACCEPT = ChiCapabilityKey(
    "chi.snoopee.snp_make_invalid.accept"
)
CHI_SNOOPEE_SNP_MAKE_INVALID_DISCARD_DIRTY = ChiCapabilityKey(
    "chi.snoopee.snp_make_invalid.discard_dirty"
)
CHI_REQUESTER_EVICT_ISSUE = ChiCapabilityKey(
    "chi.requester.evict.issue"
)
CHI_REQUESTER_EVICT_COMP_ACCEPT = ChiCapabilityKey(
    "chi.requester.evict.comp.accept"
)
CHI_HOME_EVICT_ACCEPT = ChiCapabilityKey(
    "chi.home.evict.accept"
)
CHI_HOME_EVICT_COMP_PRODUCE = ChiCapabilityKey(
    "chi.home.evict.comp.produce"
)


CHI_READ_NO_SNP_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUESTER_READ_NO_SNP_ISSUE,
        CHI_REQUESTER_COMP_DATA_ACCEPT,
    )
)
CHI_READ_NO_SNP_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_READ_NO_SNP_ACCEPT,
        CHI_HOME_COMP_DATA_PRODUCE,
    )
)
CHI_READ_NO_SNP_NDERR_REQUESTER_CAPABILITIES = frozenset(
    (
        *CHI_READ_NO_SNP_REQUESTER_CAPABILITIES,
        CHI_REQUESTER_READ_NO_SNP_NDERR_ACCEPT,
    )
)
CHI_READ_NO_SNP_NDERR_HOME_CAPABILITIES = frozenset(
    (
        *CHI_READ_NO_SNP_HOME_CAPABILITIES,
        CHI_HOME_READ_NO_SNP_NDERR_PRODUCE,
    )
)
CHI_REQUEST_RETRY_REQUESTER_CAPABILITIES = frozenset(
    (
        *CHI_READ_NO_SNP_REQUESTER_CAPABILITIES,
        CHI_REQUESTER_RETRY_ACK_ACCEPT,
        CHI_REQUESTER_PCREDIT_CONSUME,
        CHI_REQUESTER_PCREDIT_RETURN,
    )
)
CHI_REQUEST_RETRY_HOME_CAPABILITIES = frozenset(
    (
        *CHI_READ_NO_SNP_HOME_CAPABILITIES,
        CHI_HOME_RETRY_ACK_PRODUCE,
        CHI_HOME_PCREDIT_GRANT,
        CHI_HOME_PCREDIT_RECLAIM,
    )
)
CHI_CLEAN_READ_SHARED_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUESTER_READ_SHARED_ISSUE,
        CHI_REQUESTER_SHARED_COMP_DATA_ACCEPT,
        CHI_REQUESTER_COMP_ACK_PRODUCE,
    )
)
CHI_CLEAN_READ_SHARED_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_READ_SHARED_ACCEPT,
        CHI_HOME_CLEAN_SNOOP_COORDINATE,
        CHI_HOME_SHARED_COMP_DATA_PRODUCE,
        CHI_HOME_COMP_ACK_ACCEPT,
    )
)
CHI_CLEAN_READ_SHARED_SNOOPEE_CAPABILITIES = frozenset(
    (
        CHI_SNOOPEE_SNP_SHARED_ACCEPT,
        CHI_SNOOPEE_CLEAN_SNP_RESP_PRODUCE,
    )
)
CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUESTER_READ_UNIQUE_ISSUE,
        CHI_REQUESTER_UNIQUE_COMP_DATA_ACCEPT,
        CHI_REQUESTER_COMP_ACK_PRODUCE,
    )
)
CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_READ_UNIQUE_ACCEPT,
        CHI_HOME_CLEAN_SNOOP_COORDINATE,
        CHI_HOME_UNIQUE_COMP_DATA_PRODUCE,
        CHI_HOME_COMP_ACK_ACCEPT,
    )
)
CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES = frozenset(
    (
        CHI_SNOOPEE_SNP_UNIQUE_ACCEPT,
        CHI_SNOOPEE_READ_UNIQUE_PENDING_SNP_UNIQUE_ACCEPT,
        CHI_SNOOPEE_CLEAN_SNP_RESP_PRODUCE,
    )
)
CHI_CLEAN_READ_UNIQUE_NDERR_REQUESTER_CAPABILITIES = frozenset(
    (
        *CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
        CHI_REQUESTER_READ_UNIQUE_NDERR_ACCEPT,
    )
)
CHI_CLEAN_READ_UNIQUE_NDERR_HOME_CAPABILITIES = frozenset(
    (
        *CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
        CHI_HOME_READ_UNIQUE_NDERR_PRODUCE,
    )
)
CHI_CLEAN_READ_UNIQUE_RETRY_REQUESTER_CAPABILITIES = frozenset(
    (
        *CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
        CHI_REQUESTER_RETRY_ACK_ACCEPT,
        CHI_REQUESTER_PCREDIT_CONSUME,
    )
)
CHI_CLEAN_READ_UNIQUE_RETRY_HOME_CAPABILITIES = frozenset(
    (
        *CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
        CHI_HOME_RETRY_ACK_PRODUCE,
        CHI_HOME_PCREDIT_GRANT,
    )
)
CHI_DIRTY_UNIQUE_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUEST_NODE_UNIQUE_LOCAL_WRITE,
        CHI_REQUESTER_DIRTY_COMP_DATA_ACCEPT,
    )
)
CHI_DIRTY_UNIQUE_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_DIRTY_SNP_DATA_ACCEPT,
        CHI_HOME_DIRTY_COMP_DATA_PRODUCE,
    )
)
CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES = frozenset(
    (
        CHI_REQUEST_NODE_UNIQUE_LOCAL_WRITE,
        CHI_SNOOPEE_DIRTY_SNP_DATA_PRODUCE,
    )
)
CHI_MESI_READ_NOT_SHARED_DIRTY_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUESTER_READ_NOT_SHARED_DIRTY_ISSUE,
        CHI_REQUESTER_SHARED_COMP_DATA_ACCEPT,
        CHI_REQUESTER_DIRTY_COMP_DATA_ACCEPT,
        CHI_REQUESTER_COMP_ACK_PRODUCE,
    )
)
CHI_MESI_READ_NOT_SHARED_DIRTY_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_READ_NOT_SHARED_DIRTY_ACCEPT,
        CHI_HOME_CLEAN_SNOOP_COORDINATE,
        CHI_HOME_DIRTY_SNP_DATA_ACCEPT,
        CHI_HOME_DIRTY_TO_CLEAN_SHARED_COMMIT,
        CHI_HOME_SHARED_COMP_DATA_PRODUCE,
        CHI_HOME_COMP_ACK_ACCEPT,
    )
)
CHI_MESI_READ_NOT_SHARED_DIRTY_SNOOPEE_CAPABILITIES = frozenset(
    (
        CHI_SNOOPEE_SNP_NOT_SHARED_DIRTY_ACCEPT,
        CHI_SNOOPEE_CLEAN_SNP_RESP_PRODUCE,
        CHI_SNOOPEE_DIRTY_SNP_DATA_PRODUCE,
        CHI_SNOOPEE_DIRTY_TO_CLEAN_SHARED_DOWNGRADE,
    )
)
CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUEST_NODE_UNIQUE_LOCAL_WRITE,
        CHI_REQUESTER_WRITEBACK_FULL_ISSUE,
        CHI_REQUESTER_COMP_DBID_RESP_ACCEPT,
        CHI_REQUESTER_COPYBACK_WR_DATA_PRODUCE,
        CHI_SNOOPEE_WRITEBACK_PENDING_INVALIDATING_SNP_ACCEPT,
        CHI_REQUESTER_COPYBACK_CANCEL_PRODUCE,
    )
)
CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_WRITEBACK_FULL_ACCEPT,
        CHI_HOME_COMP_DBID_RESP_PRODUCE,
        CHI_HOME_COPYBACK_WR_DATA_ACCEPT,
        CHI_HOME_COPYBACK_CANCEL_ACCEPT,
    )
)
CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUEST_NODE_UNIQUE_LOCAL_WRITE,
        CHI_REQUESTER_CLEAN_UNIQUE_ISSUE,
        CHI_REQUESTER_COMP_UC_ACCEPT,
        CHI_REQUESTER_COMP_ACK_PRODUCE,
    )
)
CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_CLEAN_UNIQUE_ACCEPT,
        CHI_HOME_CLEAN_SNOOP_COORDINATE,
        CHI_HOME_COMP_UC_PRODUCE,
        CHI_HOME_COMP_ACK_ACCEPT,
    )
)
CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES = frozenset(
    (
        CHI_SNOOPEE_SNP_CLEAN_INVALID_ACCEPT,
        CHI_SNOOPEE_CLEAN_UNIQUE_PENDING_INVALIDATING_SNP_ACCEPT,
        CHI_SNOOPEE_CLEAN_SNP_RESP_PRODUCE,
    )
)
CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_DIRTY_SNP_DATA_ACCEPT,
        CHI_HOME_PASS_DIRTY_MEMORY_UPDATE,
    )
)
CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES = frozenset(
    (CHI_SNOOPEE_DIRTY_SNP_DATA_PRODUCE,)
)
CHI_MAKE_UNIQUE_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUEST_NODE_UNIQUE_LOCAL_WRITE,
        CHI_REQUESTER_MAKE_UNIQUE_ISSUE,
        CHI_REQUESTER_COMP_UC_ACCEPT,
        CHI_REQUESTER_COMP_ACK_PRODUCE,
    )
)
CHI_MAKE_UNIQUE_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_MAKE_UNIQUE_ACCEPT,
        CHI_HOME_CLEAN_SNOOP_COORDINATE,
        CHI_HOME_COMP_UC_PRODUCE,
        CHI_HOME_COMP_ACK_ACCEPT,
    )
)
CHI_MAKE_UNIQUE_SNOOPEE_CAPABILITIES = frozenset(
    (
        CHI_SNOOPEE_SNP_MAKE_INVALID_ACCEPT,
        CHI_SNOOPEE_SNP_MAKE_INVALID_DISCARD_DIRTY,
        CHI_SNOOPEE_CLEAN_SNP_RESP_PRODUCE,
    )
)
CHI_CLEAN_EVICT_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUESTER_EVICT_ISSUE,
        CHI_REQUESTER_EVICT_COMP_ACCEPT,
    )
)
CHI_CLEAN_EVICT_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_EVICT_ACCEPT,
        CHI_HOME_EVICT_COMP_PRODUCE,
    )
)
CHI_WRITE_EVICT_FULL_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUESTER_WRITE_EVICT_FULL_ISSUE,
        CHI_REQUESTER_COMP_DBID_RESP_ACCEPT,
        CHI_REQUESTER_CLEAN_COPYBACK_WR_DATA_PRODUCE,
        CHI_SNOOPEE_WRITE_EVICT_PENDING_INVALIDATING_SNP_ACCEPT,
        CHI_REQUESTER_COPYBACK_CANCEL_PRODUCE,
    )
)
CHI_WRITE_EVICT_FULL_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_WRITE_EVICT_FULL_ACCEPT,
        CHI_HOME_COMP_DBID_RESP_PRODUCE,
        CHI_HOME_CLEAN_COPYBACK_WR_DATA_ACCEPT,
        CHI_HOME_CLEAN_RESIDENCY_RETAIN,
        CHI_HOME_COPYBACK_CANCEL_ACCEPT,
    )
)
CHI_WRITE_EVICT_FULL_COPY_AT_HOME_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUESTER_COPY_AT_HOME_PROVENANCE_CACHE,
        CHI_REQUESTER_WRITE_EVICT_FULL_COPY_AT_HOME_ISSUE,
        CHI_REQUESTER_WRITE_EVICT_FULL_COMP_ACCEPT,
    )
)
CHI_WRITE_EVICT_FULL_COPY_AT_HOME_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_COPY_AT_HOME_COMP_DATA_PRODUCE,
        CHI_HOME_WRITE_EVICT_FULL_COPY_AT_HOME_ACCEPT,
        CHI_HOME_WRITE_EVICT_FULL_COMP_PRODUCE,
    )
)
CHI_WRITE_EVICT_OR_EVICT_REQUESTER_CAPABILITIES = frozenset(
    (
        CHI_REQUESTER_WRITE_EVICT_OR_EVICT_ISSUE,
        CHI_REQUESTER_COMP_DBID_RESP_ACCEPT,
        CHI_REQUESTER_CLEAN_COPYBACK_WR_DATA_PRODUCE,
        CHI_REQUESTER_WRITE_EVICT_OR_EVICT_COMP_ACCEPT,
        CHI_REQUESTER_COMP_ACK_PRODUCE,
        CHI_SNOOPEE_WRITE_EVICT_OR_EVICT_PENDING_INVALIDATING_SNP_ACCEPT,
        CHI_REQUESTER_COPYBACK_CANCEL_PRODUCE,
    )
)
CHI_WRITE_EVICT_OR_EVICT_HOME_CAPABILITIES = frozenset(
    (
        CHI_HOME_WRITE_EVICT_OR_EVICT_ACCEPT,
        CHI_HOME_COMP_DBID_RESP_PRODUCE,
        CHI_HOME_CLEAN_COPYBACK_WR_DATA_ACCEPT,
        CHI_HOME_CLEAN_RESIDENCY_RETAIN,
        CHI_HOME_WRITE_EVICT_OR_EVICT_COMP_PRODUCE,
        CHI_HOME_COMP_ACK_ACCEPT,
        CHI_HOME_COPYBACK_CANCEL_ACCEPT,
    )
)


@dataclass(frozen=True)
class ChiParticipantCapability:
    """Capabilities explicitly offered by one participant binding name."""

    participant: str
    provides: frozenset[ChiCapabilityKey] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.participant, str) or not self.participant:
            raise ValueError(
                "CHI participant capability requires a participant name"
            )
        try:
            provides = frozenset(self.provides)
        except TypeError as error:
            raise TypeError(
                "CHI participant capabilities must be iterable"
            ) from error
        if any(not isinstance(item, ChiCapabilityKey) for item in provides):
            raise TypeError(
                "CHI participant capabilities require ChiCapabilityKey values"
            )
        object.__setattr__(self, "provides", provides)

    def supports(self, capability: ChiCapabilityKey) -> bool:
        if not isinstance(capability, ChiCapabilityKey):
            raise TypeError("CHI capability query requires ChiCapabilityKey")
        return capability in self.provides

    def missing(
        self,
        required: frozenset[ChiCapabilityKey],
    ) -> frozenset[ChiCapabilityKey]:
        return frozenset(required) - self.provides


__all__ = [
    "CHI_CLEAN_EVICT_HOME_CAPABILITIES",
    "CHI_CLEAN_EVICT_REQUESTER_CAPABILITIES",
    "CHI_CLEAN_READ_SHARED_HOME_CAPABILITIES",
    "CHI_CLEAN_READ_SHARED_REQUESTER_CAPABILITIES",
    "CHI_CLEAN_READ_SHARED_SNOOPEE_CAPABILITIES",
    "CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES",
    "CHI_CLEAN_READ_UNIQUE_NDERR_HOME_CAPABILITIES",
    "CHI_CLEAN_READ_UNIQUE_NDERR_REQUESTER_CAPABILITIES",
    "CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES",
    "CHI_CLEAN_READ_UNIQUE_RETRY_HOME_CAPABILITIES",
    "CHI_CLEAN_READ_UNIQUE_RETRY_REQUESTER_CAPABILITIES",
    "CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES",
    "CHI_CLEAN_UNIQUE_CLEAN_PEERS_HOME_CAPABILITIES",
    "CHI_CLEAN_UNIQUE_CLEAN_PEERS_REQUESTER_CAPABILITIES",
    "CHI_CLEAN_UNIQUE_CLEAN_PEERS_SNOOPEE_CAPABILITIES",
    "CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_HOME_CAPABILITIES",
    "CHI_CLEAN_UNIQUE_SHARED_DIRTY_PEER_SNOOPEE_CAPABILITIES",
    "CHI_DIRTY_UNIQUE_HOME_CAPABILITIES",
    "CHI_DIRTY_UNIQUE_REQUESTER_CAPABILITIES",
    "CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES",
    "CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES",
    "CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES",
    "CHI_WRITE_EVICT_FULL_COPY_AT_HOME_HOME_CAPABILITIES",
    "CHI_WRITE_EVICT_FULL_COPY_AT_HOME_REQUESTER_CAPABILITIES",
    "CHI_WRITE_EVICT_FULL_HOME_CAPABILITIES",
    "CHI_WRITE_EVICT_FULL_REQUESTER_CAPABILITIES",
    "CHI_WRITE_EVICT_OR_EVICT_HOME_CAPABILITIES",
    "CHI_WRITE_EVICT_OR_EVICT_REQUESTER_CAPABILITIES",
    "CHI_MAKE_UNIQUE_HOME_CAPABILITIES",
    "CHI_MAKE_UNIQUE_REQUESTER_CAPABILITIES",
    "CHI_MAKE_UNIQUE_SNOOPEE_CAPABILITIES",
    "CHI_HOME_COMP_DBID_RESP_PRODUCE",
    "CHI_HOME_COPYBACK_CANCEL_ACCEPT",
    "CHI_HOME_COPYBACK_WR_DATA_ACCEPT",
    "CHI_HOME_CLEAN_COPYBACK_WR_DATA_ACCEPT",
    "CHI_HOME_CLEAN_RESIDENCY_RETAIN",
    "CHI_HOME_COPY_AT_HOME_COMP_DATA_PRODUCE",
    "CHI_HOME_DIRTY_COMP_DATA_PRODUCE",
    "CHI_HOME_DIRTY_SNP_DATA_ACCEPT",
    "CHI_HOME_PASS_DIRTY_MEMORY_UPDATE",
    "CHI_HOME_DIRTY_TO_CLEAN_SHARED_COMMIT",
    "CHI_HOME_EVICT_ACCEPT",
    "CHI_HOME_EVICT_COMP_PRODUCE",
    "CHI_HOME_MAKE_UNIQUE_ACCEPT",
    "CHI_HOME_READ_NOT_SHARED_DIRTY_ACCEPT",
    "CHI_HOME_CLEAN_SNOOP_COORDINATE",
    "CHI_HOME_COMP_ACK_ACCEPT",
    "CHI_HOME_COMP_DATA_PRODUCE",
    "CHI_HOME_READ_NO_SNP_NDERR_PRODUCE",
    "CHI_HOME_COMP_UC_PRODUCE",
    "CHI_HOME_CLEAN_UNIQUE_ACCEPT",
    "CHI_HOME_PCREDIT_GRANT",
    "CHI_HOME_PCREDIT_RECLAIM",
    "CHI_HOME_READ_NO_SNP_ACCEPT",
    "CHI_HOME_READ_SHARED_ACCEPT",
    "CHI_HOME_READ_UNIQUE_ACCEPT",
    "CHI_HOME_READ_UNIQUE_NDERR_PRODUCE",
    "CHI_HOME_RETRY_ACK_PRODUCE",
    "CHI_HOME_SHARED_COMP_DATA_PRODUCE",
    "CHI_HOME_UNIQUE_COMP_DATA_PRODUCE",
    "CHI_HOME_WRITEBACK_FULL_ACCEPT",
    "CHI_HOME_WRITE_EVICT_FULL_COMP_PRODUCE",
    "CHI_HOME_WRITE_EVICT_FULL_COPY_AT_HOME_ACCEPT",
    "CHI_HOME_WRITE_EVICT_FULL_ACCEPT",
    "CHI_HOME_WRITE_EVICT_OR_EVICT_ACCEPT",
    "CHI_HOME_WRITE_EVICT_OR_EVICT_COMP_PRODUCE",
    "CHI_READ_NO_SNP_HOME_CAPABILITIES",
    "CHI_READ_NO_SNP_NDERR_HOME_CAPABILITIES",
    "CHI_READ_NO_SNP_NDERR_REQUESTER_CAPABILITIES",
    "CHI_READ_NO_SNP_REQUESTER_CAPABILITIES",
    "CHI_MESI_READ_NOT_SHARED_DIRTY_HOME_CAPABILITIES",
    "CHI_MESI_READ_NOT_SHARED_DIRTY_REQUESTER_CAPABILITIES",
    "CHI_MESI_READ_NOT_SHARED_DIRTY_SNOOPEE_CAPABILITIES",
    "CHI_REQUESTER_COMP_ACK_PRODUCE",
    "CHI_REQUESTER_COMP_DATA_ACCEPT",
    "CHI_REQUESTER_COPY_AT_HOME_PROVENANCE_CACHE",
    "CHI_REQUESTER_READ_NO_SNP_NDERR_ACCEPT",
    "CHI_REQUESTER_COMP_UC_ACCEPT",
    "CHI_REQUESTER_CLEAN_UNIQUE_ISSUE",
    "CHI_REQUESTER_COMP_DBID_RESP_ACCEPT",
    "CHI_REQUESTER_COPYBACK_CANCEL_PRODUCE",
    "CHI_REQUESTER_COPYBACK_WR_DATA_PRODUCE",
    "CHI_REQUESTER_CLEAN_COPYBACK_WR_DATA_PRODUCE",
    "CHI_REQUESTER_PCREDIT_CONSUME",
    "CHI_REQUESTER_PCREDIT_RETURN",
    "CHI_REQUESTER_READ_NO_SNP_ISSUE",
    "CHI_REQUESTER_READ_NOT_SHARED_DIRTY_ISSUE",
    "CHI_REQUESTER_READ_SHARED_ISSUE",
    "CHI_REQUESTER_READ_UNIQUE_ISSUE",
    "CHI_REQUESTER_READ_UNIQUE_NDERR_ACCEPT",
    "CHI_REQUESTER_RETRY_ACK_ACCEPT",
    "CHI_REQUESTER_SHARED_COMP_DATA_ACCEPT",
    "CHI_REQUESTER_UNIQUE_COMP_DATA_ACCEPT",
    "CHI_REQUESTER_WRITEBACK_FULL_ISSUE",
    "CHI_REQUESTER_WRITE_EVICT_FULL_COMP_ACCEPT",
    "CHI_REQUESTER_WRITE_EVICT_FULL_COPY_AT_HOME_ISSUE",
    "CHI_REQUESTER_WRITE_EVICT_FULL_ISSUE",
    "CHI_REQUESTER_WRITE_EVICT_OR_EVICT_COMP_ACCEPT",
    "CHI_REQUESTER_WRITE_EVICT_OR_EVICT_ISSUE",
    "CHI_REQUESTER_DIRTY_COMP_DATA_ACCEPT",
    "CHI_REQUESTER_EVICT_COMP_ACCEPT",
    "CHI_REQUESTER_EVICT_ISSUE",
    "CHI_REQUESTER_MAKE_UNIQUE_ISSUE",
    "CHI_REQUEST_NODE_UNIQUE_LOCAL_WRITE",
    "CHI_REQUEST_RETRY_HOME_CAPABILITIES",
    "CHI_REQUEST_RETRY_REQUESTER_CAPABILITIES",
    "CHI_SNOOPEE_CLEAN_SNP_RESP_PRODUCE",
    "CHI_SNOOPEE_CLEAN_UNIQUE_PENDING_INVALIDATING_SNP_ACCEPT",
    "CHI_SNOOPEE_SNP_CLEAN_INVALID_ACCEPT",
    "CHI_SNOOPEE_SNP_MAKE_INVALID_ACCEPT",
    "CHI_SNOOPEE_SNP_MAKE_INVALID_DISCARD_DIRTY",
    "CHI_SNOOPEE_SNP_SHARED_ACCEPT",
    "CHI_SNOOPEE_SNP_UNIQUE_ACCEPT",
    "CHI_SNOOPEE_READ_UNIQUE_PENDING_SNP_UNIQUE_ACCEPT",
    "CHI_SNOOPEE_WRITEBACK_PENDING_INVALIDATING_SNP_ACCEPT",
    "CHI_SNOOPEE_WRITE_EVICT_PENDING_INVALIDATING_SNP_ACCEPT",
    "CHI_SNOOPEE_WRITE_EVICT_OR_EVICT_PENDING_INVALIDATING_SNP_ACCEPT",
    "CHI_SNOOPEE_DIRTY_SNP_DATA_PRODUCE",
    "CHI_SNOOPEE_DIRTY_TO_CLEAN_SHARED_DOWNGRADE",
    "CHI_SNOOPEE_SNP_NOT_SHARED_DIRTY_ACCEPT",
    "ChiCapabilityKey",
    "ChiParticipantCapability",
]

from __future__ import annotations

from collections import Counter
import unittest

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_RETRY_HOME_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_RETRY_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
    CHI_DIRTY_UNIQUE_HOME_CAPABILITIES,
    CHI_DIRTY_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES,
    CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES,
    CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES,
    CHI_MESI_READ_NOT_SHARED_DIRTY_HOME_CAPABILITIES,
    CHI_MESI_READ_NOT_SHARED_DIRTY_REQUESTER_CAPABILITIES,
    CHI_MESI_READ_NOT_SHARED_DIRTY_SNOOPEE_CAPABILITIES,
    ChiBehaviorFacet,
    ChiCacheLine,
    ChiCacheState,
    ChiCoherentHomeNode,
    ChiExactNodeRoute,
    ChiFacetKind,
    ChiHomeDirectoryEntry,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
    ChiStoreForwardRouterNode,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiCompAckMessage,
    ChiCompDBIDRespMessage,
    ChiCompDataMessage,
    ChiCopyBackWrDataMessage,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiIssueHSnpProfile,
    ChiReadNotSharedDirtyMessage,
    ChiReadUniqueMessage,
    ChiPCrdGrantMessage,
    ChiRespCode,
    ChiRetryAckMessage,
    ChiSnpRespMessage,
    ChiSnpRespDataMessage,
    ChiSnpNotSharedDirtyMessage,
    ChiSnpUniqueMessage,
    ChiWriteBackFullMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY,
    CHI_FEATURE_DIRTY_UNIQUE_TRANSFER,
    CHI_FEATURE_DIRTY_WRITEBACK,
    CHI_MESI_NO_SD_REQUIRED_FEATURES,
    CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
    CHI_SYSTEM_CLEAN_READ_UNIQUE_RETRY_LIFECYCLE,
    CHI_SYSTEM_DIRTY_UNIQUE_TRANSFER_LIFECYCLE,
    CHI_SYSTEM_DIRTY_WRITEBACK_LIFECYCLE,
    CHI_SYSTEM_MESI_READ_NOT_SHARED_DIRTY_LIFECYCLE,
    ChiAdvanceCoherenceNetwork,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceNetworkEventKind,
    ChiCoherenceNetworkSession,
    ChiCoherenceNetworkState,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiSubmitCoherentRead,
    ChiSubmitWriteBackFull,
    ChiWriteUniqueCacheLine,
    resolve_chi_system,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiDatChannelProfile,
    ChiReqChannelProfile,
    ChiRspChannelProfile,
    ChiSnpChannelProfile,
    ChiTransportLinkProfile,
)
from protocol_model.system import (
    AddressClaim,
    AddressWindow,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)
from protocol_model.virtual_dut.boundary import (
    DutBehaviorTag,
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHCoherenceNetworkTest(unittest.TestCase):
    """Run clean, dirty, and MESI downgrade paths through one caller-built NoC.

    All protocol packets cross ``xp0``.  In particular, the two snoops are
    separate packets sharing the same Home egress connection.  Its capacity
    is one, so the composite runtime must retain the second packet instead of
    dropping it when the first packet occupies the transport transmitter.
    """

    REQUESTER = 0x07
    FIRST_SNOOPEE = 0x08
    SECOND_SNOOPEE = 0x09
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xC0DE
    DIRTY_DATA = (1 << 420) | 0xD177

    @staticmethod
    def port(
        name: str,
        direction: TransportDirection,
    ) -> TransportPort:
        return TransportPort(
            name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            direction,
            clock_domain="chi_clk",
        )

    @staticmethod
    def link_profile(
        name: str,
        channels: frozenset[ChiChannelKind],
        *,
        data_width: int = 512,
    ) -> ChiTransportLinkProfile:
        return ChiTransportLinkProfile(
            request=(
                ChiReqChannelProfile(
                    ChiIssueHReqProfile(),
                    (1,),
                    f"{name}.req",
                )
                if ChiChannelKind.REQ in channels
                else None
            ),
            response=(
                ChiRspChannelProfile(
                    ChiIssueHRspProfile(),
                    1,
                    f"{name}.rsp",
                )
                if ChiChannelKind.RSP in channels
                else None
            ),
            snoop=(
                ChiSnpChannelProfile(
                    ChiIssueHSnpProfile(),
                    1,
                    f"{name}.snp",
                )
                if ChiChannelKind.SNP in channels
                else None
            ),
            data=(
                ChiDatChannelProfile(
                    ChiIssueHDatProfile(data_width=data_width),
                    1,
                    f"{name}.dat",
                )
                if ChiChannelKind.DAT in channels
                else None
            ),
            clock="chi_clk",
            activation_observation=f"{name}.active",
        )

    def build_resolved(
        self,
        *,
        dirty: bool = False,
        mesi: bool = False,
        writeback: bool = False,
        retry: bool = False,
        data_width: int = 512,
    ):
        if sum((dirty, mesi, writeback, retry)) > 1:
            raise ValueError(
                "select one dirty-unique, MESI read, writeback, or retry mode"
            )
        snoop_uses_dirty_data = dirty or mesi
        home_transmit_channels = (
            frozenset((ChiChannelKind.RSP,))
            if writeback
            else frozenset(
                (
                    ChiChannelKind.DAT,
                    ChiChannelKind.SNP,
                    *((ChiChannelKind.RSP,) if retry else ()),
                )
            )
        )
        requester_receive_channels = (
            frozenset((ChiChannelKind.RSP,))
            if writeback
            else frozenset(
                (
                    ChiChannelKind.DAT,
                    *((ChiChannelKind.RSP,) if retry else ()),
                )
            )
        )
        builder = SystemProtocolBuilder(
            (
                "chi_dirty_writeback_via_xp"
                if writeback
                else (
                    "chi_mesi_read_not_shared_dirty_via_xp"
                    if mesi
                    else (
                        "chi_dirty_unique_via_xp"
                        if dirty
                        else (
                            "chi_clean_unique_retry_via_xp"
                            if retry
                            else "chi_clean_unique_via_xp"
                        )
                    )
                )
            )
        )
        builder.add_dut(
            VirtualDut(
                "rn0",
                {
                    "tx_to_xp": self.port(
                        "tx_to_xp",
                        TransportDirection.TRANSMIT,
                    ),
                    "rx_from_xp": self.port(
                        "rx_from_xp",
                        TransportDirection.RECEIVE,
                    ),
                },
            )
        )
        for name in ("rn1", "rn2"):
            builder.add_dut(
                VirtualDut(
                    name,
                    {
                        "rx_snp": self.port(
                            "rx_snp",
                            TransportDirection.RECEIVE,
                        ),
                        "tx_rsp": self.port(
                            "tx_rsp",
                            TransportDirection.TRANSMIT,
                        ),
                    },
                )
            )
        builder.add_dut(
            VirtualDut(
                "hn0",
                {
                    "rx_from_xp": self.port(
                        "rx_from_xp",
                        TransportDirection.RECEIVE,
                    ),
                    "tx_to_xp": self.port(
                        "tx_to_xp",
                        TransportDirection.TRANSMIT,
                    ),
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "xp0",
                {
                    **{
                        f"from_{name}": self.port(
                            f"from_{name}",
                            TransportDirection.RECEIVE,
                        )
                        for name in ("rn0", "rn1", "rn2", "hn0")
                    },
                    **{
                        f"to_{name}": self.port(
                            f"to_{name}",
                            TransportDirection.TRANSMIT,
                        )
                        for name in ("rn0", "rn1", "rn2", "hn0")
                    },
                },
                behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
            )
        )

        connection_specs = (
            (
                "rn0_to_xp",
                VirtualDutPortRef("rn0", "tx_to_xp"),
                VirtualDutPortRef("xp0", "from_rn0"),
                frozenset(
                    (
                        ChiChannelKind.REQ,
                        (
                            ChiChannelKind.DAT
                            if writeback
                            else ChiChannelKind.RSP
                        ),
                    )
                ),
            ),
            (
                "rn1_to_xp",
                VirtualDutPortRef("rn1", "tx_rsp"),
                VirtualDutPortRef("xp0", "from_rn1"),
                frozenset(
                    (
                        ChiChannelKind.RSP,
                        *(
                            (ChiChannelKind.DAT,)
                            if snoop_uses_dirty_data
                            else ()
                        ),
                    )
                ),
            ),
            (
                "rn2_to_xp",
                VirtualDutPortRef("rn2", "tx_rsp"),
                VirtualDutPortRef("xp0", "from_rn2"),
                frozenset(
                    (
                        ChiChannelKind.RSP,
                        *(
                            (ChiChannelKind.DAT,)
                            if snoop_uses_dirty_data
                            else ()
                        ),
                    )
                ),
            ),
            (
                "hn0_to_xp",
                VirtualDutPortRef("hn0", "tx_to_xp"),
                VirtualDutPortRef("xp0", "from_hn0"),
                home_transmit_channels,
            ),
            (
                "xp_to_rn0",
                VirtualDutPortRef("xp0", "to_rn0"),
                VirtualDutPortRef("rn0", "rx_from_xp"),
                requester_receive_channels,
            ),
            (
                "xp_to_rn1",
                VirtualDutPortRef("xp0", "to_rn1"),
                VirtualDutPortRef("rn1", "rx_snp"),
                frozenset((ChiChannelKind.SNP,)),
            ),
            (
                "xp_to_rn2",
                VirtualDutPortRef("xp0", "to_rn2"),
                VirtualDutPortRef("rn2", "rx_snp"),
                frozenset((ChiChannelKind.SNP,)),
            ),
            (
                "xp_to_hn0",
                VirtualDutPortRef("xp0", "to_hn0"),
                VirtualDutPortRef("hn0", "rx_from_xp"),
                frozenset(
                    (
                        ChiChannelKind.REQ,
                        (
                            ChiChannelKind.DAT
                            if writeback
                            else ChiChannelKind.RSP
                        ),
                        *(
                            (ChiChannelKind.DAT,)
                            if snoop_uses_dirty_data
                            else ()
                        ),
                    )
                ),
            ),
        )
        for name, transmitter, receiver, channels in connection_specs:
            builder.connect_transport(
                name,
                CHI_ISSUE_H_TRANSPORT_FAMILY,
                transmitter,
                receiver,
                profile=self.link_profile(
                    name,
                    channels,
                    data_width=data_width,
                ),
            )

        home_address_claim = "hn0.cache_line"
        builder.add_address_claim(
            AddressClaim(
                home_address_claim,
                VirtualDutPortRef("hn0", "rx_from_xp"),
                AddressWindow(self.ADDRESS, 0x40),
            )
        )
        system = builder.build().elaborate()
        duts = system.spec.virtual_duts
        requester_assembly = bind_chi_issue_h_cache_lines(
            duts["rn0"],
            self.REQUESTER,
            self.HOME,
            port_channels={
                "tx_to_xp": (
                    frozenset(
                        (ChiChannelKind.REQ, ChiChannelKind.DAT)
                    )
                    if writeback
                    else frozenset(
                        (ChiChannelKind.REQ, ChiChannelKind.RSP)
                    )
                ),
                "rx_from_xp": requester_receive_channels,
            },
            initial_lines=(
                (
                    ChiCacheLine(
                        self.ADDRESS,
                        ChiCacheState.UD,
                        self.DIRTY_DATA,
                    ),
                )
                if writeback
                else ()
            ),
            participant_name="requester",
            binding_name="rn0",
        )
        snoopee_assemblies = {
            "rn1": bind_chi_issue_h_cache_lines(
                duts["rn1"],
                self.FIRST_SNOOPEE,
                self.HOME,
                port_channels={
                    "rx_snp": frozenset((ChiChannelKind.SNP,)),
                    "tx_rsp": frozenset(
                        (
                            ChiChannelKind.RSP,
                            *(
                                (ChiChannelKind.DAT,)
                                if snoop_uses_dirty_data
                                else ()
                            ),
                        )
                    ),
                },
                initial_lines=(
                    ChiCacheLine(
                        self.ADDRESS,
                        (
                            ChiCacheState.UC
                            if snoop_uses_dirty_data
                            else (
                                ChiCacheState.I
                                if writeback
                                else ChiCacheState.SC
                            )
                        ),
                        (
                            None
                            if writeback
                            else self.DATA
                        ),
                    ),
                ),
                participant_name="snoopee_1",
                binding_name="rn1",
            ),
            "rn2": bind_chi_issue_h_cache_lines(
                duts["rn2"],
                self.SECOND_SNOOPEE,
                self.HOME,
                port_channels={
                    "rx_snp": frozenset((ChiChannelKind.SNP,)),
                    "tx_rsp": frozenset(
                        (
                            ChiChannelKind.RSP,
                            *(
                                (ChiChannelKind.DAT,)
                                if snoop_uses_dirty_data
                                else ()
                            ),
                        )
                    ),
                },
                initial_lines=(
                    ChiCacheLine(
                        self.ADDRESS,
                        (
                            ChiCacheState.I
                            if snoop_uses_dirty_data or writeback
                            else ChiCacheState.SC
                        ),
                        (
                            None
                            if snoop_uses_dirty_data or writeback
                            else self.DATA
                        ),
                    ),
                ),
                participant_name="snoopee_2",
                binding_name="rn2",
            ),
        }
        requester = requester_assembly.participant
        snoopees = {
            name: assembly.participant
            for name, assembly in snoopee_assemblies.items()
        }
        home = ChiCoherentHomeNode(
            "home",
            self.HOME,
            backing_core=FullLineBackingCore(
                "home.backing",
                line_bytes=64,
                initial_lines=(BackingLine(self.ADDRESS, self.DATA),),
            ),
            initial_directory=(
                ChiHomeDirectoryEntry(
                    self.ADDRESS,
                    sharers=(
                        frozenset()
                        if snoop_uses_dirty_data or writeback
                        else frozenset(
                            (
                                self.FIRST_SNOOPEE,
                                self.SECOND_SNOOPEE,
                            )
                        )
                    ),
                    unique_owner=(
                        (
                            self.REQUESTER
                            if writeback
                            else self.FIRST_SNOOPEE
                        )
                        if snoop_uses_dirty_data or writeback
                        else None
                    ),
                ),
            ),
            initial_snoop_transaction_id=0x100,
            initial_data_buffer_id=0x200,
            allow_dirty_data_transfer=(
                snoop_uses_dirty_data or writeback
            ),
            **(
                {
                    "retry_policy": lambda request, state: 4,
                    "default_protocol_credit_type": 4,
                }
                if retry
                else {}
            ),
        )
        router = ChiStoreForwardRouterNode(
            "xp0",
            ingress_ports=(
                "from_rn0",
                "from_rn1",
                "from_rn2",
                "from_hn0",
            ),
            egress_ports=("to_rn0", "to_rn1", "to_rn2", "to_hn0"),
            routes=(
                ChiExactNodeRoute(
                    self.REQUESTER,
                    "to_rn0",
                    requester_receive_channels,
                ),
                ChiExactNodeRoute(
                    self.FIRST_SNOOPEE,
                    "to_rn1",
                    frozenset((ChiChannelKind.SNP,)),
                ),
                ChiExactNodeRoute(
                    self.SECOND_SNOOPEE,
                    "to_rn2",
                    frozenset((ChiChannelKind.SNP,)),
                ),
                ChiExactNodeRoute(
                    self.HOME,
                    "to_hn0",
                    frozenset(
                        (
                            ChiChannelKind.REQ,
                            (
                                ChiChannelKind.DAT
                                if writeback
                                else ChiChannelKind.RSP
                            ),
                            *(
                                (ChiChannelKind.DAT,)
                                if snoop_uses_dirty_data
                                else ()
                            ),
                        )
                    ),
                ),
            ),
            queue_capacity=1,
        )

        port_binding = ChiParticipantPortBinding
        bindings = {
            "rn0": requester_assembly.binding,
            "hn0": ChiParticipantBinding(
                "hn0",
                duts["hn0"],
                home,
                (
                    port_binding(
                        duts["hn0"].port("rx_from_xp"),
                        frozenset(
                            (
                                ChiChannelKind.REQ,
                                (
                                    ChiChannelKind.DAT
                                    if writeback
                                    else ChiChannelKind.RSP
                                ),
                                *(
                                    (ChiChannelKind.DAT,)
                                    if snoop_uses_dirty_data
                                    else ()
                                ),
                            )
                        ),
                    ),
                    port_binding(
                        duts["hn0"].port("tx_to_xp"),
                        home_transmit_channels,
                    ),
                ),
                frozenset((self.HOME,)),
            ),
        }
        for name in ("rn1", "rn2"):
            bindings[name] = snoopee_assemblies[name].binding
        bindings["xp0"] = ChiParticipantBinding(
            "xp0",
            duts["xp0"],
            router,
            tuple(
                port_binding(
                    duts["xp0"].port(name),
                    channels,
                )
                for name, channels in (
                    (
                        "from_rn0",
                        frozenset(
                            (
                                ChiChannelKind.REQ,
                                (
                                    ChiChannelKind.DAT
                                    if writeback
                                    else ChiChannelKind.RSP
                                ),
                            )
                        ),
                    ),
                    (
                        "from_rn1",
                        frozenset(
                            (
                                ChiChannelKind.RSP,
                                *(
                                    (ChiChannelKind.DAT,)
                                    if snoop_uses_dirty_data
                                    else ()
                                ),
                            )
                        ),
                    ),
                    (
                        "from_rn2",
                        frozenset(
                            (
                                ChiChannelKind.RSP,
                                *(
                                    (ChiChannelKind.DAT,)
                                    if snoop_uses_dirty_data
                                    else ()
                                ),
                            )
                        ),
                    ),
                    (
                        "from_hn0",
                        home_transmit_channels,
                    ),
                    (
                        "to_rn0",
                        requester_receive_channels,
                    ),
                    ("to_rn1", frozenset((ChiChannelKind.SNP,))),
                    ("to_rn2", frozenset((ChiChannelKind.SNP,))),
                    (
                        "to_hn0",
                        frozenset(
                            (
                                ChiChannelKind.REQ,
                                (
                                    ChiChannelKind.DAT
                                    if writeback
                                    else ChiChannelKind.RSP
                                ),
                                *(
                                    (ChiChannelKind.DAT,)
                                    if snoop_uses_dirty_data
                                    else ()
                                ),
                            )
                        ),
                    ),
                )
            ),
        )

        contract = ChiFeatureContract(
            {"requester": "rn0"},
            frozenset(
                (CHI_FEATURE_DIRTY_WRITEBACK,)
                if writeback
                else (
                    CHI_MESI_NO_SD_REQUIRED_FEATURES
                    if mesi
                    else (
                        (
                            CHI_FEATURE_DIRTY_UNIQUE_TRANSFER
                            if dirty
                            else (
                                CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY
                                if retry
                                else CHI_FEATURE_CLEAN_READ_UNIQUE
                            )
                        ),
                    )
                )
            ),
        )
        capabilities = (
            ChiParticipantCapability(
                "rn0",
                (
                    CHI_DIRTY_WRITEBACK_REQUESTER_CAPABILITIES
                    if writeback
                    else (
                        CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_REQUESTER_CAPABILITIES
                        | CHI_MESI_READ_NOT_SHARED_DIRTY_REQUESTER_CAPABILITIES
                        if mesi
                        else (
                            CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES
                            | CHI_DIRTY_UNIQUE_REQUESTER_CAPABILITIES
                            if dirty
                            else (
                                CHI_CLEAN_READ_UNIQUE_RETRY_REQUESTER_CAPABILITIES
                                if retry
                                else CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES
                            )
                        )
                    )
                ),
            ),
            ChiParticipantCapability(
                "hn0",
                (
                    CHI_DIRTY_WRITEBACK_HOME_CAPABILITIES
                    if writeback
                    else (
                        CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_HOME_CAPABILITIES
                        | CHI_MESI_READ_NOT_SHARED_DIRTY_HOME_CAPABILITIES
                        if mesi
                        else (
                            CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES
                            | CHI_DIRTY_UNIQUE_HOME_CAPABILITIES
                            if dirty
                            else (
                                CHI_CLEAN_READ_UNIQUE_RETRY_HOME_CAPABILITIES
                                if retry
                                else CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES
                            )
                        )
                    )
                ),
            ),
            ChiParticipantCapability(
                "rn1",
                (
                    frozenset()
                    if writeback
                    else (
                        CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES
                        | CHI_MESI_READ_NOT_SHARED_DIRTY_SNOOPEE_CAPABILITIES
                        if mesi
                        else (
                            CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                            | CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES
                            if dirty
                            else CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                        )
                    )
                ),
            ),
            ChiParticipantCapability(
                "rn2",
                (
                    frozenset()
                    if writeback
                    else (
                        CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                        | CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES
                        | CHI_MESI_READ_NOT_SHARED_DIRTY_SNOOPEE_CAPABILITIES
                        if mesi
                        else (
                            CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                            | CHI_DIRTY_UNIQUE_SNOOPEE_CAPABILITIES
                            if dirty
                            else CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES
                        )
                    )
                ),
            ),
        )
        return resolve_chi_system(
            system,
            facets=(
                requester_assembly.facets.facets[0],
                *(
                    snoopee_assemblies[name].facets.facets[0]
                    for name in ("rn1", "rn2")
                ),
                ChiBehaviorFacet.from_binding(
                    bindings["hn0"],
                    ChiFacetKind.TRANSACTION,
                ),
                ChiBehaviorFacet.from_binding(
                    bindings["xp0"],
                    ChiFacetKind.FORWARDING,
                ),
            ),
            feature_contract=contract,
            authority_contract=ChiCoherenceAuthorityContract(
                authorities=(
                    ChiHomeAuthority(
                        home_address_claim,
                        "hn0",
                        "coherent_agents",
                    ),
                ),
                domains=(
                    ChiCoherenceDomain(
                        "coherent_agents",
                        frozenset(("rn0", "rn1", "rn2")),
                    ),
                ),
            ),
            feature_address_claim=home_address_claim,
            participant_capabilities=capabilities,
            system_capabilities=frozenset(
                (
                    *(
                        (CHI_SYSTEM_DIRTY_WRITEBACK_LIFECYCLE,)
                        if writeback
                        else (
                            (
                                CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
                                CHI_SYSTEM_DIRTY_UNIQUE_TRANSFER_LIFECYCLE,
                                CHI_SYSTEM_MESI_READ_NOT_SHARED_DIRTY_LIFECYCLE,
                            )
                            if mesi
                            else (
                                (
                                    CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
                                    CHI_SYSTEM_DIRTY_UNIQUE_TRANSFER_LIFECYCLE,
                                )
                                if dirty
                                else (
                                    CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
                                    *(
                                        (
                                            CHI_SYSTEM_CLEAN_READ_UNIQUE_RETRY_LIFECYCLE,
                                        )
                                        if retry
                                        else ()
                                    ),
                                )
                            )
                        )
                    ),
                )
            ),
            transmitter_capacity_by_connection={"hn0_to_xp": 1},
        )

    @staticmethod
    def packets_from(transition) -> tuple:
        return tuple(
            event.packet
            for event in transition.emissions
            if getattr(event, "packet", None) is not None
        )

    def apply(self, session, state, action):
        transition = session.step(state, action)
        self.assertIsNone(transition.fault)
        self.assertIsNone(transition.blocked)
        return transition

    def test_read_unique_closes_through_one_xp_without_losing_fanout(
        self,
    ) -> None:
        resolved = self.build_resolved()
        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        state = session.initial_state()

        for name in ("rn0", "rn1", "rn2"):
            self.assertIs(
                resolved.system.spec.virtual_duts[name],
                resolved.binding_by_name[name].dut,
            )
        self.assertIsInstance(state, ChiCoherenceNetworkState)
        self.assertIs(session.network, resolved.network)
        self.assertEqual(0, state.scheduler_cursor)
        self.assertEqual(0, state.committed_microsteps)

        packet_by_identity = {}
        issued = self.apply(
            session,
            state,
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadUniqueMessage(
                    transaction_id=0x12,
                    address=self.ADDRESS,
                ),
            ),
        )
        state = issued.state
        for packet in self.packets_from(issued):
            packet_by_identity[id(packet)] = packet

        maximum_pending_egress = len(state.pending_egress)
        for _ in range(1024):
            if session.is_quiescent(state):
                break
            advanced = self.apply(
                session,
                state,
                ChiAdvanceCoherenceNetwork(),
            )
            state = advanced.state
            maximum_pending_egress = max(
                maximum_pending_egress,
                len(state.pending_egress),
            )
            for packet in self.packets_from(advanced):
                packet_by_identity[id(packet)] = packet
        else:
            self.fail("clean ReadUnique did not quiesce within 1024 microsteps")

        packets = tuple(packet_by_identity.values())
        message_counts = Counter(type(packet.message) for packet in packets)
        self.assertEqual(1, message_counts[ChiReadUniqueMessage])
        self.assertEqual(2, message_counts[ChiSnpUniqueMessage])
        self.assertEqual(2, message_counts[ChiSnpRespMessage])
        self.assertEqual(1, message_counts[ChiCompDataMessage])
        self.assertEqual(1, message_counts[ChiCompAckMessage])
        self.assertEqual(7, len(packets))

        snoops = tuple(
            packet
            for packet in packets
            if isinstance(packet.message, ChiSnpUniqueMessage)
        )
        self.assertEqual(
            {self.FIRST_SNOOPEE, self.SECOND_SNOOPEE},
            {packet.target_id for packet in snoops},
        )
        self.assertGreaterEqual(maximum_pending_egress, 2)

        router_state = state.network.routers["xp0"]
        self.assertEqual(7, router_state.accepted_count)
        self.assertEqual(7, router_state.forwarded_count)
        self.assertFalse(state.pending_egress)
        self.assertTrue(session.network.is_quiescent(state.network))
        self.assertTrue(session.coherence.is_quiescent(state.coherence))
        self.assertTrue(session.is_quiescent(state))

        requester = state.coherence.request_nodes[self.REQUESTER]
        first = state.coherence.request_nodes[self.FIRST_SNOOPEE]
        second = state.coherence.request_nodes[self.SECOND_SNOOPEE]
        self.assertEqual(
            ChiCacheState.UC,
            requester.lines[self.ADDRESS].state,
        )
        self.assertEqual(
            ChiCacheState.I,
            first.lines[self.ADDRESS].state,
        )
        self.assertEqual(
            ChiCacheState.I,
            second.lines[self.ADDRESS].state,
        )
        directory = state.coherence.home.directory[self.ADDRESS]
        self.assertEqual(self.REQUESTER, directory.unique_owner)
        self.assertFalse(directory.sharers)

    def test_read_unique_retry_closes_through_one_xp_automatically(
        self,
    ) -> None:
        resolved = self.build_resolved(retry=True)
        evidence = resolved.capabilities.require(
            CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY
        )
        self.assertEqual(
            ("hn0_to_xp", "xp_to_rn0"),
            evidence.flows["retry_response"].connections,
        )
        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        initial = session.initial_state()

        issued = self.apply(
            session,
            initial,
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadUniqueMessage(0x16, self.ADDRESS),
            ),
        )
        run = session.run_until_quiescent(
            issued.state,
            max_steps=1024,
        )

        self.assertTrue(run.ok)
        self.assertIsNone(run.blocked)
        self.assertTrue(session.is_quiescent(run.final_state))
        packets_by_identity = {}
        for event in (*issued.emissions, *run.emissions):
            packet = getattr(event, "packet", None)
            if packet is not None:
                packets_by_identity.setdefault(id(packet), packet)
        packets = tuple(packets_by_identity.values())
        message_counts = Counter(
            type(packet.message) for packet in packets
        )
        self.assertEqual(2, message_counts[ChiReadUniqueMessage])
        self.assertEqual(1, message_counts[ChiRetryAckMessage])
        self.assertEqual(1, message_counts[ChiPCrdGrantMessage])
        self.assertEqual(2, message_counts[ChiSnpUniqueMessage])
        self.assertEqual(2, message_counts[ChiSnpRespMessage])
        self.assertEqual(1, message_counts[ChiCompDataMessage])
        self.assertEqual(1, message_counts[ChiCompAckMessage])
        self.assertEqual(10, len(packets))
        requests = tuple(
            packet.message
            for packet in packets
            if isinstance(packet.message, ChiReadUniqueMessage)
        )
        self.assertTrue(requests[0].allow_retry)
        self.assertFalse(requests[1].allow_retry)
        self.assertEqual(4, requests[1].protocol_credit_type)

        state = run.final_state.coherence
        requester = state.request_nodes[self.REQUESTER]
        first = state.request_nodes[self.FIRST_SNOOPEE]
        second = state.request_nodes[self.SECOND_SNOOPEE]
        self.assertIs(
            ChiCacheState.UC,
            requester.lines[self.ADDRESS].state,
        )
        self.assertIs(
            ChiCacheState.I,
            first.lines[self.ADDRESS].state,
        )
        self.assertIs(
            ChiCacheState.I,
            second.lines[self.ADDRESS].state,
        )
        entry = state.home.directory[self.ADDRESS]
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertFalse(entry.sharers)
        backing = state.home.backing.line_at(self.ADDRESS)
        assert backing is not None
        self.assertEqual(self.DATA, backing.data)
        self.assertEqual(0, backing.version)

        self.assertFalse(requester.pending_transactions)
        self.assertFalse(requester.pending_writebacks)
        self.assertFalse(requester.request_retry.entries)
        self.assertFalse(requester.request_retry.protocol_credits)
        self.assertFalse(state.home.pending)
        self.assertFalse(state.home.pending_writebacks)
        self.assertFalse(state.home.request_retry.retry_debts)
        self.assertFalse(state.home.request_retry.reservations)
        self.assertEqual(1, state.home.request_retry.retry_ack_count)
        self.assertEqual(1, state.home.request_retry.grant_count)
        self.assertEqual(1, state.home.request_retry.consumed_count)

    def test_dirty_unique_responsibility_crosses_the_same_xp(self) -> None:
        resolved = self.build_resolved(dirty=True)
        self.assertTrue(resolved.is_closed)
        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        state = session.initial_state()
        dirty_data = (1 << 420) | 0xD177

        dirtied = self.apply(
            session,
            state,
            ChiWriteUniqueCacheLine(
                self.FIRST_SNOOPEE,
                self.ADDRESS,
                dirty_data,
            ),
        )
        state = dirtied.state
        self.assertIs(
            ChiCacheState.UD,
            state.coherence.request_nodes[self.FIRST_SNOOPEE]
            .lines[self.ADDRESS]
            .state,
        )

        packet_by_identity = {}
        issued = self.apply(
            session,
            state,
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadUniqueMessage(0x13, self.ADDRESS),
            ),
        )
        state = issued.state
        for packet in self.packets_from(issued):
            packet_by_identity[id(packet)] = packet

        for _ in range(1024):
            if session.is_quiescent(state):
                break
            advanced = self.apply(
                session,
                state,
                ChiAdvanceCoherenceNetwork(),
            )
            state = advanced.state
            for packet in self.packets_from(advanced):
                packet_by_identity[id(packet)] = packet
        else:
            self.fail(
                "dirty ReadUnique did not quiesce within 1024 microsteps"
            )

        packets = tuple(packet_by_identity.values())
        message_counts = Counter(type(packet.message) for packet in packets)
        self.assertEqual(1, message_counts[ChiReadUniqueMessage])
        self.assertEqual(1, message_counts[ChiSnpUniqueMessage])
        self.assertEqual(1, message_counts[ChiSnpRespDataMessage])
        self.assertEqual(1, message_counts[ChiCompDataMessage])
        self.assertEqual(1, message_counts[ChiCompAckMessage])
        self.assertEqual(5, len(packets))

        snoop_data = next(
            packet.message
            for packet in packets
            if isinstance(packet.message, ChiSnpRespDataMessage)
        )
        completion = next(
            packet.message
            for packet in packets
            if isinstance(packet.message, ChiCompDataMessage)
        )
        self.assertEqual(ChiRespCode.I_PD, snoop_data.response)
        self.assertEqual(dirty_data, snoop_data.data)
        self.assertEqual(ChiRespCode.UD_PD, completion.response)
        self.assertEqual(dirty_data, completion.data)

        final_line = state.coherence.request_nodes[
            self.REQUESTER
        ].lines[self.ADDRESS]
        self.assertIs(ChiCacheState.UD, final_line.state)
        self.assertEqual(dirty_data, final_line.data)
        entry = state.coherence.home.directory[self.ADDRESS]
        self.assertEqual(self.REQUESTER, entry.unique_owner)
        self.assertEqual(
            self.DATA,
            state.coherence.home.backing.line_at(self.ADDRESS).data,
        )

    def test_writeback_full_closes_req_rsp_dat_through_the_xp(self) -> None:
        resolved = self.build_resolved(writeback=True)
        self.assertTrue(resolved.is_closed)
        evidence = resolved.capabilities.require(
            CHI_FEATURE_DIRTY_WRITEBACK
        )
        self.assertEqual(
            {
                "writeback_request",
                "writeback_dbid_response",
                "writeback_copyback_data",
            },
            set(evidence.flows),
        )
        self.assertEqual(
            {
                ChiChannelKind.REQ: ("rn0_to_xp", "xp_to_hn0"),
                ChiChannelKind.RSP: ("hn0_to_xp", "xp_to_rn0"),
                ChiChannelKind.DAT: ("rn0_to_xp", "xp_to_hn0"),
            },
            {
                flow.channel: flow.connections
                for flow in resolved.flow_projection.flows
            },
        )

        rn_binding = resolved.binding_by_name["rn0"]
        self.assertIs(
            resolved.system.spec.virtual_duts["rn0"],
            rn_binding.dut,
        )
        for channel, direction, expected_port in (
            (
                ChiChannelKind.REQ,
                TransportDirection.TRANSMIT,
                "tx_to_xp",
            ),
            (
                ChiChannelKind.RSP,
                TransportDirection.RECEIVE,
                "rx_from_xp",
            ),
            (
                ChiChannelKind.DAT,
                TransportDirection.TRANSMIT,
                "tx_to_xp",
            ),
        ):
            self.assertEqual(
                (expected_port,),
                tuple(
                    port.name
                    for port in rn_binding.ports_for(channel, direction)
                ),
            )

        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        state = session.initial_state()
        self.assertIs(
            ChiCacheState.UD,
            state.coherence.request_nodes[self.REQUESTER]
            .permissions[self.ADDRESS],
        )
        self.assertEqual(
            self.REQUESTER,
            state.coherence.home.directory[self.ADDRESS].unique_owner,
        )

        events = []
        issued = self.apply(
            session,
            state,
            ChiSubmitWriteBackFull(
                self.REQUESTER,
                ChiWriteBackFullMessage(0x15, self.ADDRESS),
            ),
        )
        state = issued.state
        events.extend(issued.emissions)
        for _ in range(1024):
            if session.is_quiescent(state):
                break
            advanced = self.apply(
                session,
                state,
                ChiAdvanceCoherenceNetwork(),
            )
            state = advanced.state
            events.extend(advanced.emissions)
        else:
            self.fail(
                "WriteBackFull did not quiesce within 1024 microsteps"
            )

        endpoint_events = tuple(
            event
            for event in events
            if event.kind is ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT
        )
        self.assertEqual(3, len(endpoint_events))
        by_message_type = {
            type(event.packet.message): event
            for event in endpoint_events
            if event.packet is not None
        }
        self.assertEqual(
            {
                ChiWriteBackFullMessage,
                ChiCompDBIDRespMessage,
                ChiCopyBackWrDataMessage,
            },
            set(by_message_type),
        )
        request_event = by_message_type[ChiWriteBackFullMessage]
        response_event = by_message_type[ChiCompDBIDRespMessage]
        data_event = by_message_type[ChiCopyBackWrDataMessage]
        assert request_event.packet is not None
        assert response_event.packet is not None
        assert data_event.packet is not None
        self.assertIs(ChiChannelKind.REQ, request_event.packet.channel)
        self.assertIs(ChiChannelKind.RSP, response_event.packet.channel)
        self.assertIs(ChiChannelKind.DAT, data_event.packet.channel)
        self.assertEqual(
            request_event.lineage,
            response_event.lineage[: len(request_event.lineage)],
        )
        self.assertEqual(
            response_event.lineage,
            data_event.lineage[: len(response_event.lineage)],
        )
        self.assertEqual("rn0.issue", request_event.lineage[0])
        self.assertEqual("hn0.accept", request_event.lineage[-1])
        self.assertEqual("rn0.accept", response_event.lineage[-1])
        self.assertEqual("hn0.accept", data_event.lineage[-1])
        route_segments = (
            (
                request_event.lineage,
                ("rn0_to_xp@", "xp_to_hn0@"),
            ),
            (
                response_event.lineage[len(request_event.lineage) :],
                ("hn0_to_xp@", "xp_to_rn0@"),
            ),
            (
                data_event.lineage[len(response_event.lineage) :],
                ("rn0_to_xp@", "xp_to_hn0@"),
            ),
        )
        for lineage, connection_prefixes in route_segments:
            for prefix in connection_prefixes:
                with self.subTest(route_prefix=prefix):
                    self.assertTrue(
                        any(
                            item.startswith(prefix)
                            for item in lineage
                        ),
                        (prefix, lineage),
                    )

        response = response_event.packet.message
        copyback = data_event.packet.message
        assert isinstance(response, ChiCompDBIDRespMessage)
        assert isinstance(copyback, ChiCopyBackWrDataMessage)
        self.assertEqual(0x15, response.transaction_id)
        self.assertEqual(
            response.data_buffer_id,
            copyback.transaction_id,
        )
        self.assertEqual(self.DIRTY_DATA, copyback.data)

        home_state = state.coherence.home
        rn_state = state.coherence.request_nodes[self.REQUESTER]
        entry = home_state.directory[self.ADDRESS]
        self.assertEqual(
            self.DIRTY_DATA,
            home_state.backing.line_at(self.ADDRESS).data,
        )
        self.assertIsNone(entry.unique_owner)
        self.assertFalse(entry.sharers)
        self.assertFalse(home_state.pending_writebacks)
        self.assertEqual(
            (response.data_buffer_id + 1) % (1 << 12),
            home_state.next_data_buffer_id,
        )
        self.assertFalse(rn_state.pending_writebacks)
        self.assertIs(
            ChiCacheState.I,
            rn_state.permissions[self.ADDRESS],
        )
        self.assertNotIn(self.ADDRESS, rn_state.cache.lines)
        self.assertTrue(session.is_quiescent(state))

    def test_mesi_dirty_owner_downgrades_to_two_clean_sharers(self) -> None:
        resolved = self.build_resolved(mesi=True)
        self.assertTrue(resolved.is_closed)
        session = ChiCoherenceNetworkSession.from_resolved(resolved)
        state = session.initial_state()
        dirty_data = (1 << 420) | 0xD175

        dirtied = self.apply(
            session,
            state,
            ChiWriteUniqueCacheLine(
                self.FIRST_SNOOPEE,
                self.ADDRESS,
                dirty_data,
            ),
        )
        state = dirtied.state
        self.assertIs(
            ChiCacheState.UD,
            state.coherence.request_nodes[self.FIRST_SNOOPEE]
            .lines[self.ADDRESS]
            .state,
        )

        packet_by_identity = {}
        issued = self.apply(
            session,
            state,
            ChiSubmitCoherentRead(
                self.REQUESTER,
                ChiReadNotSharedDirtyMessage(0x14, self.ADDRESS),
            ),
        )
        state = issued.state
        for packet in self.packets_from(issued):
            packet_by_identity[id(packet)] = packet

        observed_pending_dirty_responsibility = False
        for _ in range(1024):
            if session.is_quiescent(state):
                break
            advanced = self.apply(
                session,
                state,
                ChiAdvanceCoherenceNetwork(),
            )
            state = advanced.state
            emitted_packets = self.packets_from(advanced)
            for packet in emitted_packets:
                packet_by_identity[id(packet)] = packet
            if any(
                isinstance(packet.message, ChiCompDataMessage)
                for packet in emitted_packets
            ):
                pending = tuple(state.coherence.home.pending.values())
                self.assertEqual(1, len(pending))
                self.assertIsNotNone(pending[0].dirty_result)
                assert pending[0].dirty_result is not None
                self.assertEqual(
                    dirty_data,
                    pending[0].dirty_result.data,
                )
                self.assertIsNotNone(
                    pending[0].prepared_backing_write
                )
                prepared = pending[0].prepared_backing_write
                assert prepared is not None
                self.assertEqual(
                    0,
                    prepared.expected_version,
                )
                self.assertEqual(
                    self.DATA,
                    state.coherence.home.backing.line_at(
                        self.ADDRESS
                    ).data,
                )
                self.assertEqual(
                    0,
                    state.coherence.home.backing.line_at(
                        self.ADDRESS
                    ).version,
                )
                observed_pending_dirty_responsibility = True
        else:
            self.fail(
                "MESI ReadNotSharedDirty did not quiesce within 1024 "
                "microsteps"
            )

        self.assertTrue(observed_pending_dirty_responsibility)
        packets = tuple(packet_by_identity.values())
        message_counts = Counter(type(packet.message) for packet in packets)
        self.assertEqual(1, message_counts[ChiReadNotSharedDirtyMessage])
        self.assertEqual(1, message_counts[ChiSnpNotSharedDirtyMessage])
        self.assertEqual(1, message_counts[ChiSnpRespDataMessage])
        self.assertEqual(1, message_counts[ChiCompDataMessage])
        self.assertEqual(1, message_counts[ChiCompAckMessage])
        self.assertEqual(5, len(packets))

        snoop = next(
            packet.message
            for packet in packets
            if isinstance(packet.message, ChiSnpNotSharedDirtyMessage)
        )
        snoop_data = next(
            packet.message
            for packet in packets
            if isinstance(packet.message, ChiSnpRespDataMessage)
        )
        completion = next(
            packet.message
            for packet in packets
            if isinstance(packet.message, ChiCompDataMessage)
        )
        self.assertTrue(snoop.do_not_go_to_shared_dirty)
        self.assertEqual(ChiRespCode.SC_PD, snoop_data.response)
        self.assertEqual(dirty_data, snoop_data.data)
        self.assertEqual(ChiRespCode.SC, completion.response)
        self.assertEqual(dirty_data, completion.data)

        requester_line = state.coherence.request_nodes[
            self.REQUESTER
        ].lines[self.ADDRESS]
        former_owner_line = state.coherence.request_nodes[
            self.FIRST_SNOOPEE
        ].lines[self.ADDRESS]
        self.assertIs(ChiCacheState.SC, requester_line.state)
        self.assertIs(ChiCacheState.SC, former_owner_line.state)
        self.assertEqual(dirty_data, requester_line.data)
        self.assertEqual(dirty_data, former_owner_line.data)

        entry = state.coherence.home.directory[self.ADDRESS]
        self.assertIsNone(entry.unique_owner)
        self.assertEqual(
            frozenset((self.REQUESTER, self.FIRST_SNOOPEE)),
            entry.sharers,
        )
        self.assertEqual(
            dirty_data,
            state.coherence.home.backing.line_at(self.ADDRESS).data,
        )
        self.assertEqual(
            1,
            state.coherence.home.backing.line_at(self.ADDRESS).version,
        )

    def test_full_line_coherence_rejects_a_narrow_dat_path(self) -> None:
        resolved = self.build_resolved(data_width=256)

        with self.assertRaisesRegex(ValueError, "full 512-bit cache line"):
            ChiCoherenceNetworkSession.from_resolved(resolved)


if __name__ == "__main__":
    unittest.main()

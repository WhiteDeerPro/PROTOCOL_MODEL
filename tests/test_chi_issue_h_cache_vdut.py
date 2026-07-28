from __future__ import annotations

import unittest

from protocol_model.integrations.recipes import (
    attach_chi_issue_h_coherence,
    bind_chi_issue_h_cache_vdut,
    build_chi_issue_h_cache_vdut,
)
from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiCacheLine,
    ChiCacheState,
    ChiRnAcceptSnoop,
    ChiRnIssueCoherentRead,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiNetworkPacket,
    ChiReadSharedMessage,
    ChiSnpSharedMessage,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
)
from protocol_model.system import SystemProtocolBuilder
from protocol_model.virtual_dut import (
    CacheCore,
    CacheLinePayload,
    CacheLineStore,
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHCacheVdutRecipeTest(unittest.TestCase):
    def test_recipe_binds_cache_participant_to_future_ready_chi_ports(
        self,
    ) -> None:
        line = ChiCacheLine(0x8000, ChiCacheState.SC, 0x1234)
        assembly = build_chi_issue_h_cache_vdut(
            "l1d0",
            0x10,
            0x20,
            initial_lines=(line,),
            coherence_transaction_capacity=3,
            clock_domain="core_clk",
            reset_domain="core_reset",
        )

        self.assertEqual("l1d0", assembly.virtual_dut.name)
        self.assertIs(
            assembly.cache_store,
            assembly.participant.cache_store,
        )
        self.assertIs(
            assembly.participant,
            assembly.binding.component,
        )
        self.assertEqual(frozenset((0x10,)), assembly.binding.node_ids)
        self.assertEqual(3, assembly.participant.outstanding_capacity)
        self.assertEqual(
            line,
            assembly.participant.initial_state().lines[0x8000],
        )

        tx = assembly.virtual_dut.port("chi_tx")
        rx = assembly.virtual_dut.port("chi_rx")
        self.assertIs(TransportDirection.TRANSMIT, tx.direction)
        self.assertIs(TransportDirection.RECEIVE, rx.direction)
        self.assertEqual("core_clk", tx.clock_domain)
        self.assertEqual("core_reset", rx.reset_domain)

        self.assertEqual(
            (tx,),
            assembly.binding.ports_for(
                ChiChannelKind.REQ,
                TransportDirection.TRANSMIT,
            ),
        )
        self.assertEqual(
            (tx,),
            assembly.binding.ports_for(
                ChiChannelKind.RSP,
                TransportDirection.TRANSMIT,
            ),
        )
        self.assertEqual(
            (tx,),
            assembly.binding.ports_for(
                ChiChannelKind.DAT,
                TransportDirection.TRANSMIT,
            ),
        )
        self.assertEqual(
            (rx,),
            assembly.binding.ports_for(
                ChiChannelKind.RSP,
                TransportDirection.RECEIVE,
            ),
        )
        self.assertEqual(
            (rx,),
            assembly.binding.ports_for(
                ChiChannelKind.SNP,
                TransportDirection.RECEIVE,
            ),
        )
        self.assertEqual(
            (rx,),
            assembly.binding.ports_for(
                ChiChannelKind.DAT,
                TransportDirection.RECEIVE,
            ),
        )

    def test_explicit_attachment_starts_from_cache_storage(self) -> None:
        store = CacheLineStore(
            "l1d0.lines",
            line_bytes=64,
            initial_lines=(CacheLinePayload(0x8000, 0x1234),),
        )
        core = CacheCore("l1d0.cache", store)
        assembly = attach_chi_issue_h_coherence(
            "l1d0",
            core,
            0x10,
            0x20,
            initial_permissions={0x8000: ChiCacheState.SC},
        )

        self.assertIs(core, assembly.cache_core)
        self.assertIs(core, assembly.participant.cache_core)
        self.assertIs(store, assembly.cache_store)
        state = assembly.participant.initial_state()
        self.assertEqual(0x1234, state.cache.lines[0x8000].data)
        self.assertIs(ChiCacheState.SC, state.permissions[0x8000])

    def test_binder_reuses_one_canonical_virtual_dut_boundary(self) -> None:
        tx = TransportPort(
            "tx_req_rsp",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            TransportDirection.TRANSMIT,
        )
        rx = TransportPort(
            "rx_dat",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            TransportDirection.RECEIVE,
        )
        dut = VirtualDut("rn0", {tx.name: tx, rx.name: rx})
        store = CacheLineStore(
            "rn0.lines",
            line_bytes=64,
            initial_lines=(CacheLinePayload(0x8000, 0x1234),),
        )
        core = CacheCore("rn0.cache", store)
        assembly = bind_chi_issue_h_cache_vdut(
            dut,
            core,
            0x10,
            0x20,
            port_channels={
                "tx_req_rsp": frozenset(
                    (ChiChannelKind.REQ, ChiChannelKind.RSP)
                ),
                "rx_dat": frozenset((ChiChannelKind.DAT,)),
            },
            initial_permissions={0x8000: ChiCacheState.SC},
            participant_name="requester",
            binding_name="rn0",
        )
        system = SystemProtocolBuilder("canonical_cache").add_dut(
            dut
        ).build()

        self.assertIs(dut, assembly.virtual_dut)
        self.assertIs(dut, assembly.facets.dut)
        self.assertIs(dut, assembly.binding.dut)
        self.assertIs(dut, system.virtual_duts["rn0"])
        self.assertIs(core, assembly.cache_core)
        self.assertIs(core, assembly.participant.cache_core)
        self.assertIs(tx, assembly.binding.ports[0].port)
        self.assertIs(rx, assembly.binding.ports[1].port)
        self.assertEqual("requester", assembly.participant.name)
        self.assertEqual("rn0", assembly.binding.name)

    def test_binder_rejects_non_rn_channel_directions(self) -> None:
        tx = TransportPort(
            "tx",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            TransportDirection.TRANSMIT,
        )
        rx = TransportPort(
            "rx",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            TransportDirection.RECEIVE,
        )
        dut = VirtualDut("rn0", {tx.name: tx, rx.name: rx})

        with self.subTest("REQ is not received by an RN"):
            with self.assertRaisesRegex(ValueError, "cannot receive REQ"):
                bind_chi_issue_h_cache_lines(
                    dut,
                    0x10,
                    0x20,
                    port_channels={
                        "rx": frozenset((ChiChannelKind.REQ,))
                    },
                )
        with self.subTest("SNP is not transmitted by an RN"):
            with self.assertRaisesRegex(ValueError, "cannot transmit SNP"):
                bind_chi_issue_h_cache_lines(
                    dut,
                    0x10,
                    0x20,
                    port_channels={
                        "tx": frozenset((ChiChannelKind.SNP,))
                    },
                )

    def test_line_convenience_requires_an_existing_virtual_dut(self) -> None:
        with self.assertRaisesRegex(TypeError, "existing VirtualDut"):
            bind_chi_issue_h_cache_lines(  # type: ignore[arg-type]
                object(),
                0x10,
                0x20,
                port_channels={
                    "tx": frozenset((ChiChannelKind.REQ,))
                },
            )

    def test_first_transient_policy_reserves_one_local_line(self) -> None:
        assembly = build_chi_issue_h_cache_vdut("l1d0", 0x10, 0x20)
        node = assembly.participant
        address = 0x8000

        first = node.step(
            node.initial_state(),
            ChiRnIssueCoherentRead(
                ChiReadSharedMessage(1, address),
            ),
        )
        self.assertIsNone(first.fault)
        self.assertIsNone(first.blocked)

        same_line = node.step(
            first.state,
            ChiRnIssueCoherentRead(
                ChiReadSharedMessage(2, address),
            ),
        )
        self.assertIsNone(same_line.fault)
        self.assertIsNotNone(same_line.blocked)
        self.assertIn("reserves this cache line", same_line.blocked.reason)

        snoop = node.step(
            first.state,
            ChiRnAcceptSnoop(
                ChiNetworkPacket.snoop(
                    ChiSnpSharedMessage(3, address),
                    source_id=0x20,
                    target_id=0x10,
                )
            ),
        )
        self.assertIsNone(snoop.fault)
        self.assertIsNotNone(snoop.blocked)
        self.assertIn("defers the Snoop", snoop.blocked.reason)


if __name__ == "__main__":
    unittest.main()

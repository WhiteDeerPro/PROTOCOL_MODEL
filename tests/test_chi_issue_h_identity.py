from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiReadNoSnpDirectLedger,
    ChiReadNoSnpDirectProfile,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiBehaviorFacet,
    ChiExactNodeRoute,
    ChiFacetKind,
    ChiParticipantBinding,
    ChiParticipantPortBinding,
    ChiStoreForwardRouterNode,
    ChiVirtualDutFacets,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    ChiIdentityIssueCode,
    ChiIdentityResolutionError,
    resolve_chi_node_identities,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
)
from protocol_model.system import SystemProtocolBuilder, VirtualDutPortRef
from protocol_model.virtual_dut.boundary import (
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHIdentityClosureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dut = VirtualDut(
            "combo",
            {
                "tx": self._port("tx", TransportDirection.TRANSMIT),
                "rx": self._port("rx", TransportDirection.RECEIVE),
            },
        )
        peer = VirtualDut(
            "peer",
            {
                "tx": self._port("tx", TransportDirection.TRANSMIT),
                "rx": self._port("rx", TransportDirection.RECEIVE),
            },
        )
        builder = SystemProtocolBuilder("identity_topology")
        builder.add_dut(self.dut).add_dut(peer)
        builder.connect_transport(
            "combo_to_peer",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("combo", "tx"),
            VirtualDutPortRef("peer", "rx"),
        )
        builder.connect_transport(
            "peer_to_combo",
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef("peer", "tx"),
            VirtualDutPortRef("combo", "rx"),
        )
        self.system = builder.build().elaborate()
        profile = ChiReadNoSnpDirectProfile(0x07, 0x21)
        self.transaction_component = ChiReadNoSnpDirectLedger(
            "combo.transactions", profile
        )
        self.forwarding_component = ChiStoreForwardRouterNode(
            "combo.forwarding",
            ingress_ports=("rx",),
            egress_ports=("tx",),
            routes=(
                ChiExactNodeRoute(
                    0x21,
                    "tx",
                    frozenset((ChiChannelKind.REQ,)),
                ),
            ),
        )

    @staticmethod
    def _port(
        name: str, direction: TransportDirection
    ) -> TransportPort:
        return TransportPort(
            name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            direction,
        )

    def _binding(
        self,
        name: str,
        *,
        forwarding: bool = False,
        node_ids: frozenset[int] = frozenset(),
    ) -> ChiParticipantBinding:
        component = (
            self.forwarding_component
            if forwarding
            else self.transaction_component
        )
        return ChiParticipantBinding(
            name,
            self.dut,
            component,
            (
                ChiParticipantPortBinding(
                    self.dut.port("tx"),
                    frozenset((ChiChannelKind.REQ,)),
                ),
                ChiParticipantPortBinding(
                    self.dut.port("rx"),
                    frozenset((ChiChannelKind.REQ,)),
                ),
            ),
            node_ids,
        )

    def _facet(
        self,
        name: str,
        kind: ChiFacetKind,
        node_ids: frozenset[int],
        *,
        identity_ports: frozenset[str] | None = None,
        share_group: str | None = None,
    ) -> ChiBehaviorFacet:
        return ChiBehaviorFacet.from_binding(
            self._binding(
                name,
                forwarding=kind is ChiFacetKind.FORWARDING,
                node_ids=node_ids,
            ),
            kind,
            identity_ports=identity_ports,
            share_group=share_group,
        )

    def test_facets_compose_without_replacing_runtime_binding(self) -> None:
        transaction = self._facet(
            "transactions", ChiFacetKind.TRANSACTION, frozenset((0x07,))
        )
        forwarding = self._facet(
            "forwarding", ChiFacetKind.FORWARDING, frozenset()
        )

        composition = ChiVirtualDutFacets(
            self.dut, (transaction, forwarding)
        )

        self.assertIs(
            transaction.as_participant_binding(), transaction.binding
        )
        self.assertEqual(
            composition.of_kind(ChiFacetKind.FORWARDING), (forwarding,)
        )

    def test_unique_identity_closes_to_immutable_owner_plan(self) -> None:
        transaction = self._facet(
            "transactions", ChiFacetKind.TRANSACTION, frozenset((0x07,))
        )

        plan = resolve_chi_node_identities(self.system, (transaction,))

        self.assertTrue(plan.is_closed)
        self.assertEqual(plan.owner_by_node_id[0x07].dut, "combo")
        self.assertEqual(
            tuple(
                port.qualified_name
                for port in plan.owner_by_node_id[0x07].ports
            ),
            ("combo.rx", "combo.tx"),
        )
        with self.assertRaises(TypeError):
            plan.owner_by_node_id[0x08] = plan.owner_by_node_id[0x07]

    def test_same_named_clone_is_not_the_canonical_topology_dut(self) -> None:
        clone = VirtualDut(
            self.dut.name,
            {
                "tx": self._port("tx", TransportDirection.TRANSMIT),
                "rx": self._port("rx", TransportDirection.RECEIVE),
            },
        )
        binding = ChiParticipantBinding(
            "transactions",
            clone,
            self.transaction_component,
            (
                ChiParticipantPortBinding(
                    clone.port("tx"),
                    frozenset((ChiChannelKind.REQ,)),
                ),
                ChiParticipantPortBinding(
                    clone.port("rx"),
                    frozenset((ChiChannelKind.REQ,)),
                ),
            ),
            frozenset((0x07,)),
        )

        plan = resolve_chi_node_identities(
            self.system,
            (
                ChiBehaviorFacet.from_binding(
                    binding,
                    ChiFacetKind.TRANSACTION,
                ),
            ),
        )

        self.assertEqual(
            tuple(issue.code for issue in plan.errors),
            (ChiIdentityIssueCode.NONCANONICAL_DUT,),
        )
        self.assertNotIn(0x07, plan.owner_by_node_id)

    def test_transaction_identity_gap_is_structured(self) -> None:
        transaction = self._facet(
            "transactions", ChiFacetKind.TRANSACTION, frozenset()
        )
        forwarding = self._facet(
            "forwarding", ChiFacetKind.FORWARDING, frozenset()
        )

        plan = resolve_chi_node_identities(
            self.system, (transaction, forwarding)
        )

        self.assertEqual(
            tuple(issue.code for issue in plan.gaps),
            (ChiIdentityIssueCode.MISSING_PARTICIPANT_IDENTITY,),
        )
        self.assertFalse(plan.errors)
        with self.assertRaises(ChiIdentityResolutionError) as caught:
            plan.require_closed()
        self.assertEqual(caught.exception.issues, plan.issues)

    def test_duplicate_identity_is_ambiguous_by_default(self) -> None:
        transaction = self._facet(
            "transactions", ChiFacetKind.TRANSACTION, frozenset((0x07,))
        )
        forwarding = self._facet(
            "forwarding",
            ChiFacetKind.FORWARDING,
            frozenset((0x07,)),
        )

        plan = resolve_chi_node_identities(
            self.system, (transaction, forwarding)
        )

        self.assertNotIn(0x07, plan.owner_by_node_id)
        self.assertEqual(
            tuple(issue.code for issue in plan.errors),
            (ChiIdentityIssueCode.AMBIGUOUS_NODE_ID,),
        )

    def test_explicit_same_boundary_identity_sharing_is_resolved(self) -> None:
        transaction = self._facet(
            "transactions",
            ChiFacetKind.TRANSACTION,
            frozenset((0x07,)),
            share_group="combo-node",
        )
        forwarding = self._facet(
            "forwarding",
            ChiFacetKind.FORWARDING,
            frozenset((0x07,)),
            share_group="combo-node",
        )

        plan = resolve_chi_node_identities(
            self.system, (transaction, forwarding)
        )

        owner = plan.owner_by_node_id[0x07]
        self.assertTrue(plan.is_closed)
        self.assertTrue(owner.shared)
        self.assertEqual(owner.share_group, "combo-node")
        self.assertEqual(
            owner.facets, ("combo:forwarding", "combo:transactions")
        )

    def test_shared_identity_requires_the_exact_same_port_boundary(self) -> None:
        transaction = self._facet(
            "transactions",
            ChiFacetKind.TRANSACTION,
            frozenset((0x07,)),
            identity_ports=frozenset(("tx",)),
            share_group="combo-node",
        )
        forwarding = self._facet(
            "forwarding",
            ChiFacetKind.FORWARDING,
            frozenset((0x07,)),
            identity_ports=frozenset(("rx",)),
            share_group="combo-node",
        )

        plan = resolve_chi_node_identities(
            self.system, (transaction, forwarding)
        )

        self.assertEqual(
            tuple(issue.code for issue in plan.errors),
            (ChiIdentityIssueCode.INVALID_SHARED_NODE_ID,),
        )
        self.assertNotIn(0x07, plan.owner_by_node_id)


if __name__ == "__main__":
    unittest.main()

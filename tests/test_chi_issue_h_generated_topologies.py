"""Contracts for the public caller-built CHI topology-shape assemblies."""

from __future__ import annotations

from collections.abc import Mapping
import unittest

from showcase.demos.system.chi_issue_h_topology_shapes.model import (
    GeneratedTopologyAssembly,
    build_four_by_four_mesh,
    build_heterogeneous_ring_star,
    execute_topology_read,
)


class ChiIssueHGeneratedTopologyTest(unittest.TestCase):
    def assert_topology_counts(
        self,
        result: Mapping[str, object],
        *,
        router_count: int,
        endpoint_count: int,
        physical_edge_count: int,
        backbone_count: int,
        total_hop_count: int,
        exact_route_count: int,
    ) -> None:
        topology = result["topology"]
        self.assertEqual(router_count, topology["router_count"])
        self.assertEqual(endpoint_count, topology["endpoint_count"])
        self.assertEqual(
            router_count + endpoint_count,
            topology["virtual_dut_count"],
        )
        self.assertEqual(
            physical_edge_count,
            topology["physical_backbone_edge_count"],
        )
        self.assertEqual(
            backbone_count,
            topology["directed_backbone_hop_count"],
        )
        self.assertEqual(
            endpoint_count * 2,
            topology["directed_endpoint_hop_count"],
        )
        self.assertEqual(total_hop_count, topology["directed_hop_count"])
        self.assertEqual(exact_route_count, topology["exact_route_count"])

    def assert_exact_routes(
        self,
        assembly: GeneratedTopologyAssembly,
    ) -> None:
        expected_ids = {
            endpoint.node_id for endpoint in assembly.endpoints
        }
        for router_name, router in assembly.routers.items():
            routes = {route.target_id: route for route in router.routes}
            self.assertEqual(expected_ids, set(routes))
            for endpoint in assembly.endpoints:
                route = routes[endpoint.node_id]
                self.assertEqual(
                    assembly.expected_egress(router_name, endpoint),
                    route.egress_port,
                )
                self.assertEqual(endpoint.rx_channels, route.channels)

    def assert_passes_and_quiesces(
        self,
        result: Mapping[str, object],
    ) -> None:
        self.assertEqual("PASS", result["verdict"])
        self.assertEqual(0x5300_4020, result["transaction"]["response"]["data"])
        self.assertTrue(all(result["assertions"].values()))
        self.assertTrue(result["assertions"]["session_is_quiescent"])

    def test_nonuniform_ring_resolves_exact_routes_and_runs(self) -> None:
        assembly = build_heterogeneous_ring_star()
        result = execute_topology_read(assembly)

        self.assert_topology_counts(
            result,
            router_count=4,
            endpoint_count=4,
            physical_edge_count=4,
            backbone_count=8,
            total_hop_count=16,
            exact_route_count=16,
        )
        self.assert_exact_routes(assembly)
        r1_ports = set(
            assembly.elaborated.spec.virtual_duts["r1"].ports
        )
        self.assertTrue(
            {
                "rx_local_leaf_a",
                "tx_local_leaf_a",
                "rx_local_leaf_b",
                "tx_local_leaf_b",
            }
            <= r1_ports
        )
        r3_ports = assembly.elaborated.spec.virtual_duts["r3"].ports
        self.assertFalse(any("local" in name for name in r3_ports))
        self.assertEqual(
            (
                "rn_to_r0",
                "r0_to_r1",
                "r1_to_r2",
                "r2_to_hn",
            ),
            result["transaction"]["request_route"],
        )
        self.assertEqual(
            (
                "hn_to_r2",
                "r2_to_r3",
                "r3_to_r0",
                "r0_to_rn",
            ),
            result["transaction"]["data_route"],
        )
        self.assert_passes_and_quiesces(result)

    def test_four_by_four_mesh_runs_corner_read(self) -> None:
        assembly = build_four_by_four_mesh()
        result = execute_topology_read(assembly)

        self.assert_topology_counts(
            result,
            router_count=16,
            endpoint_count=4,
            physical_edge_count=24,
            backbone_count=48,
            total_hop_count=56,
            exact_route_count=64,
        )
        self.assert_exact_routes(assembly)
        self.assertEqual(
            (
                "rn_to_r00",
                "r00_to_r10",
                "r10_to_r20",
                "r20_to_r30",
                "r30_to_r31",
                "r31_to_r32",
                "r32_to_r33",
                "r33_to_hn",
            ),
            result["transaction"]["request_route"],
        )
        self.assertEqual(
            (
                "hn_to_r33",
                "r33_to_r23",
                "r23_to_r13",
                "r13_to_r03",
                "r03_to_r02",
                "r02_to_r01",
                "r01_to_r00",
                "r00_to_rn",
            ),
            result["transaction"]["data_route"],
        )
        self.assertEqual(8, len(result["transaction"]["request_route"]))
        self.assertEqual(8, len(result["transaction"]["data_route"]))
        self.assert_passes_and_quiesces(result)


if __name__ == "__main__":
    unittest.main()

"""Explicit ownership and execution manifests for the unittest suite.

Lifecycle status and execution scope are deliberately separate:

* active tests are maintained evidence;
* legacy sentinels protect a named migration boundary;
* smoke, target, integration, and release are overlapping execution views.

Keep these tuples explicit.  Runtime import scanning is useful for auditing,
but it must not silently decide which regression evidence is in scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import unittest
from collections.abc import Iterable, Iterator


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TESTS_ROOT = REPOSITORY_ROOT / "tests"


CHI_MODULES = (
    "tests.test_chi_issue_h_address_home",
    "tests.test_chi_issue_h_cache_vdut",
    "tests.test_chi_issue_h_capability",
    "tests.test_chi_issue_h_coherence_authority",
    "tests.test_chi_issue_h_coherence_network",
    "tests.test_chi_issue_h_coherence_representation",
    "tests.test_chi_issue_h_dat_transport",
    "tests.test_chi_issue_h_data_path",
    "tests.test_chi_issue_h_direct_read_path",
    "tests.test_chi_issue_h_dirty_unique_coherence",
    "tests.test_chi_issue_h_identity",
    "tests.test_chi_issue_h_logical_fields",
    "tests.test_chi_issue_h_path",
    "tests.test_chi_issue_h_read_no_snp",
    "tests.test_chi_issue_h_read_shared_coherence",
    "tests.test_chi_issue_h_read_unique_coherence",
    "tests.test_chi_issue_h_representation_domain",
    "tests.test_chi_issue_h_representation_layers",
    "tests.test_chi_issue_h_resolved_coherence",
    "tests.test_chi_issue_h_retry",
    "tests.test_chi_issue_h_retry_system",
    "tests.test_chi_issue_h_router",
    "tests.test_chi_issue_h_rsp_transport",
    "tests.test_chi_issue_h_showcase_resources",
    "tests.test_chi_issue_h_snp_network",
    "tests.test_chi_issue_h_snp_transport",
    "tests.test_chi_issue_h_transport",
    "tests.test_chi_issue_h_transport_connection",
    "tests.test_chi_issue_h_transport_domain",
    "tests.test_chi_issue_h_transport_network",
    "tests.test_chi_issue_h_writeback_lifecycle",
    "tests.test_chi_issue_h_writeback_representation",
)

VIRTUAL_DUT_MODULES = (
    "tests.test_virtual_dut_address_space",
    "tests.test_virtual_dut_ahb_attachment",
    "tests.test_virtual_dut_amba_serial_bridges",
    "tests.test_virtual_dut_apb_attachment",
    "tests.test_virtual_dut_apb_fabric",
    "tests.test_virtual_dut_arbitration",
    "tests.test_virtual_dut_axi4_ahb_bridge",
    "tests.test_virtual_dut_axi4_apb_bridge",
    "tests.test_virtual_dut_axi4_attachment",
    "tests.test_virtual_dut_axi4_lite_apb_bridge",
    "tests.test_virtual_dut_axi4_lite_attachment",
    "tests.test_virtual_dut_axi4_lite_crossbar",
    "tests.test_virtual_dut_axi4_read_crossbar",
    "tests.test_virtual_dut_axi4_read_demux",
    "tests.test_virtual_dut_axi4_stepped_response",
    "tests.test_virtual_dut_axi4_stream_attachment",
    "tests.test_virtual_dut_axi4_write_crossbar",
    "tests.test_virtual_dut_binding",
    "tests.test_virtual_dut_cache_store",
    "tests.test_virtual_dut_empty_endpoints",
    "tests.test_virtual_dut_interrupt_controller",
    "tests.test_virtual_dut_memory_copy",
    "tests.test_virtual_dut_queued_address_responder",
    "tests.test_virtual_dut_recipe_catalog",
    "tests.test_virtual_dut_sensor_fifo",
    "tests.test_virtual_dut_translation",
    "tests.test_virtual_dut_translation_address",
    "tests.test_virtual_dut_visualization",
)

INTERFACE_MODULES = (
    "tests.test_ace_lite_interface",
    "tests.test_ahb_interface",
    "tests.test_apb_interface",
    "tests.test_async_four_phase",
    "tests.test_axi4_exclusive",
    "tests.test_axi4_interface",
    "tests.test_axi4_lite",
    "tests.test_axi4_narrow",
    "tests.test_axi4_observation",
    "tests.test_axi4_stream",
    "tests.test_observation",
    "tests.test_quiet",
)

SYSTEM_MODULES = (
    "tests.test_capacity_admission",
    "tests.test_random_traffic_controller",
    "tests.test_system_address_resolution",
    "tests.test_system_protocol",
    "tests.test_transport_topology_values",
)

E2E_MODULES = (
    "tests.test_amba_bridge_chain",
    "tests.test_system_sensor_dma",
)

ARCHITECTURE_MODULES = (
    "tests.test_artifacts",
    "tests.test_causal_graph",
    "tests.test_source_architecture",
    "tests.test_suite_manifest",
    "tests.test_visualization_interconnect",
)

CLASSIFIED_MODULES = (
    *CHI_MODULES,
    *VIRTUAL_DUT_MODULES,
    *INTERFACE_MODULES,
    *SYSTEM_MODULES,
    *E2E_MODULES,
    *ARCHITECTURE_MODULES,
)


SMOKE_MODULES = (
    "tests.test_observation",
    "tests.test_axi4_interface",
    "tests.test_virtual_dut_translation",
    "tests.test_system_protocol",
    "tests.test_chi_issue_h_coherence_authority",
    "tests.test_chi_issue_h_transport_connection",
    "tests.test_chi_issue_h_resolved_coherence",
    "tests.test_virtual_dut_recipe_catalog",
)

# This is an explicit, reviewable projection of tests that combine a concrete
# protocol family with SystemProtocol construction/runtime.  Do not derive it
# dynamically from imports during normal test execution.
INTEGRATION_MODULES = (
    "tests.test_amba_bridge_chain",
    "tests.test_chi_issue_h_capability",
    "tests.test_chi_issue_h_coherence_authority",
    "tests.test_chi_issue_h_coherence_network",
    "tests.test_chi_issue_h_identity",
    "tests.test_chi_issue_h_resolved_coherence",
    "tests.test_chi_issue_h_retry_system",
    "tests.test_chi_issue_h_snp_network",
    "tests.test_chi_issue_h_transport_connection",
    "tests.test_chi_issue_h_transport_network",
    "tests.test_random_traffic_controller",
    "tests.test_system_sensor_dma",
    "tests.test_virtual_dut_ahb_attachment",
    "tests.test_virtual_dut_amba_serial_bridges",
    "tests.test_virtual_dut_apb_attachment",
    "tests.test_virtual_dut_apb_fabric",
    "tests.test_virtual_dut_axi4_ahb_bridge",
    "tests.test_virtual_dut_axi4_apb_bridge",
    "tests.test_virtual_dut_axi4_attachment",
    "tests.test_virtual_dut_axi4_lite_apb_bridge",
    "tests.test_virtual_dut_axi4_lite_attachment",
    "tests.test_virtual_dut_axi4_lite_crossbar",
    "tests.test_virtual_dut_axi4_read_crossbar",
    "tests.test_virtual_dut_axi4_read_demux",
    "tests.test_virtual_dut_axi4_stepped_response",
    "tests.test_virtual_dut_axi4_stream_attachment",
    "tests.test_virtual_dut_axi4_write_crossbar",
    "tests.test_virtual_dut_empty_endpoints",
    "tests.test_virtual_dut_interrupt_controller",
    "tests.test_virtual_dut_queued_address_responder",
    "tests.test_virtual_dut_visualization",
    "tests.test_visualization_interconnect",
)


TARGET_MODULES = {
    "chi": CHI_MODULES,
    "virtual-dut": VIRTUAL_DUT_MODULES,
    "interfaces": INTERFACE_MODULES,
    "system": SYSTEM_MODULES,
    "architecture": ARCHITECTURE_MODULES,
    "e2e": E2E_MODULES,
    "integration": INTEGRATION_MODULES,
}


@dataclass(frozen=True)
class LegacySentinel:
    test_id: str
    owner: str
    reason: str
    removal_condition: str


LEGACY_SENTINELS = (
    LegacySentinel(
        test_id=(
            "tests.test_system_address_resolution.SystemAddressResolutionTest."
            "test_topology_types_remain_reexported_from_the_public_facade"
        ),
        owner="system topology facade migration",
        reason=(
            "The public protocol_model.system.protocol facade remains supported "
            "while topology ownership is migrated."
        ),
        removal_condition=(
            "Remove this sentinel together with the documented facade re-export; "
            "do not preserve it through another compatibility layer."
        ),
    ),
)


@dataclass(frozen=True)
class LimitationNegative:
    test_id: str
    turn_positive_when: str


# These remain active tests.  The metadata prevents a current implementation
# gap from quietly becoming a permanent architectural prohibition.
LIMITATION_NEGATIVES = (
    LimitationNegative(
        test_id=(
            "tests.test_chi_issue_h_address_home.ChiIssueHAddressHomeTest."
            "test_unmodeled_sideband_is_rejected_without_accepting_request"
        ),
        turn_positive_when="the direct Home profile lowers the modeled MemAttr values",
    ),
    LimitationNegative(
        test_id=(
            "tests.test_chi_issue_h_address_home.ChiIssueHAddressHomeTest."
            "test_narrow_read_is_outside_first_address_home_profile"
        ),
        turn_positive_when="narrow DAT placement is implemented for the Home participant",
    ),
    LimitationNegative(
        test_id=(
            "tests.test_chi_issue_h_address_home.ChiIssueHAddressHomeTest."
            "test_decode_error_waits_for_a_future_chi_error_mapping"
        ),
        turn_positive_when="AddressTarget failures map to typed CHI error completions",
    ),
    LimitationNegative(
        test_id=(
            "tests.test_chi_issue_h_read_no_snp."
            "ChiIssueHReadNoSnpLifecycleTest."
            "test_request_crossing_one_dat_chunk_is_outside_subset"
        ),
        turn_positive_when="multi-packet DAT splitting and reassembly are implemented",
    ),
    LimitationNegative(
        test_id=(
            "tests.test_chi_issue_h_dirty_unique_coherence."
            "ChiIssueHDirtyUniqueCoherenceTest."
            "test_read_shared_waits_for_a_dirty_shared_policy"
        ),
        turn_positive_when="the dirty-shared transition policy is explicitly modeled",
    ),
)


def iter_tests(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_tests(item)
        else:
            yield item


def suite_ids(suite: unittest.TestSuite) -> tuple[str, ...]:
    return tuple(test.id() for test in iter_tests(suite))


def load_modules(
    loader: unittest.TestLoader,
    modules: Iterable[str],
    *,
    excluded_ids: frozenset[str] = frozenset(),
) -> unittest.TestSuite:
    loaded = loader.loadTestsFromNames(tuple(modules))
    return unittest.TestSuite(
        test for test in iter_tests(loaded) if test.id() not in excluded_ids
    )


def discover_all(loader: unittest.TestLoader) -> unittest.TestSuite:
    return loader.discover(
        start_dir=str(TESTS_ROOT),
        pattern="test_*.py",
        top_level_dir=str(REPOSITORY_ROOT),
    )


def legacy_sentinel_ids() -> frozenset[str]:
    return frozenset(item.test_id for item in LEGACY_SENTINELS)


def active_suite(loader: unittest.TestLoader) -> unittest.TestSuite:
    return load_modules(
        loader,
        CLASSIFIED_MODULES,
        excluded_ids=legacy_sentinel_ids(),
    )


def smoke_suite(loader: unittest.TestLoader) -> unittest.TestSuite:
    return load_modules(
        loader,
        SMOKE_MODULES,
        excluded_ids=legacy_sentinel_ids(),
    )


def integration_suite(loader: unittest.TestLoader) -> unittest.TestSuite:
    return load_modules(
        loader,
        INTEGRATION_MODULES,
        excluded_ids=legacy_sentinel_ids(),
    )


def target_suite(
    loader: unittest.TestLoader,
    target: str,
) -> unittest.TestSuite:
    try:
        modules = TARGET_MODULES[target]
    except KeyError as error:
        supported = ", ".join(sorted(TARGET_MODULES))
        raise ValueError(
            f"unknown test target {target!r}; expected one of: {supported}"
        ) from error
    return load_modules(
        loader,
        modules,
        excluded_ids=legacy_sentinel_ids(),
    )


def sentinel_suite(loader: unittest.TestLoader) -> unittest.TestSuite:
    return loader.loadTestsFromNames(
        tuple(item.test_id for item in LEGACY_SENTINELS)
    )


def release_suite(loader: unittest.TestLoader) -> unittest.TestSuite:
    return discover_all(loader)

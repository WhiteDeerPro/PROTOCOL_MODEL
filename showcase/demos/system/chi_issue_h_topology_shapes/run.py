#!/usr/bin/env python3
"""Publish two independent CHI Issue H topology witnesses."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory


if sys.version_info < (3, 10):
    raise SystemExit("this demo requires Python 3.10 or newer")


DEMO_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = DEMO_DIRECTORY.parents[3]
SHOWCASE_ROOT = REPOSITORY_ROOT / "showcase"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from model import (  # noqa: E402
    MESH_CASE,
    RING_CASE,
    GeneratedTopologyAssembly,
    execute_four_by_four_mesh,
    execute_heterogeneous_ring_star,
)
from presentation import (  # noqa: E402
    four_by_four_mesh_dot,
    guide,
    heterogeneous_ring_star_dot,
)
from protocol_model import __version__  # noqa: E402
from protocol_model.artifacts import RunArtifactStore  # noqa: E402
from protocol_model.visualization import (  # noqa: E402
    GraphvizRenderer,
    VisualizationPublisher,
)


LEGACY_DEMO_NAME = "chi-issue-h-topology-shapes"
PUBLICATION_NAMES = {
    RING_CASE: "chi-issue-h-heterogeneous-ring-star",
    MESH_CASE: "chi-issue-h-four-by-four-mesh",
}


def _require_renderers() -> None:
    if shutil.which("neato") is None:
        raise SystemExit("Missing renderer dependency: Graphviz 'neato'")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _case_details(
    case: str,
) -> tuple[
    str,
    str,
    str,
    str,
    str,
]:
    if case == RING_CASE:
        return (
            "heterogeneous-ring-star",
            (
                "REQ and DAT take opposite halves of a bidirectional ring "
                "while uneven leaf attachments remain explicit"
            ),
            "chi.issue_h.heterogeneous_ring_star_witness",
            (
                "one operation executed over an explicitly elaborated "
                "four-router ring with uneven point-to-point leaf attachment"
            ),
            (
                "ring leaf attachment is not a shared bus or broadcast "
                "medium"
            ),
        )
    if case == MESH_CASE:
        return (
            "four-by-four-mesh",
            (
                "a corner read completes over deterministic routes in a "
                "generated 4x4 bidirectional mesh"
            ),
            "chi.issue_h.four_by_four_mesh_witness",
            (
                "one operation executed over an explicitly elaborated "
                "16-router mesh with deterministic X-then-Y exact routes"
            ),
            (
                "mesh size and route-table closure do not imply broader "
                "opcode or traffic-pattern coverage"
            ),
        )
    raise ValueError(f"unknown topology case {case!r}")


def _topology_dot(
    assembly: GeneratedTopologyAssembly,
    result: Mapping[str, object],
) -> str:
    if assembly.case == RING_CASE:
        return heterogeneous_ring_star_dot(assembly, result)
    if assembly.case == MESH_CASE:
        return four_by_four_mesh_dot(assembly, result)
    raise ValueError(f"unknown topology case {assembly.case!r}")


def _build_publication(
    directory: Path,
    assembly: GeneratedTopologyAssembly,
    result: Mapping[str, object],
) -> Path:
    case = assembly.case
    if result["case"] != case:
        raise ValueError("topology result belongs to another assembly")
    if result["verdict"] != "PASS":
        raise RuntimeError(f"{case} publication requires a PASS execution")

    publication_name = PUBLICATION_NAMES[case]
    (
        artifact_name,
        expected,
        system_identity,
        system_definition,
        topology_boundary,
    ) = _case_details(case)
    store = RunArtifactStore(publication_name, directory)
    publisher = VisualizationPublisher(
        store,
        graphviz=GraphvizRenderer("neato"),
    )
    publisher.render_dot(
        artifact_name,
        _topology_dot(assembly, result),
        kind="system_topology_and_route",
    )
    store.write_json(
        "result.json",
        result,
        kind="scenario_result",
    )
    store.write_text(
        "README.md",
        guide(assembly, result),
        kind="demo_guide",
        media_type="text/markdown",
    )

    topology = _mapping(result.get("topology"))
    provenance_case = {
        "shape": result["shape"],
        "router_count": topology["router_count"],
        "directed_hop_count": topology["directed_hop_count"],
        "exact_route_count": topology["exact_route_count"],
    }
    if case == MESH_CASE:
        provenance_case["route_policy"] = "deterministic X-then-Y"
    store.write_json(
        "provenance.json",
        {
            "schema": "protocol-model.showcase.provenance/v1",
            "demo": publication_name,
            "source": (
                "showcase/demos/system/"
                "chi_issue_h_topology_shapes/run.py"
            ),
            "command": (
                ".venv/bin/python showcase/demos/system/"
                f"chi_issue_h_topology_shapes/run.py --case {case}"
            ),
            "protocol_model_version": __version__,
            "time_basis": (
                "committed semantic microsteps and per-hop transport ticks; "
                "not a physical latency measurement"
            ),
            "router_boundary": (
                "ChiStoreForwardRouterNode is presented as an XP "
                "abstraction with finite ingress, exact NodeID route, "
                "egress, and Link Credit; not a complete XP "
                "microarchitecture or cycle-latency model"
            ),
            "construction": [
                "SystemProtocolBuilder",
                "DirectedTransportConnection",
                "ChiStoreForwardRouterNode",
                "ChiExactNodeRoute",
                "ChiParticipantBinding[requester,home]",
                "ChiReadNoSnpSystemSession",
            ],
            "case": {
                case: provenance_case,
            },
            "renderer": (
                "Graphviz neato; fixed showcase-only positions"
            ),
            "topology_projection": (
                "nodes and directed connections are validated against the "
                "executed SystemProtocol; paired directed hops are folded "
                "into a physical-edge backdrop, then the actual REQ/DAT "
                "routes are overlaid"
            ),
            "presentation_boundary": (
                "model-level topology, exact routes, transaction lineage, "
                "and quiescence; no raw pin waveform or RTL cycle spacing"
            ),
            "model_boundary": (
                "restricted ReadNoSnp/CompData over REQ/DAT; "
                f"{topology_boundary}; no shared-bus arbitration, RSP/SNP "
                "coherence, adaptive routing, complete CHI, performance, "
                "QoS/fairness, or deadlock proof"
            ),
        },
        kind="provenance",
    )

    return store.finalize(
        verdict="PASS",
        protocols=(
            {
                "scope": "interface",
                "identity": "chi.issue_h.restricted_direct_read",
                "definition": (
                    "ReadNoSnp to one correlated CompData completion"
                ),
                "parameters": result["profile"],
            },
            {
                "scope": "transport",
                "identity": (
                    "chi.issue_h.caller_built_exact_route_topology"
                ),
                "definition": (
                    "finite directed REQ/DAT hops and exact-NodeID "
                    "store-forward routers"
                ),
                "parameters": {
                    key: topology[key]
                    for key in (
                        "router_count",
                        "physical_backbone_edge_count",
                        "directed_hop_count",
                        "exact_route_count",
                    )
                },
            },
            {
                "scope": "system",
                "identity": system_identity,
                "definition": system_definition,
                "parameters": {
                    "case": case,
                    "topology_in_protocol_core": False,
                },
            },
        ),
        cases=(
            {
                "name": case,
                "expected": expected,
                "observed": result["verdict"],
            },
        ),
        state={
            "committed_microsteps": result["runtime"][
                "committed_microsteps"
            ],
            "request_route": result["transaction"]["request_route"],
            "data_route": result["transaction"]["data_route"],
            "assertions": result["assertions"],
        },
        metadata={
            "publication": (
                f"showcase/generated/system/{publication_name}"
            ),
            "scope": f"caller_built_chi_{case}_witness",
            "raw_waveform": False,
            "runtime_executable": True,
            "topology_source": "SystemProtocol",
        },
        tool_version=__version__,
    )


def _publish(staged: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.with_name(f".{target.name}.previous")
    if previous.exists():
        shutil.rmtree(previous)
    if target.exists():
        target.replace(previous)
    try:
        staged.replace(target)
    except Exception:
        if previous.exists() and not target.exists():
            previous.replace(target)
        raise
    if previous.exists():
        shutil.rmtree(previous)


def _execute(
    case: str,
) -> tuple[GeneratedTopologyAssembly, dict[str, object]]:
    if case == RING_CASE:
        return execute_heterogeneous_ring_star()
    if case == MESH_CASE:
        return execute_four_by_four_mesh()
    raise ValueError(f"unknown topology case {case!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish-root",
        type=Path,
        default=SHOWCASE_ROOT / "generated" / "system",
        help="parent directory of the two leaf publications",
    )
    parser.add_argument(
        "--case",
        choices=("all", RING_CASE, MESH_CASE),
        default="all",
        help="publish both independent leaves or rebuild one leaf",
    )
    args = parser.parse_args()
    publish_root = args.publish_root.expanduser().resolve()
    publish_root.mkdir(parents=True, exist_ok=True)
    selected = (
        (RING_CASE, MESH_CASE)
        if args.case == "all"
        else (args.case,)
    )
    _require_renderers()
    with TemporaryDirectory(
        prefix=".chi-issue-h-topologies.stage-",
        dir=publish_root,
    ) as temporary:
        stage_root = Path(temporary)
        for case in selected:
            assembly, result = _execute(case)
            staged = stage_root / PUBLICATION_NAMES[case]
            _build_publication(staged, assembly, result)
        for case in selected:
            staged = stage_root / PUBLICATION_NAMES[case]
            _publish(staged, publish_root / PUBLICATION_NAMES[case])

    legacy = publish_root / LEGACY_DEMO_NAME
    if legacy.exists():
        shutil.rmtree(legacy)

    for case in selected:
        target = publish_root / PUBLICATION_NAMES[case]
        print(f"Published CHI Issue H {case}: {target}")
        print(f"Manifest: {target / 'manifest.json'}")


if __name__ == "__main__":
    main()

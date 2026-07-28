#!/usr/bin/env python3
"""Publish the CHI Issue H caller-built topology-shapes showcase."""

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
    execute_topology_shapes,
)
from presentation import (  # noqa: E402
    four_by_four_mesh_dot,
    guide,
    heterogeneous_ring_star_dot,
    route_comparison_dot,
)
from protocol_model import __version__  # noqa: E402
from protocol_model.artifacts import RunArtifactStore  # noqa: E402
from protocol_model.visualization import (  # noqa: E402
    GraphvizRenderer,
    VisualizationPublisher,
)


DEMO_NAME = "chi-issue-h-topology-shapes"


def _require_renderers() -> None:
    missing = tuple(
        executable
        for executable in ("dot", "neato")
        if shutil.which(executable) is None
    )
    if missing:
        joined = ", ".join(f"Graphviz '{item}'" for item in missing)
        raise SystemExit(f"Missing renderer dependency: {joined}")


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _build_publication(directory: Path) -> Path:
    cases = execute_topology_shapes()
    ring_assembly, ring = cases[RING_CASE]
    mesh_assembly, mesh = cases[MESH_CASE]
    if ring["verdict"] != "PASS" or mesh["verdict"] != "PASS":
        raise RuntimeError("topology-shapes publication requires two PASS cases")

    combined_result = {
        "schema": "protocol-model.showcase.chi-topology-shapes/v1",
        "verdict": "PASS",
        "cases": {
            RING_CASE: ring,
            MESH_CASE: mesh,
        },
    }
    store = RunArtifactStore(DEMO_NAME, directory)
    topology_publisher = VisualizationPublisher(
        store,
        graphviz=GraphvizRenderer("neato"),
    )
    diagram_publisher = VisualizationPublisher(
        store,
        graphviz=GraphvizRenderer("dot"),
    )
    topology_publisher.render_dot(
        "heterogeneous-ring-star",
        heterogeneous_ring_star_dot(ring_assembly, ring),
        kind="system_topology_and_route",
    )
    topology_publisher.render_dot(
        "four-by-four-mesh",
        four_by_four_mesh_dot(mesh_assembly, mesh),
        kind="system_topology_and_route",
    )
    diagram_publisher.render_dot(
        "route-comparison",
        route_comparison_dot(cases),
        kind="route_and_scope_comparison",
    )
    store.write_json(
        "result.json",
        combined_result,
        kind="scenario_result",
    )
    store.write_text(
        "README.md",
        guide(cases),
        kind="demo_guide",
        media_type="text/markdown",
    )
    store.write_json(
        "provenance.json",
        {
            "schema": "protocol-model.showcase.provenance/v1",
            "demo": DEMO_NAME,
            "source": (
                "showcase/demos/system/"
                "chi_issue_h_topology_shapes/run.py"
            ),
            "command": (
                ".venv/bin/python showcase/demos/system/"
                "chi_issue_h_topology_shapes/run.py"
            ),
            "protocol_model_version": __version__,
            "time_basis": (
                "committed semantic microsteps and per-hop transport ticks; "
                "not a physical latency measurement"
            ),
            "construction": [
                "SystemProtocolBuilder",
                "DirectedTransportConnection",
                "ChiStoreForwardRouterNode",
                "ChiExactNodeRoute",
                "ChiParticipantBinding[requester,home]",
                "ChiReadNoSnpSystemSession",
            ],
            "cases": {
                RING_CASE: {
                    "shape": ring["shape"],
                    "router_count": ring["topology"]["router_count"],
                    "directed_hop_count": ring["topology"][
                        "directed_hop_count"
                    ],
                    "exact_route_count": ring["topology"][
                        "exact_route_count"
                    ],
                },
                MESH_CASE: {
                    "shape": mesh["shape"],
                    "router_count": mesh["topology"]["router_count"],
                    "directed_hop_count": mesh["topology"][
                        "directed_hop_count"
                    ],
                    "exact_route_count": mesh["topology"][
                        "exact_route_count"
                    ],
                    "route_policy": "deterministic X-then-Y",
                },
            },
            "renderers": {
                "topologies": (
                    "Graphviz neato; fixed showcase-only positions"
                ),
                "comparison": (
                    "Graphviz dot; result-derived route/scope table"
                ),
            },
            "topology_projection": (
                "nodes and directed connections are validated against each "
                "executed SystemProtocol; paired directed hops are folded "
                "into a physical-edge backdrop, then actual REQ/DAT routes "
                "are overlaid"
            ),
            "presentation_boundary": (
                "model-level topology, exact routes, transaction lineage, "
                "and quiescence; no raw pin waveform or RTL cycle spacing"
            ),
            "model_boundary": (
                "restricted ReadNoSnp/CompData over REQ/DAT; ring leaf "
                "attachment is not a shared bus or broadcast medium; no "
                "shared-bus arbitration, RSP/SNP coherence, adaptive "
                "routing, complete CHI, performance, QoS/fairness, or "
                "deadlock proof"
            ),
        },
        kind="provenance",
    )

    ring_topology = _mapping(ring.get("topology"))
    mesh_topology = _mapping(mesh.get("topology"))
    return store.finalize(
        verdict="PASS",
        protocols=(
            {
                "scope": "interface",
                "identity": "chi.issue_h.restricted_direct_read",
                "definition": (
                    "ReadNoSnp to one correlated CompData completion"
                ),
                "parameters": ring["profile"],
            },
            {
                "scope": "transport",
                "identity": "chi.issue_h.caller_built_topology_shapes",
                "definition": (
                    "finite directed REQ/DAT hops and exact-NodeID "
                    "store-forward routers"
                ),
                "parameters": {
                    RING_CASE: {
                        key: ring_topology[key]
                        for key in (
                            "router_count",
                            "physical_backbone_edge_count",
                            "directed_hop_count",
                            "exact_route_count",
                        )
                    },
                    MESH_CASE: {
                        key: mesh_topology[key]
                        for key in (
                            "router_count",
                            "physical_backbone_edge_count",
                            "directed_hop_count",
                            "exact_route_count",
                        )
                    },
                },
            },
            {
                "scope": "system",
                "identity": "chi.issue_h.topology_shape_witnesses",
                "definition": (
                    "one operation executed over two explicitly elaborated "
                    "caller-owned SystemProtocol topologies"
                ),
                "parameters": {
                    "cases": (RING_CASE, MESH_CASE),
                    "topology_in_protocol_core": False,
                },
            },
        ),
        cases=(
            {
                "name": RING_CASE,
                "expected": (
                    "REQ and DAT take opposite halves of a bidirectional "
                    "ring while uneven leaf attachments remain explicit"
                ),
                "observed": ring["verdict"],
            },
            {
                "name": MESH_CASE,
                "expected": (
                    "a corner read completes over deterministic routes in "
                    "a generated 4x4 bidirectional mesh"
                ),
                "observed": mesh["verdict"],
            },
        ),
        state={
            RING_CASE: {
                "committed_microsteps": ring["runtime"][
                    "committed_microsteps"
                ],
                "request_route": ring["transaction"]["request_route"],
                "data_route": ring["transaction"]["data_route"],
                "assertions": ring["assertions"],
            },
            MESH_CASE: {
                "committed_microsteps": mesh["runtime"][
                    "committed_microsteps"
                ],
                "request_route": mesh["transaction"]["request_route"],
                "data_route": mesh["transaction"]["data_route"],
                "assertions": mesh["assertions"],
            },
        },
        metadata={
            "publication": (
                "showcase/generated/system/chi-issue-h-topology-shapes"
            ),
            "scope": "caller_built_chi_topology_shape_witnesses",
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--publish-root",
        type=Path,
        default=SHOWCASE_ROOT / "generated" / "system",
        help="parent directory of the demo publication",
    )
    args = parser.parse_args()
    target = args.publish_root.expanduser().resolve() / DEMO_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    _require_renderers()
    with TemporaryDirectory(
        prefix=f".{target.name}.stage-",
        dir=target.parent,
    ) as temporary:
        staged = Path(temporary) / target.name
        _build_publication(staged)
        _publish(staged, target)
    print(f"Published CHI Issue H topology shapes: {target}")
    print(f"Manifest: {target / 'manifest.json'}")


if __name__ == "__main__":
    main()

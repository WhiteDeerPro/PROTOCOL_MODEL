#!/usr/bin/env python3
"""Publish the CHI Issue H clean ReadUnique 2x2 XP mesh showcase."""

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


from model import execute_clean_mesh  # noqa: E402
from presentation import (  # noqa: E402
    coherence_state_dot,
    guide,
    sequence_dot,
    topology_dot,
)
from protocol_model import __version__  # noqa: E402
from protocol_model.artifacts import RunArtifactStore  # noqa: E402
from protocol_model.visualization import (  # noqa: E402
    GraphvizRenderer,
    VisualizationPublisher,
)


DEMO_NAME = "chi-issue-h-clean-2x2-mesh"


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


def _verdict(result: Mapping[str, object]) -> str:
    run = _mapping(result.get("result"))
    return str(run.get("verdict", result.get("verdict", "PASS")))


def _manifest_state(result: Mapping[str, object]) -> dict[str, object]:
    runtime = _mapping(result.get("runtime"))
    topology = _mapping(result.get("topology"))
    coherence = _mapping(result.get("coherence"))
    packets = result.get("packets")
    return {
        "committed_microsteps": runtime.get("committed_microsteps"),
        "packet_count": (
            len(packets) if isinstance(packets, (tuple, list)) else None
        ),
        "packet_paths": packets,
        "ring_edges_used": topology.get("used_physical_edges"),
        "coherence_before": coherence.get("before"),
        "coherence_after": coherence.get("after"),
        "assertions": result.get("assertions", {}),
    }


def _build_publication(directory: Path) -> Path:
    assembly, result = execute_clean_mesh()
    if not isinstance(result, Mapping):
        raise TypeError("clean-mesh demo result must be a mapping")

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
        "topology",
        topology_dot(assembly, result),
        kind="system_topology",
    )
    diagram_publisher.render_dot(
        "transaction-sequence",
        sequence_dot(result),
        kind="transaction_sequence",
    )
    diagram_publisher.render_dot(
        "coherence-state",
        coherence_state_dot(result),
        kind="coherence_state",
    )
    store.write_json("result.json", result, kind="scenario_result")
    store.write_text(
        "README.md",
        guide(result),
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
                "chi_issue_h_clean_2x2_mesh/run.py"
            ),
            "command": (
                ".venv/bin/python showcase/demos/system/"
                "chi_issue_h_clean_2x2_mesh/run.py"
            ),
            "protocol_model_version": __version__,
            "time_basis": (
                "committed semantic microsteps and per-hop transport ticks"
            ),
            "construction": [
                "SystemProtocolBuilder",
                "DirectedTransportConnection",
                "ChiStoreForwardRouterNode[xp00,xp10,xp11,xp01]",
                "ChiParticipantBinding[requester,home,snoopee]",
                "ChiCoherenceNetworkSession",
                "CleanCoherenceDomain",
            ],
            "topology_projection": (
                "demo projection of the executed SystemProtocol topology; "
                "fixed 2x2 XP positions preserve the visible ring"
            ),
            "renderers": {
                "topology": "Graphviz neato; fixed semantic positions",
                "transaction_sequence": (
                    "Graphviz dot; participant-level causal ordering"
                ),
                "coherence_state": (
                    "Graphviz dot; before/after state projection"
                ),
            },
            "presentation_boundary": (
                "the diagrams project executed packet paths and clean "
                "coherence state transitions; they are not raw pin "
                "waveforms and do not prescribe RTL cycle spacing"
            ),
            "model_boundary": (
                "clean-only I/SC/UC ReadUnique witness on a caller-built "
                "four-XP mesh; no dirty owner, full MESI/MOESI, arbitrary "
                "adaptive routing, QoS/fairness, or deadlock proof"
            ),
        },
        kind="provenance",
    )

    topology = _mapping(result.get("topology"))
    profile = _mapping(result.get("profile"))
    return store.finalize(
        verdict=_verdict(result),
        protocols=(
            {
                "scope": "interface",
                "identity": "chi.issue_h.clean_read_unique",
                "definition": (
                    "clean ReadUnique transaction with correlated SNP, "
                    "RSP, DAT, and CompAck"
                ),
                "parameters": profile,
            },
            {
                "scope": "transport",
                "identity": "chi.issue_h.four_xp_mesh_transport",
                "definition": (
                    "directed, credit-controlled connections forming a "
                    "four-XP square ring"
                ),
                "parameters": {
                    "router_count": 4,
                    "physical_shape": "2x2-square",
                    "channels": ("REQ", "RSP", "SNP", "DAT"),
                },
            },
            {
                "scope": "system",
                "identity": "chi.issue_h.clean_coherence_mesh",
                "definition": (
                    "requester, Home, and two snoopees coordinated across "
                    "an elaborated transport topology"
                ),
                "parameters": topology,
            },
        ),
        cases=(
            {
                "name": "clean-read-unique",
                "expected": (
                    "RN0 acquires the clean unique copy, both previous "
                    "clean sharers become invalid, and all four ring sides "
                    "carry part of the transaction lifecycle"
                ),
                "observed": _verdict(result),
            },
        ),
        state=_manifest_state(result),
        metadata={
            "publication": (
                "showcase/generated/system/chi-issue-h-clean-2x2-mesh"
            ),
            "scope": "clean_read_unique_four_xp_mesh_witness",
            "raw_waveform": False,
            "runtime_executable": True,
            "topology_source": "SystemProtocol",
            "layout": {
                "topology": "fixed semantic positions",
                "sequence": "automatic hierarchical",
                "coherence_state": "automatic hierarchical",
            },
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
        prefix=f".{target.name}.stage-", dir=target.parent
    ) as temporary:
        staged = Path(temporary) / target.name
        _build_publication(staged)
        _publish(staged, target)
    print(f"Published CHI Issue H clean 2x2 mesh demo: {target}")
    print(f"Manifest: {target / 'manifest.json'}")


if __name__ == "__main__":
    main()

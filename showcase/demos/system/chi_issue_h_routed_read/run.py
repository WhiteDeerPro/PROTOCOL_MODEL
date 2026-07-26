#!/usr/bin/env python3
"""Publish the restricted CHI Issue H two-XP routed-read showcase."""

from __future__ import annotations

import argparse
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


from model import execute_routed_read  # noqa: E402
from presentation import guide, lineage_dot, transaction_path_dot  # noqa: E402
from protocol_model import __version__  # noqa: E402
from protocol_model.artifacts import RunArtifactStore  # noqa: E402
from protocol_model.visualization import (  # noqa: E402
    GraphvizRenderer,
    VisualizationPublisher,
    system_topology_dot,
)


DEMO_NAME = "chi-issue-h-routed-read"


def _require_renderer() -> None:
    if shutil.which("dot") is None:
        raise SystemExit("Missing renderer dependency: Graphviz 'dot'")


def _build_publication(directory: Path) -> Path:
    assembly, result = execute_routed_read()
    store = RunArtifactStore("chi-issue-h-routed-read", directory)
    publisher = VisualizationPublisher(
        store, graphviz=GraphvizRenderer("dot")
    )
    publisher.render_dot(
        "topology",
        system_topology_dot(assembly.system),
        kind="system_topology",
    )
    publisher.render_dot(
        "transaction-path",
        transaction_path_dot(result),
        kind="transaction_path",
    )
    publisher.render_dot(
        "lineage",
        lineage_dot(result),
        kind="causal_lineage",
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
                "showcase/demos/system/chi_issue_h_routed_read/run.py"
            ),
            "command": (
                ".venv/bin/python "
                "showcase/demos/system/chi_issue_h_routed_read/run.py"
            ),
            "protocol_model_version": __version__,
            "time_basis": (
                "committed semantic microsteps and per-hop reference ticks"
            ),
            "construction": [
                "SystemProtocolBuilder",
                "DirectedTransportConnection",
                "ChiReadNoSnpDirectLedger",
                "ChiAddressHomeNode",
                "AddressSpace/MemoryRegion AddressTarget",
                "ChiStoreForwardRouterNode[xp0,xp1]",
                "ChiParticipantBinding",
                "ChiReadNoSnpSystemSession",
            ],
            "topology_projection": (
                "protocol_model.visualization.system_topology_dot"
            ),
            "renderer": "Graphviz dot; automatic hierarchical layout",
            "presentation_boundary": (
                "two-XP direct-Home ReadNoSnp witness; single DAT flit; "
                "REQ/DAT-only directed hops; no raw waveform, bit codec, "
                "narrow DAT placement, CHI error-response mapping, "
                "SNP/coherence, complete CHI Port, QoS/fairness, or "
                "deadlock proof"
            ),
            "peripheral_boundary": (
                "CHI Home participant delegates to one protocol-neutral "
                "AddressSpace/MemoryRegion state authority; Sensor FIFO "
                "progress and global address-to-Home authority remain open"
            ),
        },
        kind="provenance",
    )
    return store.finalize(
        verdict=result["result"]["verdict"],
        protocols=(
            {
                "scope": "interface",
                "identity": "chi.issue_h.direct_read",
                "definition": (
                    "restricted ReadNoSnp to one correlated CompData"
                ),
                "parameters": result["profile"],
            },
            {
                "scope": "transport",
                "identity": "chi.issue_h.req_dat_hops",
                "definition": (
                    "six independent, directed, credit-controlled hops"
                ),
                "parameters": {
                    "request_hops": 3,
                    "data_hops": 3,
                    "activation": "per directed connection",
                    "credit_capacity": 1,
                },
            },
            {
                "scope": "system",
                "identity": "chi.issue_h.two_xp_routed_read",
                "definition": (
                    "caller-built topology with exact-NodeID store-forward "
                    "routing and end-to-end transaction completion"
                ),
                "parameters": result["topology"],
            },
        ),
        cases=(
            {
                "name": "sensor-register-read",
                "expected": (
                    "ReadNoSnp crosses XP0 and XP1, then correlated "
                    "CompData returns over the reverse route"
                ),
                "observed": "PASS",
            },
        ),
        state={
            "completed_count": result["result"]["completed_count"],
            "committed_microsteps": result["result"][
                "committed_microsteps"
            ],
            "request_route": result["topology"]["request_route"],
            "data_route": result["topology"]["data_route"],
            "assertions": result["assertions"],
        },
        metadata={
            "publication": (
                "showcase/generated/system/chi-issue-h-routed-read"
            ),
            "scope": "restricted_two_xp_read_no_snp_witness",
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
    _require_renderer()
    with TemporaryDirectory(
        prefix=f".{target.name}.stage-", dir=target.parent
    ) as temporary:
        staged = Path(temporary) / target.name
        _build_publication(staged)
        _publish(staged, target)
    print(f"Published CHI Issue H routed-read demo: {target}")
    print(f"Manifest: {target / 'manifest.json'}")


if __name__ == "__main__":
    main()

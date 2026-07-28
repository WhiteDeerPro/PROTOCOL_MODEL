#!/usr/bin/env python3
"""Publish the executable CHI Issue H transaction-flow gallery."""

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


from protocol_model import __version__  # noqa: E402
from protocol_model.artifacts import RunArtifactStore  # noqa: E402
from protocol_model.visualization import (  # noqa: E402
    VisualizationPublisher,
    transaction_causal_dot,
    transaction_semantic_wavejson,
    transaction_time_space_dot,
)
from showcase.demos.chi.issue_h_flow_gallery.model import (  # noqa: E402
    execute_flow_gallery,
    flow_gallery_result,
)
from showcase.demos.chi.issue_h_flow_gallery.presentation import (  # noqa: E402
    guide,
)
from showcase.demos.chi.issue_h_flow_gallery.topology import (  # noqa: E402
    flow_case_topology_dot,
)


DEMO_NAME = "issue-h-flow-gallery"
PUBLICATION_NAME = "issue-h-flow-gallery"


def _require_renderers() -> None:
    if shutil.which("dot") is None:
        raise SystemExit("Missing renderer dependency: Graphviz 'dot'")
    wavedrom = REPOSITORY_ROOT / "node_modules" / ".bin" / "wavedrom"
    if not wavedrom.is_file():
        raise SystemExit(
            "Missing renderer dependency: run 'npm ci' for WaveDrom"
        )


def _build_publication(directory: Path) -> Path:
    cases = execute_flow_gallery()
    if not cases or not all(case.passed for case in cases.values()):
        raise RuntimeError("CHI flow gallery requires five PASS cases")
    result = flow_gallery_result(cases)
    store = RunArtifactStore(DEMO_NAME, directory)
    publisher = VisualizationPublisher(store)

    for case in cases.values():
        publisher.render_dot(
            "topology",
            flow_case_topology_dot(case),
            kind="resolved_topology",
            case=case.case_id,
        )
        store.write_json(
            "transaction-time-space-view.json",
            case.view.to_dict(),
            kind="transaction_time_space_view_ir",
            case=case.case_id,
            source=True,
        )
        publisher.render_dot(
            "transaction-time-space",
            transaction_time_space_dot(case.view),
            kind="transaction_time_space",
            case=case.case_id,
        )
        publisher.render_dot(
            "causal",
            transaction_causal_dot(case.view),
            kind="explicit_causality",
            case=case.case_id,
        )
        publisher.render_wave(
            "semantic-event-timeline",
            transaction_semantic_wavejson(case.view),
            kind="semantic_event_timeline",
            case=case.case_id,
        )

    store.write_json(
        "result.json",
        result,
        kind="scenario_result",
    )
    store.write_text(
        "README.md",
        guide(cases, result),
        kind="demo_guide",
        media_type="text/markdown",
    )
    store.write_json(
        "provenance.json",
        {
            "schema": "protocol-model.showcase.provenance/v1",
            "demo": DEMO_NAME,
            "source": (
                "showcase/demos/chi/issue_h_flow_gallery/run.py"
            ),
            "command": (
                ".venv/bin/python "
                "showcase/demos/chi/issue_h_flow_gallery/run.py"
            ),
            "protocol_model_version": __version__,
            "case_order": list(cases),
            "execution": {
                "resolved_network_round_robin": [
                    "clean-read-unique-fanout",
                    "dirty-peer-clean-unique",
                    "make-unique-local-intent",
                    "clean-evict-retry",
                ],
                "resolved_network_selected_moves": [
                    "writeback-snoop-cancel"
                ],
            },
            "views": {
                "topology": (
                    "resolved SystemProtocol participant-XP connections "
                    "for all five cases"
                ),
                "transaction-time-space": (
                    "accepted CHI messages and selected participant/Home "
                    "state transitions"
                ),
                "causal": (
                    "explicit packet production, correlation, Snoop join, "
                    "Retry/P-Credit, and same-line cancellation edges"
                ),
                "semantic-event-timeline": (
                    "WaveJSON rendering of the same model_step event refs; "
                    "not pins, cycles, or RTL timing"
                ),
            },
            "source_ir": (
                "typed TransactionTimeSpaceView JSON plus topology/flow/"
                "causal DOT and WaveJSON"
            ),
            "xp_visibility": (
                "all five cases construct and execute one store-forward "
                "XP abstraction; endpoint routes contain two transport "
                "legs and forwarding counters retire every packet, while "
                "per-hop MOVE events remain outside the semantic "
                "time-space projection"
            ),
            "selected_ordering": (
                "the WriteBackFull case holds only its RN0-to-XP REQ "
                "router-capture candidate until CleanUnique retires; this "
                "is model ordering control, not a latency or cycle claim"
            ),
            "reference_boundary": (
                "docs/reviews/chi-injected-flow-digest.md guided case "
                "selection; raw injected images are not publication inputs"
            ),
            "model_boundary": (
                "selected executable Issue H lifecycle witnesses, not a "
                "complete opcode catalog, specification coverage claim, "
                "packed pin/phit model, CDC analysis, or deadlock proof"
            ),
        },
        kind="provenance",
    )
    return store.finalize(
        verdict="PASS",
        protocols=(
            {
                "scope": "interface",
                "identity": "chi.issue_h.selected_flow_lifecycles",
                "definition": (
                    "ReadUnique, CleanUnique, MakeUnique, Evict Retry, and "
                    "WriteBackFull/Snoop cancellation message correlation"
                ),
                "parameters": {
                    "case_count": len(cases),
                    "packed_codec": False,
                },
            },
            {
                "scope": "system",
                "identity": "chi.issue_h.coherence_and_progress_witnesses",
                "definition": (
                    "resolved participant authority and XP routes, including "
                    "one selected-move interference ordering"
                ),
                "parameters": {
                    "resolved_network_cases": 5,
                    "selected_scheduler_cases": 1,
                },
            },
        ),
        cases=tuple(
            {
                "name": case.case_id,
                "expected": case.learning_goal,
                "observed": case.execution.verdict.value,
            }
            for case in cases.values()
        ),
        state={
            case.case_id: {
                "assertions": dict(case.execution.assertions),
                "messages": len(case.view.messages),
                "state_changes": len(case.view.state_changes),
                "causal_edges": len(case.view.causal_edges),
                "operation_refs": sorted(
                    {
                        message.operation_ref
                        for message in case.view.messages
                    }
                ),
            }
            for case in cases.values()
        },
        metadata={
            "publication": (
                "showcase/generated/chi/issue-h-flow-gallery"
            ),
            "runtime_executable": True,
            "time_basis": "model_step",
            "raw_waveform": False,
            "cycle_accurate": False,
            "source_ir_retained": True,
            "topology_projection": True,
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
        default=SHOWCASE_ROOT / "generated" / "chi",
        help="parent directory of the demo publication",
    )
    args = parser.parse_args()
    target = (
        args.publish_root.expanduser().resolve() / PUBLICATION_NAME
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    _require_renderers()
    with TemporaryDirectory(
        prefix=f".{target.name}.stage-",
        dir=target.parent,
    ) as temporary:
        staged = Path(temporary) / target.name
        _build_publication(staged)
        _publish(staged, target)
    print(f"Published CHI Issue H flow gallery: {target}")
    print(f"Manifest: {target / 'manifest.json'}")


if __name__ == "__main__":
    main()

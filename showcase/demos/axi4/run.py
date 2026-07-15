#!/usr/bin/env python3
"""Execute and atomically publish the unified AXI4 example set.

Run from any working directory with Python 3.10 or newer:

    python3 showcase/demos/axi4/run.py

Every case is executed by the repository's current AXI4 component.  This
runner only constructs inputs and projects the resulting evidence; it does not
contain a second protocol checker.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory


if sys.version_info < (3, 10):
    raise SystemExit(
        "AXI4 examples require Python 3.10 or newer; "
        f"this interpreter is Python {sys.version_info.major}.{sys.version_info.minor}."
    )


DEMO_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = DEMO_DIRECTORY.parents[2]
SHOWCASE_ROOT = REPOSITORY_ROOT / "showcase"
for path in (REPOSITORY_ROOT, DEMO_DIRECTORY):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


from protocol_model import (  # noqa: E402
    DutFacet,
    ProtocolPort,
    SystemProtocol,
    VirtualDut,
    __version__,
)
from protocol_model.artifacts import (  # noqa: E402
    RunArtifactStore,
    protocol_record_from_link,
    protocol_record_from_system,
)
from protocol_model.visualization import VisualizationPublisher  # noqa: E402

from cases import build_example_cases  # noqa: E402
from execution import compact_record, execute, result_record  # noqa: E402
from hero_cases import DEEP_DIVE_CASES, merge_deep_dive_cases  # noqa: E402
from presentation import (  # noqa: E402
    causality_dot,
    coverage_dot,
    example_set_record,
    index_report,
    network_dot,
    scope_dot,
    waveform_wavejson,
)


DEMO_NAME = "axi4"


def _build_demo_system(protocol) -> SystemProtocol:
    requester = VirtualDut(
        "requester",
        {"m_axi": ProtocolPort("m_axi", protocol, "manager")},
        frozenset((DutFacet.INITIATING,)),
        description="Illustrative AXI4 request source",
    )
    endpoint = VirtualDut(
        "memory_endpoint",
        {"s_axi": ProtocolPort("s_axi", protocol, "subordinate")},
        frozenset((DutFacet.ADDRESSABLE,)),
        description="Illustrative addressable endpoint",
    )
    system = SystemProtocol.from_link(
        "axi4-point-to-point",
        link_name="axi4-link",
        protocol=protocol,
        endpoints={
            "manager": (requester, "m_axi"),
            "subordinate": (endpoint, "s_axi"),
        },
    )
    system.elaborate()
    return system


def _require_renderers() -> None:
    missing = []
    if shutil.which("dot") is None:
        missing.append("Graphviz 'dot'")
    wavedrom = REPOSITORY_ROOT / "node_modules" / ".bin" / "wavedrom"
    if not wavedrom.is_file():
        missing.append("WaveDrom (run 'npm ci' at the repository root)")
    if missing:
        raise SystemExit("Missing renderer dependency: " + "; ".join(missing))


def _build_publication(directory: Path):
    cases = merge_deep_dive_cases(tuple(build_example_cases()))
    names = [case.name for case in cases]
    if len(cases) != 24:
        raise ValueError(f"AXI4 public set expects 24 cases, got {len(cases)}")
    if len(names) != len(set(names)):
        raise ValueError("AXI4 example names must be unique")
    marked = {case.name for case in cases if case.deep_dive}
    if marked != DEEP_DIVE_CASES:
        raise ValueError(f"unexpected deep-dive cases: {sorted(marked)}")

    runs = tuple(execute(case) for case in cases)
    system = _build_demo_system(cases[0].protocol)
    store = RunArtifactStore(DEMO_NAME, directory)
    publisher = VisualizationPublisher(store)

    publisher.render_dot(
        "topology",
        network_dot(system),
        kind="topology",
    )
    publisher.render_dot(
        "evidence-path",
        scope_dot(),
        kind="evidence_path",
    )
    publisher.render_dot(
        "coverage",
        coverage_dot(runs),
        kind="coverage_matrix",
    )

    for run in runs:
        case = run.case.name
        record = result_record(run)
        record["presentation"]["waveform_basis"] = (
            "AtomicFrame protocol observation"
            if run.case.mode.value == "atomic-frames"
            else "sequential CanonicalEvent inputs"
        )
        store.write_json(
            "result.json",
            record,
            kind="case_result",
            case=case,
        )
        publisher.render_wave(
            "waveform",
            waveform_wavejson(run),
            kind="waveform",
            case=case,
        )
        publisher.render_dot(
            "causality",
            causality_dot(run),
            kind="causality",
            case=case,
        )

    compact = tuple(compact_record(run) for run in runs)
    store.write_json(
        "examples.json",
        example_set_record(runs, compact),
        kind="example_set_index",
    )
    store.write_text(
        "README.en.md",
        index_report(runs, language="en"),
        kind="example_set_guide",
        media_type="text/markdown",
    )
    store.write_text(
        "README.zh-CN.md",
        index_report(runs, language="zh-CN"),
        kind="example_set_guide",
        media_type="text/markdown",
    )
    store.write_json(
        "provenance.json",
        {
            "schema": "protocol-model.showcase.provenance/v1",
            "demo": DEMO_NAME,
            "source": "showcase/demos/axi4/run.py",
            "command": "python3 showcase/demos/axi4/run.py",
            "protocol_model_version": __version__,
            "catalog_modules": [
                "cases.lifecycle",
                "cases.geometry",
                "cases.ordering",
                "cases.observation",
                "cases.exclusive_profile",
            ],
            "execution_models": ["LinkSession", "Axi4ObservationSession"],
            "case_count": len(runs),
            "deep_dive_cases": sorted(DEEP_DIVE_CASES),
            "waveform_basis": {
                "link-events": (
                    "one column per sequential CanonicalEvent input; not pin, "
                    "cycle, VALID/READY, or RTL timing"
                ),
                "atomic-frames": (
                    "ready/valid protocol observations; ARESETn is projected "
                    "as the inverse of normalized active-high reset"
                ),
            },
            "renderers": {
                "waveform": "WaveDrom 3.6.2 (package.json)",
                "causality": "Graphviz dot",
                "coverage_matrix": "Graphviz dot",
                "topology": "Graphviz dot",
            },
            "publication_boundary": (
                "representative protocol-model scenarios; not complete AXI4 "
                "specification coverage, RTL capture, or compliance evidence"
            ),
        },
        kind="provenance",
    )

    protocols = {}
    for run in runs:
        protocols.setdefault(run.case.protocol.name, run.case.protocol)
    all_met = all(run.expectation_met for run in runs)
    legal = sum(run.case.expected_verdict.value == "PASS" for run in runs)
    manifest = store.finalize(
        verdict="PASS" if all_met else "FAIL",
        protocols=(
            protocol_record_from_system(system),
            *(protocol_record_from_link(protocol) for protocol in protocols.values()),
        ),
        cases=tuple(
            {
                "name": run.case.name,
                "theme": run.case.theme,
                "deep_dive": run.case.deep_dive,
                "input_mode": run.case.mode.value,
                "expected": run.case.expected_verdict.value,
                "observed": run.actual_verdict.value,
                "expected_rule": run.case.expected_rule,
                "observed_rule": (
                    run.fault.rule if run.fault is not None else None
                ),
                "expectation": "MET" if run.expectation_met else "MISMATCH",
            }
            for run in runs
        ),
        metadata={
            "publication": "showcase/generated/axi4",
            "case_count": len(runs),
            "legal_case_count": legal,
            "expected_rejection_count": len(runs) - legal,
            "deep_dive_case_count": len(DEEP_DIVE_CASES),
            "run_status": "success" if all_met else "expectation_mismatch",
            "verdict_meaning": "all case expectations met",
            "coverage_interpretation": (
                "representative executable scenarios, not specification coverage"
            ),
            "rtl_capture": False,
        },
        tool_version=__version__,
    )
    return manifest, runs, all_met


def _publish(staged: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.with_name(f".{target.name}.previous")
    if previous.exists():
        shutil.rmtree(previous)
    if target.exists():
        target.replace(previous)
    try:
        staged.replace(target)
    except BaseException:
        if previous.exists() and not target.exists():
            previous.replace(target)
        raise
    else:
        if previous.exists():
            shutil.rmtree(previous)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Execute and publish the unified AXI4 example set."
    )
    parser.add_argument(
        "--publish-root",
        type=Path,
        default=SHOWCASE_ROOT / "generated",
        help="parent of the stable axi4 publication",
    )
    args = parser.parse_args(argv)
    publish_root = args.publish_root.expanduser().resolve()
    target = publish_root / DEMO_NAME
    build_root = publish_root.parent / ".build"
    build_root.mkdir(parents=True, exist_ok=True)

    _require_renderers()
    with TemporaryDirectory(prefix=f"{DEMO_NAME}-", dir=build_root) as temporary:
        staged = Path(temporary) / DEMO_NAME
        manifest, runs, all_met = _build_publication(staged)
        if not manifest.is_file():
            raise RuntimeError("staged AXI4 examples have no manifest")
        for run in runs:
            case_root = staged / "cases" / run.case.name
            required = ("result.json", "waveform.svg", "causality.svg")
            missing = [name for name in required if not (case_root / name).is_file()]
            if missing:
                raise RuntimeError(
                    f"case {run.case.name!r} lacks artifacts: {', '.join(missing)}"
                )
        if not all_met:
            mismatches = [run.case.name for run in runs if not run.expectation_met]
            raise RuntimeError(
                "AXI4 example expectations did not match: " + ", ".join(mismatches)
            )
        _publish(staged, target)

    try:
        build_root.rmdir()
    except OSError:
        pass
    print(f"Published {len(runs)} AXI4 examples: {target}")
    print(f"Manifest: {target / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

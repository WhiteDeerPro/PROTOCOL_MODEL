"""Run the project and publish its report artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from protocol_model.evidence import (
    ArtifactBundle,
    axi_cycles_to_waveform,
    ConstraintEvidence,
    constraints_from_instances,
    default_run_directory,
    format_execution_dot,
    synthesize_axi_waveform,
    synthesize_axi_event_sequence_waveform,
    to_wavejson,
)

from .evidence import format_run, negative_check_dot, report_html, topology_dot
from .project import AxiReadInterleaveProject, AxiReadInterleaveRun


DEFAULT_SIM_DIR = default_run_directory("prj_axi4_read_interleave")


@dataclass(frozen=True)
class AxiReadInterleaveSimulation:
    directory: Path
    report: Path
    text_report: Path
    waveform: Path
    network: Path
    causality: Path
    run: AxiReadInterleaveRun
    project: AxiReadInterleaveProject


def build_simulation(
    directory: str | Path | None = None, *, beats_per_request: int = 2
) -> AxiReadInterleaveSimulation:
    target = DEFAULT_SIM_DIR if directory is None else Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    project = AxiReadInterleaveProject(beats_per_request=beats_per_request)
    run = project.run()
    assert project.spec is not None and project.protocol is not None
    bundle = ArtifactBundle(project.name, target)

    waveform = synthesize_axi_waveform(
        project.spec, run.trace, seed=97, stall_probability=0.25
    )
    wave_svg_path = bundle.render_wave(
        "waveform",
        to_wavejson(
            waveform,
            title=(
                "AXI4 cross-ID read interleaving "
                f"({beats_per_request} beats per request)"
            ),
            hide_inactive_channels=True,
        ),
        kind="waveform",
        case="cross_id_out_of_order",
    )
    network_svg_path = bundle.render_dot(
        "network", topology_dot(project.snapshot()), kind="network"
    )
    causality_svg_path = bundle.render_dot(
        "causality",
        format_execution_dot(
            run.trace,
            title="AXI4 read interleaving causal chain",
            address_width=int(project.spec.parameters["address_width"]),
            data_width=int(project.spec.parameters["data_width"]),
        ),
        kind="causality",
        case="cross_id_out_of_order",
    )
    bundle.write_json(
        "trace.json",
        {
            "events": [
                {
                    "index": index,
                    "kind": event.kind,
                    "key": event.key,
                    "payload": dict(event.payload),
                }
                for index, event in enumerate(run.trace.events)
            ],
            "causal_edges": sorted(run.trace.causal_graph.edges),
        },
        kind="trace",
        case="cross_id_out_of_order",
    )
    for check in run.checks:
        if check.events:
            negative_waveform = synthesize_axi_event_sequence_waveform(
                project.spec, check.events
            )
        elif check.cycles:
            negative_waveform = axi_cycles_to_waveform(project.spec, check.cycles)
        else:
            raise RuntimeError(f"constraint check {check.name} has no evidence")
        bundle.render_wave(
            "waveform",
            to_wavejson(
                negative_waveform,
                title=f"Negative: {check.name}",
                hide_inactive_channels=True,
            ),
            kind="waveform",
            case=check.name,
        )
        bundle.render_dot(
            "causality",
            negative_check_dot(check),
            kind="causality",
            case=check.name,
        )
        bundle.write_json(
            "trace.json",
            {
                "expected": check.expected.value,
                "observed": check.observed.value,
                "rule": check.rule,
                "detail": check.detail,
                "events": [
                    {
                        "kind": event.kind,
                        "key": event.key,
                        "payload": dict(event.payload),
                    }
                    for event in check.events
                ],
                "cycles": [
                    {
                        name: {
                            "reset": wrapped.asserted,
                            "cycle": wrapped.observation.cycle,
                            "valid": wrapped.observation.valid,
                            "ready": wrapped.observation.ready,
                            "event": (
                                None
                                if wrapped.observation.event is None
                                else {
                                    "kind": wrapped.observation.event.kind,
                                    "key": wrapped.observation.event.key,
                                    "payload": dict(
                                        wrapped.observation.event.payload
                                    ),
                                }
                            ),
                        }
                        for name, wrapped in cycle.channels.items()
                    }
                    for cycle in check.cycles
                ],
            },
            kind="trace",
            case=check.name,
        )
    extra = tuple(
        ConstraintEvidence(
            id=item.name,
            source="TEST",
            target="mutation",
            rule=item.detail,
            foundation=item.rule,
            status="verified" if item.matched else "mismatch",
            instances=(project.protocol.qualified_name,),
            witness=f"expected={item.expected.value}, observed={item.observed.value}",
        )
        for item in run.checks
    )
    constraints = constraints_from_instances((project.protocol,), extra=extra)
    _, markdown_path = bundle.write_constraints(constraints)
    text_path = bundle.write_text(
        "run.txt", format_run(run) + "\n", kind="text_report"
    )
    html_path = bundle.write_text(
        "report.html",
        report_html(run, project.snapshot()),
        kind="html_report",
        media_type="text/html",
    )
    cases = (
        {"name": "cross_id_out_of_order", "expected": "PASS", "observed": run.verdict.value},
        *(
            {
                "name": item.name,
                "expected": item.expected.value,
                "observed": item.observed.value,
            }
            for item in run.checks
        ),
    )
    project.publish(*(str(path) for path in bundle.artifact_paths))
    bundle.finalize(
        verdict=run.verdict.value,
        protocol_instances=(project.protocol,),
        cases=cases,
        state=project.snapshot().state,
    )
    return AxiReadInterleaveSimulation(
        target,
        html_path,
        markdown_path,
        wave_svg_path,
        network_svg_path,
        causality_svg_path,
        run,
        project,
    )

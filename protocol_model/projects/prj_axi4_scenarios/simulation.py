"""Artifact publication for the batch AXI4 scenario Project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from protocol_model.evidence import (
    ArtifactBundle,
    ConstraintEvidence,
    axi_cycles_to_waveform,
    constraints_from_instances,
    default_run_directory,
    to_wavejson,
)

from .evidence import report_html, scenario_dot, topology_dot
from .project import AxiScenarioProject, AxiScenarioRun


DEFAULT_SIM_DIR = default_run_directory("prj_axi4_scenarios")


@dataclass(frozen=True)
class AxiScenarioSimulation:
    directory: Path
    report: Path
    run: AxiScenarioRun
    project: AxiScenarioProject


def _event_json(event):
    return {
        "kind": event.kind,
        "key": event.key,
        "payload": dict(event.payload),
        "trace_index": event.trace_index,
    }


def _cycle_json(cycle):
    return {
        name: {
            "reset": wrapped.asserted,
            "cycle": wrapped.observation.cycle,
            "valid": wrapped.observation.valid,
            "ready": wrapped.observation.ready,
            "event": (
                None
                if wrapped.observation.event is None
                else _event_json(wrapped.observation.event)
            ),
        }
        for name, wrapped in cycle.channels.items()
    }


def build_simulation(directory: str | Path | None = None) -> AxiScenarioSimulation:
    target = DEFAULT_SIM_DIR if directory is None else Path(directory)
    project = AxiScenarioProject()
    run = project.run()
    assert project.spec is not None and project.protocol is not None
    bundle = ArtifactBundle(project.name, target)
    bundle.render_dot("network", topology_dot(project.snapshot()), kind="network")
    for result in run.results:
        name = result.case.name
        waveform = axi_cycles_to_waveform(project.spec, result.case.cycles)
        bundle.render_wave(
            "waveform",
            to_wavejson(
                waveform,
                title=f"{name}: {result.case.description}",
                hide_inactive_channels=True,
            ),
            kind="waveform",
            case=name,
        )
        bundle.render_dot(
            "causality",
            scenario_dot(result),
            kind="causality",
            case=name,
        )
        bundle.write_json(
            "trace.json",
            {
                "category": result.case.category,
                "description": result.case.description,
                "expected": result.case.expected.value,
                "observed": result.observed.value,
                "matched": result.matched,
                "expected_rule": result.case.expected_rule,
                "fault": (
                    None
                    if result.fault is None
                    else {"rule": result.fault.rule, "reason": result.fault.reason}
                ),
                "cycles": [_cycle_json(cycle) for cycle in result.case.cycles],
                "emissions": [_event_json(event) for event in result.emissions],
                "steps": result.steps,
                "causal_edges": result.causal_edges,
                "quiescent": result.quiescent,
            },
            kind="trace",
            case=name,
        )
    constraints = constraints_from_instances(
        (project.protocol,),
        extra=tuple(
            ConstraintEvidence(
                id=f"scenario_{result.case.name}",
                source="TEST",
                target=result.case.category,
                rule=result.case.description,
                foundation="Axi4SignalSession + source/responder VirtualDuts",
                status="verified" if result.matched else "mismatch",
                instances=(project.protocol.qualified_name,),
                witness=(
                    result.fault.rule if result.fault else result.observed.value
                ),
            )
            for result in run.results
        ),
    )
    bundle.write_constraints(constraints)
    report = bundle.write_text(
        "report.html",
        report_html(run, project.snapshot()),
        kind="html_report",
        media_type="text/html",
    )
    project.publish(*(str(path) for path in bundle.artifact_paths))
    bundle.finalize(
        verdict=run.verdict.value,
        protocol_instances=(project.protocol,),
        cases=tuple(
            {
                "name": result.case.name,
                "category": result.case.category,
                "description": result.case.description,
                "expected": result.case.expected.value,
                "observed": result.observed.value,
                "matched": result.matched,
            }
            for result in run.results
        ),
        state=project.snapshot().state,
    )
    return AxiScenarioSimulation(target, report, run, project)

"""Project-owned simulation plan and output construction."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

from .evidence import (
    ready_valid_event_dot,
    ready_valid_sink_report_html,
    ready_valid_topology_dot,
    ready_valid_wavejson,
)
from .project import ReadyValidSinkCase, ReadyValidSinkProject, ReadyValidSinkRun


DEFAULT_SIM_DIR = Path(__file__).resolve().parent / "sims" / "01"


@dataclass(frozen=True)
class ReadyValidSinkSimulation:
    directory: Path
    report: Path
    legal: ReadyValidSinkRun
    mutation: ReadyValidSinkRun
    legal_phase: str
    mutation_phase: str
    files: tuple[Path, ...]


def _render_wavedrom(source: Path, target: Path) -> None:
    rendered = subprocess.run(
        ("node_modules/.bin/wavedrom", "--input", str(source)),
        check=True,
        capture_output=True,
        text=True,
    )
    target.write_text(rendered.stdout, encoding="utf-8")


def build_simulation(
    directory: str | Path | None = None,
) -> ReadyValidSinkSimulation:
    """Run the Project's default plan and publish every simulation artifact."""

    target = DEFAULT_SIM_DIR if directory is None else Path(directory)
    target.mkdir(parents=True, exist_ok=True)

    legal_project = ReadyValidSinkProject()
    legal = legal_project.run_case(
        ReadyValidSinkCase("legal_stall", (0x12, 0x34))
    )
    mutation_project = ReadyValidSinkProject()
    mutation = mutation_project.run_case(
        ReadyValidSinkCase(
            "changed_while_stalled",
            (0x12,),
            mutate_stalled_payload=True,
            expect_violation=True,
        )
    )

    generated = []
    for stem, run, title in (
        ("legal", legal, "Legal ready-valid stall and transfers"),
        ("mutation", mutation, "Payload mutation while stalled"),
    ):
        wave_json = target / f"{stem}.wave.json"
        wave_svg = target / f"{stem}.wave.svg"
        events_dot = target / f"{stem}.events.dot"
        events_svg = target / f"{stem}.events.svg"
        wave_json.write_text(
            json.dumps(ready_valid_wavejson(run, title=title), indent=2),
            encoding="utf-8",
        )
        _render_wavedrom(wave_json, wave_svg)
        events_dot.write_text(
            ready_valid_event_dot(run, title=title), encoding="utf-8"
        )
        subprocess.run(
            ("dot", "-Tsvg", str(events_dot), "-o", str(events_svg)),
            check=True,
        )
        generated.extend((wave_json, wave_svg, events_dot, events_svg))

    topology_dot = target / "topology.dot"
    topology_svg = target / "topology.svg"
    report = target / "index.html"
    topology_dot.write_text(
        ready_valid_topology_dot(legal_project.snapshot()), encoding="utf-8"
    )
    subprocess.run(
        ("dot", "-Tsvg", str(topology_dot), "-o", str(topology_svg)),
        check=True,
    )
    generated.extend((topology_dot, topology_svg, report))

    legal_project.publish(*(str(path) for path in generated))
    report.write_text(
        ready_valid_sink_report_html(
            legal,
            legal_project.snapshot(),
            mutation,
            mutation_project.snapshot(),
        ),
        encoding="utf-8",
    )
    return ReadyValidSinkSimulation(
        target,
        report,
        legal,
        mutation,
        legal_project.phase.value,
        mutation_project.phase.value,
        tuple(generated),
    )

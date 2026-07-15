"""A thin Project-facing facade over storage and visualization services."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Mapping, Sequence

from .model import CONSTRAINT_SCHEMA, ConstraintEvidence, ProtocolRecord
from .store import RunArtifactStore


class RunBundle:
    def __init__(
        self,
        subject: str,
        directory: str | Path | None = None,
        *,
        run_id: str = "01",
    ) -> None:
        from protocol_model.visualization import VisualizationPublisher

        self.store = RunArtifactStore(
            subject, directory, run_id=run_id
        )
        self.visuals = VisualizationPublisher(self.store)

    @property
    def subject(self) -> str:
        return self.store.subject

    @property
    def root(self) -> Path:
        return self.store.root

    @property
    def run_id(self) -> str:
        return self.store.run_id

    @property
    def artifact_paths(self) -> tuple[Path, ...]:
        return self.store.artifact_paths

    def path(self, name: str, *, case: str | None = None) -> Path:
        return self.store.path(name, case=case)

    def write_text(self, *args, **kwargs) -> Path:
        return self.store.write_text(*args, **kwargs)

    def write_json(self, *args, **kwargs) -> Path:
        return self.store.write_json(*args, **kwargs)

    def render_dot(self, *args, **kwargs) -> Path:
        return self.visuals.render_dot(*args, **kwargs)

    def render_wave(self, *args, **kwargs) -> Path:
        return self.visuals.render_wave(*args, **kwargs)

    def write_constraints(
        self, constraints: Sequence[ConstraintEvidence]
    ) -> tuple[Path, Path]:
        payload = {
            "schema": CONSTRAINT_SCHEMA,
            "subject": self.subject,
            "constraints": [asdict(item) for item in constraints],
        }
        json_path = self.write_json(
            "constraints.json", payload, kind="constraint_report_json"
        )
        lines = [
            f"# {self.subject} constraints",
            "",
            "| ID | Source | Instance | Target | Status | Rule | Foundation | Witness |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for item in constraints:
            values = (
                item.id,
                item.source,
                ", ".join(item.instances) or "-",
                item.target,
                item.status,
                item.rule,
                item.foundation,
                item.witness or "-",
            )
            lines.append(
                "| "
                + " | ".join(value.replace("|", "\\|") for value in values)
                + " |"
            )
        markdown_path = self.write_text(
            "constraints.md",
            "\n".join(lines) + "\n",
            kind="constraint_report_markdown",
            media_type="text/markdown",
        )
        return json_path, markdown_path

    def finalize(
        self,
        *,
        verdict: str,
        protocols: Sequence[ProtocolRecord | Mapping[str, object]] = (),
        cases: Sequence[Mapping[str, object]] = (),
        state: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> Path:
        from protocol_model import __version__

        return self.store.finalize(
            verdict=verdict,
            protocols=protocols,
            cases=cases,
            state=state,
            metadata=metadata,
            tool_version=__version__,
        )

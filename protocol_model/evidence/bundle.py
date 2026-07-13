"""Uniform run bundles, constraint reports, and artifact publication."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Iterable, Mapping, Sequence

from protocol_model import __version__
from protocol_model.protocols.spec import ProtocolInstance


RUN_SCHEMA = "protocol-model.run/v2"
CONSTRAINT_SCHEMA = "protocol-model.constraints/v1"


@dataclass(frozen=True)
class ConstraintEvidence:
    id: str
    source: str
    target: str
    rule: str
    foundation: str
    status: str
    instances: tuple[str, ...] = ()
    witness: str = ""


@dataclass(frozen=True)
class ArtifactRecord:
    kind: str
    path: str
    media_type: str
    sha256: str
    case: str | None = None


def default_run_directory(project: str, run_id: str = "01") -> Path:
    repository = Path(__file__).resolve().parents[2]
    return repository / "out" / project / run_id


def _json_value(value):
    """Preserve structured evidence instead of hiding it behind ``str()``."""

    if is_dataclass(value) and not isinstance(value, type):
        return {name: _json_value(item) for name, item in asdict(value).items()}
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Mapping):
        return {str(name): _json_value(item) for name, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


def constraints_from_instances(
    instances: Iterable[ProtocolInstance],
    *,
    extra: Sequence[ConstraintEvidence] = (),
) -> tuple[ConstraintEvidence, ...]:
    """Lower protocol requirements and instance profiles into one report IR."""

    result = []
    for instance in instances:
        profile = {item.name: item for item in instance.constraints}
        for requirement in instance.spec.requirements:
            record = profile.get(requirement.name)
            result.append(
                ConstraintEvidence(
                    id=requirement.name,
                    source="PROFILE" if record else "SPEC",
                    target=(
                        ", ".join(record.targets)
                        if record
                        else f"{instance.qualified_name}.protocol"
                    ),
                    rule=requirement.rule,
                    foundation=requirement.foundation,
                    status=requirement.status,
                    instances=(instance.qualified_name,),
                )
            )
    result.extend(extra)
    return tuple(result)


class ArtifactBundle:
    """One deterministic directory contract shared by every Project."""

    def __init__(
        self,
        project: str,
        directory: str | Path | None = None,
        *,
        run_id: str = "01",
    ):
        self.project = project
        self.run_id = run_id if directory is None else Path(directory).name
        self.root = (
            default_run_directory(project, run_id)
            if directory is None
            else Path(directory)
        )
        self.sources = self.root / "sources"
        self.sources.mkdir(parents=True, exist_ok=True)
        self._artifacts: list[tuple[str, Path, str, str | None]] = []

    def path(self, name: str, *, case: str | None = None) -> Path:
        return self.root / (Path("cases") / case / name if case else Path(name))

    @property
    def artifact_paths(self) -> tuple[Path, ...]:
        return tuple(path for _, path, _, _ in self._artifacts)

    def source_path(self, name: str, *, case: str | None = None) -> Path:
        return self.sources / (Path("cases") / case / name if case else Path(name))

    def register(
        self, kind: str, path: Path, media_type: str, *, case: str | None = None
    ) -> Path:
        self._artifacts.append((kind, path, media_type, case))
        return path

    def write_text(
        self,
        name: str,
        text: str,
        *,
        kind: str,
        media_type: str = "text/plain",
        case: str | None = None,
    ) -> Path:
        path = self.path(name, case=case)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return self.register(kind, path, media_type, case=case)

    def write_json(
        self, name: str, value, *, kind: str, case: str | None = None
    ) -> Path:
        return self.write_text(
            name,
            json.dumps(_json_value(value), indent=2, ensure_ascii=False) + "\n",
            kind=kind,
            media_type="application/json",
            case=case,
        )

    def render_dot(
        self, name: str, dot: str, *, kind: str, case: str | None = None
    ) -> Path:
        source = self.source_path(f"{name}.dot", case=case)
        target = self.path(f"{name}.svg", case=case)
        source.parent.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(dot, encoding="utf-8")
        self.register(
            f"{kind}_source", source, "text/vnd.graphviz", case=case
        )
        subprocess.run(
            ("dot", "-Tsvg", str(source), "-o", str(target)), check=True
        )
        return self.register(kind, target, "image/svg+xml", case=case)

    def render_wave(
        self,
        name: str,
        wavejson,
        *,
        kind: str = "waveform",
        case: str | None = None,
    ) -> Path:
        source = self.source_path(f"{name}.json", case=case)
        target = self.path(f"{name}.svg", case=case)
        source.parent.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(
            json.dumps(wavejson, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self.register(f"{kind}_source", source, "application/json", case=case)
        rendered = subprocess.run(
            ("node_modules/.bin/wavedrom", "--input", str(source)),
            check=True,
            capture_output=True,
            text=True,
        )
        target.write_text(rendered.stdout, encoding="utf-8")
        return self.register(kind, target, "image/svg+xml", case=case)

    def write_constraints(
        self, constraints: Sequence[ConstraintEvidence]
    ) -> tuple[Path, Path]:
        payload = {
            "schema": CONSTRAINT_SCHEMA,
            "project": self.project,
            "constraints": [asdict(item) for item in constraints],
        }
        json_path = self.write_json(
            "constraints.json", payload, kind="constraint_report_json"
        )
        lines = [
            f"# {self.project} constraints",
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
            lines.append("| " + " | ".join(value.replace("|", "\\|") for value in values) + " |")
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
        protocol_instances: Sequence[ProtocolInstance],
        cases: Sequence[Mapping[str, object]],
        state: Mapping[str, object],
    ) -> Path:
        records = []
        for kind, path, media_type, case in self._artifacts:
            records.append(
                ArtifactRecord(
                    kind,
                    str(path.relative_to(self.root)),
                    media_type,
                    sha256(path.read_bytes()).hexdigest(),
                    case,
                )
            )
        case_records = []
        for item in cases:
            case = dict(_json_value(item))
            name = str(case["name"])
            case["artifacts"] = [
                record.path for record in records if record.case == name
            ]
            case_records.append(case)
        manifest = {
            "schema": RUN_SCHEMA,
            "project": self.project,
            "run_id": self.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tool_version": __version__,
            "verdict": verdict,
            "protocol_instances": [
                {
                    "identity": instance.qualified_name,
                    "owner": instance.owner,
                    "link": instance.name,
                    "base_spec": instance.base_spec.name,
                    "base_parameters": _json_value(
                        instance.base_spec.parameters
                    ),
                    "effective_spec": instance.spec.name,
                    "effective_parameters": _json_value(
                        instance.spec.parameters
                    ),
                    "private_profile": instance.is_constrained,
                    "constraints": [
                        item.name for item in instance.constraints
                    ],
                }
                for instance in protocol_instances
            ],
            "cases": case_records,
            "state": _json_value(state),
            "artifacts": [asdict(item) for item in records],
        }
        path = self.path("manifest.json")
        path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

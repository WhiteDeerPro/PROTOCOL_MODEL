"""Safe, atomic storage for generated run artifacts and their manifest."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Mapping, Sequence

from .model import ArtifactRecord, ProtocolRecord, RUN_SCHEMA, json_value


@dataclass(frozen=True)
class _PendingArtifact:
    kind: str
    path: Path
    media_type: str
    case: str | None
    source: bool


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_run_directory(subject: str, run_id: str = "01") -> Path:
    return repository_root() / "out" / subject / run_id


def _safe_relative(value: str, *, label: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise ValueError(f"{label} must be a non-empty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe {label} {value!r}")
    return path


def _safe_case(case: str | None) -> str | None:
    if case is None:
        return None
    path = _safe_relative(case, label="case")
    if len(path.parts) != 1:
        raise ValueError("case must be one path segment")
    return case


class RunArtifactStore:
    """Own one run directory; rendering and protocol semantics live elsewhere."""

    def __init__(
        self,
        subject: str,
        directory: str | Path | None = None,
        *,
        run_id: str = "01",
    ) -> None:
        if not subject:
            raise ValueError("run artifact store requires a subject")
        self.subject = subject
        self.root = (
            default_run_directory(subject, run_id)
            if directory is None
            else Path(directory)
        )
        self.run_id = run_id if directory is None else self.root.name
        self.root.mkdir(parents=True, exist_ok=True)
        self._artifacts: dict[str, _PendingArtifact] = {}
        self._finalized = False

    def _require_open(self) -> None:
        if self._finalized:
            raise RuntimeError("run artifact store is already finalized")

    def relative_path(
        self,
        name: str,
        *,
        case: str | None = None,
        source: bool = False,
    ) -> PurePosixPath:
        relative = _safe_relative(name, label="artifact name")
        case = _safe_case(case)
        prefix = PurePosixPath("sources") if source else PurePosixPath()
        if case is not None:
            prefix = prefix / "cases" / case
        return prefix / relative

    def path(
        self,
        name: str,
        *,
        case: str | None = None,
        source: bool = False,
    ) -> Path:
        return self.root / self.relative_path(name, case=case, source=source)

    @property
    def artifact_paths(self) -> tuple[Path, ...]:
        return tuple(item.path for item in self._artifacts.values())

    def _atomic_write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
            temporary.write(data)
            temporary.flush()
            temporary_path = Path(temporary.name)
        temporary_path.replace(path)

    def register(
        self,
        kind: str,
        path: Path,
        media_type: str,
        *,
        case: str | None = None,
        source: bool = False,
    ) -> Path:
        self._require_open()
        if not kind or not media_type:
            raise ValueError("artifact registration requires kind and media type")
        root = self.root.resolve()
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"artifact {path} is outside run root {self.root}")
        if not path.is_file():
            raise FileNotFoundError(path)
        relative = path.relative_to(self.root).as_posix()
        if relative in self._artifacts:
            raise ValueError(f"artifact path {relative!r} is already registered")
        case = _safe_case(case)
        self._artifacts[relative] = _PendingArtifact(
            kind, path, media_type, case, source
        )
        return path

    def write_text(
        self,
        name: str,
        text: str,
        *,
        kind: str,
        media_type: str = "text/plain",
        case: str | None = None,
        source: bool = False,
    ) -> Path:
        self._require_open()
        path = self.path(name, case=case, source=source)
        self._atomic_write(path, text.encode("utf-8"))
        return self.register(
            kind, path, media_type, case=case, source=source
        )

    def write_json(
        self,
        name: str,
        value,
        *,
        kind: str,
        case: str | None = None,
        source: bool = False,
    ) -> Path:
        return self.write_text(
            name,
            json.dumps(json_value(value), indent=2, ensure_ascii=False) + "\n",
            kind=kind,
            media_type="application/json",
            case=case,
            source=source,
        )

    def finalize(
        self,
        *,
        verdict: str,
        protocols: Sequence[ProtocolRecord | Mapping[str, object]] = (),
        cases: Sequence[Mapping[str, object]] = (),
        state: Mapping[str, object] | None = None,
        metadata: Mapping[str, object] | None = None,
        tool_version: str,
    ) -> Path:
        self._require_open()
        records = tuple(
            ArtifactRecord(
                item.kind,
                relative,
                item.media_type,
                item.case,
                item.source,
            )
            for relative, item in sorted(self._artifacts.items())
        )
        case_records = []
        for raw_case in cases:
            case = dict(json_value(raw_case))
            name = str(case["name"])
            _safe_case(name)
            case["artifacts"] = [
                item.path for item in records if item.case == name
            ]
            case_records.append(case)
        manifest = {
            "schema": RUN_SCHEMA,
            "subject": self.subject,
            "run_id": self.run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tool_version": tool_version,
            "verdict": verdict,
            "protocols": [json_value(item) for item in protocols],
            "cases": case_records,
            "state": json_value(state or {}),
            "metadata": json_value(metadata or {}),
            "artifacts": [asdict(item) for item in records],
        }
        path = self.path("manifest.json")
        self._atomic_write(
            path,
            (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode(
                "utf-8"
            ),
        )
        self._finalized = True
        return path

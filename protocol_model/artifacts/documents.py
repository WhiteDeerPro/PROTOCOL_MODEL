"""Explicit publication storage for maintained documentation.

Run artifacts are immutable evidence for one execution. Documentation is a
maintained publication tree, so replacement and removal are deliberate APIs
instead of side effects hidden in project simulations.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from .store import _safe_relative


@dataclass(frozen=True)
class PublishedDocument:
    path: str
    source: str | None = None


class DocumentationStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._published: dict[str, PublishedDocument] = {}

    def path(self, name: str) -> Path:
        return self.root / _safe_relative(name, label="documentation path")

    @property
    def published(self) -> tuple[PublishedDocument, ...]:
        return tuple(self._published[name] for name in sorted(self._published))

    def _atomic_bytes(self, target: Path, content: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        temporary.write_bytes(content)
        temporary.replace(target)

    def _record(self, target: Path, source: Path | None) -> Path:
        relative = target.relative_to(self.root).as_posix()
        self._published[relative] = PublishedDocument(
            relative,
            str(source) if source is not None else None,
        )
        return target

    def write_text(self, name: str, content: str) -> Path:
        target = self.path(name)
        self._atomic_bytes(target, content.encode("utf-8"))
        return self._record(target, None)

    def publish(self, source: str | Path, name: str) -> Path:
        source_path = Path(source)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        target = self.path(name)
        self._atomic_bytes(target, source_path.read_bytes())
        return self._record(target, source_path)

    def remove(self, name: str) -> None:
        target = self.path(name)
        if target.is_dir():
            raise IsADirectoryError(target)
        target.unlink(missing_ok=True)
        self._published.pop(target.relative_to(self.root).as_posix(), None)

    def replace_tree(self, name: str) -> Path:
        """Clear a publisher-owned subtree before deterministically rebuilding it."""

        target = self.path(name)
        if target.exists():
            if not target.is_dir():
                raise NotADirectoryError(target)
            shutil.rmtree(target)
        target.mkdir(parents=True)
        prefix = target.relative_to(self.root).as_posix() + "/"
        self._published = {
            path: item
            for path, item in self._published.items()
            if not path.startswith(prefix)
        }
        return target

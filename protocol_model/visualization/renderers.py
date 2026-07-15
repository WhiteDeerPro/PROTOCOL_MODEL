"""External format renderers with no knowledge of protocol semantics or storage."""

from __future__ import annotations

from pathlib import Path
import subprocess

from protocol_model.artifacts.store import repository_root


class GraphvizRenderer:
    source_media_type = "text/vnd.graphviz"
    output_media_type = "image/svg+xml"
    source_suffix = ".dot"
    output_suffix = ".svg"

    def __init__(self, executable: str | Path = "dot") -> None:
        self.executable = str(executable)

    def render(self, source: Path, target: Path) -> None:
        subprocess.run(
            (self.executable, "-Tsvg", str(source), "-o", str(target)),
            check=True,
        )


class WaveDromRenderer:
    source_media_type = "application/json"
    output_media_type = "image/svg+xml"
    source_suffix = ".json"
    output_suffix = ".svg"

    def __init__(self, executable: str | Path | None = None) -> None:
        self.executable = str(
            executable
            if executable is not None
            else repository_root() / "node_modules" / ".bin" / "wavedrom"
        )

    def render(self, source: Path, target: Path) -> None:
        rendered = subprocess.run(
            (self.executable, "--input", str(source)),
            check=True,
            capture_output=True,
            text=True,
        )
        target.write_text(rendered.stdout, encoding="utf-8")

"""Publish visualization IR and rendered views through a run artifact store."""

from __future__ import annotations

from pathlib import Path

from protocol_model.artifacts.store import RunArtifactStore

from .renderers import GraphvizRenderer, WaveDromRenderer


class VisualizationPublisher:
    def __init__(
        self,
        store: RunArtifactStore,
        *,
        graphviz=None,
        wavedrom=None,
    ) -> None:
        self.store = store
        self.graphviz = graphviz or GraphvizRenderer()
        self.wavedrom = wavedrom or WaveDromRenderer()

    def _render(
        self,
        name: str,
        content: str,
        *,
        kind: str,
        renderer,
        case: str | None,
    ) -> Path:
        source = self.store.write_text(
            f"{name}{renderer.source_suffix}",
            content,
            kind=f"{kind}_source",
            media_type=renderer.source_media_type,
            case=case,
            source=True,
        )
        target = self.store.path(f"{name}{renderer.output_suffix}", case=case)
        target.parent.mkdir(parents=True, exist_ok=True)
        renderer.render(source, target)
        return self.store.register(
            kind, target, renderer.output_media_type, case=case
        )

    def render_dot(
        self, name: str, dot: str, *, kind: str, case: str | None = None
    ) -> Path:
        return self._render(
            name, dot, kind=kind, renderer=self.graphviz, case=case
        )

    def render_wave(
        self,
        name: str,
        wavejson,
        *,
        kind: str = "waveform",
        case: str | None = None,
    ) -> Path:
        import json

        return self._render(
            name,
            json.dumps(wavejson, indent=2, ensure_ascii=False) + "\n",
            kind=kind,
            renderer=self.wavedrom,
            case=case,
        )

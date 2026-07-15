from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
import unittest

from protocol_model.artifacts import (
    DocumentationStore,
    ProtocolRecord,
    RunArtifactStore,
)
from protocol_model.visualization import VisualizationPublisher


class _TextRenderer:
    source_media_type = "text/x-view-source"
    output_media_type = "image/svg+xml"
    source_suffix = ".view"
    output_suffix = ".svg"

    def render(self, source: Path, target: Path) -> None:
        target.write_text(f"<svg>{source.read_text(encoding='utf-8')}</svg>", encoding="utf-8")


class ArtifactStorageTest(unittest.TestCase):
    def test_run_store_indexes_sources_and_freezes_after_finalize(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore("tiny_network", Path(directory) / "01")
            publisher = VisualizationPublisher(
                store, graphviz=_TextRenderer(), wavedrom=_TextRenderer()
            )
            rendered = publisher.render_dot(
                "trace", "digraph { a -> b }", kind="causality", case="legal"
            )
            manifest_path = store.finalize(
                verdict="PASS",
                protocols=(
                    ProtocolRecord(
                        "system",
                        "tiny_network",
                        "tiny_network",
                        MappingProxyType({"width": 32}),
                    ),
                ),
                cases=({"name": "legal", "observed": "PASS"},),
                tool_version="test",
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual("protocol-model.run/v3", manifest["schema"])
            self.assertEqual("system", manifest["protocols"][0]["scope"])
            self.assertEqual(2, len(manifest["artifacts"]))
            source = next(item for item in manifest["artifacts"] if item["source"])
            self.assertEqual("sources/cases/legal/trace.view", source["path"])
            self.assertNotIn("sha256", source)
            self.assertIn("cases/legal/trace.svg", manifest["cases"][0]["artifacts"])
            self.assertTrue(rendered.is_file())
            with self.assertRaisesRegex(RuntimeError, "already finalized"):
                store.write_text("late.txt", "late", kind="late")

    def test_store_rejects_path_escape_and_duplicate_registration(self) -> None:
        with TemporaryDirectory() as directory:
            store = RunArtifactStore("subject", directory)
            with self.assertRaisesRegex(ValueError, "unsafe"):
                store.write_text("../escape", "bad", kind="bad")
            store.write_text("one.txt", "one", kind="text")
            with self.assertRaisesRegex(ValueError, "already registered"):
                store.register("text", store.root / "one.txt", "text/plain")

    def test_document_store_makes_publication_mutations_explicit(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "generated.svg"
            source.write_text("<svg/>", encoding="utf-8")
            docs = DocumentationStore(root / "docs")

            published = docs.publish(source, "assets/network.svg")
            docs.write_text("guide.md", "# Guide\n")

            self.assertEqual("<svg/>", published.read_text(encoding="utf-8"))
            self.assertEqual(
                ("assets/network.svg", "guide.md"),
                tuple(item.path for item in docs.published),
            )
            docs.replace_tree("assets")
            self.assertFalse(published.exists())
            self.assertEqual(("guide.md",), tuple(item.path for item in docs.published))


if __name__ == "__main__":
    unittest.main()

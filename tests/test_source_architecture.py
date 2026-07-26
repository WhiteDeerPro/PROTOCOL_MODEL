from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path
import subprocess
import sys
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "protocol_model"


def _module_name(path: Path) -> str:
    relative = path.relative_to(REPOSITORY_ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _absolute_import(module_name: str, path: Path, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package = module_name if path.name == "__init__.py" else module_name.rpartition(".")[0]
    relative = "." * node.level + (node.module or "")
    return resolve_name(relative, package)


def _protocol_model_imports(path: Path) -> set[str]:
    module_name = _module_name(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        names: tuple[str, ...] = ()
        if isinstance(node, ast.Import):
            names = tuple(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names = (_absolute_import(module_name, path, node),)
        imports.update(
            name for name in names if name == "protocol_model" or name.startswith("protocol_model.")
        )
    return imports


def _root_facade_imported_names(path: Path) -> set[str]:
    """Return names obtained directly from the broad package root."""

    module_name = _module_name(path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "protocol_model" for alias in node.names):
                imported_names.add("<module>")
        elif isinstance(node, ast.ImportFrom):
            if _absolute_import(module_name, path, node) == "protocol_model":
                imported_names.update(alias.name for alias in node.names)
    return imported_names


class SourceArchitectureTests(unittest.TestCase):
    def test_source_uses_named_owners_instead_of_the_root_facade(self) -> None:
        violations: list[str] = []
        root_init = SOURCE_ROOT / "__init__.py"
        for path in SOURCE_ROOT.rglob("*.py"):
            if path == root_init:
                continue
            unexpected = _root_facade_imported_names(path) - {"__version__"}
            if unexpected:
                violations.append(
                    f"{path}: imports {sorted(unexpected)!r} from broad root facade"
                )
        self.assertEqual([], violations, "\n" + "\n".join(violations))

    def test_root_facade_loads_conceptual_anchors_lazily(self) -> None:
        script = """
import sys
import protocol_model

assert protocol_model.__all__ == [
    "CanonicalEvent",
    "InterfaceProtocol",
    "SystemProtocol",
    "VirtualDut",
    "__version__",
]
assert not any(
    name.startswith("protocol_model.") for name in sys.modules
), sorted(name for name in sys.modules if name.startswith("protocol_model."))

from protocol_model import CanonicalEvent, InterfaceProtocol, SystemProtocol, VirtualDut

assert CanonicalEvent.__name__ == "CanonicalEvent"
assert InterfaceProtocol.__name__ == "InterfaceProtocol"
assert SystemProtocol.__name__ == "SystemProtocol"
assert VirtualDut.__name__ == "VirtualDut"
assert "protocol_model.integrations" not in sys.modules
assert "protocol_model.protocols" not in sys.modules
"""
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPOSITORY_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            0,
            completed.returncode,
            completed.stdout + completed.stderr,
        )

    def test_generic_packages_keep_their_dependency_direction(self) -> None:
        allowed = {
            "semantics": set(),
            "patterns": {"semantics"},
            "observation": {"semantics"},
            "interface": {"patterns", "semantics"},
            "virtual_dut": {"interface", "semantics"},
            "system": {"interface", "semantics", "virtual_dut"},
            "integrations": {
                "interface",
                "protocols",
                "semantics",
                "virtual_dut",
            },
        }
        violations: list[str] = []
        for owner, permitted in allowed.items():
            for path in (SOURCE_ROOT / owner).rglob("*.py"):
                for imported in _protocol_model_imports(path):
                    parts = imported.split(".")
                    if len(parts) < 2:
                        violations.append(f"{path}: imports broad root facade")
                        continue
                    target = parts[1]
                    if target != owner and target not in permitted:
                        violations.append(
                            f"{path}: {owner} must not depend on {imported}"
                        )
        self.assertEqual([], violations, "\n" + "\n".join(violations))

    def test_integration_artifact_roles_do_not_reverse(self) -> None:
        forbidden_by_role = {
            "attachments": (
                "protocol_model.integrations.backends",
                "protocol_model.integrations.recipes",
            ),
            "backends": ("protocol_model.integrations.recipes",),
            "translations": (
                "protocol_model.integrations.backends",
                "protocol_model.integrations.recipes",
            ),
        }
        violations: list[str] = []
        integration_root = SOURCE_ROOT / "integrations"
        for role, forbidden in forbidden_by_role.items():
            for path in (integration_root / role).rglob("*.py"):
                for imported in _protocol_model_imports(path):
                    if imported.startswith(forbidden):
                        violations.append(
                            f"{path}: {role} must not depend on {imported}"
                        )
        self.assertEqual([], violations, "\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()

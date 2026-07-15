"""Composable semantic fragments; patterns compile to this representation."""

from __future__ import annotations

from dataclasses import dataclass

from .model import ObligationDecl, ResourceDecl, SemanticConstraint


@dataclass(frozen=True)
class SemanticFragment:
    name: str
    constraints: tuple[SemanticConstraint, ...] = ()
    resources: tuple[ResourceDecl, ...] = ()
    obligations: tuple[ObligationDecl, ...] = ()
    dependencies: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("semantic fragment requires a name")
        _require_unique("constraint", (item.name for item in self.constraints))
        _require_unique("resource", (item.name for item in self.resources))
        _require_unique("obligation", (item.name for item in self.obligations))

    @classmethod
    def empty(cls, name: str) -> "SemanticFragment":
        return cls(name=name, sources=(name,))

    def namespaced(self, prefix: str) -> "SemanticFragment":
        if not prefix:
            raise ValueError("semantic namespace must not be empty")
        return SemanticFragment(
            name=f"{prefix}.{self.name}",
            constraints=tuple(item.namespaced(prefix) for item in self.constraints),
            resources=tuple(item.namespaced(prefix) for item in self.resources),
            obligations=tuple(item.namespaced(prefix) for item in self.obligations),
            dependencies=tuple(f"{prefix}.{item}" for item in self.dependencies),
            sources=tuple(f"{prefix}.{item}" for item in (self.sources or (self.name,))),
        )


def _require_unique(kind: str, names) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise ValueError(f"duplicate {kind} declaration {name!r}")
        seen.add(name)


def compose_fragments(
    name: str, *fragments: SemanticFragment
) -> SemanticFragment:
    """Conjoin fragments without hiding their origin or analysis declarations."""

    constraints = tuple(
        item for fragment in fragments for item in fragment.constraints
    )
    resources = tuple(item for fragment in fragments for item in fragment.resources)
    obligations = tuple(
        item for fragment in fragments for item in fragment.obligations
    )
    dependencies = tuple(
        item for fragment in fragments for item in fragment.dependencies
    )
    sources = tuple(
        source
        for fragment in fragments
        for source in (fragment.sources or (fragment.name,))
    )
    return SemanticFragment(
        name=name,
        constraints=constraints,
        resources=resources,
        obligations=obligations,
        dependencies=dependencies,
        sources=sources,
    )

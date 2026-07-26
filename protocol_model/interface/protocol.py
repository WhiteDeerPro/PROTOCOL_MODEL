"""Protocol declarations decidable at one logical interface boundary."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from random import Random
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintKind,
    ConstraintScope,
    EventOffer,
    EventSchema,
    SemanticComponent,
    SemanticConstraint,
    SemanticFragment,
    compose_fragments,
)


@dataclass(frozen=True)
class InterfaceEventKind:
    """Bind one canonical event schema to its direction at an interface.

    ``name`` is the local declaration key.  This object does not imply that
    the standard exposes an independent wire-level channel; concrete protocol
    packages remain responsible for naming real channels such as AXI AW/W/B.
    """

    name: str
    source_role: str
    destination_role: str
    schema: EventSchema

    def __post_init__(self) -> None:
        if not self.name or not self.source_role or not self.destination_role:
            raise ValueError(
                "interface event kind requires name, source role, and destination role"
            )
        if self.source_role == self.destination_role:
            raise ValueError(
                "interface event kind source and destination roles must differ"
            )


@dataclass(frozen=True)
class InterfaceProtocol:
    """A protocol whose constraints are decidable on one logical interface."""

    name: str
    roles: frozenset[str]
    event_kinds: Mapping[str, InterfaceEventKind]
    semantics: SemanticFragment
    interface_family: str = ""
    parameters: Mapping[str, object] = field(default_factory=dict)
    lineage: tuple[str, ...] = ()
    monitors: Mapping[str, SemanticComponent] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("interface protocol requires a name")
        if not self.interface_family:
            object.__setattr__(self, "interface_family", self.name)
        if len(self.roles) < 2:
            raise ValueError("interface protocol requires at least two roles")
        event_kinds = dict(self.event_kinds)
        if set(event_kinds) != {item.name for item in event_kinds.values()}:
            raise ValueError(
                "event-kind mapping keys must match interface event-kind names"
            )
        for event_kind in event_kinds.values():
            if event_kind.source_role not in self.roles:
                raise ValueError(
                    f"event kind {event_kind.name!r} has unknown source role"
                )
            if event_kind.destination_role not in self.roles:
                raise ValueError(
                    f"event kind {event_kind.name!r} has unknown destination role"
                )
        schema_names = [item.schema.name for item in event_kinds.values()]
        if len(set(schema_names)) != len(schema_names):
            raise ValueError(
                "canonical event kinds must be unique within an InterfaceProtocol"
            )
        monitors = dict(self.monitors)
        if set(monitors) != {item.name for item in monitors.values()}:
            raise ValueError("monitor mapping keys must match monitor names")
        object.__setattr__(self, "event_kinds", MappingProxyType(event_kinds))
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "monitors", MappingProxyType(monitors))

    @classmethod
    def define(
        cls,
        name: str,
        *,
        interface_family: str | None = None,
        roles: frozenset[str],
        event_kinds: Mapping[str, InterfaceEventKind],
        fragments: tuple[SemanticFragment, ...],
        parameters: Mapping[str, object] | None = None,
        monitors: Mapping[str, SemanticComponent] | None = None,
    ) -> "InterfaceProtocol":
        return cls(
            name=name,
            roles=roles,
            event_kinds=event_kinds,
            semantics=compose_fragments(f"{name}.semantics", *fragments),
            interface_family=(
                name if interface_family is None else interface_family
            ),
            parameters=parameters or {},
            monitors=monitors or {},
        )

    def refine(
        self,
        name: str,
        *additional_fragments: SemanticFragment,
        parameters: Mapping[str, object] | None = None,
        monitors: Mapping[str, SemanticComponent] | None = None,
    ) -> "InterfaceProtocol":
        """Create a monotonic profile by adding constraints and monitors."""

        if not name or name == self.name:
            raise ValueError("refined interface protocol requires a distinct name")
        overrides = dict(parameters or {})
        unknown = set(overrides) - set(self.parameters)
        if unknown:
            raise ValueError(f"unknown protocol parameters: {sorted(unknown)!r}")
        added_monitors = dict(monitors or {})
        duplicates = set(added_monitors) & set(self.monitors)
        if duplicates:
            raise ValueError(f"duplicate interface monitors: {sorted(duplicates)!r}")
        return InterfaceProtocol(
            name=name,
            roles=self.roles,
            event_kinds=self.event_kinds,
            semantics=compose_fragments(
                f"{name}.semantics", self.semantics, *additional_fragments
            ),
            interface_family=self.interface_family,
            parameters={**self.parameters, **overrides},
            lineage=(*self.lineage, self.name),
            monitors={**self.monitors, **added_monitors},
        )

    def forbid_events(
        self,
        name: str,
        event_kinds,
        *,
        reason: str = "disabled by the interface profile",
    ) -> "InterfaceProtocol":
        """Refine this interface by disabling selected canonical event kinds.

        This is an InterfaceProtocol restriction. Pin-level requirements such as
        tying VALID low are observation policies and are configured separately.
        """

        from protocol_model.patterns import ForbiddenEventMonitor

        kinds = frozenset(event_kinds)
        available = {item.schema.name for item in self.event_kinds.values()}
        unknown = kinds - available
        if not kinds:
            raise ValueError("forbidden-event profile requires at least one event kind")
        if unknown:
            raise ValueError(f"unknown interface event kinds: {sorted(unknown)!r}")
        monitor = ForbiddenEventMonitor(
            f"{name}.forbidden_events", kinds, reason=reason
        )
        fragment = SemanticFragment(
            f"{name}.forbidden_event_semantics",
            constraints=(
                SemanticConstraint(
                    f"{name}.forbidden_events",
                    f"canonical events {sorted(kinds)!r} are {reason}",
                    ConstraintScope.INTERFACE,
                    targets=tuple(sorted(kinds)),
                ),
            ),
        )
        return self.refine(name, fragment, monitors={monitor.name: monitor})

    @property
    def forbidden_event_kinds(self) -> frozenset[str]:
        """Return event kinds disabled by monotonic interface profiles.

        Callers that implement only one channel slice can use this public
        projection without depending on the concrete monitor used by
        :meth:`forbid_events`.  The declared ``event_kinds`` mapping remains
        the physical/logical interface shape; this property describes which
        members of that shape the current profile permits at runtime.
        """

        from protocol_model.patterns import ForbiddenEventMonitor

        return frozenset(
            kind
            for monitor in self.monitors.values()
            if isinstance(monitor, ForbiddenEventMonitor)
            for kind in monitor.event_kinds
        )

    @property
    def enabled_event_kinds(self) -> frozenset[str]:
        """Return declared event kinds not disabled by the current profile."""

        return frozenset(self.event_kinds) - self.forbidden_event_kinds

    def with_resource_capacities(
        self, name: str, capacities: Mapping[str, int]
    ) -> "InterfaceProtocol":
        """Create a bounded profile by tightening declared interface resources."""

        if not name or name == self.name:
            raise ValueError("bounded interface profile requires a distinct name")
        capacities = dict(capacities)
        if not capacities:
            raise ValueError("bounded interface profile requires at least one capacity")
        declared = {item.name: item for item in self.semantics.resources}
        unknown = set(capacities) - set(declared)
        if unknown:
            raise ValueError(f"unknown interface resources: {sorted(unknown)!r}")
        for resource_name, capacity in capacities.items():
            if type(capacity) is not int or capacity <= 0:
                raise ValueError(
                    f"resource capacity for {resource_name!r} must be a positive integer"
                )
            current = declared[resource_name]
            if not current.acquired_by:
                raise ValueError(
                    f"resource {resource_name!r} has no declared lifecycle to bound"
                )
            if current.capacity is not None and capacity > current.capacity:
                raise ValueError(
                    f"capacity {capacity} would widen existing bound {current.capacity} "
                    f"for {resource_name!r}"
                )

        providers: set[str] = set()
        for monitor_name, monitor in self.monitors.items():
            provider = getattr(monitor, "resource_usage", None)
            if provider is None:
                continue
            reported = set(provider(monitor.initial_state()))
            duplicates = providers & reported
            if duplicates:
                raise ValueError(
                    f"multiple monitors report resources: {sorted(duplicates)!r}"
                )
            providers.update(reported)
        missing_providers = set(capacities) - providers
        if missing_providers:
            raise ValueError(
                "bounded resources require executable usage providers: "
                f"{sorted(missing_providers)!r}"
            )

        constraints = list(self.semantics.constraints)
        for resource_name, capacity in capacities.items():
            constraints.append(
                SemanticConstraint(
                    f"{name}.{resource_name}.capacity",
                    f"resource {resource_name} usage does not exceed {capacity}",
                    ConstraintScope.INTERFACE,
                    kind=ConstraintKind.RESOURCE,
                    targets=(resource_name,),
                )
            )
        resources = tuple(
            replace(item, capacity=capacities.get(item.name, item.capacity))
            for item in self.semantics.resources
        )
        semantics = SemanticFragment(
            f"{name}.semantics",
            constraints=tuple(constraints),
            resources=resources,
            obligations=self.semantics.obligations,
            dependencies=self.semantics.dependencies,
            sources=(*self.semantics.sources, f"{name}.resource_capacities"),
        )
        return InterfaceProtocol(
            name=name,
            roles=self.roles,
            event_kinds=self.event_kinds,
            semantics=semantics,
            interface_family=self.interface_family,
            parameters=self.parameters,
            lineage=(*self.lineage, self.name),
            monitors=self.monitors,
        )

    def has_same_interface_shape_as(self, other: "InterfaceProtocol") -> bool:
        """Whether two declarations expose the same executable interface shape.

        Semantic refinements may have different names, monitors, and
        constraints while retaining the same event kinds and concrete interface
        parameters.  Attachments use this relation instead of display names.
        """

        return (
            isinstance(other, InterfaceProtocol)
            and self.interface_family == other.interface_family
            and self.roles == other.roles
            and set(self.event_kinds) == set(other.event_kinds)
            and all(
                self._event_kind_has_same_interface_shape(
                    self.event_kinds[name], other.event_kinds[name]
                )
                for name in self.event_kinds
            )
            and self.parameters == other.parameters
        )

    @staticmethod
    def _event_kind_has_same_interface_shape(
        left: InterfaceEventKind, right: InterfaceEventKind
    ) -> bool:
        """Compare directed event schemas without predicate identity.

        Event constraints remain enforced by each InterfaceSession. Attachments
        need the stable interface shape: direction, event/key domain,
        payload fields, and extra-field policy.  Comparing constraint callable
        objects would make two independently built AXI declarations appear
        different even when they came from the same configuration.
        """

        left_event = left.schema
        right_event = right.schema
        return (
            left.name == right.name
            and left.source_role == right.source_role
            and left.destination_role == right.destination_role
            and left_event.name == right_event.name
            and left_event.key == right_event.key
            and left_event.allow_extra_fields == right_event.allow_extra_fields
            and set(left_event.fields) == set(right_event.fields)
            and all(
                left_event.fields[name].domain
                == right_event.fields[name].domain
                for name in left_event.fields
            )
        )

    def event_kind_for(self, kind: str) -> InterfaceEventKind:
        for event_kind in self.event_kinds.values():
            if event_kind.schema.name == kind:
                return event_kind
        raise KeyError(
            f"event kind {kind!r} is not in InterfaceProtocol {self.name!r}"
        )

    def generate_event(self, offer: EventOffer, rng: Random) -> CanonicalEvent:
        return self.event_kind_for(offer.kind).schema.generate(rng, offer)

    def open_session(self):
        from .session import InterfaceSession

        return InterfaceSession(self)

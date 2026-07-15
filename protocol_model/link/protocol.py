"""Local, point-to-point communication protocol declarations."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from random import Random
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    CanonicalEvent,
    ConstantDomain,
    ConstraintKind,
    ConstraintScope,
    EventConstraint,
    EventOffer,
    SemanticComponent,
    SemanticConstraint,
    SemanticFragment,
    ValueDomain,
    compose_fragments,
)


@dataclass(frozen=True)
class EventField:
    name: str
    domain: ValueDomain
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("event field requires a name")


@dataclass(frozen=True)
class EventSchema:
    name: str
    fields: Mapping[str, EventField] = field(default_factory=dict)
    key: ValueDomain = field(default_factory=lambda: ConstantDomain(None))
    constraints: tuple[EventConstraint, ...] = ()
    allow_extra_fields: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("event schema requires a name")
        fields = dict(self.fields)
        if set(fields) != {item.name for item in fields.values()}:
            raise ValueError("event field mapping keys must match field names")
        object.__setattr__(self, "fields", MappingProxyType(fields))

    def explain(self, event: CanonicalEvent) -> tuple[str, ...]:
        reasons: list[str] = []
        if event.kind != self.name:
            return (f"expected event kind {self.name!r}, got {event.kind!r}",)
        key_reason = self.key.explain(event.key)
        if key_reason:
            reasons.append(f"key: {key_reason}")
        missing = set(self.fields) - set(event.payload)
        if missing:
            reasons.append(f"missing payload fields {sorted(missing)!r}")
        if not self.allow_extra_fields:
            extra = set(event.payload) - set(self.fields)
            if extra:
                reasons.append(f"unexpected payload fields {sorted(extra)!r}")
        for name, event_field in self.fields.items():
            if name not in event.payload:
                continue
            reason = event_field.domain.explain(event.payload[name])
            if reason:
                reasons.append(f"payload.{name}: {reason}")
        if not reasons:
            reasons.extend(
                constraint.reason
                for constraint in self.constraints
                if not constraint.predicate(event)
            )
        return tuple(reasons)

    def contains(self, event: CanonicalEvent) -> bool:
        return not self.explain(event)

    def generate(
        self,
        rng: Random,
        offer: EventOffer | None = None,
        *,
        max_attempts: int = 10_000,
    ) -> CanonicalEvent:
        """Complete a partial enabled offer and validate the result."""

        offer = offer or EventOffer.unconstrained(self.name)
        if offer.kind != self.name:
            raise ValueError(
                f"offer kind {offer.kind!r} does not match schema {self.name!r}"
            )
        unknown = set(offer.payload) - set(self.fields)
        if unknown:
            raise ValueError(f"offer fixes unknown fields {sorted(unknown)!r}")
        if offer.key_is_set:
            reason = self.key.explain(offer.key)
            if reason:
                raise ValueError(f"offered key: {reason}")
        for name, value in offer.payload.items():
            reason = self.fields[name].domain.explain(value)
            if reason:
                raise ValueError(f"offered payload.{name}: {reason}")
        for _ in range(max_attempts):
            event = CanonicalEvent(
                self.name,
                offer.key if offer.key_is_set else self.key.sample(rng),
                {
                    name: (
                        offer.payload[name]
                        if name in offer.payload
                        else event_field.domain.sample(rng)
                    )
                    for name, event_field in self.fields.items()
                },
            )
            if self.contains(event):
                return event
        raise RuntimeError(
            f"failed to sample event {self.name!r}; constraints may be unsatisfiable"
        )

    def sample(self, rng: Random, *, max_attempts: int = 10_000) -> CanonicalEvent:
        return self.generate(rng, max_attempts=max_attempts)


@dataclass(frozen=True)
class ChannelProtocol:
    name: str
    source_role: str
    destination_role: str
    event: EventSchema

    def __post_init__(self) -> None:
        if not self.name or not self.source_role or not self.destination_role:
            raise ValueError("channel requires name, source role, and destination role")
        if self.source_role == self.destination_role:
            raise ValueError("channel source and destination roles must differ")


@dataclass(frozen=True)
class LinkProtocol:
    """A protocol whose constraints are decidable on one logical link."""

    name: str
    roles: frozenset[str]
    channels: Mapping[str, ChannelProtocol]
    semantics: SemanticFragment
    family: str = ""
    parameters: Mapping[str, object] = field(default_factory=dict)
    lineage: tuple[str, ...] = ()
    monitors: Mapping[str, SemanticComponent] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("link protocol requires a name")
        if not self.family:
            object.__setattr__(self, "family", self.name)
        if len(self.roles) < 2:
            raise ValueError("link protocol requires at least two roles")
        channels = dict(self.channels)
        if set(channels) != {item.name for item in channels.values()}:
            raise ValueError("channel mapping keys must match channel names")
        for channel in channels.values():
            if channel.source_role not in self.roles:
                raise ValueError(f"channel {channel.name!r} has unknown source role")
            if channel.destination_role not in self.roles:
                raise ValueError(
                    f"channel {channel.name!r} has unknown destination role"
                )
        event_kinds = [channel.event.name for channel in channels.values()]
        if len(set(event_kinds)) != len(event_kinds):
            raise ValueError("channel event kinds must be unique within a LinkProtocol")
        monitors = dict(self.monitors)
        if set(monitors) != {item.name for item in monitors.values()}:
            raise ValueError("monitor mapping keys must match monitor names")
        object.__setattr__(self, "channels", MappingProxyType(channels))
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))
        object.__setattr__(self, "monitors", MappingProxyType(monitors))

    @classmethod
    def define(
        cls,
        name: str,
        *,
        family: str | None = None,
        roles: frozenset[str],
        channels: Mapping[str, ChannelProtocol],
        fragments: tuple[SemanticFragment, ...],
        parameters: Mapping[str, object] | None = None,
        monitors: Mapping[str, SemanticComponent] | None = None,
    ) -> "LinkProtocol":
        return cls(
            name=name,
            roles=roles,
            channels=channels,
            semantics=compose_fragments(f"{name}.semantics", *fragments),
            family=name if family is None else family,
            parameters=parameters or {},
            monitors=monitors or {},
        )

    def refine(
        self,
        name: str,
        *additional_fragments: SemanticFragment,
        parameters: Mapping[str, object] | None = None,
        monitors: Mapping[str, SemanticComponent] | None = None,
    ) -> "LinkProtocol":
        """Create a monotonic profile by adding constraints and monitors."""

        if not name or name == self.name:
            raise ValueError("refined link protocol requires a distinct name")
        overrides = dict(parameters or {})
        unknown = set(overrides) - set(self.parameters)
        if unknown:
            raise ValueError(f"unknown protocol parameters: {sorted(unknown)!r}")
        added_monitors = dict(monitors or {})
        duplicates = set(added_monitors) & set(self.monitors)
        if duplicates:
            raise ValueError(f"duplicate link monitors: {sorted(duplicates)!r}")
        return LinkProtocol(
            name=name,
            roles=self.roles,
            channels=self.channels,
            semantics=compose_fragments(
                f"{name}.semantics", self.semantics, *additional_fragments
            ),
            family=self.family,
            parameters={**self.parameters, **overrides},
            lineage=(*self.lineage, self.name),
            monitors={**self.monitors, **added_monitors},
        )

    def forbid_events(
        self,
        name: str,
        event_kinds,
        *,
        reason: str = "disabled by the link profile",
    ) -> "LinkProtocol":
        """Refine this link by disabling selected canonical event kinds.

        This is a LinkProtocol restriction. Pin-level requirements such as
        tying VALID low are observation policies and are configured separately.
        """

        from protocol_model.patterns import ForbiddenEventMonitor

        kinds = frozenset(event_kinds)
        available = {channel.event.name for channel in self.channels.values()}
        unknown = kinds - available
        if not kinds:
            raise ValueError("forbidden-event profile requires at least one event kind")
        if unknown:
            raise ValueError(f"unknown link event kinds: {sorted(unknown)!r}")
        monitor = ForbiddenEventMonitor(
            f"{name}.forbidden_events", kinds, reason=reason
        )
        fragment = SemanticFragment(
            f"{name}.forbidden_event_semantics",
            constraints=(
                SemanticConstraint(
                    f"{name}.forbidden_events",
                    f"canonical events {sorted(kinds)!r} are {reason}",
                    ConstraintScope.LINK,
                    targets=tuple(sorted(kinds)),
                ),
            ),
        )
        return self.refine(name, fragment, monitors={monitor.name: monitor})

    def with_resource_capacities(
        self, name: str, capacities: Mapping[str, int]
    ) -> "LinkProtocol":
        """Create a bounded profile by tightening declared link resources."""

        if not name or name == self.name:
            raise ValueError("bounded link profile requires a distinct name")
        capacities = dict(capacities)
        if not capacities:
            raise ValueError("bounded link profile requires at least one capacity")
        declared = {item.name: item for item in self.semantics.resources}
        unknown = set(capacities) - set(declared)
        if unknown:
            raise ValueError(f"unknown link resources: {sorted(unknown)!r}")
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
                    ConstraintScope.LINK,
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
        return LinkProtocol(
            name=name,
            roles=self.roles,
            channels=self.channels,
            semantics=semantics,
            family=self.family,
            parameters=self.parameters,
            lineage=(*self.lineage, self.name),
            monitors=self.monitors,
        )

    def has_same_transport_as(self, other: "LinkProtocol") -> bool:
        """Whether two declarations expose the same executable link shape.

        Semantic refinements may have different names, monitors, and
        constraints while retaining the same channels and concrete transport
        parameters.  Attachments use this relation instead of display names.
        """

        return (
            isinstance(other, LinkProtocol)
            and self.family == other.family
            and self.roles == other.roles
            and set(self.channels) == set(other.channels)
            and all(
                self._channel_has_same_transport_shape(
                    self.channels[name], other.channels[name]
                )
                for name in self.channels
            )
            and self.parameters == other.parameters
        )

    @staticmethod
    def _channel_has_same_transport_shape(
        left: ChannelProtocol, right: ChannelProtocol
    ) -> bool:
        """Compare channel schemas without executable predicate identity.

        Event constraints remain enforced by each LinkSession.  Attachments
        need the stable wire/transaction shape: direction, event/key domain,
        payload fields, and extra-field policy.  Comparing constraint callable
        objects would make two independently built AXI declarations appear
        different even when they came from the same configuration.
        """

        left_event = left.event
        right_event = right.event
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

    def channel_for_event(self, kind: str) -> ChannelProtocol:
        for channel in self.channels.values():
            if channel.event.name == kind:
                return channel
        raise KeyError(f"event kind {kind!r} is not in LinkProtocol {self.name!r}")

    def generate_event(self, offer: EventOffer, rng: Random) -> CanonicalEvent:
        return self.channel_for_event(offer.kind).event.generate(rng, offer)

    def open_session(self):
        from .session import LinkSession

        return LinkSession(self)

"""Explicit lowering from protocol descriptions into report records."""

from __future__ import annotations

from .model import ConstraintEvidence, ProtocolRecord


def protocol_record_from_link(protocol, *, identity: str | None = None):
    return ProtocolRecord(
        scope="link",
        identity=identity or protocol.name,
        definition=protocol.name,
        parameters=protocol.parameters,
        lineage=protocol.lineage,
        metadata={
            "roles": sorted(protocol.roles),
            "channels": sorted(protocol.channels),
            "monitors": sorted(protocol.monitors),
            "resources": tuple(
                {
                    "name": resource.name,
                    "scope": resource.scope.value,
                    "capacity": resource.capacity,
                    "acquired_by": resource.acquired_by,
                    "released_by": resource.released_by,
                    "description": resource.description,
                }
                for resource in protocol.semantics.resources
            ),
        },
    )


def protocol_record_from_system(system):
    return ProtocolRecord(
        scope="system",
        identity=system.name,
        definition=system.name,
        parameters={},
        metadata={
            "virtual_duts": sorted(system.virtual_duts),
            "links": sorted(system.links),
            "boundary": sorted(system.boundary),
        },
    )


def constraints_from_link_protocols(*protocols) -> tuple[ConstraintEvidence, ...]:
    result = []
    for protocol in protocols:
        for constraint in protocol.semantics.constraints:
            result.append(
                ConstraintEvidence(
                    id=constraint.name,
                    source="LINK_PROTOCOL",
                    target=", ".join(constraint.targets) or protocol.name,
                    rule=constraint.rule,
                    foundation=constraint.foundation or constraint.kind.value,
                    status="implemented",
                    instances=(protocol.name,),
                )
            )
    return tuple(result)

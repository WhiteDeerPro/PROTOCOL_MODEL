"""Explicit lowering from protocol descriptions into report records."""

from __future__ import annotations

from .model import ConstraintRecord, ProtocolRecord


def protocol_record_from_interface(protocol, *, identity: str | None = None):
    return ProtocolRecord(
        scope="interface",
        identity=identity or protocol.name,
        definition=protocol.name,
        parameters=protocol.parameters,
        lineage=protocol.lineage,
        metadata={
            "interface_family": protocol.interface_family,
            "roles": sorted(protocol.roles),
            "event_kinds": sorted(protocol.event_kinds),
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
            "connections": sorted(system.connections),
            "boundary": sorted(system.boundary),
        },
    )


def constraint_records_from_interface_protocols(
    *protocols,
) -> tuple[ConstraintRecord, ...]:
    result = []
    for protocol in protocols:
        for constraint in protocol.semantics.constraints:
            result.append(
                ConstraintRecord(
                    id=constraint.name,
                    source="INTERFACE_PROTOCOL",
                    target=", ".join(constraint.targets) or protocol.name,
                    rule=constraint.rule,
                    foundation=constraint.foundation or constraint.kind.value,
                    status="declared",
                    instances=(protocol.name,),
                )
            )
    return tuple(result)

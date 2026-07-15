"""Stable identities and runtime type boundaries for translated operations."""

from __future__ import annotations

from dataclasses import dataclass


def _validate_runtime_types(
    values: tuple[type, ...], *, subject: str, allow_empty: bool
) -> None:
    if not values and not allow_empty:
        raise ValueError(f"{subject} requires at least one runtime type")
    if any(not isinstance(item, type) for item in values):
        raise TypeError(f"{subject} runtime types must be Python classes")
    if len(set(values)) != len(values):
        raise ValueError(f"{subject} runtime types must be unique")


@dataclass(frozen=True)
class OperationSignature:
    """One semantic operation family at a translation boundary.

    ``request_types`` and ``completion_types`` are tuples because a stable
    operation family can have several concrete runtime forms.  For example,
    the address family uses separate read and write classes rather than a
    synthetic superclass.  An empty completion tuple denotes a one-way
    operation family; the serial request/completion executor deliberately
    rejects such a plan.

    V1 plan closure uses exact signature compatibility.  Structural or
    subclass compatibility must be represented by an explicit stage so its
    semantic effects remain visible in the construction report.
    """

    domain: str
    name: str
    version: str
    request_types: tuple[type, ...]
    completion_types: tuple[type, ...] = ()

    def __post_init__(self) -> None:
        for value, subject in (
            (self.domain, "operation domain"),
            (self.name, "operation name"),
            (self.version, "operation version"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{subject} must be a non-empty string")
        _validate_runtime_types(
            self.request_types,
            subject=f"{self.qualified_name} request",
            allow_empty=False,
        )
        _validate_runtime_types(
            self.completion_types,
            subject=f"{self.qualified_name} completion",
            allow_empty=True,
        )

    @property
    def qualified_name(self) -> str:
        return f"{self.domain}.{self.name}@{self.version}"

    @property
    def has_completion(self) -> bool:
        return bool(self.completion_types)

    def accepts_request(self, value: object) -> bool:
        return type(value) in self.request_types

    def accepts_completion(self, value: object) -> bool:
        return type(value) in self.completion_types

    def request_contract(self) -> tuple[object, ...]:
        return (
            self.domain,
            self.name,
            self.version,
            self.request_types,
        )

    def completion_contract(self) -> tuple[object, ...]:
        return (
            self.domain,
            self.name,
            self.version,
            self.completion_types,
        )

"""Protocol-neutral cache-line storage used by constructed VirtualDuts.

This module owns the immutable address-to-line container and elementary
install/remove operations.  It deliberately does not define coherence states,
replacement policy, local CPU requests, or protocol messages.  A protocol
participant can store its own typed line records here without creating a
second copy of line data or permission.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Generic, Mapping, Protocol, TypeVar


class StoredCacheLine(Protocol):
    """Structural requirement for a record held by :class:`CacheLineStore`."""

    address: int


LineT = TypeVar("LineT", bound=StoredCacheLine)


def _require_line_address(address: int, line_bytes: int) -> None:
    if (
        not isinstance(address, int)
        or isinstance(address, bool)
        or address < 0
        or address % line_bytes
    ):
        raise ValueError(
            f"cache-line address must be aligned to {line_bytes} bytes"
        )


@dataclass(frozen=True)
class CacheLinePayload:
    """Protocol-neutral resident-line data.

    Presence in :class:`CacheLineStoreState` means that the line data is
    resident.  Coherence permission, replacement age, transaction ownership,
    and protocol identities belong to the facets that use this record.
    """

    address: int
    data: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.address, int)
            or isinstance(self.address, bool)
            or self.address < 0
        ):
            raise ValueError("cache-line payload address must be non-negative")
        if (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or self.data < 0
        ):
            raise ValueError("cache-line payload data must be non-negative")


@dataclass(frozen=True)
class CacheLineStoreState(Generic[LineT]):
    """The sole immutable mapping of resident or observed cache-line records."""

    lines: Mapping[int, LineT] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "lines", MappingProxyType(dict(self.lines)))

    def line_at(self, address: int) -> LineT | None:
        return self.lines.get(address)


@dataclass(frozen=True)
class CacheLineStoreMutation(Generic[LineT]):
    """One explicit cache-store change and the record it replaced or removed."""

    state: CacheLineStoreState[LineT]
    previous: LineT | None = None


class CacheLineStore(Generic[LineT]):
    """Immutable cache-line storage core with caller-selected line metadata.

    The first profile has no implicit capacity or victim selection.  A later
    bounded refinement can add a replacement policy without changing which
    object owns line data.
    """

    def __init__(
        self,
        name: str,
        *,
        line_bytes: int,
        initial_lines: tuple[LineT, ...] = (),
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("cache-line store requires a name")
        if (
            not isinstance(line_bytes, int)
            or isinstance(line_bytes, bool)
            or line_bytes <= 0
        ):
            raise ValueError("cache-line size must be positive")
        lines = tuple(initial_lines)
        mapping: dict[int, LineT] = {}
        for line in lines:
            address = self._record_address(line, line_bytes)
            if address in mapping:
                raise ValueError(
                    "cache-line store initial addresses must be unique"
                )
            mapping[address] = line
        self.name = name
        self.line_bytes = line_bytes
        self.initial_lines = lines
        self._initial_mapping = MappingProxyType(mapping)

    def initial_state(self) -> CacheLineStoreState[LineT]:
        return CacheLineStoreState(self._initial_mapping)

    def install(
        self,
        state: CacheLineStoreState[LineT],
        line: LineT,
    ) -> CacheLineStoreMutation[LineT]:
        self._require_state(state)
        address = self._record_address(line, self.line_bytes)
        previous = state.lines.get(address)
        lines = dict(state.lines)
        lines[address] = line
        return CacheLineStoreMutation(CacheLineStoreState(lines), previous)

    def remove(
        self,
        state: CacheLineStoreState[LineT],
        address: int,
    ) -> CacheLineStoreMutation[LineT]:
        self._require_state(state)
        _require_line_address(address, self.line_bytes)
        previous = state.lines.get(address)
        if previous is None:
            return CacheLineStoreMutation(state)
        lines = dict(state.lines)
        del lines[address]
        return CacheLineStoreMutation(CacheLineStoreState(lines), previous)

    @staticmethod
    def _record_address(line: LineT, line_bytes: int) -> int:
        try:
            address = line.address
        except AttributeError as error:
            raise TypeError(
                "cache-line store records require an address"
            ) from error
        _require_line_address(address, line_bytes)
        if isinstance(line, CacheLinePayload) and line.data >= (
            1 << (line_bytes * 8)
        ):
            raise ValueError("cache-line payload data does not fit the line")
        return address

    @staticmethod
    def _require_state(state: CacheLineStoreState[LineT]) -> None:
        if not isinstance(state, CacheLineStoreState):
            raise TypeError("cache-line store requires CacheLineStoreState")


@dataclass(frozen=True)
class CacheCore(Generic[LineT]):
    """Named protocol-neutral cache state core.

    The wrapper gives storage a backend-local identity before any protocol
    facet is selected; it is not itself a topology-visible ``VirtualDut``.
    Later refinements can add a local-access or replacement policy alongside
    ``line_store`` without making a protocol participant the creator of the
    cache.
    """

    name: str
    line_store: CacheLineStore[LineT]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("cache core requires a name")
        if not isinstance(self.line_store, CacheLineStore):
            raise TypeError("cache core requires CacheLineStore")

    def initial_state(self) -> CacheLineStoreState[LineT]:
        return self.line_store.initial_state()


__all__ = [
    "CacheCore",
    "CacheLinePayload",
    "CacheLineStore",
    "CacheLineStoreMutation",
    "CacheLineStoreState",
    "StoredCacheLine",
]

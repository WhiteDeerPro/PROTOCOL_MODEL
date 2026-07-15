"""Address-space dispatch over reusable, non-overlapping regions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol

from .access import (
    AccessResult,
    AccessStatus,
    AddressAccess,
    AddressStep,
)


class AddressRegion(Protocol):
    name: str
    base_address: int
    size_bytes: int

    def initial_state(self) -> object:
        ...

    def access(self, state: object, request: AddressAccess) -> AddressStep:
        ...


@dataclass(frozen=True)
class AddressSpaceState:
    region_states: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "region_states", MappingProxyType(dict(self.region_states))
        )


@dataclass(frozen=True)
class AddressSpace:
    """Dispatch accesses to non-overlapping regions; it is not itself memory."""

    regions: tuple[AddressRegion, ...]

    def __post_init__(self) -> None:
        regions = tuple(self.regions)
        if not regions:
            raise ValueError("address space requires at least one region")
        names: set[str] = set()
        ordered = sorted(regions, key=lambda region: region.base_address)
        previous_limit: int | None = None
        for region in ordered:
            if not region.name or region.size_bytes <= 0 or region.base_address < 0:
                raise ValueError("address-space regions require a name and valid span")
            if region.name in names:
                raise ValueError(f"duplicate address region {region.name!r}")
            if previous_limit is not None and region.base_address < previous_limit:
                raise ValueError(f"address region {region.name!r} overlaps another region")
            names.add(region.name)
            previous_limit = region.base_address + region.size_bytes
        object.__setattr__(self, "regions", tuple(ordered))

    def initial_state(self) -> AddressSpaceState:
        return AddressSpaceState(
            {region.name: region.initial_state() for region in self.regions}
        )

    def access(
        self, state: AddressSpaceState, request: AddressAccess
    ) -> AddressStep:
        if not isinstance(state, AddressSpaceState):
            raise TypeError("AddressSpace requires AddressSpaceState")
        region = next(
            (
                item
                for item in self.regions
                if item.base_address <= request.address
                and request.address + request.size
                <= item.base_address + item.size_bytes
            ),
            None,
        )
        if region is None:
            return AddressStep(
                state, AccessResult(status=AccessStatus.DECODE_ERROR)
            )
        step = region.access(state.region_states[region.name], request)
        region_states = dict(state.region_states)
        region_states[region.name] = step.state
        return AddressStep(AddressSpaceState(region_states), step.result)

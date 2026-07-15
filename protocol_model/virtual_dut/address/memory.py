"""Sparse memory-backed address regions for constructed VirtualDuts."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from .access import (
    AccessResult,
    AccessStatus,
    AddressAccess,
    AddressRead,
    AddressStep,
    ByteOrder,
)


@dataclass(frozen=True)
class MemoryRegionState:
    """Sparse absolute-address bytes; absent locations read as zero."""

    contents: Mapping[int, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        contents = dict(self.contents)
        if any(not 0 <= value <= 0xFF for value in contents.values()):
            raise ValueError("memory region values must be bytes")
        object.__setattr__(self, "contents", MappingProxyType(contents))

    def byte_at(self, address: int) -> int:
        return self.contents.get(address, 0)


@dataclass(frozen=True)
class MemoryRegion:
    name: str
    size_bytes: int
    base_address: int = 0
    byte_order: ByteOrder = ByteOrder.LITTLE
    read_only: bool = False
    initial_content: bytes = b""

    def __post_init__(self) -> None:
        if not self.name or self.size_bytes <= 0 or self.base_address < 0:
            raise ValueError("memory region requires a name and valid span")
        if not isinstance(self.byte_order, ByteOrder):
            object.__setattr__(self, "byte_order", ByteOrder(self.byte_order))
        initial_content = bytes(self.initial_content)
        if len(initial_content) > self.size_bytes:
            raise ValueError("initial content exceeds memory region")
        object.__setattr__(self, "initial_content", initial_content)

    def initial_state(self) -> MemoryRegionState:
        return MemoryRegionState(
            {
                self.base_address + offset: value
                for offset, value in enumerate(self.initial_content)
                if value
            }
        )

    def access(self, state: object, request: AddressAccess) -> AddressStep:
        if not isinstance(state, MemoryRegionState):
            raise TypeError("MemoryRegion requires MemoryRegionState")
        if not (
            self.base_address <= request.address
            and request.address + request.size
            <= self.base_address + self.size_bytes
        ):
            return AddressStep(
                state, AccessResult(status=AccessStatus.DECODE_ERROR)
            )
        if isinstance(request, AddressRead):
            raw = bytes(
                state.byte_at(request.address + index)
                for index in range(request.size)
            )
            return AddressStep(
                state,
                AccessResult(data=int.from_bytes(raw, self.byte_order.value)),
            )
        if self.read_only:
            return AddressStep(
                state, AccessResult(status=AccessStatus.ACCESS_ERROR)
            )
        contents = dict(state.contents)
        incoming = request.data.to_bytes(request.size, self.byte_order.value)
        for index, value in enumerate(incoming):
            if not request.effective_byte_enable & (1 << index):
                continue
            address = request.address + index
            if value:
                contents[address] = value
            else:
                contents.pop(address, None)
        return AddressStep(MemoryRegionState(contents), AccessResult())

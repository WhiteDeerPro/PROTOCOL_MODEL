"""Register-backed address regions for constructed VirtualDuts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from ..backend.transition import DutEffect
from .access import (
    AccessResult,
    AccessStatus,
    AddressAccess,
    AddressRead,
    AddressStep,
    ByteOrder,
)


class RegisterPermission(str, Enum):
    READ_WRITE = "read_write"
    READ_ONLY = "read_only"
    WRITE_ONLY = "write_only"


@dataclass(frozen=True)
class RegisterSpec:
    name: str
    offset: int
    width: int = 32
    reset: int = 0
    permission: RegisterPermission = RegisterPermission.READ_WRITE
    write_mask: int | None = None
    read_effect: str | None = None
    write_effect: str | None = None

    def __post_init__(self) -> None:
        if not self.name or self.offset < 0:
            raise ValueError("register requires a name and non-negative offset")
        if self.width <= 0 or self.width % 8:
            raise ValueError("register width must be a positive number of bytes")
        if not isinstance(self.permission, RegisterPermission):
            object.__setattr__(
                self, "permission", RegisterPermission(self.permission)
            )
        limit = 1 << self.width
        if not 0 <= self.reset < limit:
            raise ValueError("register reset value does not fit its width")
        write_mask = limit - 1 if self.write_mask is None else self.write_mask
        if not isinstance(write_mask, int) or not 0 <= write_mask < limit:
            raise ValueError("register write mask does not fit its width")
        object.__setattr__(self, "write_mask", write_mask)

    @property
    def size_bytes(self) -> int:
        return self.width // 8


@dataclass(frozen=True)
class RegisterRegionState:
    values: Mapping[int, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def value_at(self, offset: int) -> int:
        return self.values[offset]


@dataclass(frozen=True)
class RegisterRegion:
    name: str
    registers: tuple[RegisterSpec, ...]
    base_address: int = 0
    byte_order: ByteOrder = ByteOrder.LITTLE

    def __post_init__(self) -> None:
        registers = tuple(self.registers)
        if not self.name or not registers or self.base_address < 0:
            raise ValueError("register region requires a name, registers, and base")
        if not isinstance(self.byte_order, ByteOrder):
            object.__setattr__(self, "byte_order", ByteOrder(self.byte_order))
        names: set[str] = set()
        occupied: set[int] = set()
        for register in registers:
            if register.name in names:
                raise ValueError(f"duplicate register name {register.name!r}")
            register_bytes = set(
                range(register.offset, register.offset + register.size_bytes)
            )
            if occupied & register_bytes:
                raise ValueError(f"register {register.name!r} overlaps another register")
            names.add(register.name)
            occupied.update(register_bytes)
        object.__setattr__(
            self, "registers", tuple(sorted(registers, key=lambda item: item.offset))
        )

    @property
    def size_bytes(self) -> int:
        return max(item.offset + item.size_bytes for item in self.registers)

    def initial_state(self) -> RegisterRegionState:
        return RegisterRegionState(
            {register.offset: register.reset for register in self.registers}
        )

    def access(self, state: object, request: AddressAccess) -> AddressStep:
        if not isinstance(state, RegisterRegionState):
            raise TypeError("RegisterRegion requires RegisterRegionState")
        relative_address = request.address - self.base_address
        register = self._register_for(relative_address, request.size)
        if register is None:
            return AddressStep(
                state, AccessResult(status=AccessStatus.DECODE_ERROR)
            )
        byte_offset = relative_address - register.offset
        if isinstance(request, AddressRead):
            if register.permission is RegisterPermission.WRITE_ONLY:
                return AddressStep(
                    state, AccessResult(status=AccessStatus.ACCESS_ERROR)
                )
            raw = state.values[register.offset].to_bytes(
                register.size_bytes, self.byte_order.value
            )
            data = int.from_bytes(
                raw[byte_offset : byte_offset + request.size],
                self.byte_order.value,
            )
            effects = self._effects(register.read_effect, register, data, data)
            return AddressStep(state, AccessResult(data=data, effects=effects))

        if register.permission is RegisterPermission.READ_ONLY:
            return AddressStep(
                state, AccessResult(status=AccessStatus.ACCESS_ERROR)
            )
        old = state.values[register.offset]
        raw = bytearray(old.to_bytes(register.size_bytes, self.byte_order.value))
        incoming = request.data.to_bytes(request.size, self.byte_order.value)
        for index, value in enumerate(incoming):
            if request.effective_byte_enable & (1 << index):
                raw[byte_offset + index] = value
        candidate = int.from_bytes(raw, self.byte_order.value)
        assert register.write_mask is not None
        value = (old & ~register.write_mask) | (candidate & register.write_mask)
        values = dict(state.values)
        values[register.offset] = value
        effects = self._effects(register.write_effect, register, old, value)
        return AddressStep(
            RegisterRegionState(values), AccessResult(effects=effects)
        )

    def _register_for(self, offset: int, size: int) -> RegisterSpec | None:
        for register in self.registers:
            if register.offset <= offset and offset + size <= (
                register.offset + register.size_bytes
            ):
                return register
        return None

    def _effects(
        self,
        kind: str | None,
        register: RegisterSpec,
        previous: int,
        value: int,
    ) -> tuple[DutEffect, ...]:
        if kind is None:
            return ()
        return (
            DutEffect(
                kind,
                {
                    "region": self.name,
                    "register": register.name,
                    "previous": previous,
                    "value": value,
                },
            ),
        )

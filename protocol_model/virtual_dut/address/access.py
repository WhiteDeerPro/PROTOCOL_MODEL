"""Protocol-independent address operations shared by VirtualDut backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, Union

from ..backend.transition import DutEffect


class ByteOrder(str, Enum):
    LITTLE = "little"
    BIG = "big"


class AccessStatus(str, Enum):
    OK = "ok"
    DECODE_ERROR = "decode_error"
    ACCESS_ERROR = "access_error"


@dataclass(frozen=True)
class AddressRead:
    address: int
    size: int
    attributes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_access_shape(self.address, self.size)
        object.__setattr__(
            self, "attributes", MappingProxyType(dict(self.attributes))
        )


@dataclass(frozen=True)
class AddressWrite:
    address: int
    size: int
    data: int
    byte_enable: int | None = None
    attributes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_access_shape(self.address, self.size)
        if not isinstance(self.data, int) or isinstance(self.data, bool):
            raise ValueError("address write data must be an integer")
        if not 0 <= self.data < 1 << (8 * self.size):
            raise ValueError("address write data does not fit the access size")
        if self.byte_enable is not None and (
            not isinstance(self.byte_enable, int)
            or isinstance(self.byte_enable, bool)
            or not 0 <= self.byte_enable < 1 << self.size
        ):
            raise ValueError("byte enable does not fit the access size")
        object.__setattr__(
            self, "attributes", MappingProxyType(dict(self.attributes))
        )

    @property
    def effective_byte_enable(self) -> int:
        return (1 << self.size) - 1 if self.byte_enable is None else self.byte_enable


AddressAccess = Union[AddressRead, AddressWrite]


@dataclass(frozen=True)
class AccessResult:
    status: AccessStatus = AccessStatus.OK
    data: int | None = None
    effects: tuple[DutEffect, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.status is AccessStatus.OK


@dataclass(frozen=True)
class AddressStep:
    state: object
    result: AccessResult


def _validate_access_shape(address: int, size: int) -> None:
    if not isinstance(address, int) or isinstance(address, bool) or address < 0:
        raise ValueError("address must be a non-negative integer")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise ValueError("access size must be a positive integer")

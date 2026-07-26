"""Protocol-neutral ordered groups of address accesses."""

from __future__ import annotations

from dataclasses import dataclass

from .access import AccessResult, AddressAccess, AddressRead, AddressWrite


@dataclass(frozen=True)
class AddressBurst:
    """One ordered, homogeneous group of address accesses.

    The tuple records result order and child geometry.  It does not imply
    atomic visibility across the accesses; a bridge can already have issued
    earlier children when a later child completes with an error.
    """

    accesses: tuple[AddressAccess, ...]

    def __post_init__(self) -> None:
        accesses = tuple(self.accesses)
        if not accesses:
            raise ValueError("address burst requires at least one access")
        if any(
            not isinstance(access, (AddressRead, AddressWrite))
            for access in accesses
        ):
            raise TypeError(
                "address burst accepts AddressRead or AddressWrite values"
            )
        access_type = type(accesses[0])
        if any(type(access) is not access_type for access in accesses[1:]):
            raise ValueError("address burst accesses must share one direction")
        object.__setattr__(self, "accesses", accesses)

    @property
    def is_read(self) -> bool:
        return isinstance(self.accesses[0], AddressRead)

    @property
    def beat_count(self) -> int:
        return len(self.accesses)


@dataclass(frozen=True)
class AddressBurstResult:
    """Ordered child results returned for one ``AddressBurst``."""

    results: tuple[AccessResult, ...]

    def __post_init__(self) -> None:
        results = tuple(self.results)
        if not results:
            raise ValueError("address burst result requires at least one beat")
        if any(not isinstance(result, AccessResult) for result in results):
            raise TypeError("address burst results must be AccessResult values")
        object.__setattr__(self, "results", results)

    @property
    def beat_count(self) -> int:
        return len(self.results)


__all__ = ["AddressBurst", "AddressBurstResult"]

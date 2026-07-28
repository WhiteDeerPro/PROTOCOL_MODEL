"""Protocol-neutral full-line backing with explicit prepare/commit.

The core owns a fixed set of resident lines.  Preparing a write is pure and
captures only a line-local version; committing applies one patch to the
current state.  This lets independent lines commit in either order without
installing an old whole-store snapshot or losing another line's update.

Protocol messages, coherence permissions, directory ownership, and physical
memory transport remain outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


def _require_non_negative_integer(name: str, value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{name} must be a non-negative integer")


def _require_line_address(address: int, line_bytes: int) -> None:
    _require_non_negative_integer("backing-line address", address)
    if address % line_bytes:
        raise ValueError(
            f"backing-line address must be aligned to {line_bytes} bytes"
        )


@dataclass(frozen=True)
class BackingLine:
    """Caller-facing initial payload for one resident backing line."""

    address: int
    data: int

    def __post_init__(self) -> None:
        _require_non_negative_integer("backing-line address", self.address)
        _require_non_negative_integer("backing-line data", self.data)


@dataclass(frozen=True)
class BackingLineRecord:
    """Current payload and line-local commit version."""

    address: int
    data: int
    version: int = 0

    def __post_init__(self) -> None:
        _require_non_negative_integer(
            "backing-line record address", self.address
        )
        _require_non_negative_integer("backing-line record data", self.data)
        _require_non_negative_integer(
            "backing-line record version", self.version
        )


@dataclass(frozen=True)
class LineBackingState:
    """Immutable records owned by exactly one backing core."""

    lines: Mapping[int, BackingLineRecord] = field(default_factory=dict)
    _authority_token: object = field(
        default_factory=object,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        lines = dict(self.lines)
        if any(
            not isinstance(record, BackingLineRecord)
            or address != record.address
            for address, record in lines.items()
        ):
            raise ValueError(
                "line-backing mapping keys must match BackingLineRecord "
                "addresses"
            )
        object.__setattr__(self, "lines", MappingProxyType(lines))

    def line_at(self, address: int) -> BackingLineRecord | None:
        return self.lines.get(address)


@dataclass(frozen=True)
class PreparedBackingWrite:
    """A pure line patch guarded by its observed line-local version."""

    address: int
    data: int
    expected_version: int
    _authority_token: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_non_negative_integer(
            "prepared backing address", self.address
        )
        _require_non_negative_integer("prepared backing data", self.data)
        _require_non_negative_integer(
            "prepared backing version", self.expected_version
        )


@dataclass(frozen=True)
class BackingMutation:
    """One committed line update and the record it replaced."""

    state: LineBackingState
    previous: BackingLineRecord

    def __post_init__(self) -> None:
        if not isinstance(self.state, LineBackingState):
            raise TypeError(
                "backing mutation state requires LineBackingState"
            )
        if not isinstance(self.previous, BackingLineRecord):
            raise TypeError(
                "backing mutation previous requires BackingLineRecord"
            )


class BackingCommitConflict(RuntimeError):
    """A prepared line version no longer matches the backing authority."""


class FullLineBackingCore:
    """Fixed-resident full-line storage with line-local atomic commit.

    The core is protocol-neutral and not topology-visible by itself.  It
    validates construction and creates immutable runtime states.  Every state
    and prepared write carries an identity token so another core cannot
    accidentally accept it, even when both cores have identical contents.
    """

    def __init__(
        self,
        name: str,
        *,
        line_bytes: int,
        initial_lines: tuple[BackingLine, ...] = (),
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("full-line backing core requires a name")
        if (
            not isinstance(line_bytes, int)
            or isinstance(line_bytes, bool)
            or line_bytes <= 0
        ):
            raise ValueError("full-line backing size must be positive")
        lines = tuple(initial_lines)
        records: dict[int, BackingLineRecord] = {}
        for line in lines:
            if not isinstance(line, BackingLine):
                raise TypeError(
                    "full-line backing initial lines require BackingLine"
                )
            _require_line_address(line.address, line_bytes)
            self._require_data_width(line.data, line_bytes)
            if line.address in records:
                raise ValueError(
                    "full-line backing initial addresses must be unique"
                )
            records[line.address] = BackingLineRecord(
                line.address,
                line.data,
            )
        self.name = name
        self.line_bytes = line_bytes
        self.initial_lines = lines
        self._initial_records = MappingProxyType(records)
        self._authority_token = object()

    def initial_state(self) -> LineBackingState:
        return LineBackingState(
            self._initial_records,
            self._authority_token,
        )

    def read_line(
        self,
        state: LineBackingState,
        address: int,
    ) -> int:
        self._require_state(state)
        _require_line_address(address, self.line_bytes)
        try:
            return state.lines[address].data
        except KeyError as error:
            raise KeyError(
                f"full-line backing has no line at {address:#x}"
            ) from error

    def prepare_write(
        self,
        state: LineBackingState,
        address: int,
        data: int,
    ) -> PreparedBackingWrite:
        """Validate and describe a write without changing ``state``."""

        self._require_state(state)
        _require_line_address(address, self.line_bytes)
        self._require_data_width(data, self.line_bytes)
        try:
            record = state.lines[address]
        except KeyError as error:
            raise KeyError(
                f"full-line backing has no line at {address:#x}"
            ) from error
        return PreparedBackingWrite(
            address,
            data,
            record.version,
            self._authority_token,
        )

    def commit_write(
        self,
        state: LineBackingState,
        prepared: PreparedBackingWrite,
    ) -> BackingMutation:
        """Commit one prepared patch or reject a stale line version.

        No mutation occurs before all identity and version checks pass.  The
        replacement starts from the supplied current mapping rather than a
        whole-store snapshot captured by :meth:`prepare_write`.
        """

        self._require_state(state)
        if not isinstance(prepared, PreparedBackingWrite):
            raise TypeError(
                "full-line backing commit requires PreparedBackingWrite"
            )
        if prepared._authority_token is not self._authority_token:
            raise ValueError(
                "prepared backing write belongs to another backing core"
            )
        _require_line_address(prepared.address, self.line_bytes)
        self._require_data_width(prepared.data, self.line_bytes)
        current = state.lines.get(prepared.address)
        if current is None:
            raise BackingCommitConflict(
                f"prepared backing line {prepared.address:#x} is no longer "
                "resident"
            )
        if current.version != prepared.expected_version:
            raise BackingCommitConflict(
                f"prepared backing line {prepared.address:#x} expected "
                f"version {prepared.expected_version}, found "
                f"{current.version}"
            )
        lines = dict(state.lines)
        lines[prepared.address] = BackingLineRecord(
            prepared.address,
            prepared.data,
            current.version + 1,
        )
        return BackingMutation(
            LineBackingState(lines, self._authority_token),
            current,
        )

    def _require_state(self, state: LineBackingState) -> None:
        if not isinstance(state, LineBackingState):
            raise TypeError(
                "full-line backing core requires LineBackingState"
            )
        if state._authority_token is not self._authority_token:
            raise ValueError(
                "line-backing state belongs to another backing core"
            )

    @staticmethod
    def _require_data_width(data: int, line_bytes: int) -> None:
        _require_non_negative_integer("backing-line data", data)
        if data >= 1 << (line_bytes * 8):
            raise ValueError("backing-line data does not fit the line")


__all__ = [
    "BackingCommitConflict",
    "BackingLine",
    "BackingLineRecord",
    "BackingMutation",
    "FullLineBackingCore",
    "LineBackingState",
    "PreparedBackingWrite",
]

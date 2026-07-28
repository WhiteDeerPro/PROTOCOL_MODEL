"""Pure deterministic arbitration primitives shared by VirtualDut backends."""

from __future__ import annotations

from typing import Collection, Hashable, TypeVar


Token = TypeVar("Token", bound=Hashable)


def _validated_order(
    order: tuple[Token, ...], eligible: Collection[Token]
) -> tuple[tuple[Token, ...], frozenset[Token]]:
    order = tuple(order)
    if not order:
        raise ValueError("round-robin arbitration requires a candidate order")
    try:
        known = frozenset(order)
        selected = frozenset(eligible)
    except TypeError as error:
        raise TypeError("round-robin candidates must be hashable") from error
    if len(known) != len(order):
        raise ValueError("round-robin candidate order must be unique")
    unknown = selected - known
    if unknown:
        raise ValueError(
            "round-robin eligible set has unknown candidates: "
            f"{sorted(unknown, key=repr)!r}"
        )
    return order, selected


def round_robin_grant(
    order: tuple[Token, ...],
    eligible: Collection[Token],
    cursor: int,
) -> tuple[Token, int] | None:
    """Grant from a stable order and return the successor cursor.

    This form suits a fabric whose candidate ports remain fixed.  An
    uncontended grant still advances the cursor, so future contention starts
    after the most recently served candidate.
    """

    order, selected = _validated_order(order, eligible)
    if (
        not isinstance(cursor, int)
        or isinstance(cursor, bool)
        or not 0 <= cursor < len(order)
    ):
        raise ValueError("round-robin cursor is outside the candidate order")
    for offset in range(len(order)):
        index = (cursor + offset) % len(order)
        winner = order[index]
        if winner in selected:
            return winner, (index + 1) % len(order)
    return None


def round_robin_select(
    order: tuple[Token, ...],
    eligible: Collection[Token],
    *,
    after: Token | None = None,
) -> Token | None:
    """Select after the previous token from a changing candidate order.

    This form suits transient transaction batches.  If the previous token has
    already retired, selection restarts at the beginning of the current order;
    subsequent accepted grants again rotate from the returned token.
    """

    order, selected = _validated_order(order, eligible)
    start = 0
    if after in order:
        start = (order.index(after) + 1) % len(order)
    for offset in range(len(order)):
        candidate = order[(start + offset) % len(order)]
        if candidate in selected:
            return candidate
    return None


__all__ = ["round_robin_grant", "round_robin_select"]

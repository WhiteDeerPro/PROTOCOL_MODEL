from __future__ import annotations

import unittest

from protocol_model.virtual_dut.arbitration import (
    round_robin_grant,
    round_robin_select,
)


class VirtualDutArbitrationTest(unittest.TestCase):
    def test_fixed_order_grant_returns_successor_cursor(self) -> None:
        first = round_robin_grant(("m0", "m1", "m2"), {"m0", "m2"}, 1)
        second = round_robin_grant(("m0", "m1", "m2"), {"m0", "m2"}, 0)

        self.assertEqual(("m2", 0), first)
        self.assertEqual(("m0", 1), second)

    def test_dynamic_selection_rotates_after_last_live_token(self) -> None:
        order = (10, 20, 30)

        self.assertEqual(20, round_robin_select(order, order, after=10))
        self.assertEqual(30, round_robin_select(order, {10, 30}, after=20))
        self.assertEqual(10, round_robin_select(order, order, after=30))

    def test_retired_previous_token_restarts_current_rotation(self) -> None:
        self.assertEqual(
            10,
            round_robin_select((10, 30), (10, 30), after=20),
        )


if __name__ == "__main__":
    unittest.main()

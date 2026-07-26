from __future__ import annotations

import unittest

from protocol_model.virtual_dut import (
    CacheCore,
    CacheLinePayload,
    CacheLineStore,
)


class CacheLineStoreTest(unittest.TestCase):
    def test_install_and_remove_preserve_immutable_state(self) -> None:
        store = CacheLineStore[
            CacheLinePayload
        ](
            "l1.lines",
            line_bytes=64,
            initial_lines=(CacheLinePayload(0x1000, 0x11),),
        )
        initial = store.initial_state()
        core = CacheCore("l1", store)

        installed = store.install(
            initial,
            CacheLinePayload(0x1040, 0x22),
        )
        removed = store.remove(installed.state, 0x1000)

        self.assertEqual({0x1000}, set(initial.lines))
        self.assertIs(store, core.line_store)
        self.assertEqual(initial, core.initial_state())
        self.assertEqual({0x1000, 0x1040}, set(installed.state.lines))
        self.assertEqual({0x1040}, set(removed.state.lines))
        self.assertEqual(0x11, removed.previous.data)

    def test_store_enforces_alignment_and_payload_width(self) -> None:
        with self.assertRaisesRegex(ValueError, "aligned"):
            CacheLineStore(
                "misaligned",
                line_bytes=64,
                initial_lines=(CacheLinePayload(1, 0),),
            )
        with self.assertRaisesRegex(ValueError, "does not fit"):
            CacheLineStore(
                "too_wide",
                line_bytes=1,
                initial_lines=(CacheLinePayload(0, 0x100),),
            )


if __name__ == "__main__":
    unittest.main()

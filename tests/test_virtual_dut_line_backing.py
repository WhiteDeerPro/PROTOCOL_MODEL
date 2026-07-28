from __future__ import annotations

import unittest

from protocol_model.virtual_dut.backend import (
    BackingCommitConflict,
    BackingLine,
    FullLineBackingCore,
)


class FullLineBackingCoreTest(unittest.TestCase):
    ADDRESS_A = 0x1000
    ADDRESS_B = 0x1040

    def build_core(self, name: str = "memory") -> FullLineBackingCore:
        return FullLineBackingCore(
            name,
            line_bytes=64,
            initial_lines=(
                BackingLine(self.ADDRESS_A, 0x11),
                BackingLine(self.ADDRESS_B, 0x22),
            ),
        )

    def test_initial_state_is_immutable_and_versioned_per_line(self) -> None:
        core = self.build_core()
        state = core.initial_state()

        self.assertEqual(0x11, core.read_line(state, self.ADDRESS_A))
        self.assertEqual(0, state.line_at(self.ADDRESS_A).version)
        with self.assertRaises(TypeError):
            state.lines[self.ADDRESS_A] = state.lines[self.ADDRESS_B]

    def test_prepare_is_pure_and_commit_replaces_one_line(self) -> None:
        core = self.build_core()
        initial = core.initial_state()

        prepared = core.prepare_write(initial, self.ADDRESS_A, 0xAA)

        self.assertEqual(0x11, core.read_line(initial, self.ADDRESS_A))
        self.assertEqual(0, prepared.expected_version)
        committed = core.commit_write(initial, prepared)
        self.assertEqual(0x11, committed.previous.data)
        self.assertEqual(0, committed.previous.version)
        self.assertEqual(0xAA, core.read_line(
            committed.state,
            self.ADDRESS_A,
        ))
        self.assertEqual(1, committed.state.line_at(self.ADDRESS_A).version)
        self.assertEqual(0x22, core.read_line(
            committed.state,
            self.ADDRESS_B,
        ))
        self.assertEqual(0x11, core.read_line(initial, self.ADDRESS_A))

    def test_same_line_stale_and_duplicate_commits_are_rejected(self) -> None:
        core = self.build_core()
        initial = core.initial_state()
        first = core.prepare_write(initial, self.ADDRESS_A, 0xAA)
        stale = core.prepare_write(initial, self.ADDRESS_A, 0xBB)
        committed = core.commit_write(initial, first)

        with self.assertRaisesRegex(
            BackingCommitConflict,
            "expected version 0, found 1",
        ):
            core.commit_write(committed.state, stale)
        with self.assertRaises(BackingCommitConflict):
            core.commit_write(committed.state, first)

        self.assertEqual(
            0xAA,
            core.read_line(committed.state, self.ADDRESS_A),
        )

    def test_different_line_commits_preserve_interleaved_updates(self) -> None:
        core = self.build_core()
        initial = core.initial_state()
        write_a = core.prepare_write(initial, self.ADDRESS_A, 0xAA)
        write_b = core.prepare_write(initial, self.ADDRESS_B, 0xBB)

        committed_b = core.commit_write(initial, write_b)
        committed_a = core.commit_write(committed_b.state, write_a)

        self.assertEqual(
            0xAA,
            core.read_line(committed_a.state, self.ADDRESS_A),
        )
        self.assertEqual(
            0xBB,
            core.read_line(committed_a.state, self.ADDRESS_B),
        )
        self.assertEqual(1, committed_a.state.line_at(
            self.ADDRESS_A
        ).version)
        self.assertEqual(1, committed_a.state.line_at(
            self.ADDRESS_B
        ).version)

    def test_state_and_prepared_write_are_bound_to_core_identity(self) -> None:
        first = self.build_core("first")
        second = self.build_core("second")
        first_state = first.initial_state()
        second_state = second.initial_state()
        prepared = first.prepare_write(
            first_state,
            self.ADDRESS_A,
            0xAA,
        )

        with self.assertRaisesRegex(ValueError, "another backing core"):
            second.prepare_write(
                first_state,
                self.ADDRESS_A,
                0xBB,
            )
        with self.assertRaisesRegex(ValueError, "another backing core"):
            second.commit_write(second_state, prepared)

    def test_construction_enforces_fixed_line_geometry(self) -> None:
        with self.assertRaisesRegex(ValueError, "aligned"):
            FullLineBackingCore(
                "misaligned",
                line_bytes=64,
                initial_lines=(BackingLine(1, 0),),
            )
        with self.assertRaisesRegex(ValueError, "does not fit"):
            FullLineBackingCore(
                "too-wide",
                line_bytes=1,
                initial_lines=(BackingLine(0, 0x100),),
            )
        with self.assertRaisesRegex(ValueError, "unique"):
            FullLineBackingCore(
                "duplicate",
                line_bytes=64,
                initial_lines=(
                    BackingLine(self.ADDRESS_A, 0x11),
                    BackingLine(self.ADDRESS_A, 0x22),
                ),
            )


if __name__ == "__main__":
    unittest.main()

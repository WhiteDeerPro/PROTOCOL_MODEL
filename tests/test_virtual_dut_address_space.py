from __future__ import annotations

import unittest

from protocol_model import (
    AccessStatus,
    AddressRead,
    AddressSpace,
    AddressWrite,
    MemoryRegion,
    RegisterPermission,
    RegisterRegion,
    RegisterSpec,
)


class AddressSpaceTest(unittest.TestCase):
    def test_regions_dispatch_storage_and_register_effects(self) -> None:
        registers = RegisterRegion(
            "control",
            (
                RegisterSpec("source", 0x00, reset=0x12345678),
                RegisterSpec(
                    "status",
                    0x04,
                    permission=RegisterPermission.READ_ONLY,
                ),
                RegisterSpec(
                    "start", 0x08, write_mask=1, write_effect="dma.start"
                ),
            ),
            base_address=0x1000,
        )
        memory = MemoryRegion(
            "buffer", 0x100, base_address=0x2000, initial_content=b"\x11\x22"
        )
        space = AddressSpace((memory, registers))
        state = space.initial_state()

        narrow = space.access(state, AddressRead(0x1001, 2))
        self.assertEqual(0x3456, narrow.result.data)

        started = space.access(narrow.state, AddressWrite(0x1008, 4, 1))
        self.assertEqual("dma.start", started.result.effects[0].kind)
        self.assertEqual("start", started.result.effects[0].payload["register"])

        written = space.access(
            started.state,
            AddressWrite(0x2001, 4, 0xAABBCCDD, byte_enable=0b1011),
        )
        read = space.access(written.state, AddressRead(0x2000, 5))
        self.assertEqual(0xAA00CCDD11, read.result.data)

    def test_access_outcomes_are_results_not_model_faults(self) -> None:
        space = AddressSpace(
            (
                RegisterRegion(
                    "control",
                    (
                        RegisterSpec(
                            "status",
                            0,
                            permission=RegisterPermission.READ_ONLY,
                        ),
                    ),
                    base_address=0x1000,
                ),
            )
        )
        state = space.initial_state()

        denied = space.access(state, AddressWrite(0x1000, 4, 1))
        missing = space.access(state, AddressRead(0x2000, 4))

        self.assertEqual(AccessStatus.ACCESS_ERROR, denied.result.status)
        self.assertEqual(AccessStatus.DECODE_ERROR, missing.result.status)


if __name__ == "__main__":
    unittest.main()

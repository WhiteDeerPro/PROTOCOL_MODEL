from __future__ import annotations

import unittest

from showcase.demos.system.chi_issue_h_clean_2x2_mesh.model import (
    execute_clean_mesh,
)


class ChiIssueHShowcaseResourceTest(unittest.TestCase):
    """Keep the executable mesh recipe live without publishing artifacts."""

    def test_clean_2x2_mesh_is_executable_evidence(self) -> None:
        _, result = execute_clean_mesh()

        self.assertEqual("PASS", result["verdict"])
        self.assertEqual(7, len(result["packets"]))
        self.assertEqual(
            4,
            len(result["topology"]["used_physical_edges"]),
        )
        self.assertTrue(all(result["assertions"].values()))

if __name__ == "__main__":
    unittest.main()

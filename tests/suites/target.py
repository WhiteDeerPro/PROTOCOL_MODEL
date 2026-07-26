"""Target selected through the TEST_TARGET environment variable."""

from __future__ import annotations

import os
import unittest

from .manifest import TARGET_MODULES, target_suite


def load_tests(
    loader: unittest.TestLoader,
    _standard_tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    target = os.environ.get("TEST_TARGET", "")
    if not target:
        supported = ", ".join(sorted(TARGET_MODULES))
        raise ValueError(
            "TEST_TARGET is required; choose one of: "
            f"{supported}"
        )
    return target_suite(loader, target)

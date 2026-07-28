"""Named compatibility checks with explicit removal conditions."""

from __future__ import annotations

import unittest

from .manifest import sentinel_suite


def load_tests(
    loader: unittest.TestLoader,
    _standard_tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    return sentinel_suite(loader)

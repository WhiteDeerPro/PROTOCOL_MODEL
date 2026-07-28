"""All maintained tests except explicit legacy sentinels."""

from __future__ import annotations

import unittest

from .manifest import active_suite


def load_tests(
    loader: unittest.TestLoader,
    _standard_tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    return active_suite(loader)

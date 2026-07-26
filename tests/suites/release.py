"""Complete discovered suite, including legacy sentinels and release witnesses."""

from __future__ import annotations

import unittest

from .manifest import release_suite


def load_tests(
    loader: unittest.TestLoader,
    _standard_tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    return release_suite(loader)

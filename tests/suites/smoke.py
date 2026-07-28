"""Fast, representative edit-loop suite."""

from __future__ import annotations

import unittest

from .manifest import smoke_suite


def load_tests(
    loader: unittest.TestLoader,
    _standard_tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    return smoke_suite(loader)

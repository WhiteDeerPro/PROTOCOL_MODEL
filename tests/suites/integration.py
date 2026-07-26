"""Concrete protocol plus SystemProtocol integration checks."""

from __future__ import annotations

import unittest

from .manifest import integration_suite


def load_tests(
    loader: unittest.TestLoader,
    _standard_tests: unittest.TestSuite,
    _pattern: str | None,
) -> unittest.TestSuite:
    return integration_suite(loader)

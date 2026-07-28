from __future__ import annotations

import unittest

from tests.suites.manifest import (
    CLASSIFIED_MODULES,
    LEGACY_SENTINELS,
    LIMITATION_NEGATIVES,
    SMOKE_MODULES,
    TARGET_MODULES,
    active_suite,
    discover_all,
    integration_suite,
    iter_tests,
    legacy_sentinel_ids,
    release_suite,
    sentinel_suite,
    smoke_suite,
    suite_ids,
    target_suite,
)


class SuiteManifestTest(unittest.TestCase):
    def test_manifest_is_closed_runnable_and_has_no_hidden_skips(self) -> None:
        loader = unittest.TestLoader()
        discovered = discover_all(loader)
        discovered_tests = tuple(iter_tests(discovered))
        discovered_ids = frozenset(test.id() for test in discovered_tests)

        self.assertFalse(loader.errors, "\n".join(loader.errors))
        self.assertEqual(len(discovered_tests), len(discovered_ids))
        self.assertEqual(
            {test.__class__.__module__ for test in discovered_tests},
            set(CLASSIFIED_MODULES),
        )

        active_ids = frozenset(suite_ids(active_suite(unittest.TestLoader())))
        sentinel_ids = legacy_sentinel_ids()
        self.assertFalse(active_ids & sentinel_ids)
        self.assertEqual(discovered_ids, active_ids | sentinel_ids)
        self.assertEqual(
            sentinel_ids,
            frozenset(suite_ids(sentinel_suite(unittest.TestLoader()))),
        )
        self.assertEqual(
            discovered_ids,
            frozenset(suite_ids(release_suite(unittest.TestLoader()))),
        )

        smoke_ids = frozenset(suite_ids(smoke_suite(unittest.TestLoader())))
        integration_ids = frozenset(
            suite_ids(integration_suite(unittest.TestLoader()))
        )
        self.assertTrue(smoke_ids)
        self.assertLessEqual(smoke_ids, active_ids)
        self.assertLessEqual(integration_ids, active_ids)
        self.assertLessEqual(set(SMOKE_MODULES), set(CLASSIFIED_MODULES))

        for name, _modules in TARGET_MODULES.items():
            with self.subTest(target=name):
                target_ids = frozenset(
                    suite_ids(target_suite(unittest.TestLoader(), name))
                )
                self.assertTrue(target_ids)
                self.assertLessEqual(target_ids, active_ids)

        limitation_ids = frozenset(
            item.test_id for item in LIMITATION_NEGATIVES
        )
        self.assertLessEqual(limitation_ids, active_ids)
        self.assertEqual(
            len(LEGACY_SENTINELS),
            len(sentinel_ids),
            "legacy sentinels must have unique test IDs",
        )
        for sentinel in LEGACY_SENTINELS:
            with self.subTest(sentinel=sentinel.test_id):
                self.assertTrue(sentinel.owner)
                self.assertTrue(sentinel.reason)
                self.assertTrue(sentinel.removal_condition)
        for limitation in LIMITATION_NEGATIVES:
            with self.subTest(limitation=limitation.test_id):
                self.assertTrue(limitation.turn_positive_when)

        skipped: list[str] = []
        expected_failures: list[str] = []
        for test in discovered_tests:
            method = getattr(test, test._testMethodName)
            if getattr(test.__class__, "__unittest_skip__", False) or getattr(
                method, "__unittest_skip__", False
            ):
                skipped.append(test.id())
            if getattr(
                method, "__unittest_expecting_failure__", False
            ):
                expected_failures.append(test.id())
        self.assertEqual([], skipped)
        self.assertEqual([], expected_failures)


if __name__ == "__main__":
    unittest.main()

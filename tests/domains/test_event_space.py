from random import Random
import unittest

from protocol_model.domains import BitVectorDomain, EventSpace, IntDomain
from protocol_model.core import CanonicalEvent


class DomainTests(unittest.TestCase):
    def test_aligned_integer_sampling_and_membership_share_one_domain(self):
        domain = IntDomain(4, 100, alignment=4)
        rng = Random(9)
        values = [domain.sample(rng) for _ in range(100)]
        self.assertTrue(all(domain.contains(value) for value in values))
        self.assertFalse(domain.contains(6))
        self.assertIn("not aligned", domain.explain(6))

    def test_event_space_explains_schema_failure(self):
        space = EventSpace("word", BitVectorDomain(2), {"data": BitVectorDomain(8)})
        malformed = CanonicalEvent("word", 0, {"data": 300})
        self.assertFalse(space.contains(malformed))
        self.assertIn("payload.data", space.explain(malformed)[0])


if __name__ == "__main__":
    unittest.main()

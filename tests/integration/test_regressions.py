import unittest

from shadow_practice.domain import GroupRange, normalized_groups, validate_groups
from shadow_practice.domain.speaks import build_speaks_from_groups


class RegressionTests(unittest.TestCase):
    def test_speaks_builder_is_pure(self):
        self.assertEqual(build_speaks_from_groups([], []), [])

    def test_normalization_does_not_mutate_inputs(self):
        words = [{"word": "a", "start": -1.0, "end": 1.0, "speaker": "A"}]
        groups = [GroupRange(0, 1)]
        result = normalized_groups(words, groups, 10.0)
        self.assertEqual(words[0]["start"], -1.0)
        self.assertEqual(result.words[0]["start"], 0.0)
        validate_groups(list(result.words), list(result.groups))


if __name__ == "__main__":
    unittest.main()

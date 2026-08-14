import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "coa_tools2"))

from rig_control.semantic_transition import (  # noqa: E402
    discrete_state_key,
    smooth_compensation_keys,
)


class SemanticTransitionTests(unittest.TestCase):
    def test_public_state_is_one_constant_key(self):
        key = discrete_state_key(12, 1)
        self.assertEqual((12.0, 1.0, "CONSTANT"), (
            key.frame,
            key.value,
            key.interpolation,
        ))

    def test_private_compensation_is_a_separate_smooth_ramp(self):
        keys = smooth_compensation_keys(12, 1.0, 0.0, 3)
        self.assertEqual((12.0, 15.0), tuple(key.frame for key in keys))
        self.assertEqual((1.0, 0.0), tuple(key.value for key in keys))
        self.assertEqual(("BEZIER", "BEZIER"), tuple(
            key.interpolation for key in keys
        ))

    def test_compensation_rejects_zero_length_transition(self):
        with self.assertRaisesRegex(ValueError, "at least one frame"):
            smooth_compensation_keys(1, 0.0, 1.0, 0)


if __name__ == "__main__":
    unittest.main()

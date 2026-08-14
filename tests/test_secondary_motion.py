import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON_ROOT = ROOT / "coa_tools2"
sys.path.insert(0, str(ADDON_ROOT))

from rig_control.secondary_motion import (  # noqa: E402
    SecondaryMotionSettings,
    filter_secondary_motion,
    simulate_secondary_motion,
)


class SecondaryMotionTests(unittest.TestCase):
    @staticmethod
    def _step_targets(frame_count=240):
        return [(0.0,)] + [(1.0,)] * (frame_count - 1)

    def test_same_input_is_deterministic_and_not_mutated(self):
        targets = [[0.0, 1.0, 2.0], [1.0, 0.5, -1.0], [2.0, 0.0, 1.0]]
        original = [item[:] for item in targets]
        settings = SecondaryMotionSettings(
            frequency_hz=2.5,
            damping_ratio=0.65,
            substeps=3,
            dt=1.0 / 30.0,
        )
        first = simulate_secondary_motion(targets, settings)
        second = simulate_secondary_motion(targets, settings)
        self.assertEqual(first, second)
        self.assertEqual(original, targets)
        self.assertEqual(3, len(first.locations))
        self.assertEqual(3, len(first.locations[0]))

    def test_critical_damping_is_monotonic_for_step_target(self):
        locations = filter_secondary_motion(
            self._step_targets(),
            SecondaryMotionSettings(
                frequency_hz=2.0,
                damping_ratio=1.0,
                substeps=2,
                dt=1.0 / 60.0,
            ),
        )
        values = [item[0] for item in locations]
        self.assertTrue(
            all(after >= before - 1.0e-12 for before, after in zip(values, values[1:]))
        )
        self.assertLessEqual(max(values), 1.0 + 1.0e-12)
        self.assertAlmostEqual(1.0, values[-1], places=10)

    def test_under_damping_overshoots_and_converges(self):
        locations = filter_secondary_motion(
            self._step_targets(),
            SecondaryMotionSettings(
                frequency_hz=2.0,
                damping_ratio=0.2,
                substeps=2,
                dt=1.0 / 60.0,
            ),
        )
        values = [item[0] for item in locations]
        self.assertGreater(max(values), 1.05)
        self.assertAlmostEqual(1.0, values[-1], places=3)

    def test_over_damping_is_finite_monotonic_and_convergent(self):
        result = simulate_secondary_motion(
            self._step_targets(480),
            SecondaryMotionSettings(
                frequency_hz=2.0,
                damping_ratio=2.5,
                substeps=4,
                dt=1.0 / 60.0,
            ),
        )
        values = [item[0] for item in result.locations]
        self.assertTrue(all(math.isfinite(value) for value in values))
        self.assertTrue(
            all(after >= before - 1.0e-12 for before, after in zip(values, values[1:]))
        )
        self.assertLessEqual(max(values), 1.0 + 1.0e-12)
        self.assertAlmostEqual(1.0, values[-1], places=8)

    def test_linear_target_solution_is_substep_invariant(self):
        targets = [(0.0,), (0.4,), (1.0,), (-0.25,), (0.5,)]
        base = filter_secondary_motion(
            targets,
            SecondaryMotionSettings(
                frequency_hz=3.0,
                damping_ratio=0.8,
                substeps=1,
                dt=0.2,
            ),
        )
        refined = filter_secondary_motion(
            targets,
            SecondaryMotionSettings(
                frequency_hz=3.0,
                damping_ratio=0.8,
                substeps=16,
                dt=0.2,
            ),
        )
        for expected, actual in zip(base, refined):
            self.assertAlmostEqual(expected[0], actual[0], places=12)

    def test_equal_seconds_match_across_24_and_48_fps(self):
        def target_at(time):
            if time <= 0.5:
                return time * 2.0
            if time <= 1.0:
                return 1.0
            if time <= 1.5:
                return 3.0 - time * 2.0
            return 0.0

        targets_24 = [(target_at(frame / 24.0),) for frame in range(49)]
        targets_48 = [(target_at(frame / 48.0),) for frame in range(97)]
        result_24 = filter_secondary_motion(
            targets_24,
            SecondaryMotionSettings(
                frequency_hz=2.25,
                damping_ratio=0.55,
                substeps=1,
                dt=1.0 / 24.0,
            ),
        )
        result_48 = filter_secondary_motion(
            targets_48,
            SecondaryMotionSettings(
                frequency_hz=2.25,
                damping_ratio=0.55,
                substeps=1,
                dt=1.0 / 48.0,
            ),
        )
        for frame, value_24 in enumerate(result_24):
            self.assertAlmostEqual(value_24[0], result_48[frame * 2][0], places=11)

    def test_pre_roll_advances_explicit_initial_state_toward_first_target(self):
        without_pre_roll = simulate_secondary_motion(
            [(0.0,), (0.0,)],
            SecondaryMotionSettings(pre_roll=0.0),
            initial_location=(10.0,),
        )
        with_pre_roll = simulate_secondary_motion(
            [(0.0,), (0.0,)],
            SecondaryMotionSettings(pre_roll=0.5),
            initial_location=(10.0,),
        )
        self.assertEqual(10.0, without_pre_roll.locations[0][0])
        self.assertLess(abs(with_pre_roll.locations[0][0]), 0.1)

    def test_invalid_settings_and_vector_sizes_are_rejected(self):
        with self.assertRaises(ValueError):
            filter_secondary_motion(
                [(0.0,)], SecondaryMotionSettings(frequency_hz=0.0)
            )
        with self.assertRaises(ValueError):
            filter_secondary_motion(
                [(0.0,)], SecondaryMotionSettings(damping_ratio=-0.1)
            )
        with self.assertRaises(ValueError):
            filter_secondary_motion([(0.0,), (1.0, 2.0)])


if __name__ == "__main__":
    unittest.main()

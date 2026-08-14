import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "coa_tools2"))

from rig_control.instance_fork import (  # noqa: E402
    RigControlIdentifierSnapshot,
    build_rig_control_identifier_forks,
)


class RigControlIdentifierForkTests(unittest.TestCase):
    def test_nested_identifiers_are_fresh_and_fallback_remap_is_complete(self):
        snapshots = (
            RigControlIdentifierSnapshot(
                control_uuid="control-a",
                tip_widget_uuid="tip-a",
                base_widget_uuid="base-a",
                binding_uuids=("binding-a", "binding-b"),
                state_uuids=("rest", "smile", "round"),
                cell_uuids=("cell-a",),
            ),
            RigControlIdentifierSnapshot(
                control_uuid="control-b",
                binding_uuids=(),
                state_uuids=("idle", "open"),
                cell_uuids=(),
            ),
        )
        generated = iter(f"new-{index}" for index in range(30))
        forks = build_rig_control_identifier_forks(
            snapshots,
            uuid_factory=lambda: next(generated),
        )

        values = []
        for fork in forks:
            values.extend(
                (
                    fork.control_uuid,
                    fork.tip_widget_uuid,
                    fork.base_widget_uuid,
                    *fork.binding_uuids,
                    *fork.state_uuids,
                    *fork.cell_uuids,
                )
            )
        self.assertEqual(len(values), len(set(values)))
        self.assertFalse(set(values).intersection({
            "control-a", "tip-a", "base-a", "binding-a", "binding-b",
            "rest", "smile", "round", "cell-a", "control-b", "idle", "open",
        }))
        self.assertEqual(
            dict(forks[0].state_uuid_remap),
            dict(zip(("rest", "smile", "round"), forks[0].state_uuids)),
        )

    def test_bad_uuid_factory_is_rejected(self):
        with self.assertRaises(ValueError):
            build_rig_control_identifier_forks(
                (RigControlIdentifierSnapshot(control_uuid="same"),),
                uuid_factory=lambda: "same",
            )


if __name__ == "__main__":
    unittest.main()

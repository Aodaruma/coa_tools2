"""Reversible viewport display preset for generated COA rig bones."""

from __future__ import annotations

import json

import bpy

from ... import functions
from .properties import get_rig_data


_SNAPSHOT_KEY = "coa_rig_animator_display_backup"
_IDENTITY_KEYS = (
    "coa_rig_instance_id",
    "coa_rig_control_uuid",
    "coa_rig_artifact_role",
    "coa_rig_component_uuid",
    "coa_rig_component_role",
)
_NORMAL_COLORS = {
    "PRIMARY": (0.25, 0.78, 0.90),
    "FK": (0.45, 0.65, 0.98),
    "HANDLE": (0.98, 0.64, 0.28),
    "POLE": (0.78, 0.57, 0.96),
    "DISPLAY": (0.66, 0.73, 0.80),
}


def _identity(bone):
    return tuple(str(bone.get(key, "")) for key in _IDENTITY_KEYS)


def _control_kind(bone):
    state_role = bone.get("coa_rig_artifact_role", "")
    if state_role == "control_bone":
        return "PRIMARY"
    if state_role == "display_bone":
        return "DISPLAY"
    role = str(bone.get("coa_rig_component_role", ""))
    if role.startswith("semantic:"):
        role = role.split(":", 2)[-1]
    if role == "control_bone":
        return "PRIMARY"
    if role in {"bend_control", "pole_control"}:
        return "POLE"
    if role.startswith("fk_control:"):
        return "FK"
    if role.startswith(("spline_control:", "bbone_point:")):
        return "PRIMARY"
    if role.startswith("bbone_handle:"):
        return "HANDLE"
    return None


def _targets(armature):
    rig = get_rig_data(armature, migrate=False)
    instance_id = rig.rig_instance_id
    controls = {item.control_uuid for item in rig.rig_controls if item.control_uuid}
    components = {
        item.component_uuid for item in rig.rig_components if item.component_uuid
    }
    for bone in armature.data.bones:
        if not bone.get("coa_rig_managed") or not instance_id:
            continue
        if bone.get("coa_rig_instance_id") != instance_id:
            continue
        if (
            bone.get("coa_rig_control_uuid") in controls
            or bone.get("coa_rig_component_uuid") in components
        ):
            yield bone


def _color_snapshot(color):
    return {
        "palette": color.palette,
        "normal": list(color.custom.normal),
        "select": list(color.custom.select),
        "active": list(color.custom.active),
    }


def _restore_color(color, snapshot):
    color.palette = "CUSTOM"
    for name in ("normal", "select", "active"):
        setattr(color.custom, name, snapshot[name])
    color.palette = snapshot["palette"]


def _set_color(color, kind):
    color.palette = "CUSTOM"
    color.custom.normal = _NORMAL_COLORS[kind]
    color.custom.select = (1.0, 0.80, 0.30)
    color.custom.active = (1.0, 0.96, 0.68)


def _check_armature(armature):
    if armature is None or armature.type != "ARMATURE":
        raise ValueError("Choose a COA armature.")
    if armature.mode == "EDIT":
        raise ValueError("Leave Edit Mode before changing rig display.")
    if armature.library or armature.data.library:
        raise ValueError("Rig display requires a local armature.")
    if armature.data.users > 1:
        raise ValueError("Make the armature data single-user before changing rig display.")


def has_animator_display(armature):
    return armature is not None and _SNAPSHOT_KEY in armature


def _read_snapshot(armature):
    try:
        snapshot = json.loads(armature[_SNAPSHOT_KEY])
        if snapshot["version"] != 1 or not isinstance(snapshot["bones"], list):
            raise ValueError
        return snapshot
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("The saved rig display backup is invalid.") from error


def apply_animator_display(armature):
    """Emphasize generated controls without changing shapes or animation.

    The first application stores original values in the blend file. Reapplying
    preserves that backup and also captures newly generated bones. Source and
    other user bones, bone collections, viewport overlays and themes stay as-is.
    """
    _check_armature(armature)
    bones = tuple(_targets(armature))
    if not bones:
        raise ValueError("Build a COA rig before applying its display preset.")
    identities = [_identity(bone) for bone in bones]
    if len(identities) != len(set(identities)):
        raise ValueError("Generated bone ownership is ambiguous; repair the rig first.")
    snapshot = (
        _read_snapshot(armature)
        if has_animator_display(armature)
        else {
            "version": 1,
            "show_names": armature.data.show_names,
            "show_bone_colors": armature.data.show_bone_colors,
            "bones": [],
        }
    )
    recorded = {tuple(item["identity"]) for item in snapshot["bones"]}
    for bone in bones:
        identity = _identity(bone)
        if identity in recorded:
            continue
        pose_bone = armature.pose.bones[bone.name]
        snapshot["bones"].append({
            "identity": identity,
            "hide": bone.hide,
            "data_color": _color_snapshot(bone.color),
            "pose_color": _color_snapshot(pose_bone.color),
        })
    # Save before applying so a partially applied preset remains restorable.
    armature[_SNAPSHOT_KEY] = json.dumps(snapshot)
    armature.data.show_names = False
    armature.data.show_bone_colors = True
    for bone in bones:
        kind = _control_kind(bone)
        bone.hide = kind is None
        if kind is not None:
            _set_color(bone.color, kind)
            _set_color(armature.pose.bones[bone.name].color, kind)
    return len(bones)


def restore_animator_display(armature):
    """Restore only values recorded by the preset, resolving renamed bones."""
    _check_armature(armature)
    if not has_animator_display(armature):
        return 0
    snapshot = _read_snapshot(armature)
    by_identity = {}
    for bone in armature.data.bones:
        by_identity.setdefault(_identity(bone), []).append(bone)
    records = [
        (item, by_identity.get(tuple(item["identity"]), ()))
        for item in snapshot["bones"]
    ]
    if any(len(bones) > 1 for _item, bones in records):
        raise ValueError("Generated bone ownership is ambiguous; repair the rig first.")
    restored = 0
    for item, bones in records:
        if not bones:
            continue
        bone = bones[0]
        bone.hide = item["hide"]
        _restore_color(bone.color, item["data_color"])
        _restore_color(armature.pose.bones[bone.name].color, item["pose_color"])
        restored += 1
    armature.data.show_names = snapshot["show_names"]
    armature.data.show_bone_colors = snapshot["show_bone_colors"]
    del armature[_SNAPSHOT_KEY]
    return restored


def _context_armature(context):
    armature = functions.get_sprite_object(context.active_object)
    return armature if armature is not None and armature.type == "ARMATURE" else None


class COATOOLS2_OT_ApplyAnimatorDisplay(bpy.types.Operator):
    bl_idname = "coa_tools2.apply_animator_display"
    bl_label = "Animator Display"
    bl_description = (
        "Color generated controls and hide generated helper bones and raw names; "
        "save the current display for Restore"
    )
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature = _context_armature(context)
        return armature is not None and armature.mode != "EDIT"

    def execute(self, context):
        try:
            count = apply_animator_display(_context_armature(context))
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Updated display for {count} generated bones")
        return {"FINISHED"}


class COATOOLS2_OT_RestoreAnimatorDisplay(bpy.types.Operator):
    bl_idname = "coa_tools2.restore_animator_display"
    bl_label = "Restore Display"
    bl_description = "Restore the display saved before applying Animator Display"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        armature = _context_armature(context)
        return (
            armature is not None
            and armature.mode != "EDIT"
            and has_animator_display(armature)
        )

    def execute(self, context):
        try:
            restore_animator_display(_context_armature(context))
        except ValueError as error:
            self.report({"ERROR"}, str(error))
            return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (COATOOLS2_OT_ApplyAnimatorDisplay, COATOOLS2_OT_RestoreAnimatorDisplay)

"""Animator-facing rig controls, independent of the setup layer selection."""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, StringProperty

from ... import functions
from ..schema import graph_state_weights, hat_basis
from .properties import get_rig_data
from .selection import active_data_bone
from .semantic_contact import (
    SemanticContactError, _contact_ik_provider, contact_uses_ik_override,
    switch_contact_pin,
)
from .semantic_fk import switch_ik_fk_mode
from .states import graph_state_point_specs, state_dimensions


def rig_armature(context):
    obj = functions.get_sprite_object(context.active_object)
    return obj if obj is not None and obj.type == "ARMATURE" else None


def is_setup(context):
    settings = getattr(context.window_manager, "coa_tools2", None)
    return getattr(settings, "rig_workspace", "ANIMATE") == "SETUP"


def is_rig_animation(context):
    armature = rig_armature(context)
    if armature is None or is_setup(context):
        return False
    data = get_rig_data(armature, migrate=False)
    return bool(data.rig_controls or data.rig_components)


def selected_rig(armature):
    """Resolve the live bone tags without waiting for the selection-sync timer."""
    data = get_rig_data(armature, migrate=False)
    bone = active_data_bone(armature)
    if bone is None:
        return None, None, None
    control = next((c for c in data.rig_controls
                    if c.control_uuid == bone.get("coa_rig_control_uuid")), None)
    component = next((c for c in data.rig_components
                      if c.component_uuid == bone.get("coa_rig_component_uuid")), None)
    stage = None
    if component is not None:
        role = str(bone.get("coa_rig_component_role", "")).split(":", 2)
        if len(role) >= 2 and role[0] == "semantic":
            stage = next((s for s in component.semantic_stages
                          if s.stage_uuid == role[1]), None)
    return control, component, stage


def animation_pair(component, stage):
    """Find only the Contact owned by the selected IK chain, never another limb."""
    if stage is None or not stage.enabled:
        return None, ()
    ik = stage if stage.stage_type == "CHAIN_IK" else None
    if stage.stage_type == "CONTACT_PIN" and contact_uses_ik_override(stage):
        try:
            ik = _contact_ik_provider(component, stage)
        except SemanticContactError:
            pass
    if ik is None or not ik.enabled:
        return None, ()
    contacts = []
    for candidate in component.semantic_stages:
        if (not candidate.enabled or candidate.stage_type != "CONTACT_PIN"
                or not contact_uses_ik_override(candidate)):
            continue
        try:
            if _contact_ik_provider(component, candidate) == ik:
                contacts.append(candidate)
        except SemanticContactError:
            continue
    return ik, tuple(contacts)


def state_weight_values(armature, control):
    """Read the same constrained local input and basis functions as the drivers.

    Missing artwork does not change the state field: its share remains visible.
    These are state weights, not independently editable Shape Key values.
    """
    pose = armature.pose.bones.get(control.control_bone)
    if pose is None or not control.state_points:
        return ()
    local = armature.convert_space(
        pose_bone=pose, matrix=pose.matrix, from_space="POSE", to_space="LOCAL",
    ).translation
    horizontal = local.y if control.state_mode == "LINEAR_1D" and control.axis == "Y" else local.x
    u = float(horizontal) / max(float(control.width), 1.0e-12)
    v = float(local.y) / max(float(control.height), 1.0e-12)
    if control.state_mode == "GRAPH_2D":
        weights = graph_state_weights(
            u, v, graph_state_point_specs(control),
            control.graph_interpolation, control.graph_radius,
        )
    else:
        columns, rows = state_dimensions(control)
        weights = tuple(hat_basis(u, p.column, columns)
                        * (hat_basis(v, p.row, rows) if rows > 1 else 1.0)
                        for p in control.state_points)
    return tuple(zip(control.state_points, weights))


def has_current_key(armature, owner, path, frame):
    action = armature.animation_data.action if armature.animation_data else None
    data_path = owner.path_from_id(path)
    return any(curve.data_path == data_path
               and any(abs(key.co.x - frame) < 1.0e-4 for key in curve.keyframe_points)
               for curve in functions.iter_action_fcurves(action))


class COATOOLS2_OT_AnimateRigSwitch(bpy.types.Operator):
    bl_idname = "coa_tools2.animate_rig_switch"
    bl_label = "Switch Rig and Key"
    bl_description = "Preserve the pose and record a key at the current frame"
    bl_options = {"REGISTER", "UNDO"}

    component_uuid: StringProperty(options={"HIDDEN"})
    stage_uuid: StringProperty(options={"HIDDEN"})
    mode: EnumProperty(items=(("FK", "FK", ""), ("IK", "IK", ""),
                              ("OFF", "Off", ""), ("ON", "On", "")))

    @classmethod
    def poll(cls, context):
        return rig_armature(context) is not None and context.mode == "POSE"

    def execute(self, context):
        armature = rig_armature(context)
        data = get_rig_data(armature)
        component = next((c for c in data.rig_components
                          if c.component_uuid == self.component_uuid), None)
        stage = next((s for s in component.semantic_stages
                      if s.stage_uuid == self.stage_uuid), None) if component else None
        if stage is None or not stage.enabled:
            self.report({"ERROR"}, "The selected rig layer is unavailable.")
            return {"CANCELLED"}
        try:
            if stage.stage_type == "CHAIN_IK" and self.mode in {"FK", "IK"}:
                switch_ik_fk_mode(armature, component, stage, self.mode)
            elif (stage.stage_type == "CONTACT_PIN" and self.mode in {"OFF", "ON"}
                  and contact_uses_ik_override(stage)):
                switch_contact_pin(armature, component, stage, self.mode)
            else:
                raise ValueError("This mode does not belong to the selected layer.")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class COATOOLS2_OT_KeyRigControl(bpy.types.Operator):
    bl_idname = "coa_tools2.key_rig_control"
    bl_label = "Key Control"
    bl_description = "Key the unlocked transform channels of this control"
    bl_options = {"REGISTER", "UNDO"}
    control_uuid: StringProperty(options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        return rig_armature(context) is not None and context.mode == "POSE"

    def execute(self, context):
        armature = rig_armature(context)
        data = get_rig_data(armature)
        control = next((c for c in data.rig_controls
                        if c.control_uuid == self.control_uuid), None)
        pose = armature.pose.bones.get(control.control_bone) if control else None
        if pose is None:
            self.report({"ERROR"}, "The State Rig handle is unavailable.")
            return {"CANCELLED"}
        # State handles have translation or a dial rotation as their input.
        path = "rotation_euler" if control.control_type == "DIAL" else "location"
        axes = (2,) if path == "rotation_euler" else (
            (1 if control.axis == "Y" else 0,)
            if control.control_type == "SLIDER_1D" else (0, 1)
        )
        for index in axes:
            pose.keyframe_insert(data_path=path, index=index,
                                 frame=context.scene.frame_current, group=control.label)
        return {"FINISHED"}


class COATOOLS2_PG_RigDependencyChoice(bpy.types.PropertyGroup):
    stage_uuid: StringProperty()
    label: StringProperty()
    selected: BoolProperty()


class COATOOLS2_OT_EditRigDependencies(bpy.types.Operator):
    bl_idname = "coa_tools2.edit_rig_dependencies"
    bl_label = "Input Layers"
    bl_description = "Choose upstream layers by name"
    bl_options = {"REGISTER", "UNDO"}
    stage_uuid: StringProperty(options={"HIDDEN"})
    choices: CollectionProperty(type=COATOOLS2_PG_RigDependencyChoice)

    @classmethod
    def poll(cls, context):
        armature = rig_armature(context)
        return armature is not None and bool(get_rig_data(armature, migrate=False).rig_components)

    def invoke(self, context, _event):
        data = get_rig_data(rig_armature(context))
        component = next((c for c in data.rig_components
                          if any(s.stage_uuid == self.stage_uuid for s in c.semantic_stages)), None)
        stage = next((s for s in component.semantic_stages
                      if s.stage_uuid == self.stage_uuid), None) if component else None
        if stage is None:
            self.report({"ERROR"}, "Choose a layer in Setup first.")
            return {"CANCELLED"}
        current = {value.strip() for value in stage.depends_on.split(",")}
        self.choices.clear()
        for candidate in component.semantic_stages:
            if candidate == stage:
                continue
            choice = self.choices.add()
            choice.stage_uuid = candidate.stage_uuid
            choice.label = candidate.label
            choice.selected = candidate.stage_uuid in current
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, _context):
        for choice in self.choices:
            self.layout.prop(choice, "selected", text=choice.label)

    def execute(self, context):
        data = get_rig_data(rig_armature(context))
        component = next((c for c in data.rig_components
                          if any(s.stage_uuid == self.stage_uuid for s in c.semantic_stages)), None)
        if component is None:
            return {"CANCELLED"}
        stages = {s.stage_uuid: s for s in component.semantic_stages}
        chosen = [c.stage_uuid for c in self.choices if c.selected]
        def reaches_self(token, seen):
            if token == self.stage_uuid:
                return True
            if token in seen or token not in stages:
                return False
            return any(reaches_self(value.strip(), seen | {token})
                       for value in stages[token].depends_on.split(",") if value.strip())
        if any(token not in stages or reaches_self(token, set()) for token in chosen):
            self.report({"ERROR"}, "Input layers must not create a cycle or refer to missing layers.")
            return {"CANCELLED"}
        stages[self.stage_uuid].depends_on = ",".join(chosen)
        component.needs_rebuild = True
        return {"FINISHED"}


def draw_switch(layout, armature, component, stage, label, path, modes, frame):
    row = layout.row(align=True)
    row.label(text=label)
    for value, title in modes:
        operator = row.operator("coa_tools2.animate_rig_switch", text=title,
                                depress=getattr(stage, path) == value)
        operator.component_uuid = component.component_uuid
        operator.stage_uuid = stage.stage_uuid
        operator.mode = value
    row.label(text="", icon="KEYFRAME_HLT" if has_current_key(armature, stage, path, frame)
              else "KEYFRAME")


class COATOOLS2_PT_RigWorkspace(bpy.types.Panel):
    bl_idname = "COATOOLS2_PT_rig_workspace"
    bl_label = "Rig"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "COA Tools2"
    bl_order = 0

    @classmethod
    def poll(cls, context):
        return rig_armature(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.row(align=True).prop(context.window_manager.coa_tools2, "rig_workspace", expand=True)
        armature = rig_armature(context)
        if is_setup(context):
            from .viewport_display import has_animator_display
            header, body = layout.panel("coa_rig_viewport", default_closed=True)
            header.label(text="Viewport")
            if body:
                body.operator("coa_tools2.apply_animator_display", text="Use Animator Display")
                if has_animator_display(armature):
                    body.operator("coa_tools2.restore_animator_display", text="Restore Display")
            return
        if context.mode != "POSE":
            layout.label(text="Enter Pose Mode to animate.", icon="POSE_HLT")
            return
        control, component, stage = selected_rig(armature)
        if control is not None:
            layout.label(text=control.label, icon="BONE_DATA")
            if control.needs_rebuild:
                layout.label(text="Setup changes pending.", icon="INFO")
            values = state_weight_values(armature, control)
            if values:
                for point, weight in values:
                    name = point.label or point.target_name or f"{point.column + 1}, {point.row + 1}"
                    if not point.enabled:
                        name += " (disabled)"
                    elif not point.is_empty and not (point.target_object and point.target_name):
                        name += " (unassigned)"
                    layout.progress(factor=min(max(weight, 0.0), 1.0),
                                    type="BAR", text=f"{name}  {weight:.1%}")
            operator = layout.operator("coa_tools2.key_rig_control", icon="KEY_HLT")
            operator.control_uuid = control.control_uuid
            return
        if component is None:
            layout.label(text="Select a rig control in the viewport.", icon="BONE_DATA")
            return
        layout.label(text=component.label, icon="BONE_DATA")
        if component.needs_rebuild:
            layout.label(text="Setup changes pending.", icon="INFO")
        ik, contacts = animation_pair(component, stage)
        if ik is not None:
            draw_switch(layout, armature, component, ik, "Mode", "rig_mode",
                        (("FK", "FK"), ("IK", "IK")), context.scene.frame_current)
            for contact in contacts:
                draw_switch(layout, armature, component, contact,
                            "Contact Pin" if len(contacts) == 1 else contact.label,
                            "contact_mode", (("OFF", "Off"), ("ON", "On")),
                            context.scene.frame_current)
        elif stage is not None:
            layout.label(text=stage.label)


CLASSES = (
    COATOOLS2_PG_RigDependencyChoice,
    COATOOLS2_OT_EditRigDependencies,
    COATOOLS2_OT_AnimateRigSwitch,
    COATOOLS2_OT_KeyRigControl,
    COATOOLS2_PT_RigWorkspace,
)

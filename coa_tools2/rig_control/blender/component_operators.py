"""Operators for character posing rig components."""

from __future__ import annotations

import re
import traceback
import uuid

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    StringProperty,
)

from ... import functions
from .component_compiler import RigComponentCompileError, compile_component
from .properties import get_rig_data
from .selection import select_pose_bone


def _armature(context):
    sprite_object = functions.get_sprite_object(context.active_object)
    if sprite_object is not None and sprite_object.type == "ARMATURE":
        return sprite_object
    return None


def _active_component(context):
    armature = _armature(context)
    if armature is None:
        return None, None
    rig_data = get_rig_data(armature)
    if not rig_data.rig_components:
        return armature, None
    index = min(rig_data.rig_components_index, len(rig_data.rig_components) - 1)
    return armature, rig_data.rig_components[index]


def _selected_chain(context):
    active = context.active_pose_bone
    selected = {bone.name for bone in context.selected_pose_bones or ()}
    if active is None or active.name not in selected:
        raise RigComponentCompileError(
            "Select source bones in Pose Mode with the chain end active."
        )
    chain = []
    current = active
    while current is not None and current.name in selected:
        chain.append(current.name)
        current = current.parent
    chain.reverse()
    if set(chain) != selected:
        raise RigComponentCompileError(
            "Selected bones must form one parent chain ending at the active bone."
        )
    return chain


def _semantic_id(label):
    slug = re.sub(r"[^0-9A-Za-z_]+", "_", label.strip()).strip("_").lower()
    return f"pose.{slug or 'component'}"


def _side_from_name(name):
    lower = name.lower()
    if lower.endswith((".l", "_l", "-l", ".left", "_left")):
        return "LEFT"
    if lower.endswith((".r", "_r", "-r", ".right", "_right")):
        return "RIGHT"
    return "CENTER"


class COATOOLS2_OT_AddRigComponent(bpy.types.Operator):
    bl_idname = "coa_tools2.add_rig_component"
    bl_label = "Add Pose Rig Component"
    bl_description = "Build a managed 3D posing component from selected bones"
    bl_options = {"REGISTER", "UNDO"}

    label: StringProperty(default="Pose Component")
    component_type: EnumProperty(
        items=(
            ("ROOT", "Root", "Use the active root bone as a 3D posing control"),
            ("FK_CHAIN", "FK Chain", "Use the selected bones as all-axis FK controls"),
            ("LIMB_IK", "Limb IK", "Create an oriented 3D IK target"),
            ("SPINE_FK", "Spine FK", "Use the selected spine as FK controls"),
        ),
        default="LIMB_IK",
    )
    orientation_mode: EnumProperty(
        items=(
            (
                "SOURCE_BONE",
                "Source Bone",
                "Use the active end bone and its roll as the visual frame",
            ),
            (
                "WORLD_VIEW",
                "World View",
                "Use armature X/Z as the art plane and Y as depth",
            ),
            (
                "CUSTOM",
                "Custom Offset",
                "Offset the source bone visual frame",
            ),
        ),
        default="SOURCE_BONE",
    )
    orientation_euler: FloatVectorProperty(
        name="Orientation Offset",
        size=3,
        subtype="EULER",
    )
    depth_mode: EnumProperty(
        items=(
            ("LOCKED", "Plane", "Do not move along the visual normal"),
            (
                "LIMITED",
                "Limited Depth",
                "Move inside a bounded visual-normal slab",
            ),
            ("FREE", "Free 3D", "Allow unrestricted depth movement"),
        ),
        default="LIMITED",
    )
    depth_min: FloatProperty(name="Back", default=-0.25)
    depth_max: FloatProperty(name="Front", default=0.25)
    widget: EnumProperty(
        items=(
            ("AUTO", "Automatic", "Choose a shape from the component type"),
            ("ROOT", "Root", "3D root box"),
            ("FK", "FK", "Three-axis FK rings"),
            ("HAND", "Hand", "Palm-oriented hand outline"),
            ("FOOT", "Foot", "Sole-oriented foot outline"),
            ("SQUARE", "Square", "Neutral oriented control"),
        ),
        default="AUTO",
    )
    widget_size: FloatProperty(default=1.0, min=0.01)
    ik_solver_mode: EnumProperty(
        items=(
            ("SPATIAL", "Spatial", "Allow the limb to bend in 3D"),
            ("PLANAR", "Planar", "Constrain the limb to one bend axis"),
        ),
        default="SPATIAL",
    )
    bend_axis: EnumProperty(
        items=(
            ("AUTO", "Automatic", "Infer bend axis from the rest pose"),
            ("X", "Local X", "Use local X as bend axis"),
            ("Y", "Local Y", "Use local Y as bend axis"),
            ("Z", "Local Z", "Use local Z as bend axis"),
        ),
        default="AUTO",
    )
    use_bend_hint: BoolProperty(
        name="Bend Hint",
        default=True,
    )
    pole_distance: FloatProperty(
        name="Bend Distance",
        default=1.0,
        min=0.05,
    )
    use_stretch: BoolProperty(default=False)
    end_rotation_mode: EnumProperty(
        items=(
            ("COPY_WORLD", "Follow Target", "End bone follows target rotation"),
            ("COPY_LOCAL", "Follow Local", "Copy target local rotation"),
            ("NONE", "Position Only", "Do not copy end rotation"),
        ),
        default="COPY_WORLD",
    )

    @classmethod
    def poll(cls, context):
        return (
            _armature(context) is not None
            and context.mode == "POSE"
            and context.active_pose_bone is not None
        )

    def invoke(self, context, _event):
        active = context.active_pose_bone
        self.label = active.name if active is not None else "Pose Component"
        return context.window_manager.invoke_props_dialog(self, width=460)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "label")
        layout.prop(self, "component_type")
        if self.component_type == "LIMB_IK":
            orientation = layout.box()
            orientation.label(text="Visual Control Frame", icon="ORIENTATION_LOCAL")
            orientation.prop(self, "orientation_mode")
            if self.orientation_mode == "CUSTOM":
                orientation.prop(self, "orientation_euler")
            orientation.label(text="Local X/Y: art plane")
            orientation.label(text="Local Z: visual normal / depth")

            depth = layout.box()
            depth.prop(self, "depth_mode")
            if self.depth_mode == "LIMITED":
                row = depth.row(align=True)
                row.prop(self, "depth_min")
                row.prop(self, "depth_max")

            solver = layout.box()
            solver.prop(self, "ik_solver_mode")
            if self.ik_solver_mode == "PLANAR":
                solver.prop(self, "bend_axis")
            else:
                solver.prop(self, "use_bend_hint")
                if self.use_bend_hint:
                    solver.prop(self, "pole_distance")
            solver.prop(self, "end_rotation_mode")
            solver.prop(self, "use_stretch")
        elif self.component_type == "ROOT":
            layout.prop(self, "depth_mode")
            if self.depth_mode == "LIMITED":
                row = layout.row(align=True)
                row.prop(self, "depth_min")
                row.prop(self, "depth_max")
        layout.prop(self, "widget")
        layout.prop(self, "widget_size")

    def execute(self, context):
        armature = _armature(context)
        if armature is None:
            self.report({"ERROR"}, "No SpriteObject Armature found.")
            return {"CANCELLED"}
        try:
            chain = _selected_chain(context)
            if self.component_type == "ROOT":
                chain = [context.active_pose_bone.name]
            elif self.component_type == "LIMB_IK" and len(chain) < 3:
                raise RigComponentCompileError(
                    "Limb IK requires upper, lower, and end bones."
                )
            elif self.component_type == "SPINE_FK" and len(chain) < 2:
                raise RigComponentCompileError(
                    "Spine FK requires at least two selected bones."
                )
        except RigComponentCompileError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        rig_data = get_rig_data(armature)
        component = rig_data.rig_components.add()
        component.component_uuid = str(uuid.uuid4())
        component.semantic_id = _semantic_id(self.label)
        component.label = self.label
        component.component_type = self.component_type
        component.side = _side_from_name(chain[-1])
        component.build_mode = (
            "GENERATED" if self.component_type == "LIMB_IK" else "IN_PLACE"
        )
        component.orientation_mode = self.orientation_mode
        component.orientation_reference = chain[-1]
        component.orientation_euler = self.orientation_euler
        component.depth_mode = self.depth_mode
        component.depth_min = self.depth_min
        component.depth_max = self.depth_max
        component.allow_translation = (
            (True, True, True)
            if self.component_type in {"ROOT", "LIMB_IK"}
            else (False, False, False)
        )
        component.allow_rotation = (True, True, True)
        component.widget = (
            self.widget
            if self.widget != "AUTO"
            else "ROOT"
            if self.component_type == "ROOT"
            else "FK"
            if self.component_type in {"FK_CHAIN", "SPINE_FK"}
            else "HAND"
        )
        component.widget_size = self.widget_size
        component.ik_chain_length = min(2, max(1, len(chain) - 1))
        component.ik_solver_mode = self.ik_solver_mode
        component.bend_axis = self.bend_axis
        component.use_bend_hint = self.use_bend_hint
        component.pole_distance = self.pole_distance
        component.use_stretch = self.use_stretch
        component.end_rotation_mode = self.end_rotation_mode
        for bone_name in chain:
            reference = component.source_bones.add()
            reference.bone_name = bone_name

        try:
            result = compile_component(armature, component)
        except Exception as exc:
            traceback.print_exc()
            rig_data.rig_components.remove(len(rig_data.rig_components) - 1)
            self.report({"ERROR"}, f"Pose component build failed: {exc}")
            return {"CANCELLED"}
        rig_data.rig_components_index = len(rig_data.rig_components) - 1
        select_pose_bone(
            armature,
            result["primary_control_bone"],
            exclusive=True,
        )
        self.report({"INFO"}, f"Created pose component: {self.label}")
        return {"FINISHED"}


class COATOOLS2_OT_UpdateRigComponent(bpy.types.Operator):
    bl_idname = "coa_tools2.update_rig_component"
    bl_label = "Apply Pose Component"
    bl_description = "Rebuild the selected component from its explicit definition"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        _armature_object, component = _active_component(context)
        return component is not None

    def execute(self, context):
        armature, component = _active_component(context)
        try:
            compile_component(armature, component)
        except Exception as exc:
            traceback.print_exc()
            component.last_error = str(exc)
            component.needs_rebuild = True
            self.report({"ERROR"}, f"Pose component update failed: {exc}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Updated pose component: {component.label}")
        return {"FINISHED"}


CLASSES = (
    COATOOLS2_OT_AddRigComponent,
    COATOOLS2_OT_UpdateRigComponent,
)

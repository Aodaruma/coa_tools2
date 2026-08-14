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
from .component_outputs import (
    remove_component_binding,
)
from .drivers import binding_target_key
from .properties import get_rig_data
from .selection import select_pose_bone
from .states import state_target_key


def _armature(context):
    sprite_object = functions.get_sprite_object(context.active_object)
    if sprite_object is not None and sprite_object.type == "ARMATURE":
        return sprite_object
    return None


def _active_component(context, *, migrate=True):
    armature = _armature(context)
    if armature is None:
        return None, None
    rig_data = get_rig_data(armature, migrate=migrate)
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


def _component_binding_source_items(_self, _context):
    return (
        ("LOC_X", "Move X", "Control-local X translation"),
        ("LOC_Y", "Move Y", "Control-local Y translation"),
        ("LOC_Z", "Depth Z", "Control-local visual depth"),
        ("ROT_X", "Rotate X", "Control-local X rotation"),
        ("ROT_Y", "Rotate Y", "Control-local Y rotation"),
        ("ROT_Z", "Rotate Z", "Control-local Z rotation"),
    )


def _component_binding_target_items(self, _context):
    target = bpy.data.objects.get(self.target_object_name)
    if target is None:
        return [("", "Missing Target", "Select a target object")]
    if self.target_kind == "SHAPE_KEY_VALUE":
        shape_keys = getattr(getattr(target, "data", None), "shape_keys", None)
        if shape_keys is None:
            return [("", "No Shape Keys", "Target has no Shape Keys")]
        items = [
            (key.name, key.name, f"Drive {key.name}")
            for key in shape_keys.key_blocks
            if key.name != "Basis"
        ]
        return items or [("", "No Shape Keys", "No non-Basis Shape Keys")]
    if target.type != "ARMATURE":
        return [("", "Not an Armature", "Select an Armature")]
    pose_bone = target.pose.bones.get(self.target_bone)
    if pose_bone is None:
        return [("", "Choose Bone", "Select a pose bone")]
    items = [
        (constraint.name, constraint.name, constraint.name)
        for constraint in pose_bone.constraints
    ]
    return items or [("", "No Constraints", "Bone has no constraints")]


def _component_target_bone_items(self, _context):
    target = bpy.data.objects.get(self.target_object_name)
    if target is None or target.type != "ARMATURE":
        return [("", "No Bones", "Select an Armature target")]
    return [(bone.name, bone.name, bone.name) for bone in target.pose.bones]


def _belongs_to_armature(obj, armature):
    current = obj
    while current is not None:
        if current == armature:
            return True
        current = current.parent
    return obj.find_armature() == armature if obj.type == "MESH" else False


def _default_component_target(context, armature):
    active = context.active_object
    if active is not None and active.type == "MESH" and active.data.shape_keys:
        return active
    selected = next(
        (
            obj
            for obj in context.selected_objects
            if obj.type == "MESH" and obj.data.shape_keys is not None
        ),
        None,
    )
    if selected is not None:
        return selected
    return next(
        (
            obj
            for obj in context.scene.objects
            if obj.type == "MESH"
            and obj.data.shape_keys is not None
            and _belongs_to_armature(obj, armature)
        ),
        None,
    )


def _all_output_target_keys(armature):
    rig_data = get_rig_data(armature)
    for control in rig_data.rig_controls:
        for binding in control.bindings:
            if binding.enabled:
                yield binding_target_key(binding)
        for point in control.state_points:
            if point.enabled and not point.is_empty:
                yield state_target_key(point)
    for component in rig_data.rig_components:
        for binding in component.bindings:
            if binding.enabled:
                yield binding_target_key(binding)


def _component_input_range(component, source_component):
    if source_component == "LOC_Z" and component.depth_mode == "LIMITED":
        return component.depth_min, component.depth_max
    if source_component.startswith("ROT_"):
        return -1.5707963267948966, 1.5707963267948966
    return -1.0, 1.0


class COATOOLS2_OT_AddRigComponent(bpy.types.Operator):
    bl_idname = "coa_tools2.add_rig_component"
    bl_label = "Add Pose Rig Component"
    bl_description = "Build a managed parametric pose input from selected bones"
    bl_options = {"REGISTER", "UNDO"}

    label: StringProperty(default="Pose Component")
    component_type: EnumProperty(
        items=(
            ("ROOT", "Root / Body", "Create a root or body parameter control"),
            ("FK_CHAIN", "Part Rotation", "Create a part-oriented parameter control"),
            (
                "LIMB_IK",
                "Limb Target / IK",
                "Create a parametric limb target or legacy direct IK",
            ),
            ("SPINE_FK", "Spine / Body", "Create a body-oriented parameter control"),
        ),
        default="LIMB_IK",
    )
    deformation_mode: EnumProperty(
        name="Artwork Deformation",
        items=(
            (
                "PARAMETRIC",
                "Parametric (Shape Keys)",
                "Use the 3D control as parameter input without rotating source bones",
            ),
            (
                "DIRECT_BONES",
                "Direct Bones (Legacy)",
                "Pose source bones directly with FK or IK",
            ),
        ),
        default="PARAMETRIC",
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
        layout.prop(self, "deformation_mode")
        if self.deformation_mode == "PARAMETRIC":
            info = layout.box()
            info.label(text="Source bones stay unchanged.", icon="SHAPEKEY_DATA")
            info.label(text="Add Shape Key outputs after creation.")
            orientation = layout.box()
            orientation.label(text="Visual Control Frame", icon="ORIENTATION_LOCAL")
            orientation.prop(self, "orientation_mode")
            if self.orientation_mode == "CUSTOM":
                orientation.prop(self, "orientation_euler")
            orientation.label(text="Local X/Y: artwork axes")
            orientation.label(text="Local Z: visual depth")
            depth = layout.box()
            depth.prop(self, "depth_mode")
            if self.depth_mode == "LIMITED":
                row = depth.row(align=True)
                row.prop(self, "depth_min")
                row.prop(self, "depth_max")
        elif self.component_type == "LIMB_IK":
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
        component.deformation_mode = self.deformation_mode
        component.build_mode = (
            "GENERATED"
            if (
                self.deformation_mode == "PARAMETRIC"
                or self.component_type == "LIMB_IK"
            )
            else "IN_PLACE"
        )
        component.orientation_mode = self.orientation_mode
        component.orientation_reference = chain[-1]
        component.orientation_euler = self.orientation_euler
        component.depth_mode = self.depth_mode
        component.depth_min = self.depth_min
        component.depth_max = self.depth_max
        component.allow_translation = (
            (True, True, True)
            if (
                self.deformation_mode == "PARAMETRIC"
                or self.component_type in {"ROOT", "LIMB_IK"}
            )
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
        _armature_object, component = _active_component(context, migrate=False)
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


class COATOOLS2_OT_AddComponentBinding(bpy.types.Operator):
    bl_idname = "coa_tools2.add_component_binding"
    bl_label = "Add Pose Output"
    bl_description = "Map a pose-control transform channel to a Shape Key or constraint"
    bl_options = {"REGISTER", "UNDO"}

    source_component: EnumProperty(items=_component_binding_source_items)
    target_kind: EnumProperty(
        items=(
            ("SHAPE_KEY_VALUE", "Shape Key", "Drive a Shape Key value"),
            (
                "CONSTRAINT_INFLUENCE",
                "Constraint Influence",
                "Drive a pose-bone constraint influence",
            ),
        ),
        default="SHAPE_KEY_VALUE",
    )
    target_object_name: StringProperty()
    target_bone: EnumProperty(items=_component_target_bone_items)
    target_name: EnumProperty(items=_component_binding_target_items)
    input_min: FloatProperty(default=-1.0)
    input_max: FloatProperty(default=1.0)
    output_min: FloatProperty(default=0.0)
    output_max: FloatProperty(default=1.0)
    clamp: BoolProperty(default=True)

    @classmethod
    def poll(cls, context):
        _armature_object, component = _active_component(context, migrate=False)
        return (
            component is not None
            and component.component_type != "SEMANTIC"
            and component.deformation_mode == "PARAMETRIC"
            and bool(component.control_bone)
        )

    def invoke(self, context, _event):
        armature, component = _active_component(context)
        self.source_component = "ROT_Z"
        self.input_min, self.input_max = _component_input_range(
            component,
            self.source_component,
        )
        target = _default_component_target(context, armature)
        self.target_object_name = target.name if target else ""
        if target is not None:
            items = _component_binding_target_items(self, context)
            if items and items[0][0]:
                self.target_name = items[0][0]
        return context.window_manager.invoke_props_dialog(self, width=470)

    def draw(self, _context):
        layout = self.layout
        layout.prop(self, "source_component", text="Input Channel")
        row = layout.row(align=True)
        row.prop(self, "input_min")
        row.prop(self, "input_max")
        layout.prop(self, "target_kind", text="Target Type")
        layout.prop_search(
            self,
            "target_object_name",
            bpy.data,
            "objects",
            text="Target Object",
        )
        if self.target_kind == "CONSTRAINT_INFLUENCE":
            layout.prop(self, "target_bone", text="Target Bone")
            layout.prop(self, "target_name", text="Constraint")
        else:
            layout.prop(self, "target_name", text="Shape Key")
        row = layout.row(align=True)
        row.prop(self, "output_min")
        row.prop(self, "output_max")
        layout.prop(self, "clamp")

    def execute(self, context):
        armature, component = _active_component(context)
        if component is None or component.component_type == "SEMANTIC":
            self.report(
                {"ERROR"},
                "Character Rig outputs belong to a Recorded Pose Map stage.",
            )
            return {"CANCELLED"}
        target = bpy.data.objects.get(self.target_object_name)
        if armature is None or component is None or target is None:
            self.report({"ERROR"}, "Component and target object are required.")
            return {"CANCELLED"}
        target_key = (
            self.target_kind,
            target.name,
            (
                self.target_bone
                if self.target_kind == "CONSTRAINT_INFLUENCE"
                else ""
            ),
            self.target_name,
        )
        if target_key in set(_all_output_target_keys(armature)):
            self.report({"ERROR"}, "This target already has a rig output.")
            return {"CANCELLED"}

        binding = component.bindings.add()
        binding.binding_uuid = str(uuid.uuid4())
        binding.control_uuid = component.component_uuid
        binding.source_component = self.source_component
        binding.target_kind = self.target_kind
        binding.target_object = target
        binding.target_bone = target_key[2]
        binding.target_name = self.target_name
        binding.input_min = self.input_min
        binding.input_max = self.input_max
        binding.output_min = self.output_min
        binding.output_max = self.output_max
        binding.clamp = self.clamp
        try:
            compile_component(armature, component)
        except Exception as exc:
            traceback.print_exc()
            component.bindings.remove(len(component.bindings) - 1)
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        component.bindings_index = len(component.bindings) - 1
        self.report({"INFO"}, "Pose output added.")
        return {"FINISHED"}


class COATOOLS2_OT_RemoveComponentBinding(bpy.types.Operator):
    bl_idname = "coa_tools2.remove_component_binding"
    bl_label = "Remove Pose Output"
    bl_description = "Remove the selected output and its strictly-owned driver"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        _armature_object, component = _active_component(context, migrate=False)
        return component is not None and bool(component.bindings)

    def execute(self, context):
        armature, component = _active_component(context)
        index = min(component.bindings_index, len(component.bindings) - 1)
        binding = component.bindings[index]
        try:
            remove_component_binding(armature, component, binding)
        except Exception as exc:
            traceback.print_exc()
            self.report({"ERROR"}, f"Pose output removal failed: {exc}")
            return {"CANCELLED"}
        component.bindings.remove(index)
        component.bindings_index = max(
            0,
            min(index, len(component.bindings) - 1),
        )
        return {"FINISHED"}


CLASSES = (
    COATOOLS2_OT_AddRigComponent,
    COATOOLS2_OT_UpdateRigComponent,
    COATOOLS2_OT_AddComponentBinding,
    COATOOLS2_OT_RemoveComponentBinding,
)

"""
Copyright (C) 2023 Aodaruma
hi@aodaruma.net

Created by Aodaruma

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import bpy
import bpy_extras
import bpy_extras.view3d_utils
from math import radians
import mathutils
from mathutils import Vector, Matrix, Quaternion, geometry
import math
import bmesh
from bpy.props import (
    FloatProperty,
    IntProperty,
    BoolProperty,
    StringProperty,
    CollectionProperty,
    FloatVectorProperty,
    EnumProperty,
    IntVectorProperty,
)

# from .. functions import *
from .. import functions
from ..functions_draw import *
import traceback
import pdb


class COATOOLS2_OT_LeaveSculptmode(bpy.types.Operator):
    bl_idname = "coa_tools2.leave_sculptmode"
    bl_label = "Leave Sculptmode"
    bl_description = ""
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        obj = context.active_object
        if obj != None and obj.type == "MESH":
            bpy.ops.object.mode_set(mode="OBJECT")
        return {"FINISHED"}


class COATOOLS2_OT_ShapekeyAdd(bpy.types.Operator):
    bl_idname = "coa_tools2.shapekey_add"
    bl_label = "Add Shapekey"
    bl_description = ""
    bl_options = {"REGISTER"}

    name: StringProperty(name="Name")

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.active_object
        if obj.data.shape_keys == None:
            obj.shape_key_add(name="Basis", from_mix=False)

        shape = obj.shape_key_add(name=self.name, from_mix=False)
        shape_name = shape.name

        for i, shape in enumerate(obj.data.shape_keys.key_blocks):
            if shape.name == shape_name:
                obj.active_shape_key_index = i
                obj.coa_tools2["selected_shapekey"] = i
                break

        return {"FINISHED"}


class COATOOLS2_OT_ShapekeyRemove(bpy.types.Operator):
    bl_idname = "coa_tools2.shapekey_remove"
    bl_label = "Remove Shapekey"
    bl_description = ""
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_confirm(self, event)

    def execute(self, context):
        obj = context.active_object

        idx = int(obj.coa_tools2.selected_shapekey)

        shape = obj.data.shape_keys.key_blocks[idx]
        obj.shape_key_remove(shape)

        return {"FINISHED"}


class COATOOLS2_OT_ShapekeyRename(bpy.types.Operator):
    bl_idname = "coa_tools2.shapekey_rename"
    bl_label = "Rename Shapekey"
    bl_description = ""
    bl_options = {"REGISTER"}

    new_name: StringProperty()

    @classmethod
    def poll(cls, context):
        return True

    def invoke(self, context, event):
        obj = context.active_object
        idx = int(obj.coa_tools2.selected_shapekey)
        shape = obj.data.shape_keys.key_blocks[idx]

        self.new_name = shape.name

        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def execute(self, context):
        obj = context.active_object
        idx = int(obj.coa_tools2.selected_shapekey)
        shape = obj.data.shape_keys.key_blocks[idx]

        shape.name = self.new_name
        return {"FINISHED"}


class COATOOLS2_OT_EditShapekeyMode(bpy.types.Operator):
    bl_idname = "coa_tools2.edit_shapekey"
    bl_label = "Edit Shapekey"
    bl_description = ""
    bl_options = {"REGISTER", "UNDO"}

    def get_shapekeys(self, context):
        SHAPEKEYS = []
        SHAPEKEYS.append(("NEW_KEY", "New Shapekey", "New Shapekey", "FILE_NEW", 0))
        obj = context.active_object
        if obj.type == "MESH" and obj.data.shape_keys != None:
            i = 0
            for i, shape in enumerate(obj.data.shape_keys.key_blocks):
                if i > 0:
                    SHAPEKEYS.append(
                        (shape.name, shape.name, shape.name, "SHAPEKEY_DATA", i + 1)
                    )

        return SHAPEKEYS

    shapekeys: EnumProperty(name="Shapekey", items=get_shapekeys)
    shapekey_name: StringProperty(name="Name", default="New Shape")
    mode_init: StringProperty()
    armature = None
    armature_name = ""
    sprite_object = None
    sprite_object_name = None
    shape = None
    create_shapekey: BoolProperty(default=False)
    objs = []

    last_obj_name = ""

    @classmethod
    def poll(cls, context):
        return True

    def check(self, context):
        return True

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.prop(self, "shapekeys")
        if self.shapekeys == "NEW_KEY":
            col.prop(self, "shapekey_name")

    def invoke(self, context, event):
        obj = context.active_object

        if event.ctrl:  # or obj.data.shape_keys == None:
            wm = context.window_manager
            self.create_shapekey = True
            return wm.invoke_props_dialog(self)
        else:
            return self.execute(context)

    def set_most_driven_shapekey(self, obj):
        ### select most driven shapekey
        index = None
        value = 0.0
        if obj != None and obj.data.shape_keys != None:
            for i, shape in enumerate(obj.data.shape_keys.key_blocks):
                if shape.value > value:
                    index = i
                    value = shape.value
            if index != None:
                obj.active_shape_key_index = index

    def execute(self, context):
        self.objs = []
        if context.active_object == None or context.active_object.type != "MESH":
            self.report({"ERROR"}, "Sprite is not selected. Cannot go in Edit Mode.")
            return {"CANCELLED"}
        obj = (
            bpy.data.objects[context.active_object.name]
            if context.active_object.name in bpy.data.objects
            else None
        )

        self.sprite_object_name = functions.get_sprite_object(obj).name
        self.sprite_object = bpy.data.objects[self.sprite_object_name]

        self.armature_name = functions.get_armature(self.sprite_object).name
        self.armature = (
            context.scene.objects[self.armature_name]
            if self.armature_name in context.scene.objects
            else None
        )

        self.mode_init = obj.mode if obj.mode != "SCULPT" else "OBJECT"

        shape_name = self.shapekeys

        if self.shapekeys == "NEW_KEY" and self.create_shapekey:
            if obj.data.shape_keys == None:
                obj.shape_key_add(name="Basis", from_mix=False)
            shape = obj.shape_key_add(name=self.shapekey_name, from_mix=False)
            shape_name = shape.name

        self.sprite_object.coa_tools2.edit_shapekey = True
        self.sprite_object.coa_tools2.edit_mode = "SHAPEKEY"
        bpy.ops.object.mode_set(mode="SCULPT")
        context.scene.tool_settings.sculpt.use_symmetry_x = False
        context.scene.tool_settings.sculpt.use_symmetry_y = False
        context.scene.tool_settings.sculpt.use_symmetry_z = False

        functions.set_active_tool(self, context, "builtin_brush.Grab")
        self.set_most_driven_shapekey(obj)

        ### run modal operator and draw handler
        # args = ()
        # self.draw_handler = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback_px, args, "WINDOW", "POST_PIXEL")
        # context.window_manager.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def exit_edit_mode(self, context, event, obj):
        ### remove draw handler on exiting modal mode
        # bpy.types.SpaceView3D.draw_handler_remove(self.draw_handler, "WINDOW")

        for obj in context.selected_objects:
            obj.select_set(False)
        self.sprite_object.coa_tools2.edit_shapekey = False
        self.sprite_object.coa_tools2.edit_mode = "OBJECT"

        for obj_name in self.objs:
            obj = bpy.context.scene.objects[obj_name]
            obj.hide = False
            if obj.type == "MESH" and obj != None:
                context.scene.objects.active = obj
                bpy.ops.object.mode_set(mode="OBJECT")
                obj.show_only_shape_key = False

        context.view_layer.objects.active = obj
        obj.select = True
        if self.armature != None and self.armature.data != None:
            self.armature.data.pose_position = "POSE"
        return {"FINISHED"}

    def modal(self, context, event):
        obj = None
        obj_name = context.active_object.name if context.active_object != None else None
        # obj = context.scene.objects[obj_name] if obj_name != None else None
        obj = context.active_object
        self.sprite_object = bpy.data.objects[self.sprite_object_name]
        self.armature = bpy.data.objects[self.armature_name]

        try:
            # used for debugging
            # if event.ctrl and event.type == "Z" and len(context.selected_objects) == 2:
            #     pdb.set_trace()

            if obj != None:
                if obj_name != self.last_obj_name:
                    if obj.type == "MESH":
                        self.set_most_driven_shapekey(obj)

                if obj.name not in self.objs and obj.type == "MESH":
                    self.objs.append(obj.name)
                if obj.type == "MESH" and obj.mode in ["OBJECT", "WEIGHT_PAINT"]:
                    bpy.ops.object.mode_set(mode="SCULPT")

                if obj.type == "MESH" and obj.data.shape_keys != None:
                    if obj.coa_tools2.selected_shapekey != obj.active_shape_key.name:
                        obj.coa_tools2.selected_shapekey = str(
                            obj.active_shape_key_index
                        )  # obj.active_shape_key.name

            if self.sprite_object.coa_tools2.edit_shapekey == False and obj != None:
                return self.exit_edit_mode(context, event, obj)

        except Exception as e:
            traceback.print_exc()
            self.report(
                {"ERROR"},
                "An Error occured, please check console for more Information.",
            )
            self.exit_edit_mode(context, event, obj)

        if obj_name != self.last_obj_name:
            self.last_obj_name = str(obj_name)

        return {"PASS_THROUGH"}

    def draw_callback_px(self):
        draw_edit_mode(self, bpy.context, offset=2)


class COATOOLS2_OT_CreateShapekeySliderDriver(bpy.types.Operator):
    bl_idname = "coa_tools2.create_shapekey_slider_driver"
    bl_label = "Create Shapekey Slider Driver"
    bl_description = "Create a dedicated slider armature under sprite armature and drive active shapekey"
    bl_options = {"REGISTER", "UNDO"}

    slider_length: FloatProperty(
        name="Slider Length",
        description="Maximum local Y translation of slider bone",
        default=1.0,
        min=0.01,
        soft_max=5.0,
    )
    slider_rig_scale: FloatProperty(
        name="Slider Scale",
        description="Scale of generated slider armature object",
        default=1.3,
        min=0.2,
        soft_max=4.0,
    )
    create_text: BoolProperty(
        name="Create Label Text",
        description="Create text object parented to slider armature",
        default=True,
    )
    text_size: FloatProperty(
        name="Text Size",
        description="Text size of slider label",
        default=0.18,
        min=0.01,
        soft_max=2.0,
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            return False
        if obj.data is None or obj.data.shape_keys is None:
            return False
        return len(obj.data.shape_keys.key_blocks) > 1

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def _get_safe_name(self, value):
        safe = "".join(char if char.isalnum() else "_" for char in value)
        safe = safe.strip("_")
        return safe if safe != "" else "Item"

    def _build_unique_name(self, existing_names, base_name):
        if base_name not in existing_names:
            return base_name
        idx = 1
        while True:
            new_name = f"{base_name}.{idx:03d}"
            if new_name not in existing_names:
                return new_name
            idx += 1

    def _update_mesh_geometry(self, mesh, verts, edges, faces):
        mesh.clear_geometry()
        mesh.from_pydata(verts, edges, faces)
        mesh.update()

    def _ensure_shape_object(self, name, shape_type, collection, parent_obj):
        if name in bpy.data.objects and bpy.data.objects[name].type == "MESH":
            obj = bpy.data.objects[name]
            mesh = obj.data
        else:
            mesh = bpy.data.meshes.new(name)
            obj = bpy.data.objects.new(name, mesh)

        if shape_type == "SLIDER":
            half_w = 0.08
            half_h = 0.04
            verts = [
                (-half_w, -half_h, 0.0),
                (half_w, -half_h, 0.0),
                (half_w, half_h, 0.0),
                (-half_w, half_h, 0.0),
            ]
            edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
            faces = [(0, 1, 2, 3)]
        else:
            slider_half_w = 0.08
            slider_half_h = 0.04
            half_w = slider_half_w + 0.07
            rail_margin = slider_half_h + 0.08
            rail_min_y = -rail_margin
            rail_max_y = self.slider_length + rail_margin
            verts = [
                (-half_w, rail_min_y, 0.0),
                (half_w, rail_min_y, 0.0),
                (half_w, rail_max_y, 0.0),
                (-half_w, rail_max_y, 0.0),
            ]
            # Holder is edge-only to keep it readable as rail.
            edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
            faces = []

        self._update_mesh_geometry(mesh, verts, edges, faces)

        if obj.name not in collection.objects:
            try:
                collection.objects.link(obj)
            except RuntimeError:
                pass

        obj.parent = parent_obj
        obj.matrix_local = Matrix.Identity(4)
        obj.display_type = "WIRE"
        obj.hide_render = True
        obj.hide_select = True
        obj.show_in_front = True
        obj.hide_viewport = True
        try:
            obj.hide_set(True)
        except Exception:
            pass
        obj["coa_slider_custom_shape"] = True
        return obj

    def _ensure_text_object(self, name, text, collection, parent_obj):
        if name in bpy.data.objects and bpy.data.objects[name].type == "FONT":
            obj = bpy.data.objects[name]
            font_data = obj.data
        else:
            font_data = bpy.data.curves.new(name, type="FONT")
            obj = bpy.data.objects.new(name, font_data)

        if obj.name not in collection.objects:
            try:
                collection.objects.link(obj)
            except RuntimeError:
                pass

        font_data.body = text
        font_data.size = self.text_size
        font_data.align_x = "CENTER"
        font_data.align_y = "TOP"

        obj.parent = parent_obj
        obj.matrix_local = Matrix.Identity(4)
        obj.location = Vector((0.0, 0.0, -0.2))
        obj.rotation_euler = (math.pi * 0.5, 0.0, 0.0)
        obj.hide_render = True
        obj.hide_select = False
        obj.show_in_front = True
        obj["coa_slider_label_text"] = True
        return obj

    def _create_slider_rig(self, parent_armature_obj, mesh_obj, shapekey, collection):
        shape_label = self._get_safe_name(shapekey.name)
        obj_label = self._get_safe_name(mesh_obj.name)
        base_name = f"SSD_{obj_label}_{shape_label}_rig"
        rig_name = self._build_unique_name(set(bpy.data.objects.keys()), base_name)

        armature_data = bpy.data.armatures.new(rig_name)
        slider_rig = bpy.data.objects.new(rig_name, armature_data)
        collection.objects.link(slider_rig)

        slider_rigs = [
            child
            for child in parent_armature_obj.children
            if child.type == "ARMATURE" and bool(child.get("coa_slider_rig", False))
        ]
        x_offset = len(slider_rigs) * 0.25

        mesh_world_location = mesh_obj.matrix_world.to_translation()
        local_location = (
            parent_armature_obj.matrix_world.inverted() @ mesh_world_location
        )

        slider_rig.parent = parent_armature_obj
        slider_rig.location = local_location + Vector((x_offset, -0.1, 0.0))
        slider_rig.rotation_euler = (0.0, 0.0, 0.0)
        slider_rig.scale = (
            self.slider_rig_scale,
            self.slider_rig_scale,
            self.slider_rig_scale,
        )
        slider_rig.show_in_front = True
        slider_rig.display_type = "WIRE"
        slider_rig["coa_slider_rig"] = True
        slider_rig["coa_slider_target_mesh"] = mesh_obj.name
        slider_rig["coa_slider_target_shapekey"] = shapekey.name
        return slider_rig

    def _create_slider_bones(self, slider_rig):
        edit_bones = slider_rig.data.edit_bones

        base_name = "Base"
        slider_name = "Slider"

        base_bone = edit_bones.new(base_name)
        base_bone.head = (0.0, 0.0, 0.0)
        base_bone.tail = (0.0, 0.0, 0.35)
        base_bone.use_deform = False

        slider_bone = edit_bones.new(slider_name)
        # Align slider origin to holder origin so the shape starts from rail minimum.
        slider_bone.head = (0.0, 0.0, 0.0)
        slider_bone.tail = (0.0, 0.0, 0.35)
        slider_bone.parent = base_bone
        slider_bone.use_connect = False
        slider_bone.use_deform = False
        return base_name, slider_name

    def _assign_pose_settings(
        self,
        slider_rig,
        base_name,
        slider_name,
        holder_shape,
        slider_shape,
    ):
        base_pose_bone = slider_rig.pose.bones[base_name]
        slider_pose_bone = slider_rig.pose.bones[slider_name]

        base_pose_bone.custom_shape = holder_shape
        slider_pose_bone.custom_shape = slider_shape
        base_pose_bone.use_custom_shape_bone_size = False
        slider_pose_bone.use_custom_shape_bone_size = False

        base_pose_bone.lock_location = (True, True, True)
        base_pose_bone.lock_rotation = (True, True, True)
        base_pose_bone.lock_scale = (True, True, True)

        slider_pose_bone.location = (0.0, 0.0, 0.0)
        slider_pose_bone.lock_location[0] = True
        slider_pose_bone.lock_location[2] = True
        slider_pose_bone.lock_rotation = (True, True, True)
        slider_pose_bone.lock_scale = (True, True, True)

        for constraint in list(slider_pose_bone.constraints):
            if constraint.type == "LIMIT_LOCATION" and constraint.name.startswith(
                "SSD_"
            ):
                slider_pose_bone.constraints.remove(constraint)

        limit = slider_pose_bone.constraints.new("LIMIT_LOCATION")
        limit.name = "SSD_LimitLocation"
        limit.owner_space = "LOCAL"
        limit.use_min_y = True
        limit.min_y = 0.0
        limit.use_max_y = True
        limit.max_y = self.slider_length
        limit.use_transform_limit = True

    def _add_shapekey_driver(self, mesh_obj, armature_obj, slider_bone_name, shapekey):
        shapekey_data = mesh_obj.data.shape_keys
        escaped = shapekey.name.replace("\\", "\\\\").replace('"', '\\"')
        data_path = f'key_blocks["{escaped}"].value'

        try:
            shapekey_data.driver_remove(data_path)
        except Exception:
            pass

        fcurve = shapekey_data.driver_add(data_path)
        driver = fcurve.driver
        driver.type = "SCRIPTED"
        while len(driver.variables) > 0:
            driver.variables.remove(driver.variables[0])

        dvar = driver.variables.new()
        dvar.name = "slider"
        dvar.type = "TRANSFORMS"
        dvar.targets[0].id = armature_obj
        dvar.targets[0].bone_target = slider_bone_name
        dvar.targets[0].transform_type = "LOC_Y"
        dvar.targets[0].transform_space = "LOCAL_SPACE"

        driver.expression = f"max(0.0, min(1.0, slider / {self.slider_length:.6f}))"

    def execute(self, context):
        mesh_obj = context.active_object
        if mesh_obj is None or mesh_obj.type != "MESH":
            self.report({"ERROR"}, "Active object must be a mesh.")
            return {"CANCELLED"}
        if mesh_obj.data.shape_keys is None:
            self.report({"ERROR"}, "No shapekeys found.")
            return {"CANCELLED"}
        if mesh_obj.active_shape_key_index <= 0:
            self.report({"ERROR"}, "Select a non-Basis shapekey first.")
            return {"CANCELLED"}

        active_shapekey = mesh_obj.data.shape_keys.key_blocks[
            mesh_obj.active_shape_key_index
        ]
        sprite_object = functions.get_sprite_object(mesh_obj)
        armature_obj = functions.get_armature(sprite_object)
        if sprite_object is None or armature_obj is None:
            self.report({"ERROR"}, "Sprite object or armature was not found.")
            return {"CANCELLED"}
        if armature_obj.type != "ARMATURE":
            self.report({"ERROR"}, "Target armature is invalid.")
            return {"CANCELLED"}

        collection = (
            sprite_object.users_collection[0]
            if len(sprite_object.users_collection) > 0
            else context.scene.collection
        )

        prev_active = context.view_layer.objects.active
        prev_active_name = prev_active.name if prev_active is not None else None
        prev_mode = prev_active.mode if prev_active is not None else "OBJECT"
        prev_selected_names = [obj.name for obj in context.selected_objects]

        try:
            if prev_active is not None:
                bpy.ops.object.mode_set(mode="OBJECT")

            slider_rig = self._create_slider_rig(
                armature_obj, mesh_obj, active_shapekey, collection
            )

            for selected in context.selected_objects:
                selected.select_set(False)

            context.view_layer.objects.active = slider_rig
            slider_rig.select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")

            base_name, slider_name = self._create_slider_bones(slider_rig)

            bpy.ops.object.mode_set(mode="POSE")
            slider_shape_name = f"{slider_rig.name}_slider_shape"
            holder_shape_name = f"{slider_rig.name}_holder_shape"
            slider_shape = self._ensure_shape_object(
                slider_shape_name, "SLIDER", collection, slider_rig
            )
            holder_shape = self._ensure_shape_object(
                holder_shape_name, "HOLDER", collection, slider_rig
            )
            self._assign_pose_settings(
                slider_rig,
                base_name,
                slider_name,
                holder_shape,
                slider_shape,
            )
            self._add_shapekey_driver(
                mesh_obj, slider_rig, slider_name, active_shapekey
            )

            if self.create_text:
                text_name = f"{slider_rig.name}_text"
                self._ensure_text_object(
                    text_name,
                    active_shapekey.name,
                    collection,
                    slider_rig,
                )
        except Exception:
            traceback.print_exc()
            self.report(
                {"ERROR"}, "Failed to create slider rig. Check the console for details."
            )
            return {"CANCELLED"}
        finally:
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

            for obj in context.selected_objects:
                obj.select_set(False)
            for name in prev_selected_names:
                if name in bpy.data.objects:
                    bpy.data.objects[name].select_set(True)
            if prev_active_name in bpy.data.objects:
                context.view_layer.objects.active = bpy.data.objects[prev_active_name]
                if prev_mode != "OBJECT":
                    try:
                        bpy.ops.object.mode_set(mode=prev_mode)
                    except Exception:
                        pass

        self.report({"INFO"}, f'Slider driver created for "{active_shapekey.name}".')
        return {"FINISHED"}


def add_armature_menu_shapekey_slider_driver(self, context):
    self.layout.separator()
    self.layout.operator(
        COATOOLS2_OT_CreateShapekeySliderDriver.bl_idname,
        text="Shapekey Slider Driver",
        icon="DRIVER",
    )

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
from mathutils import Vector, Matrix, Quaternion
import math
import bmesh
import re
from bpy.props import (
    FloatProperty,
    IntProperty,
    BoolProperty,
    StringProperty,
    CollectionProperty,
    FloatVectorProperty,
    EnumProperty,
    IntVectorProperty,
    PointerProperty,
)
import os
from bpy_extras.io_utils import ExportHelper, ImportHelper
from .. import functions


def get_blender_collection(data, name):
    try:
        return getattr(bpy.data, name)
    except AttributeError:
        return None


class COATOOLS2_OT_ConvertOldVersionCoatools(bpy.types.Operator):
    bl_idname = "coa_tools2.convert_old_version_coatools"
    bl_label = "Convert from old version COA Tools"
    bl_description = "convert all sprites from old version COA Tools (by ndee85)"
    bl_options = {"REGISTER", "UNDO"}

    OLD_PROP_NAME = "coa_tools"
    NEW_PROP_NAME = "coa_tools2"

    def has_id_customdata(self, data):
        try:
            return self.OLD_PROP_NAME in data or data.get(self.OLD_PROP_NAME) is not None
        except (AttributeError, TypeError):
            return False

    def has_rna_customdata(self, data):
        return hasattr(data, self.OLD_PROP_NAME) and hasattr(data, self.NEW_PROP_NAME)

    def has_customdata(self, data):
        return self.has_id_customdata(data) or self.has_rna_customdata(data)

    def get_enum_value(self, prop, value):
        if isinstance(value, str):
            return value

        try:
            index = int(value)
        except (TypeError, ValueError):
            return value

        enum_items = list(prop.enum_items)
        if 0 <= index < len(enum_items):
            return enum_items[index].identifier
        for item in enum_items:
            if item.value == index:
                return item.identifier
        return value

    def get_pointer_value(self, prop, value):
        if value is None or hasattr(value, "name"):
            return value

        fixed_type = getattr(prop, "fixed_type", None)
        if fixed_type is None or not isinstance(value, str):
            return value

        collection_name_by_type = {
            "Mesh": "meshes",
            "Object": "objects",
            "Material": "materials",
            "Image": "images",
            "Armature": "armatures",
            "Action": "actions",
        }
        collection = get_blender_collection(
            bpy.data, collection_name_by_type.get(fixed_type.identifier, "")
        )
        if collection is not None:
            pointer = collection.get(value)
            if pointer is not None:
                return pointer
        return value

    def get_property_value(self, prop, value):
        if prop.type == "ENUM":
            return self.get_enum_value(prop, value)
        if prop.type == "POINTER":
            return self.get_pointer_value(prop, value)
        return value

    def set_property_value(self, dst, key, prop, value):
        value = self.get_property_value(prop, value)

        if prop.type in {"ENUM", "POINTER"}:
            try:
                setattr(dst, key, value)
                return
            except (AttributeError, TypeError, ValueError):
                pass

        try:
            dst[key] = value
        except (AttributeError, TypeError, ValueError):
            try:
                setattr(dst, key, value)
            except (AttributeError, TypeError, ValueError):
                pass

    def copy_mapping_to_property_group(self, src, dst):
        for key in src.keys():
            prop = dst.bl_rna.properties.get(key)
            if prop is None:
                try:
                    dst[key] = src[key]
                except (AttributeError, TypeError, ValueError):
                    pass
                continue

            value = src[key]
            if prop.type == "COLLECTION":
                dst_collection = getattr(dst, key)
                try:
                    dst_collection.clear()
                except AttributeError:
                    while len(dst_collection) > 0:
                        dst_collection.remove(0)
                for src_item in value:
                    dst_item = dst_collection.add()
                    object.__setattr__(dst_item, "_lock_active_update", True)
                    try:
                        self.copy_mapping_to_property_group(src_item, dst_item)
                    finally:
                        object.__setattr__(dst_item, "_lock_active_update", False)
            elif prop.is_readonly:
                try:
                    dst[key] = value
                except (AttributeError, TypeError, ValueError):
                    pass
            else:
                self.set_property_value(dst, key, prop, value)

    def copy_property_group(self, src, dst):
        for prop in src.bl_rna.properties:
            name = prop.identifier
            if name == "rna_type":
                continue

            try:
                value = getattr(src, name)
            except (AttributeError, TypeError):
                continue

            if prop.type == "COLLECTION":
                dst_collection = getattr(dst, name)
                try:
                    dst_collection.clear()
                except AttributeError:
                    while len(dst_collection) > 0:
                        dst_collection.remove(0)
                for src_item in value:
                    dst_item = dst_collection.add()
                    object.__setattr__(dst_item, "_lock_active_update", True)
                    try:
                        self.copy_property_group(src_item, dst_item)
                    finally:
                        object.__setattr__(dst_item, "_lock_active_update", False)
            elif prop.is_readonly:
                continue
            else:
                self.set_property_value(dst, name, prop, value)

        for key in getattr(src, "keys", lambda: [])():
            if dst.bl_rna.properties.get(key) is not None:
                continue
            try:
                dst[key] = src[key]
            except (AttributeError, TypeError, ValueError):
                pass

    def change_customdata_name(self, context, data):
        # Change custom property's name from "coa_tools" to "coa_tools2".
        if self.has_id_customdata(data):
            if hasattr(data, self.NEW_PROP_NAME):
                self.copy_mapping_to_property_group(
                    data[self.OLD_PROP_NAME],
                    getattr(data, self.NEW_PROP_NAME),
                )
            else:
                data[self.NEW_PROP_NAME] = data[self.OLD_PROP_NAME]
            del data[self.OLD_PROP_NAME]
            return True

        if self.has_rna_customdata(data):
            self.copy_property_group(
                getattr(data, self.OLD_PROP_NAME),
                getattr(data, self.NEW_PROP_NAME),
            )
            return True

        return False

    def get_slot_meshes(self, obj):
        meshes = []
        if obj.type != "MESH":
            return meshes

        try:
            if obj.coa_tools2.type != "SLOT":
                return meshes

            for slot in obj.coa_tools2.slot:
                if slot.mesh is not None and slot.mesh not in meshes:
                    meshes.append(slot.mesh)
        except (AttributeError, TypeError):
            pass
        return meshes

    def collect_meshes_referenced_by_objects(self):
        meshes = []
        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            if obj.data is not None and obj.data not in meshes:
                meshes.append(obj.data)
            for mesh in self.get_slot_meshes(obj):
                if mesh not in meshes:
                    meshes.append(mesh)
        return meshes

    def normalize_slot_objects(self):
        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            try:
                if obj.coa_tools2.type != "SLOT" or len(obj.coa_tools2.slot) == 0:
                    continue
            except (AttributeError, TypeError):
                continue

            slot_count = len(obj.coa_tools2.slot)
            slot_index = max(0, min(int(obj.coa_tools2.slot_index), slot_count - 1))

            object.__setattr__(obj.coa_tools2, "_lock_slot_index_update", True)
            try:
                obj.coa_tools2.slot_index = slot_index
                obj.coa_tools2.slot_reset_index = max(
                    0, min(int(obj.coa_tools2.slot_reset_index), slot_count - 1)
                )
            finally:
                object.__setattr__(obj.coa_tools2, "_lock_slot_index_update", False)

            for i, slot in enumerate(obj.coa_tools2.slot):
                slot.index = i
                slot["active"] = i == slot_index

            active_mesh = obj.coa_tools2.slot[slot_index].mesh
            if active_mesh is not None:
                functions.set_object_mesh_data_preserve_vertex_groups(obj, active_mesh)

    def normalize_edit_state(self):
        for obj in bpy.data.objects:
            try:
                obj.coa_tools2["edit_mesh"] = False
                obj.coa_tools2["edit_armature"] = False
                obj.coa_tools2["edit_weights"] = False
                obj.coa_tools2["edit_shapekey"] = False
                obj.coa_tools2["edit_mode"] = "OBJECT"
            except (AttributeError, TypeError):
                pass

    def iter_action_fcurves(self, action):
        legacy_fcurves = getattr(action, "fcurves", None)
        if legacy_fcurves is not None:
            yield from legacy_fcurves
            return

        action_slots = list(getattr(action, "slots", []))
        for layer in getattr(action, "layers", []):
            for strip in getattr(layer, "strips", []):
                for action_slot in action_slots:
                    try:
                        channelbag = strip.channelbag(action_slot)
                    except Exception:
                        continue
                    if channelbag is not None:
                        yield from getattr(channelbag, "fcurves", [])

    def convert_animation_data_paths(self):
        for action in bpy.data.actions:
            for fcurve in self.iter_action_fcurves(action):
                fcurve.data_path = self.convert_data_path(fcurve.data_path)

        animated_data = []
        animated_data.extend(bpy.data.objects)
        animated_data.extend(bpy.data.meshes)
        animated_data.extend(bpy.data.armatures)
        animated_data.extend(bpy.data.scenes)

        for data in animated_data:
            if data.animation_data is None:
                continue
            for driver in data.animation_data.drivers:
                driver.data_path = self.convert_data_path(driver.data_path)
                for variable in driver.driver.variables:
                    for target in variable.targets:
                        if target.data_path:
                            target.data_path = self.convert_data_path(target.data_path)

    def convert_data_path(self, data_path):
        if not data_path:
            return data_path
        data_path = re.sub(
            r'\["coa_tools"\]\["([^"]+)"\]',
            r"coa_tools2.\1",
            data_path,
        )
        return data_path.replace("coa_tools.", "coa_tools2.").replace(
            '["coa_tools"]', "coa_tools2"
        )

    def convert_bones(self):
        converted = 0
        for armature_data in bpy.data.armatures:
            for bone in armature_data.bones:
                if self.change_customdata_name(bpy.context, bone):
                    converted += 1
        return converted

    def execute(self, context):
        converted_objects = 0
        for obj in bpy.data.objects:
            if self.change_customdata_name(context, obj):
                converted_objects += 1

        converted_meshes = 0
        meshes = list(bpy.data.meshes)
        for mesh in self.collect_meshes_referenced_by_objects():
            if mesh not in meshes:
                meshes.append(mesh)
        for mesh in meshes:
            if self.change_customdata_name(context, mesh):
                converted_meshes += 1

        converted_scenes = 0
        for scene in bpy.data.scenes:
            if self.change_customdata_name(context, scene):
                converted_scenes += 1

        converted_bones = self.convert_bones()
        self.convert_animation_data_paths()
        self.normalize_slot_objects()
        self.normalize_edit_state()

        # finish
        self.report(
            {"INFO"},
            "Convert old COA Tools data finished. "
            f"Objects: {converted_objects}, meshes: {converted_meshes}, "
            f"bones: {converted_bones}, scenes: {converted_scenes}.",
        )
        context.scene.coa_tools2.old_coatools_found = False
        return {"FINISHED"}

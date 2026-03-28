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
import os
from bpy_extras.io_utils import ExportHelper, ImportHelper
import json
from bpy.app.handlers import persistent
from .. import functions


class COATOOLS2_OT_ExtractSlots(bpy.types.Operator):
    bl_idname = "coa_tools2.extract_slots"
    bl_label = "Extract Slots"
    bl_description = ""
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        obj = context.active_object
        if obj.type == "MESH" and len(obj.coa_tools2.slot) > 0:
            for i, slot in enumerate(obj.coa_tools2.slot):
                name = obj.name + "_" + str(i).zfill(2)
                ob = obj.copy()
                functions.link_object(context, ob)
                ob.name = name
                ob.coa_tools2.type = "MESH"
                ob.data = slot.mesh
                for slot in ob.coa_tools2.slot:
                    ob.coa_tools2.slot.remove(0)
                ob.parent = obj.parent
                ob.matrix_world = obj.matrix_world
                ob.select_set(True)
                context.view_layer.objects.active = ob

        bpy.data.objects.remove(obj, do_unlink=True)
        return {"FINISHED"}


class COATOOLS2_OT_CreateSlotObject(bpy.types.Operator):
    bl_idname = "coa_tools2.create_slot_object"
    bl_label = "Create Slot Object"
    bl_description = ""
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        return True

    slot_name: StringProperty(name="Slot Name")
    keep_sprite_position: BoolProperty(
        name="Keep Sprite Position",
        description="Keeps the sprite at current position by applying a new origin.",
        default=True,
    )

    def draw(self, context):
        layout = self.layout
        if context.active_object.coa_tools2.type == "MESH":
            layout.prop(self, "slot_name")
        layout.prop(self, "keep_sprite_position")

    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_props_dialog(self)

    def objects_are_valid(self, context):
        count = 0
        for obj in context.selected_objects:
            if obj.type != "MESH":
                return False
            else:
                count += 1
        if count > 1:
            return True
        else:
            return False

    def find_slot_item_by_mesh(self, slot_collection, mesh):
        for slot_item in slot_collection:
            if slot_item.mesh == mesh:
                return slot_item
        return None

    def execute(self, context):
        if not self.objects_are_valid(context):
            self.report(
                {"INFO"}, "Please select at least to Sprites to combine into a slot."
            )
            return {"CANCELLED"}

        name = str(context.active_object.name)
        init_obj = bpy.data.objects[context.active_object.name]
        objs = context.selected_objects[:]
        obj = context.active_object.copy()
        functions.link_object(context, obj)
        context.view_layer.objects.active = obj
        if obj.coa_tools2.type == "MESH":
            name = self.slot_name
            obj.name = self.slot_name

        if self.keep_sprite_position:
            for ob in objs:
                slots = []
                if ob.coa_tools2.type == "MESH":
                    slots = [ob.data]
                elif ob.coa_tools2.type == "SLOT":
                    for slot in ob.coa_tools2.slot:
                        slots.append(slot.mesh)

                ob.location[1] = obj.location[1]
                for i, slot in enumerate(slots):
                    ob_tmp = ob.copy()
                    functions.link_object(context, ob_tmp)
                    ob_tmp.data = slot
                    ob_tmp.select_set(True)

                    ### deselect all objects, select the current from iteration
                    bpy.ops.object.select_all(action="DESELECT")
                    ob_tmp.select_set(True)
                    context.view_layer.objects.active = ob_tmp

                    cursor_location = Vector(context.scene.cursor.location)
                    context.scene.cursor.location = obj.matrix_world.to_translation()
                    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
                    context.scene.cursor.location = cursor_location

                    bpy.data.objects.remove(ob_tmp, do_unlink=True)

            cursor_location = Vector(context.scene.cursor.location)
            context.scene.cursor.location = obj.matrix_world.to_translation()
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
            context.scene.cursor.location = cursor_location

        obj.select_set(True)
        context.view_layer.objects.active = obj

        obj.coa_tools2.type = "SLOT"
        for sprite in objs:
            if sprite != obj:
                if sprite.type == "MESH":
                    item = None
                    if sprite.coa_tools2.type == "MESH":
                        item = self.find_slot_item_by_mesh(obj.coa_tools2.slot, sprite.data)
                        is_new_item = item is None
                        if is_new_item:
                            item = obj.coa_tools2.slot.add()
                        item.mesh = sprite.data
                        # item.name = sprite.data.name
                        if is_new_item:
                            item.index = len(obj.coa_tools2.slot) - 1
                        if sprite == init_obj:
                            obj.coa_tools2.slot_index = item.index
                            obj.coa_tools2.slot_reset_index = item.index
                    elif sprite.coa_tools2.type == "SLOT" and sprite != init_obj:
                        for slot in sprite.coa_tools2.slot:
                            item = obj.coa_tools2.slot.add()
                            # item.name = slot.name
                            item.mesh = slot.mesh
                    if item != None:
                        object.__setattr__(item, "_lock_active_update", True)
                        try:
                            item.active = False
                        finally:
                            object.__setattr__(item, "_lock_active_update", False)
        obj.coa_tools2.slot[0].active = True
        ### delete original sprite
        for sprite in objs:
            bpy.data.objects.remove(sprite, do_unlink=True)
        for i, s in enumerate(obj.coa_tools2.slot):
            s.index = i
        obj.name = name
        return {"FINISHED"}


class COATOOLS2_OT_MoveSlotItem(bpy.types.Operator):
    bl_idname = "coa_tools2.move_slot_item"
    bl_label = "Move Slot Item"
    bl_description = ""
    bl_options = {"REGISTER"}

    idx: IntProperty()
    ob_name: StringProperty()
    mode: StringProperty()

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        obj = bpy.data.objects[self.ob_name]

        if self.mode == "UP":
            new_idx = max(self.idx - 1, 0)
            obj.coa_tools2.slot.move(self.idx, new_idx)
        elif self.mode == "DOWN":
            new_idx = min(self.idx + 1, len(obj.coa_tools2.slot) - 1)
            obj.coa_tools2.slot.move(self.idx, new_idx)

        for i, s in enumerate(obj.coa_tools2.slot):
            s.index = i

        return {"FINISHED"}


class COATOOLS2_OT_RemoveFromSlot(bpy.types.Operator):
    bl_idname = "coa_tools2.remove_from_slot"
    bl_label = "Remove From Slot"
    bl_description = ""
    bl_options = {"REGISTER"}

    idx: IntProperty()
    ob_name: StringProperty()

    @classmethod
    def poll(cls, context):
        return True

    def execute(self, context):
        obj = bpy.data.objects[self.ob_name]
        slot = obj.coa_tools2.slot[self.idx]
        active_idx = 0
        for i, s in enumerate(obj.coa_tools2.slot):
            if s.active:
                active_idx = i
                break
        obj.coa_tools2.slot.remove(self.idx)

        active_idx = max(0, (active_idx - 1))

        for i, s in enumerate(obj.coa_tools2.slot):
            s["index"] = i
        if len(obj.coa_tools2.slot) > 0:
            obj.coa_tools2.slot[active_idx].active = True
        else:
            bpy.data.objects.remove(obj, do_unlink=True)

        #        for s in obj.coa_tools2.slot:
        #            if s.index > self.idx:
        #                s["index"] -= 1
        return {"FINISHED"}

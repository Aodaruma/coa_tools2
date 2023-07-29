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
    PointerProperty,
)
import os
from bpy_extras.io_utils import ExportHelper, ImportHelper


class COATOOLS2_OT_ConvertOldVersionCoatools(bpy.types.Operator):
    bl_idname = "coa_tools2.convert_old_version_coatools"
    bl_label = "Convert from old version COA Tools"
    bl_description = "convert all sprites from old version COA Tools (by ndee85)"
    bl_options = {"REGISTER", "UNDO"}

    def change_customdata_name(self, context, obj):
        # change custom property's name "coa_tools" to "coa_tools2"
        if "coa_tools" in obj or obj.get("coa_tools") is not None:
            obj["coa_tools2"] = obj["coa_tools"]
            # obj["coa_tools"]
            del obj["coa_tools"]

        else:
            print("coa_tools not found in " + obj.name, type(obj))

    def execute(self, context):
        # convert objects
        objects = []
        for obj in bpy.data.objects:
            # print(obj.name, obj.type, dir(obj), obj.get("coa_tools"))
            if obj.get("coa_tools") is not None:
                objects.append(obj)

        if len(objects) == 0:
            self.report(
                {"ERROR"},
                "objects registered with old_version COA Tools was not found.",
            )
            # context.scene.coa_tools2.old_coatools_found = False
            return {"CANCELLED"}

        # search sprite in each armature and convert to new version
        for obj in objects:
            if obj.type == "ARMATURE":
                for child in obj.children:
                    if child.type == "MESH":
                        # convert object
                        self.change_customdata_name(context, child)

                        # convert mesh of object
                        self.change_customdata_name(context, child.data)

            # convert armature
            self.change_customdata_name(context, obj)

        # finish
        self.report(
            {"INFO"}, "Convert All sprites from old version COA Tools is finished."
        )
        context.scene.coa_tools2.old_coatools_found = False
        return {"FINISHED"}

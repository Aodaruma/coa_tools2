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

from ..functions import hide_base_sprite


class copymeshdata(bpy.types.PropertyGroup):
    from_mesh: PointerProperty(
        name="From Mesh",
        description="Mesh data from this object will be copied",
        type=bpy.types.Object,
    )


bpy.utils.register_class(copymeshdata)

bpy.types.Object.copy_data_from_mesh_object = bpy.props.PointerProperty(
    type=copymeshdata
)


class COATOOLS2_OT_CopyMeshData(bpy.types.Operator):
    bl_idname = "coa_tools2.copy_mesh_data"
    bl_label = "Copy Mesh Data"
    bl_description = "Copy mesh data from active object to selected objects"
    bl_options = {"REGISTER", "UNDO"}

    # from_mesh: PointerProperty(
    #     name="From Mesh",
    #     description="Mesh data from this object will be copied",
    #     type=bpy.types.Object.copy_data_from_mesh_object,
    # )

    is_copy_vertex_groups: BoolProperty(
        name="Copy Vertex Groups",
        description="Copy vertex groups from selected object",
        default=True,
    )

    is_copy_shapekeys: BoolProperty(
        name="Copy Shapekeys",
        description="Copy shapekeys from selected object",
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return (
            context.object is not None
            and context.object.type == "MESH"
            and context.object.mode == "OBJECT"
        )

    def draw(self, context):
        layout = self.layout
        # layout.prop(self, "from_mesh")
        layout.prop(self, "is_copy_vertex_groups")
        layout.prop(self, "is_copy_shapekeys")

    def execute(self, context):
        # copy mesh data
        active_obj = context.object
        for obj in context.selected_objects:
            # obj = context.object
            # active_obj = self.from_mesh
            if obj.type == "MESH" and obj != active_obj:
                basevg: bpy.types.VertexGroup = active_obj.vertex_groups.get(
                    "coa_base_sprite"
                )
                coor_diff = obj.location - active_obj.location

                # delete all vertex while vertex group "coa_base_sprite" is assigned
                bm = bmesh.new()
                bm.from_mesh(obj.data)
                bm.verts.layers.deform.verify()
                dvert_layer = bm.verts.layers.deform.active
                for v in bm.verts:
                    dv = v[dvert_layer]
                    if basevg.index not in dv:
                        bm.verts.remove(v)
                bm.to_mesh(obj.data)
                bm.free()

                bm = bmesh.new()
                # load mesh data from active_obj
                bm.from_mesh(active_obj.data)

                # remove vertex group "coa_base_sprite" from bm
                bm.verts.layers.deform.verify()
                dvert_layer = bm.verts.layers.deform.active
                for v in bm.verts:
                    dv = v[dvert_layer]
                    if basevg.index in dv:
                        bm.verts.remove(v)

                bmesh.ops.translate(bm, verts=bm.verts, vec=-coor_diff)

                # load mesh data from obj
                bm.from_mesh(obj.data)

                # convert bm to mesh data
                bm.to_mesh(obj.data)
                bm.free()

                # deselect all objects and select obj and active object
                bpy.ops.object.select_all(action="DESELECT")
                context.view_layer.objects.active = obj
                bpy.ops.coa_tools2.reproject_sprite_texture()
                bpy.ops.object.mode_set(mode="OBJECT")
                obj.data.coa_tools2.hide_base_sprite = True
                obj.coa_tools2.copy_data_from_mesh = active_obj.data

                # copy vertex groups
                if self.is_copy_vertex_groups:
                    for vg in active_obj.vertex_groups:
                        if vg.name != "coa_base_sprite":
                            if vg.name in obj.vertex_groups:
                                group = obj.vertex_groups[vg.name]
                            else:
                                group = obj.vertex_groups.new(name=vg.name)
                            for av, v in zip(
                                active_obj.data.vertices, obj.data.vertices
                            ):
                                for g in av.groups:
                                    if g.group == vg.index:
                                        w = vg.weight(av.index)
                                        group.add([v.index], w, "REPLACE")
                                        break

                # copy shapekeys
                if self.is_copy_shapekeys:
                    if active_obj.data.shape_keys:
                        for sk in active_obj.data.shape_keys.key_blocks:
                            if (
                                obj.data.shape_keys is None
                                or sk.name not in obj.data.shape_keys.key_blocks
                            ):
                                obj.shape_key_add(name=sk.name)
                            obj.data.shape_keys.key_blocks[sk.name].relative_key = sk

        bpy.ops.object.select_all(action="DESELECT")
        for obj in context.selected_objects:
            obj.select_set(True)
        context.view_layer.objects.active = active_obj

        return {"FINISHED"}

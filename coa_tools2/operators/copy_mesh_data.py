"""
Copyright (C) 2023 Aodaruma
hi@aodaruma.net

Created by Aodaruma

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.
"""

import bpy
import bmesh
from bpy.props import BoolProperty


class COATOOLS2_OT_CopyMeshData(bpy.types.Operator):
    bl_idname = "coa_tools2.copy_mesh_data"
    bl_label = "Copy Mesh Data"
    bl_description = "Copy mesh data from active object to selected objects"
    bl_options = {"REGISTER", "UNDO"}

    is_copy_vertex_groups: BoolProperty(
        name="Copy Vertex Groups",
        description="Copy vertex groups from active object",
        default=True,
    )

    is_copy_shapekeys: BoolProperty(
        name="Copy Shapekeys",
        description="Copy shapekeys from active object",
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
        layout.prop(self, "is_copy_vertex_groups")
        layout.prop(self, "is_copy_shapekeys")

    def execute(self, context):
        active_obj = context.object
        targets = [obj for obj in context.selected_objects if obj.type == "MESH" and obj != active_obj]

        if not targets:
            self.report({"WARNING"}, "No target mesh selected.")
            return {"CANCELLED"}

        basevg = active_obj.vertex_groups.get("coa_base_sprite")
        if basevg is None:
            self.report({"ERROR"}, "Active mesh has no 'coa_base_sprite' vertex group.")
            return {"CANCELLED"}

        original_selection = list(context.selected_objects)

        for obj in targets:
            coor_diff = obj.location - active_obj.location

            # Keep only base-sprite verts in target before appending source data.
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bm.verts.layers.deform.verify()
            dvert_layer = bm.verts.layers.deform.active
            for v in list(bm.verts):
                dv = v[dvert_layer]
                if basevg.index not in dv:
                    bm.verts.remove(v)
            bm.to_mesh(obj.data)
            bm.free()

            # Copy active mesh geometry except base-sprite verts.
            bm = bmesh.new()
            bm.from_mesh(active_obj.data)
            bm.verts.layers.deform.verify()
            dvert_layer = bm.verts.layers.deform.active
            for v in list(bm.verts):
                dv = v[dvert_layer]
                if basevg.index in dv:
                    bm.verts.remove(v)

            bmesh.ops.translate(bm, verts=bm.verts, vec=-coor_diff)
            bm.from_mesh(obj.data)
            bm.to_mesh(obj.data)
            bm.free()

            bpy.ops.object.select_all(action="DESELECT")
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.coa_tools2.reproject_sprite_texture()
            bpy.ops.object.mode_set(mode="OBJECT")
            obj.data.coa_tools2.hide_base_sprite = True
            obj.coa_tools2.copy_data_from_mesh = active_obj.data

            if self.is_copy_vertex_groups:
                for vg in active_obj.vertex_groups:
                    if vg.name == "coa_base_sprite":
                        continue

                    if vg.name in obj.vertex_groups:
                        group = obj.vertex_groups[vg.name]
                    else:
                        group = obj.vertex_groups.new(name=vg.name)

                    for av, v in zip(active_obj.data.vertices, obj.data.vertices):
                        for g in av.groups:
                            if g.group == vg.index:
                                weight = vg.weight(av.index)
                                group.add([v.index], weight, "REPLACE")
                                break

            if self.is_copy_shapekeys and active_obj.data.shape_keys:
                for sk in active_obj.data.shape_keys.key_blocks:
                    if (
                        obj.data.shape_keys is None
                        or sk.name not in obj.data.shape_keys.key_blocks
                    ):
                        obj.shape_key_add(name=sk.name)
                    obj.data.shape_keys.key_blocks[sk.name].relative_key = sk

        bpy.ops.object.select_all(action="DESELECT")
        for obj in original_selection:
            obj.select_set(True)
        context.view_layer.objects.active = active_obj

        return {"FINISHED"}

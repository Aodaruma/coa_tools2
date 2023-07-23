import os
import bpy
import bpy_extras
import bpy_extras.view3d_utils
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
from .. import functions
from ..functions_draw import *
import bgl
import blf
from math import radians, degrees
import pdb
import cv2
from typing import Optional
import numpy as np

# ======================================================================================================================


def get_texture_image(context, obj) -> Optional[bpy.types.Image]:
    """Get the texture image from the object material"""
    if obj.type == "MESH":
        mat = obj.active_material
        if mat:
            if mat.node_tree:
                for node in mat.node_tree.nodes:
                    if node.type == "TEX_IMAGE":
                        return node.image
    return None


def get_contour(
    context,
    filepath,
    resolution: Optional[float] = 0.25,
    dilate: Optional[int] = 0,
    padding: Optional[int] = 50,
):
    """Get the contour points of image"""
    # get image with alpha
    img = cv2.imread(filepath, cv2.IMREAD_UNCHANGED)
    # check if image has alpha channel
    if img.shape[2] == 4:
        img = img[:, :, 3]
        img = cv2.resize(img, (0, 0), fx=resolution, fy=resolution)
        img = cv2.copyMakeBorder(
            img, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=0
        )

        if not isinstance(dilate, int):
            dilate = int(dilate)
        if dilate < 0:
            dilate = -dilate
            kernel = np.ones((dilate, dilate), np.uint8)
            img = cv2.erode(img, kernel, iterations=1)
        elif dilate > 0:
            kernel = np.ones((dilate, dilate), np.uint8)
            img = cv2.dilate(img, kernel, iterations=1)

        ret, thresh = cv2.threshold(img, 127, 255, 0)
        contours, hierarchy = cv2.findContours(
            thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_TC89_KCOS
        )
        return contours, hierarchy
    else:
        return [], []


def reconstruct_contour(
    contours,
    max_distance: Optional[float] = 1.0,
    min_distance: Optional[float] = 0.5,
    threadhold_angle: Optional[float] = 50.0,
    padding: Optional[int] = 50,
):
    """Reconstruct the contour points"""
    points = []
    for c in contours:
        p = []
        c0 = None
        for i in range(len(c)):
            c1 = c[i]
            c2 = c[i + 1] if i < len(c) - 1 else c[0]

            # d0 = mathutils.Vector(c0[0]) / 100 if c0 is not None else None
            # d1 = mathutils.Vector(c1[0]) / 100
            # d2 = mathutils.Vector(c2[0]) / 100
            d1 = mathutils.Vector(c1[0]) - mathutils.Vector((padding, padding))
            p.append(d1)
            # length_01 = (d0 - d1).length if d0 else 0
            # length_12 = (d1 - d2).length
            # if length_12 > max_distance:
            #     middle_point_num = int(length_12 / max_distance)
            #     for j in range(middle_point_num):
            #         p.append(d1.lerp(d2, j / middle_point_num))
            # elif length_12 < min_distance:
            #     if c0 is not None:
            #         angle_012 = math.degrees(mathutils.Vector.angle(d0 - d1, d2 - d1))
            #         if (
            #             angle_012 < threadhold_angle
            #             or 360 - angle_012 < threadhold_angle
            #         ):
            #             p.append(d1)
            #             c0 = None
            #             continue
            #     if length_01 + length_12 >= min_distance:
            #         p.append(d1)
            #         c0 = None
            #     else:
            #         c0 = c1
            # else:
            #     p.append(d1)
            #     c0 = None
        points.append(p)
    return points


def points_to_mesh(
    context,
    outer_contour,
    inner_contour,
    resolution: Optional[float] = 0.25,
    is_create_faces: Optional[bool] = True,
):
    """Create a mesh from points"""
    me = context.object.data
    if not me.is_editmode:
        bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(me)

    outer_verts_contours = []
    inner_verts_contours = []

    for c in outer_contour:
        outer_verts = []
        for i, p in enumerate(c):
            p = mathutils.Vector((p.x, 0, -p.y)) / resolution / 100
            v = bm.verts.new(p)
            outer_verts.append(v)
        outer_verts_contours.append(outer_verts)

    for c in inner_contour:
        innver_verts = []
        for i, p in enumerate(c):
            p = mathutils.Vector((p.x, 0, -p.y)) / resolution / 100
            v = bm.verts.new(p)
            innver_verts.append(v)
        inner_verts_contours.append(innver_verts)

    # bmesh.ops.contextual_create(bm, geom=bm_outer.edges[:] + bm_inner.edges[:])
    inner_faces, inner_edges, outer_faces, outer_edges = [], [], [], []
    for iv in inner_verts_contours:
        r = bmesh.ops.contextual_create(bm, geom=iv)
        if r["faces"]:
            f = r["faces"][0]
            inner_faces.append(f)
            inner_edges.append(f.edges[:])
    for ov in outer_verts_contours:
        r = bmesh.ops.contextual_create(bm, geom=ov)
        if r["faces"]:
            f = r["faces"][0]
            outer_faces.append(f)
            outer_edges.append(f.edges[:])
    for f in outer_faces:
        bm.faces.remove(f)

    if bpy.ops.mesh.looptools_relax and bpy.ops.mesh.looptools_space:
        for f in inner_faces:
            bm.faces.remove(f)
            del f
        bmesh.update_edit_mesh(me)
        bpy.ops.mesh.looptools_relax()
        bpy.ops.mesh.looptools_space()
        for iv in inner_verts_contours:
            r = bmesh.ops.contextual_create(bm, geom=iv)
            if r["faces"]:
                f = r["faces"][0]
                inner_faces.append(f)

    if is_create_faces:
        bm.edges.ensure_lookup_table()
        flatten_inner_edges = [e for edges in inner_edges for e in edges]
        flatten_outer_edges = [e for edges in outer_edges for e in edges]
        bmesh.ops.triangle_fill(
            bm,
            use_beauty=True,
            use_dissolve=False,
            edges=flatten_inner_edges + flatten_outer_edges,
        )
    else:
        for f in inner_faces:
            bm.faces.remove(f)
    bmesh.update_edit_mesh(me)


class COATOOLS2_OT_AutomeshFromTexture(bpy.types.Operator):
    """Automesh from texture"""

    bl_idname = "coa_tools2.automesh_from_texture"
    bl_label = "Automesh from texture"
    bl_options = {"REGISTER", "UNDO"}

    resolution: FloatProperty(
        name="Resolution",
        description="Image resolution when deteting contours",
        default=0.25,
        min=0.01,
        max=1.0,
    )
    margin: FloatProperty(
        name="Margin",
        description="Margin of the contour",
        default=5.0,
        min=0.01,
        max=10.0,
    )
    # threadhold_angle: FloatProperty(
    #     name="Threadhold Angle",
    #     description="Threadhold angle of the contour",
    #     default=50.0,
    #     min=0.01,
    #     max=180.0,
    # )
    is_create_faces: BoolProperty(
        name="Create Faces",
        description="Create faces",
        default=False,
    )

    outer_contours = None
    inner_contours = None
    padding = 50

    @classmethod
    def poll(cls, context):
        return (
            context.active_object is not None and context.active_object.type == "MESH"
        )

    def execute(self, context):
        print("Automesh from texture...")
        if self.outer_contours is None or self.inner_contours is None:
            obj = context.active_object
            blimg = get_texture_image(context, obj)
            filepath = bpy.path.abspath(blimg.filepath)
            if filepath is not None and os.path.exists(filepath):
                print("got img:", filepath)
                self.inner_contours, _ = get_contour(
                    context, filepath, self.resolution, -self.margin, self.padding
                )
                self.outer_contours, _ = get_contour(
                    context, filepath, self.resolution, self.margin, self.padding
                )

        if len(self.inner_contours) > 0 and len(self.outer_contours) > 0:
            inner_points = reconstruct_contour(
                self.inner_contours, padding=self.padding
            )
            outer_points = reconstruct_contour(
                self.outer_contours, padding=self.padding
            )
            points_to_mesh(
                context,
                outer_points,
                inner_points,
                self.resolution,
                self.is_create_faces,
            )
            print("done")
            return {"FINISHED"}
        else:
            # show error dialog

            return {"CANCELLED"}

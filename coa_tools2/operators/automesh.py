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
    threshold: Optional[int] = 127,
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

        ret, thresh = cv2.threshold(img, threshold, 255, cv2.THRESH_BINARY)
        contours, hierarchy = cv2.findContours(
            thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_TC89_KCOS
        )
        return contours, hierarchy
    else:
        return [], []


def reconstruct_contour(
    contours,
    padding: Optional[int] = 50,
):
    """Reconstruct the contour points"""
    result = []
    for c in contours:
        points = []
        for p in c:
            v = mathutils.Vector(p[0]) - mathutils.Vector((padding, padding))
            points.append(v)
        result.append(points)
    return result


def points_to_mesh(
    context,
    outer_contour,
    inner_contour,
    resolution: Optional[float] = 0.25,
    is_create_faces: Optional[bool] = True,
):
    """Create a mesh from points"""
    if inner_contour is None:
        inner_contour = []

    me = context.object.data
    if not me.is_editmode:
        bpy.ops.object.mode_set(mode="EDIT")
    bm = bmesh.from_edit_mesh(me)

    outer_verts, inner_verts = [], []
    outer_edges, inner_edges = [], []

    for c in outer_contour:
        if len(c) < 3:
            continue

        verts, edges = [], []
        pv = None
        for i, p in enumerate(c):
            p = mathutils.Vector((p.x, 0, -p.y)) / resolution / 100
            v = bm.verts.new(p)
            if pv is not None:
                edges.append(bm.edges.new((pv, v)))
            pv = v
            verts.append(v)
        edges.append(bm.edges.new((pv, verts[0])))
        outer_verts.append(verts)

    for c in inner_contour:
        if len(c) < 3:
            continue

        verts, edges = [], []
        pv = None
        for i, p in enumerate(c):
            p = mathutils.Vector((p.x, 0, -p.y)) / resolution / 100
            v = bm.verts.new(p)
            if pv is not None:
                edges.append(bm.edges.new((pv, v)))
            pv = v
            verts.append(v)
        edges.append(bm.edges.new((pv, verts[0])))
        inner_verts.append(verts)

    if bpy.ops.mesh.looptools_relax and bpy.ops.mesh.looptools_space:
        bmesh.update_edit_mesh(me)
        bpy.ops.mesh.looptools_relax("INVOKE_DEFAULT")
        bpy.ops.mesh.looptools_space("INVOKE_DEFAULT")

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
        for ie in inner_edges:
            bmesh.ops.contextual_create(bm, geom=ie)

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
    threshold: FloatProperty(
        name="Threshold",
        description="Alpha Threshold when deteting contours",
        default=127.0,
        min=0.0,
        max=255.0,
    )
    margin: FloatProperty(
        name="Margin",
        description="Margin of the contour",
        default=5.0,
        min=0.01,
        max=100.0,
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
    old_resolution = 0.25
    old_margin = 5.0

    @classmethod
    def poll(cls, context):
        return (
            context.active_object is not None and context.active_object.type == "MESH"
        )

    def execute(self, context):
        print("Automesh from texture...")
        if (
            self.outer_contours is None
            or self.inner_contours is None
            or self.resolution != self.old_resolution
            or self.margin != self.old_margin
        ):
            print("get contours...")
            obj = context.active_object
            blimg = get_texture_image(context, obj)
            filepath = bpy.path.abspath(blimg.filepath)
            if filepath is not None and os.path.exists(filepath):
                print("got img:", filepath)
                self.inner_contours, _ = get_contour(
                    context,
                    filepath,
                    self.resolution,
                    self.threshold,
                    -self.margin,
                    self.padding,
                )
                self.outer_contours, _ = get_contour(
                    context,
                    filepath,
                    self.resolution,
                    self.threshold,
                    self.margin,
                    self.padding,
                )

        self.old_resolution = self.resolution
        self.old_margin = self.margin

        if self.outer_contours is not None and len(self.outer_contours) > 0:
            print("reconstruct contours...")
            inner_points = None
            if self.inner_contours is not None and len(self.inner_contours) > 0:
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

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

bl_info = {
    "name": "COA Tools2",
    "description": "This Addon provides a Toolset for a 2D Animation Workflow.",
    "author": "Aodaruma",
    "version": (1, 0, 0),
    "blender": (3, 40, 0),
    "location": "View 3D > Tools > Cutout Animation Tools",
    "warning": "",
    "wiki_url": "https://github.com/aodaruma/coa_tools2/wiki",
    "tracker_url": "https://github.com/aodaruma/coa_tools2/issues",
    "category": "Animation",
}


import bpy
import os
import shutil
import tempfile
from bpy.app.handlers import persistent

from . import addon_updater_ops

# load and reload submodules
##################################

from . import properties as props

from . import ui as user_interface
from .ui import preview_collections
from . import outliner
from .operators.pie_menu import preview_collections_pie
from .functions import *

from .operators import create_sprite_object
from .operators import help_display

from .operators import advanced_settings
from .operators import animation_handling
from .operators import create_ortho_cam
from .operators import create_spritesheet_preview
from .operators import draw_bone_shape
from .operators import edit_armature
from .operators import edit_mesh
from .operators import automesh
from .operators import edit_shapekey
from .operators import edit_weights
from .operators import import_sprites
from .operators import material_converter
from .operators import pie_menu
from .operators import slot_handling
from .operators import toggle_animation_area
from .operators import view_sprites
from .operators import version_converter
from .operators import change_alpha_mode
from .operators import convert_from_old
from .operators import copy_mesh_data

from .operators.exporter import export_dragonbones
from .operators.exporter import export_creature

# register
##################################

import traceback


class COATools2Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    enable_updater: bpy.props.BoolProperty(
        name="Enable Updater",
        description="If enabled, an update notification will appear when a new version is available",
        default=True,
    )
    auto_check_update: bpy.props.BoolProperty(
        name="Auto-check for Update",
        description="If enabled, auto-check for updates using an interval",
        default=False,
    )
    updater_intrval_months: bpy.props.IntProperty(
        name="Months",
        description="Number of months between checking for updates",
        default=0,
        min=0,
    )
    updater_intrval_days: bpy.props.IntProperty(
        name="Days",
        description="Number of days between checking for updates",
        default=1,
        min=0,
    )
    updater_intrval_hours: bpy.props.IntProperty(
        name="Hours",
        description="Number of hours between checking for updates",
        default=0,
        min=0,
        max=23,
    )
    updater_intrval_minutes: bpy.props.IntProperty(
        name="Minutes",
        description="Number of minutes between checking for updates",
        default=0,
        min=0,
        max=59,
    )
    sprite_import_export_scale: bpy.props.FloatProperty(
        name="Scale",
        description="Import/Export scale factor, 1 px = X units",
        default=0.01,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "sprite_import_export_scale")

        row = layout.row(align=True)
        row.prop(self, "enable_updater")
        row.prop(self, "auto_check_update", text="Auto-check for Update")

        if self.enable_updater:
            addon_updater_ops.update_settings_ui(self, context)


classes = (
    COATools2Preferences,
    # outliner
    outliner.COAOutliner,
    outliner.COATOOLS2_UL_Outliner,
    # properties
    props.UVData,
    props.SlotData,
    props.Event,
    props.TimelineEvent,
    props.AnimationCollections,
    props.ObjectProperties,
    props.SceneProperties,
    props.MeshProperties,
    props.BoneProperties,
    props.WindowManagerProperties,
    # operator
    create_sprite_object.COATOOLS2_OT_CreateSpriteObject,
    create_sprite_object.COATOOLS2_OT_DefineSpriteObject,
    import_sprites.JsonImportData,
    import_sprites.COATOOLS2_OT_CreateMaterialGroup,
    import_sprites.COATOOLS2_OT_ImportSprite,
    import_sprites.COATOOLS2_OT_ImportSprites,
    import_sprites.COATOOLS2_OT_LoadJsonData,
    import_sprites.COATOOLS2_UL_JsonImport,
    import_sprites.COATOOLS2_OT_ReImportSprite,
    user_interface.COATOOLS2_OT_ChangeShadingMode,
    user_interface.COATOOLS2_PT_Info,
    user_interface.COATOOLS2_PT_ObjectProperties,
    user_interface.COATOOLS2_PT_Tools,
    user_interface.COATOOLS2_UL_AnimationCollections,
    user_interface.COATOOLS2_UL_EventCollection,
    user_interface.COATOOLS2_OT_SelectChild,
    user_interface.COATOOLS2_PT_Collections,
    view_sprites.COATOOLS2_OT_ChangeZOrdering,
    view_sprites.COATOOLS2_OT_ViewSprite,
    advanced_settings.COATOOLS2_OT_AdvancedSettings,
    edit_mesh.COATOOLS2_OT_ReprojectSpriteTexture,
    edit_mesh.COATOOLS2_OT_GenerateMeshFromEdgesAndVerts,
    edit_mesh.COATOOLS2_OT_DrawContour,
    edit_mesh.COATOOLS2_OT_PickEdgeLength,
    copy_mesh_data.COATOOLS2_OT_CopyMeshData,
    automesh.COATOOLS2_OT_AutomeshFromTexture,
    edit_armature.COATOOLS2_OT_TooglePoseMode,
    edit_armature.COATOOLS2_OT_BindMeshToBones,
    edit_armature.COATOOLS2_OT_QuickArmature,
    edit_armature.COATOOLS2_OT_SetStretchBone,
    edit_armature.COATOOLS2_OT_RemoveIK,
    edit_armature.COATOOLS2_OT_SetIK,
    edit_armature.COATOOLS2_OT_CreateStretchIK,
    edit_armature.COATOOLS2_OT_RemoveStretchIK,
    edit_shapekey.COATOOLS2_OT_LeaveSculptmode,
    edit_shapekey.COATOOLS2_OT_ShapekeyAdd,
    edit_shapekey.COATOOLS2_OT_ShapekeyRemove,
    edit_shapekey.COATOOLS2_OT_ShapekeyRename,
    edit_shapekey.COATOOLS2_OT_EditShapekeyMode,
    edit_weights.COATOOLS2_OT_EditWeights,
    slot_handling.COATOOLS2_OT_ExtractSlots,
    slot_handling.COATOOLS2_OT_CreateSlotObject,
    slot_handling.COATOOLS2_OT_MoveSlotItem,
    slot_handling.COATOOLS2_OT_RemoveFromSlot,
    animation_handling.COATOOLS2_OT_AddKeyframe,
    animation_handling.COATOOLS2_OT_DuplicateAnimationCollection,
    animation_handling.COATOOLS2_OT_AddAnimationCollection,
    animation_handling.COATOOLS2_OT_RemoveAnimationCollection,
    animation_handling.COATOOLS2_OT_CreateNlaTrack,
    animation_handling.COATOOLS2_OT_BatchRender,
    animation_handling.COATOOLS2_OT_AddEvent,
    animation_handling.COATOOLS2_OT_RemoveEvent,
    animation_handling.COATOOLS2_OT_AddTimelineEvent,
    animation_handling.COATOOLS2_OT_RemoveTimelineEvent,
    create_ortho_cam.COATOOLS2_OT_CreateOrtpographicCamera,
    create_ortho_cam.COATOOLS2_OT_AlignCamera,
    create_spritesheet_preview.COATOOLS2_OT_SelectFrameThumb,
    help_display.COATOOLS2_OT_ShowHelp,
    draw_bone_shape.COATOOLS2_OT_DrawBoneShape,
    pie_menu.COATOOLS2_MT_menu,
    pie_menu.COATOOLS2_MT_keyframe_menu_01,
    pie_menu.COATOOLS2_MT_keyframe_menu_add,
    pie_menu.COATOOLS2_MT_keyframe_menu_remove,
    toggle_animation_area.COATOOLS2_OT_ToggleAnimationArea,
    version_converter.COATOOLS2_OT_VersionConverter,
    convert_from_old.COATOOLS2_OT_ConvertOldVersionCoatools,
    change_alpha_mode.COATOOLS2_OT_ChangeAlphaMode,
    change_alpha_mode.COATOOLS2_OT_ChangeTextureInterpolationMode,
    # exporter
    export_dragonbones.COATOOLS2_OT_DragonBonesExport,
    export_dragonbones.COATOOLS2_PT_ExportPanel,
    export_creature.COATOOLS2_OT_CreatureExport,
)

addon_keymaps = []


def register_keymaps():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km = kc.keymaps.new(name="3D View", space_type="VIEW_3D")
        kmi = km.keymap_items.new("view3d.move", "MIDDLEMOUSE", "PRESS")
        kmi.active = False

    addon = bpy.context.window_manager.keyconfigs.addon
    km = addon.keymaps.new(name="3D View", space_type="VIEW_3D")
    # insert keymap items here
    kmi = km.keymap_items.new("wm.call_menu_pie", type="F", value="PRESS")
    kmi.properties.name = "COATOOLS2_MT_menu"
    addon_keymaps.append(km)


def unregister_keymaps():
    wm = bpy.context.window_manager
    for km in addon_keymaps:
        for kmi in km.keymap_items:
            km.keymap_items.remove(kmi)
        wm.keyconfigs.addon.keymaps.remove(km)
    addon_keymaps.clear()


def register():
    addon_updater_ops.register(bl_info)

    # register classes
    for cls in classes:
        bpy.utils.register_class(cls)

    # register tools
    # deleted in upstream/master, need to be validated whether it is still needed
    bpy.utils.register_tool(
        edit_mesh.COATOOLS2_TO_DrawPolygon,
        after={"builtin.cursor"},
        separator=True,
        group=True,
    )

    # register props and keymap
    props.register()
    register_keymaps()

    # create handler
    bpy.app.handlers.depsgraph_update_pre.append(outliner.create_outliner_items)
    bpy.app.handlers.frame_change_post.append(update_properties)
    bpy.app.handlers.depsgraph_update_post.append(update_properties)
    bpy.app.handlers.load_post.append(check_view_2D_3D)
    bpy.app.handlers.load_post.append(check_for_deprecated_data)
    bpy.app.handlers.load_post.append(check_for_old_coatools)
    bpy.app.handlers.load_post.append(set_shading)


def unregister():
    addon_updater_ops.unregister()

    # unregister classes
    for cls in classes:
        bpy.utils.unregister_class(cls)

    # unregister tools
    bpy.utils.unregister_tool(edit_mesh.COATOOLS2_TO_DrawPolygon)

    # unregisters props and keymap
    props.unregister()
    unregister_keymaps()

    # delete handler
    bpy.app.handlers.depsgraph_update_pre.remove(outliner.create_outliner_items)
    bpy.app.handlers.frame_change_post.remove(update_properties)
    bpy.app.handlers.depsgraph_update_post.remove(update_properties)
    bpy.app.handlers.load_post.remove(check_view_2D_3D)
    bpy.app.handlers.load_post.remove(check_for_deprecated_data)
    bpy.app.handlers.load_post.remove(check_for_old_coatools)


@persistent
def check_for_deprecated_data(dummy):
    for obj in bpy.data.objects:
        if "sprite_object" in obj:
            bpy.context.scene.coa_tools2.deprecated_data_found = True


@persistent
def check_for_old_coatools(dummy):
    for obj in bpy.data.objects:
        if "coa_tools" in obj:
            bpy.context.scene.coa_tools2.old_coatools_found = True


@persistent
def check_view_2D_3D(dummy):
    context = bpy.context
    if context != None:
        scene = context.scene
        if scene != None:
            if scene.coa_tools2.view == "2D":
                set_middle_mouse_move(True)
            elif scene.coa_tools2.view == "3D":
                set_middle_mouse_move(False)


@persistent
def set_shading(dummy):
    bpy.context.scene.eevee.use_taa_reprojection = False
    for obj in bpy.data.objects:
        if "sprite_object" in obj.coa_tools2:
            for screen in bpy.data.screens:
                for area in screen.areas:
                    if area.type == "VIEW_3D":
                        area.spaces[0].shading.type = "RENDERED"
            break
    bpy.ops.coa_tools2.updater_check_now()


@persistent
def update_properties(scene, depsgraph):
    context = bpy.context
    for obj in bpy.data.objects:
        obj_eval = obj.evaluated_get(depsgraph)

        if obj_eval.coa_tools2.slot_index != obj_eval.coa_tools2.slot_index_last:
            change_slot_mesh_data(bpy.context, obj, obj_eval)
            obj.coa_tools2.slot_index_last = obj_eval.coa_tools2.slot_index

        if obj_eval.coa_tools2.alpha != obj_eval.coa_tools2.alpha_last:
            set_alpha(obj, context, obj_eval.coa_tools2.alpha)
            obj.coa_tools2.alpha_last = obj_eval.coa_tools2.alpha

        if (
            obj_eval.coa_tools2.modulate_color
            != obj_eval.coa_tools2.modulate_color_last
        ):
            set_modulate_color(obj, context, obj_eval.coa_tools2.modulate_color)
            obj.coa_tools2.modulate_color_last = obj_eval.coa_tools2.modulate_color

        if obj_eval.coa_tools2.z_value != obj_eval.coa_tools2.z_value_last:
            set_z_value(context, obj, obj_eval.coa_tools2.z_value)
            obj.coa_tools2.z_value_last = obj_eval.coa_tools2.z_value

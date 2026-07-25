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
    "version": (2, 2, 1),
    "blender": (4, 2, 0),
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
from . import dependency_manager

dependency_manager.ensure_vendor_path()

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
from .operators import install_dependencies

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
from .operators import export_json

from .operators.exporter import export_dragonbones
from .operators.exporter import export_creature
from .rig_control.blender import operators as rig_control_operators
from .rig_control.blender import properties as rig_control_properties
from .rig_control.blender import ui as rig_control_ui

# register
##################################

import traceback

_slot_index_cache = {}
_updating_properties = False


def _slot_index_cache_key(obj):
    try:
        return obj.as_pointer()
    except ReferenceError:
        return None


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
    redirect_direct_edit_mode: bpy.props.BoolProperty(
        name="Redirect Direct Edit Mode",
        description="Automatically switch COA sprite meshes from Blender Edit Mode to COA Tools2 Edit Mesh",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "sprite_import_export_scale")
        layout.prop(self, "redirect_direct_edit_mode")

        deps_state, deps_errors = dependency_manager.dependency_state_with_errors()
        deps_ok = all(deps_state.values())

        box = layout.box()
        box.label(text="Automesh Dependencies (Optional)")
        row = box.row(align=True)
        row.label(
            text="numpy: "
            + ("Installed" if deps_state["numpy"] else "Missing / Incompatible"),
            icon="CHECKMARK" if deps_state["numpy"] else "ERROR",
        )
        row = box.row(align=True)
        row.label(
            text="opencv (cv2): "
            + ("Installed" if deps_state["cv2"] else "Missing / Incompatible"),
            icon="CHECKMARK" if deps_state["cv2"] else "ERROR",
        )
        row = box.row(align=True)
        row.operator_context = "INVOKE_DEFAULT"
        row.operator(
            "coa_tools2.install_python_dependencies",
            icon="IMPORT",
            text="Install numpy / opencv",
        )
        install_state = install_dependencies.get_install_state()
        if install_state is not None and (
            install_state["running"] or install_state["done"]
        ):
            status_icon = "CHECKMARK" if install_state["success"] else "INFO"
            if install_state["done"] and not install_state["success"]:
                status_icon = "ERROR"
            box.label(
                text=f"Install progress: {int(install_state['progress'])}%",
                icon=status_icon,
            )
            box.label(text=install_state["status_message"])
        if not deps_ok:
            box.label(
                text="After install, restart Blender or re-enable addon.", icon="INFO"
            )
            if deps_errors:
                box.label(
                    text="If manually copied, ensure numpy/cv2 match Blender Python ABI.",
                    icon="INFO",
                )
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
    rig_control_properties.COATOOLS2_PG_RigBinding,
    rig_control_properties.COATOOLS2_PG_RigValidationIssue,
    rig_control_properties.COATOOLS2_PG_RigStatePoint,
    rig_control_properties.COATOOLS2_PG_RigStateCell,
    rig_control_properties.COATOOLS2_PG_RigComponentBoneRef,
    rig_control_properties.COATOOLS2_PG_RigComponentArtifact,
    rig_control_properties.COATOOLS2_PG_RigComponent,
    rig_control_properties.COATOOLS2_PG_RigControl,
    rig_control_properties.COATOOLS2_PG_RigObjectProperties,
    props.ObjectProperties,
    props.SceneProperties,
    props.MeshProperties,
    props.BoneProperties,
    props.WindowManagerProperties,
    # operator
    create_sprite_object.COATOOLS2_OT_CreateSpriteObject,
    create_sprite_object.COATOOLS2_OT_DefineSpriteObject,
    install_dependencies.COATOOLS2_OT_InstallPythonDependencies,
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
    # rig controls
    rig_control_operators.COATOOLS2_OT_AddRigControl,
    rig_control_operators.COATOOLS2_OT_AddRigBinding,
    rig_control_operators.COATOOLS2_OT_RemoveRigBinding,
    rig_control_operators.COATOOLS2_OT_SetupRigStates,
    rig_control_operators.COATOOLS2_OT_SetRigStateMixPolicy,
    rig_control_operators.COATOOLS2_OT_ToggleRigStateCell,
    rig_control_operators.COATOOLS2_OT_AssignRigStatePoint,
    rig_control_operators.COATOOLS2_OT_ClearRigStatePoint,
    rig_control_operators.COATOOLS2_OT_SnapRigStatePoint,
    rig_control_operators.COATOOLS2_OT_UpdateRigControl,
    rig_control_operators.COATOOLS2_OT_ValidateRig,
    rig_control_operators.COATOOLS2_OT_RepairRig,
    rig_control_ui.COATOOLS2_UL_RigControls,
    rig_control_ui.COATOOLS2_UL_RigBindings,
    rig_control_ui.COATOOLS2_UL_RigStatePoints,
    rig_control_ui.COATOOLS2_UL_RigStateCells,
    rig_control_ui.COATOOLS2_PT_RigControls,
    # exporter
    export_dragonbones.COATOOLS2_OT_DragonBonesExport,
    export_dragonbones.COATOOLS2_PT_ExportPanel,
    export_creature.COATOOLS2_OT_CreatureExport,
    export_json.COATOOLS2_OT_ExportToJson,
)

addon_keymaps = []

_DIRECT_EDIT_REDIRECT_TARGET = "coa_tools2_direct_edit_redirect_target"
_DIRECT_EDIT_REDIRECT_SUPPRESS = "coa_tools2_direct_edit_redirect_suppress"


def _get_parent_sprite_object(obj):
    while obj is not None:
        try:
            if "sprite_object" in obj.coa_tools2:
                return obj
        except ReferenceError:
            return None
        obj = obj.parent
    return None


def _is_direct_edit_redirect_candidate(context, obj):
    wm = context.window_manager if context is not None else None
    if not getattr(get_addon_prefs(context), "redirect_direct_edit_mode", False):
        return False

    if (
        wm is None
        or bool(wm.get("coa_tools2_edit_mesh_modal_running", False))
        or bool(wm.get(_DIRECT_EDIT_REDIRECT_SUPPRESS, False))
        or wm.get(_DIRECT_EDIT_REDIRECT_TARGET, "") != ""
    ):
        return False

    if (
        obj is None
        or obj.type != "MESH"
        or obj.mode != "EDIT"
        or obj.name == "COA TEXTURE PREVIEW"
        or "coa_base_sprite" not in obj.vertex_groups
    ):
        return False

    sprite_object = _get_parent_sprite_object(obj)
    if sprite_object is None:
        return False

    try:
        return not (
            sprite_object.coa_tools2.edit_mesh
            or sprite_object.coa_tools2.edit_armature
            or sprite_object.coa_tools2.edit_weights
            or sprite_object.coa_tools2.edit_shapekey
        )
    except ReferenceError:
        return False


def _get_view3d_override(context):
    screen = context.screen if context is not None else None
    if screen is None:
        return None

    for area in screen.areas:
        if area.type != "VIEW_3D":
            continue
        region = next(
            (region for region in area.regions if region.type == "WINDOW"), None
        )
        space = next((space for space in area.spaces if space.type == "VIEW_3D"), None)
        if region is None or space is None:
            continue

        override = {
            "area": area,
            "region": region,
            "space_data": space,
        }
        if context.window is not None:
            override["window"] = context.window
        return override

    return None


def _enter_coa_edit_mesh_from_direct_edit():
    context = bpy.context
    wm = context.window_manager if context is not None else None
    if wm is None:
        return None

    target_name = wm.get(_DIRECT_EDIT_REDIRECT_TARGET, "")
    if _DIRECT_EDIT_REDIRECT_TARGET in wm:
        del wm[_DIRECT_EDIT_REDIRECT_TARGET]

    if target_name not in bpy.data.objects:
        return None

    obj = bpy.data.objects[target_name]
    if context.active_object != obj or not _is_direct_edit_redirect_candidate(
        context, obj
    ):
        return None

    wm[_DIRECT_EDIT_REDIRECT_SUPPRESS] = True
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
        for selected in list(context.selected_objects):
            selected.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        override = _get_view3d_override(context)
        if override is not None:
            with context.temp_override(**override):
                bpy.ops.coa_tools2.edit_mesh(mode="EDIT_MESH")
        else:
            bpy.ops.coa_tools2.edit_mesh(mode="EDIT_MESH")
    except Exception:
        traceback.print_exc()
    finally:
        if _DIRECT_EDIT_REDIRECT_SUPPRESS in wm:
            del wm[_DIRECT_EDIT_REDIRECT_SUPPRESS]

    return None


@persistent
def redirect_direct_sprite_mesh_edit_mode(scene, depsgraph):
    context = bpy.context
    obj = context.active_object if context is not None else None
    if not _is_direct_edit_redirect_candidate(context, obj):
        return

    context.window_manager[_DIRECT_EDIT_REDIRECT_TARGET] = obj.name
    bpy.app.timers.register(_enter_coa_edit_mesh_from_direct_edit, first_interval=0.0)


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
    # 一部環境で bl_info が見えず NameError になることがあるため安全に取得
    info = globals().get("bl_info")
    if info is None:
        info = {
            "name": "COA Tools2",
            "version": (2, 2, 1),
            "blender": (4, 2, 0),
        }
    addon_updater_ops.register(info)

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
    rig_control_properties.start_selection_sync()
    register_keymaps()

    # create handler
    bpy.app.handlers.depsgraph_update_pre.append(outliner.create_outliner_items)
    bpy.app.handlers.frame_change_post.append(update_properties)
    bpy.app.handlers.depsgraph_update_post.append(update_properties)
    bpy.app.handlers.depsgraph_update_post.append(redirect_direct_sprite_mesh_edit_mode)
    bpy.app.handlers.load_post.append(check_view_2D_3D)
    bpy.app.handlers.load_post.append(check_for_deprecated_data)
    bpy.app.handlers.load_post.append(check_for_old_coatools)
    bpy.app.handlers.load_post.append(set_shading)


def unregister():
    rig_control_properties.cancel_auto_rebuild()
    rig_control_properties.cancel_selection_sync()
    # Remove callbacks before unregistering the classes and properties they use.
    handlers = (
        (bpy.app.handlers.depsgraph_update_pre, outliner.create_outliner_items),
        (bpy.app.handlers.frame_change_post, update_properties),
        (bpy.app.handlers.depsgraph_update_post, update_properties),
        (
            bpy.app.handlers.depsgraph_update_post,
            redirect_direct_sprite_mesh_edit_mode,
        ),
        (bpy.app.handlers.load_post, check_view_2D_3D),
        (bpy.app.handlers.load_post, check_for_deprecated_data),
        (bpy.app.handlers.load_post, check_for_old_coatools),
        (bpy.app.handlers.load_post, set_shading),
    )
    for handler_list, callback in handlers:
        while callback in handler_list:
            handler_list.remove(callback)

    unregister_keymaps()

    try:
        bpy.utils.unregister_tool(edit_mesh.COATOOLS2_TO_DrawPolygon)
    except RuntimeError:
        pass

    # RNA pointer properties must be removed before their PropertyGroup classes.
    props.unregister()

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            # Supports cleanup after a partially registered older add-on version.
            pass

    addon_updater_ops.unregister()


@persistent
def check_for_deprecated_data(dummy):
    for obj in bpy.data.objects:
        if "sprite_object" in obj:
            bpy.context.scene.coa_tools2.deprecated_data_found = True


def has_old_coatools_customdata(data):
    try:
        return "coa_tools" in data or data.get("coa_tools") is not None
    except (AttributeError, TypeError):
        return False


def data_path_has_old_coatools(data_path):
    return bool(data_path) and (
        "coa_tools." in data_path or '["coa_tools"]' in data_path
    )


def has_old_coatools_animation_data(data):
    animation_data = getattr(data, "animation_data", None)
    if animation_data is None:
        return False

    for driver in animation_data.drivers:
        if data_path_has_old_coatools(driver.data_path):
            return True
        for variable in driver.driver.variables:
            for target in variable.targets:
                if data_path_has_old_coatools(target.data_path):
                    return True
    return False


@persistent
def check_for_old_coatools(dummy):
    data_blocks = []
    data_blocks.extend(bpy.data.objects)
    data_blocks.extend(bpy.data.meshes)
    data_blocks.extend(bpy.data.armatures)
    data_blocks.extend(bpy.data.scenes)

    for armature_data in bpy.data.armatures:
        data_blocks.extend(armature_data.bones)

    for data in data_blocks:
        if has_old_coatools_customdata(data) or has_old_coatools_animation_data(data):
            bpy.context.scene.coa_tools2.old_coatools_found = True
            return

    for action in bpy.data.actions:
        for fcurve in action.fcurves:
            if data_path_has_old_coatools(fcurve.data_path):
                bpy.context.scene.coa_tools2.old_coatools_found = True
                return


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
    global _updating_properties
    if _updating_properties:
        return

    _updating_properties = True
    context = bpy.context
    try:
        for obj in bpy.data.objects:
            obj_eval = obj.evaluated_get(depsgraph)

            if obj.type == "MESH" and obj.coa_tools2.type == "SLOT":
                slot_index = get_clamped_slot_index(obj, obj_eval)
                if slot_index is not None:
                    slot = obj.coa_tools2.slot[slot_index]
                    cache_key = _slot_index_cache_key(obj)
                    cache_index = _slot_index_cache.get(cache_key)
                    if (
                        slot.mesh is not None
                        and (cache_index != slot_index or obj.data != slot.mesh)
                    ):
                        change_slot_mesh_data(
                            context,
                            obj,
                            obj_eval,
                            clamp_property=False,
                            sync_active=False,
                            alpha=obj_eval.coa_tools2.alpha,
                            modulate_color=obj_eval.coa_tools2.modulate_color,
                        )
                    _slot_index_cache[cache_key] = slot_index

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
    finally:
        _updating_properties = False

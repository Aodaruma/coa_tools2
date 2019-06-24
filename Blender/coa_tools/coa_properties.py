import bpy
from bpy.props import BoolProperty, FloatVectorProperty, IntProperty, FloatProperty, StringProperty, EnumProperty, PointerProperty, CollectionProperty
# from . functions import *
from . import functions

def hide_bone(self, context):
    self.hide = self.coa_hide


def hide_select_bone(self, context):
    self.hide_select = self.coa_hide_select


def hide(self, context):
    if self.id_data.hide_viewport != self.hide:
        self.id_data.hide_viewport = self.hide


def hide_select(self, context):
    if self.hide_select:
        self.id_data.select_set(False)
        if context.scene.view_layers[0].objects.active == self:
            context.scene.view_layers[0].objects.active = self.parent
    self.id_data.hide_select = self.hide_select


def update_uv(self, context):
    self.sprite_frame_last = -1
    if self.sprite_frame >= (self.tiles_x * self.tiles_y):
        self.sprite_frame = (self.tiles_x * self.tiles_y) - 1
    update_uv(context, context.active_object)


def set_z_value(self, context):
    if context.scene.view_layers[0].objects.active == self.id_data:
        for obj in bpy.context.selected_objects:
            if obj.type == "MESH":
                if obj != self.id_data:
                    obj.coa_tools.z_value = self.z_value
                functions.set_z_value(context, obj, self.z_value)


def set_alpha(self, context):
    if context.scene.view_layers[0].objects.active == self.id_data:
        for obj in bpy.context.selected_objects:
            if obj.type == "MESH":
                if obj != self.id_data:
                    obj.coa_tools.alpha = self.alpha
                functions.set_alpha(obj, context, self.alpha)


def set_modulate_color(self, context):
    if context.scene.view_layers[0].objects.active == self.id_data:
        for obj in bpy.context.selected_objects:
            if obj.type == "MESH":
                if obj != self.id_data:
                    obj.coa_tools.modulate_color = self.modulate_color
                functions.set_modulate_color(obj, context, self.modulate_color)


def set_sprite_frame(self, context):
    if self.type == "MESH":
        self.coa_sprite_frame_last = -1
        self.coa_sprite_frame = int(self.coa_sprite_frame_previews)
        if context.scene.tool_settings.use_keyframe_insert_auto:
            bpy.ops.coa_tools.add_keyframe(prop_name="coa_sprite_frame", interpolation="CONSTANT")
    elif self.type == "SLOT":
        self.coa_slot_index = int(self.coa_sprite_frame_previews)


def exit_edit_weights(self, context):
    if not self.coa_edit_weights:
        obj = context.active_object
        if obj != None and obj.mode == "WEIGHT_PAINT":
            bpy.ops.object.mode_set(mode="OBJECT")


def hide_base_sprite(self, context):
    # hide_base_sprite(self)
    functions.hide_base_sprite(context.active_object)


def change_slot_mesh(self, context):
    self.coa_slot_index_last = -1
    self.coa_slot_index_last = self.coa_slot_index
    functions.change_slot_mesh_data(context, self)
    self.data.coa_hide_base_sprite = self.data.coa_hide_base_sprite


def change_edit_mode(self, context):
    if self.edit_mesh == False:
        bpy.ops.object.mode_set(mode="OBJECT")
        functions.set_local_view(False)


def update_filter(self, context):
    pass


def change_direction(self, context):
    functions.set_direction(self)
    self.coa_flip_direction_last = self.coa_flip_direction


def get_shapekeys(self, context):
    SHAPEKEYS = []
    obj = context.active_object
    if obj.data.shape_keys != None:
        for i, shape in enumerate(obj.data.shape_keys.key_blocks):
            SHAPEKEYS.append((str(i), shape.name, shape.name, "SHAPEKEY_DATA", i))
    return SHAPEKEYS


def select_shapekey(self, context):
    if self.data.shape_keys != None:
        self.active_shape_key_index = int(self.coa_selected_shapekey)

def enum_sprite_previews(self, context):
    """EnumProperty callback"""
    enum_items = []
    if context is None:
        return enum_items

    if self.coa_type == "SLOT":
        for i, slot in enumerate(self.coa_slot):
            if slot.mesh != None:
                img = slot.mesh.materials[0].texture_slots[0].texture.image
                icon = bpy.types.UILayout.icon(img)
                enum_items.append((str(i), slot.mesh.name, "", icon, i))

    return enum_items

def snapping(self,context):
    if self.surface_snap:
        bpy.context.scene.tool_settings.use_snap = True
        bpy.context.scene.tool_settings.snap_elements = {'FACE'}
    else:
        bpy.context.scene.tool_settings.use_snap = False

def update_stroke_distance(self,context):
    mult = bpy.context.space_data.region_3d.view_distance*.05
    if self.distance_constraint:
        context.scene.coa_distance /= mult
    else:
        context.scene.coa_distance *= mult

def lock_view(self,context):
    screens = []
    screens.append(context.screen)
    # screen = context.screen

    for scr in bpy.data.screens:
        if scr not in screens:
            screens.append(scr)

    for screen in screens:
        if screen != self.id_data:
            screen.coa_tools["view"] = self["view"]
        if "-nonnormal" in screen.name:
            bpy.data.screens[screen.name.split("-nonnormal")[0]].coa_tools.view = self.view
        if self.view == "3D":
            functions.set_view(screen, "3D")
        elif self.view == "2D":
            functions.set_view(screen, "2D")
    if self.view == "3D":
        functions.set_middle_mouse_move(False)
    elif self.view == "2D":
        functions.set_middle_mouse_move(True)



class UVData(bpy.types.PropertyGroup):
    uv: FloatVectorProperty(default=(0,0),size=2)

class SlotData(bpy.types.PropertyGroup):
    def change_slot_mesh(self,context):
        obj = self.id_data
        self["active"] = True
        if self.active:
            obj.coa_slot_index = self.index
            hide_base_sprite(obj)
            for slot in obj.coa_slot:
                if slot != self:
                    slot["active"] = False

    mesh: bpy.props.PointerProperty(type=bpy.types.Mesh)
    offset: FloatVectorProperty()
    name: StringProperty()
    active: BoolProperty(update=change_slot_mesh)
    index: IntProperty()

class Event(bpy.types.PropertyGroup):
    name: StringProperty()
    type: EnumProperty(name="Object Type",default="SOUND",items=(("SOUND","Sound","Sound","SOUND",0),("EVENT","Event","Event","PHYSICS",1)))
    value: StringProperty(description="Define which sound or event key is triggered.")

class TimelineEvent(bpy.types.PropertyGroup):
    def change_event_order(self, context):
        timeline_events = self.id_data.coa_anim_collections[self.id_data.coa_anim_collections_index].timeline_events
        for i, event in enumerate(timeline_events):
            event_next = None
            if i < len(timeline_events)-1:
                event_next = timeline_events[i+1]
            if event_next != None and event_next.frame < event.frame:
                timeline_events.move(i+1, i)

    event: CollectionProperty(type=Event)
    frame: IntProperty(default=0, min=0, update=change_event_order)
    collapsed: BoolProperty(default=False)

class AnimationCollections(bpy.types.PropertyGroup):
    def set_frame_start(self,context):
        bpy.context.scene.frame_start = self.frame_start
    def set_frame_end(self,context):
        bpy.context.scene.frame_end = self.frame_end

    def check_name(self, context):
        sprite_object = functions.get_sprite_object(context.active_object)

        if self.name_old != "" and self.name_change_to != self.name:
            name_array = []
            for item in sprite_object.coa_anim_collections:
                name_array.append(item.name_old)
            self.name_change_to = functions.check_name(name_array,self.name)
            self.name = self.name_change_to

        children = functions.get_children(context, sprite_object, ob_list=[])
        objs = []
        if sprite_object.type == "ARMATURE":
            objs.append(sprite_object)
        for child in children:
            objs.append(child)

        for child in objs:
            action_name = self.name_old + "_" + child.name
            action_name_new = self.name + "_" + child.name

            # if action_name_new in bpy.data.actions:
            #     bpy.data.actions.remove(bpy.data.actions[action_name])
            if action_name_new in bpy.data.actions:
                print(child.name,"",action_name_new , " -- ",action_name_new in bpy.data.actions)
            if action_name_new not in bpy.data.actions and action_name in bpy.data.actions:
                action = bpy.data.actions[action_name]
                action.name = action_name_new
        self.name_old = self.name
        self.id_data.coa_anim_collections_index = self.id_data.coa_anim_collections_index

    name: StringProperty(update=check_name)
    name_change_to: StringProperty()
    name_old: StringProperty()
    action_collection: BoolProperty(default=False)
    frame_start: IntProperty(default=0, update=set_frame_start)
    frame_end: IntProperty(default=250, min=1, update=set_frame_end)
    timeline_events: CollectionProperty(type=TimelineEvent)
    event_index: IntProperty(default=-1, max=-1)

class ObjectProperties(bpy.types.PropertyGroup):
    anim_collections: bpy.props.CollectionProperty(type=AnimationCollections)
    uv_default_state: bpy.props.CollectionProperty(type=UVData)
    slot: bpy.props.CollectionProperty(type=SlotData)

    dimensions_old: FloatVectorProperty()
    sprite_dimension: FloatVectorProperty()
    sprite_frame: IntProperty(description="Frame", default=0, min=0, update=update_uv)
    sprite_frame_last: IntProperty(description="Frame")
    z_value: IntProperty(description="Z Depth", default=0, update=set_z_value)
    z_value_last: IntProperty(default=0)
    alpha: FloatProperty(default=1.0, min=0.0, max=1.0, update=set_alpha)
    alpha_last: FloatProperty(default=1.0, min=0.0, max=1.0)
    show_bones: BoolProperty()
    filter_names: StringProperty(update=update_filter, options={'TEXTEDIT_UPDATE'})
    favorite: BoolProperty()
    hide_base_sprite: BoolProperty(default=False, update=hide_base_sprite)
    animation_loop: BoolProperty(default=False, description="Sets the Timeline frame to 0 when it reaches the end of the animation. Also works for changing frame with cursor keys.")
    hide: BoolProperty(default=False, update=hide)
    hide_select: BoolProperty(default=False, update=hide_select)
    data_path: StringProperty()
    show_children: BoolProperty(default=True)
    show_export_box: BoolProperty()
    sprite_frame_previews: EnumProperty(items=enum_sprite_previews, update=set_sprite_frame)
    sprite_updated: BoolProperty(default=False)
    modulate_color: FloatVectorProperty(name="Modulate Color",
                                                             description="Modulate color for sprites. This will tint your sprite with given color.",
                                                             default=(1.0, 1.0, 1.0), min=0.0, max=1.0, soft_min=0.0,
                                                             soft_max=1.0, size=3, subtype="COLOR",
                                                             update=set_modulate_color)
    modulate_color_last: FloatVectorProperty(default=(1.0, 1.0, 1.0), min=0.0, max=1.0,
                                                                  soft_min=0.0, soft_max=1.0, size=3, subtype="COLOR")
    type: EnumProperty(name="Object Type", default="MESH", items=(
        ("SPRITE", "Sprite", "Sprite"), ("MESH", "Mesh", "Mesh"), ("SLOT", "Slot", "Slot")))
    slot_index: bpy.props.IntProperty(default=0, update=change_slot_mesh, min=0)
    slot_index_last: bpy.props.IntProperty()
    slot_reset_index: bpy.props.IntProperty(default=0, min=0)
    slot_show: bpy.props.BoolProperty(default=False)
    flip_direction: bpy.props.BoolProperty(default=False, update=change_direction)
    flip_direction_last: bpy.props.BoolProperty(default=False)
    change_z_ordering: bpy.props.BoolProperty(default=False)
    selected_shapekey: bpy.props.EnumProperty(items=get_shapekeys, update=select_shapekey,
                                                                   name="Active Shapkey")

    edit_mode: EnumProperty(name="Edit Mode", items=(
        ("OBJECT", "Object", "Object"), ("MESH", "Mesh", "Mesh"), ("ARMATURE", "Armature", "Armature"),
        ("WEIGHTS", "Weights", "Weights"), ("SHAPEKEY", "Shapkey", "Shapekey")))
    edit_weights: BoolProperty(default=False, update=exit_edit_weights)
    edit_armature: BoolProperty(default=False)
    edit_shapekey: BoolProperty(default=False)
    edit_mesh: BoolProperty(default=False, update=change_edit_mode)

class SceneProperties(bpy.types.PropertyGroup):
    display_all: BoolProperty(default=True)
    display_page: IntProperty(default=0, min=0, name="Display Page",
                                                  description="Defines which page is displayed")
    display_length: IntProperty(default=10, min=0, name="Page Length",
                                                    description="Defines how Many Items are displayed")
    distance: FloatProperty(description="Set the asset distance for each Paint Stroke",default = 1.0,min=-.0, max=30.0)
    detail: FloatProperty(description="Detail",default = .3,min=0,max=1.0)
    snap_distance: FloatProperty(description="Snap Distance",default = 0.01,min=0)
    surface_snap: BoolProperty(default=True,description="Snap Vertices on Surface",update=snapping)
    automerge: BoolProperty(default=False)
    distance_constraint: BoolProperty(default=False,description="Constraint Distance to Viewport", update=update_stroke_distance)
    lock_to_bounds: BoolProperty(default=True,description="Lock Cursor to Object Bounds")
    frame_last: IntProperty(description="Stores last frame Number",default=0)

class ScreenProperties(bpy.types.PropertyGroup):
    view: EnumProperty(default="3D",
                       items=(("3D", "3D View", "3D", "MESH_CUBE", 0), ("2D", "2D View", "2D", "MESH_PLANE", 1)),
                       update=lock_view)

class MeshProperties(bpy.types.PropertyGroup):
    hide_base_sprite: BoolProperty(default=False, update=hide_base_sprite,
                                                      description="Make sure to hide base sprite when adding a custom mesh.")

class BoneProperties(bpy.types.PropertyGroup):
    favorite: BoolProperty()
    draw_bone: BoolProperty(default=False)
    z_value: IntProperty(description="Z Depth", default=0)
    data_path: StringProperty()
    hide_select: BoolProperty(default=False, update=hide_select_bone)
    hide: BoolProperty(default=False, update=hide_bone)

class WindowManagerProperties(bpy.types.PropertyGroup):
    show_help: BoolProperty(default=False, description="Hide Help")

def register():
    bpy.types.Object.coa_tools = PointerProperty(type=ObjectProperties)
    bpy.types.Scene.coa_tools = PointerProperty(type=SceneProperties)
    bpy.types.Screen.coa_tools = PointerProperty(type=ScreenProperties)
    bpy.types.Mesh.coa_tools = PointerProperty(type=MeshProperties)
    bpy.types.Bone.coa_tools = PointerProperty(type=BoneProperties)
    bpy.types.WindowManager.coa_tools = PointerProperty(type=WindowManagerProperties)
    bpy.types.SpaceView3D.coa_tools_test = PointerProperty(type=MeshProperties)
    print("COATools Properties have been registered")
def unregister():
    del bpy.types.Object.coa_tools
    del bpy.types.Scene.coa_tools
    del bpy.types.Mesh.coa_tools
    del bpy.types.Bone.coa_tools

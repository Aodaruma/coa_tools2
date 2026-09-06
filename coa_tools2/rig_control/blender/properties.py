"""Blender PropertyGroups used to persist rig-control definitions."""

from __future__ import annotations

import math
import time
import traceback

import bpy
from bpy.props import (
    BoolProperty,
    BoolVectorProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

from ..component_schema import (
    RIG_COMPONENT_SCHEMA_VERSION,
    RigComponentSpec,
    RigWidgetPresentationSpec,
)
from ..schema import SCHEMA_VERSION
from ..semantic_schema import SEMANTIC_RIG_SCHEMA_VERSION


AUTO_REBUILD_DELAY = 0.35
_PENDING_REBUILDS: dict[tuple[str, str], float] = {}
_AUTO_REBUILD_ACTIVE = False
_LAST_ACTIVE_RIG_BONE: tuple[int, str] | None = None


def _find_control(armature, control_uuid):
    rig_data = getattr(armature, "coa_tools2_rig", None)
    if rig_data is None:
        return None
    return next(
        (
            control
            for control in rig_data.rig_controls
            if control.control_uuid == control_uuid
        ),
        None,
    )


def _flush_auto_rebuilds():
    global _AUTO_REBUILD_ACTIVE

    now = time.monotonic()
    due = [
        key
        for key, changed_at in _PENDING_REBUILDS.items()
        if now - changed_at >= AUTO_REBUILD_DELAY
    ]
    if not due:
        return 0.1 if _PENDING_REBUILDS else None

    from .compiler import compile_control

    for key in due:
        _PENDING_REBUILDS.pop(key, None)
        armature_name, control_uuid = key
        armature = bpy.data.objects.get(armature_name)
        if armature is None or armature.type != "ARMATURE":
            continue
        control = _find_control(armature, control_uuid)
        if control is None or not control.needs_rebuild:
            continue
        try:
            _AUTO_REBUILD_ACTIVE = True
            compile_control(armature, control)
        except Exception as exc:
            traceback.print_exc()
            control.auto_rebuild_error = str(exc)
            control.needs_rebuild = True
        finally:
            _AUTO_REBUILD_ACTIVE = False
    return 0.1 if _PENDING_REBUILDS else None


def _schedule_auto_rebuild(control):
    armature = getattr(control, "id_data", None)
    if (
        armature is None
        or not isinstance(armature, bpy.types.Object)
        or armature.type != "ARMATURE"
        or not control.control_uuid
        or not control.live_preview
    ):
        return
    _PENDING_REBUILDS[(armature.name, control.control_uuid)] = time.monotonic()
    if not bpy.app.timers.is_registered(_flush_auto_rebuilds):
        bpy.app.timers.register(
            _flush_auto_rebuilds,
            first_interval=AUTO_REBUILD_DELAY,
        )


def _mark_control_dirty(self, _context):
    if _AUTO_REBUILD_ACTIVE:
        return
    self.needs_rebuild = True
    self.auto_rebuild_error = ""
    _schedule_auto_rebuild(self)


def _mark_state_point_dirty(self, context):
    """Route nested State Point edits to the owning control preview."""

    armature = getattr(self, "id_data", None)
    if armature is None or not getattr(self, "control_uuid", ""):
        return
    control = _find_control(armature, self.control_uuid)
    if control is not None:
        _mark_control_dirty(control, context)


def _mark_component_dirty(self, _context):
    """Structural component changes are intentionally applied manually."""

    self.needs_rebuild = True
    self.last_error = ""


def _schedule_widget_presentation_update(presentation):
    """Hand a dirty presentation to the optional debounced compiler bridge."""

    try:
        from .semantic_presentations import schedule_semantic_presentation_update
    except ImportError:
        return
    schedule_semantic_presentation_update(presentation)


def _cancel_widget_presentation_update(presentation):
    try:
        from .semantic_presentations import cancel_semantic_presentation_update
    except ImportError:
        return
    cancel_semantic_presentation_update(presentation)


def _mark_widget_presentation_dirty(self, _context):
    """Invalidate only replaceable visual data, never the solver structure."""

    self.needs_rebuild = True
    self.last_error = ""
    if self.live_preview:
        _schedule_widget_presentation_update(self)


def _update_widget_presentation_live_preview(self, _context):
    if not self.live_preview:
        _cancel_widget_presentation_update(self)
    elif self.needs_rebuild:
        _schedule_widget_presentation_update(self)


def _mark_pin_driven_explicit(self, _context):
    """A UI edit takes ownership back from dependency auto-wiring."""

    self.pin_driven_stage_uuid = ""


def _update_live_preview(self, _context):
    armature = getattr(self, "id_data", None)
    key = (
        (armature.name, self.control_uuid)
        if isinstance(armature, bpy.types.Object) and self.control_uuid
        else None
    )
    if not self.live_preview:
        if key is not None:
            _PENDING_REBUILDS.pop(key, None)
        return
    if self.needs_rebuild:
        _schedule_auto_rebuild(self)


def cancel_auto_rebuild():
    _PENDING_REBUILDS.clear()
    if bpy.app.timers.is_registered(_flush_auto_rebuilds):
        bpy.app.timers.unregister(_flush_auto_rebuilds)


def flush_auto_rebuilds_now():
    """Compile pending definitions immediately; primarily useful for tests."""

    for key in tuple(_PENDING_REBUILDS):
        _PENDING_REBUILDS[key] = 0.0
    return _flush_auto_rebuilds()


def _poll_active_rig_bone():
    global _LAST_ACTIVE_RIG_BONE

    armature = bpy.context.active_object
    if armature is None or armature.type != "ARMATURE":
        _LAST_ACTIVE_RIG_BONE = None
        return 0.15
    from .selection import active_data_bone

    active_bone = active_data_bone(armature)
    if active_bone is None:
        _LAST_ACTIVE_RIG_BONE = None
        return 0.15
    token = (armature.as_pointer(), active_bone.name)
    if token == _LAST_ACTIVE_RIG_BONE:
        return 0.15
    _LAST_ACTIVE_RIG_BONE = token

    from .component_ui import sync_component_index_from_active_bone
    from .ui import sync_control_index_from_active_bone

    sync_control_index_from_active_bone(
        armature,
        getattr(armature, "coa_tools2_rig", None),
    )
    sync_component_index_from_active_bone(
        armature,
        getattr(armature, "coa_tools2_rig", None),
    )
    return 0.15


def start_selection_sync():
    if not bpy.app.timers.is_registered(_poll_active_rig_bone):
        bpy.app.timers.register(_poll_active_rig_bone, first_interval=0.15)


def cancel_selection_sync():
    global _LAST_ACTIVE_RIG_BONE

    _LAST_ACTIVE_RIG_BONE = None
    if bpy.app.timers.is_registered(_poll_active_rig_bone):
        bpy.app.timers.unregister(_poll_active_rig_bone)


class COATOOLS2_PG_RigBinding(bpy.types.PropertyGroup):
    schema_version: IntProperty(default=SCHEMA_VERSION)
    binding_uuid: StringProperty()
    control_uuid: StringProperty()
    source_component: EnumProperty(
        items=(
            ("X", "X", "Control local X"),
            ("Y", "Y", "Control local Y"),
            ("ROTATION", "Rotation Z (Legacy)", "Control local Z rotation"),
            ("LOC_X", "Location X", "Control local X location"),
            ("LOC_Y", "Location Y", "Control local Y location"),
            ("LOC_Z", "Location Z", "Control local Z / visual depth"),
            ("ROT_X", "Rotation X", "Control local X rotation"),
            ("ROT_Y", "Rotation Y", "Control local Y rotation"),
            ("ROT_Z", "Rotation Z", "Control local Z rotation"),
        ),
        default="X",
    )
    target_kind: EnumProperty(
        items=(
            ("SHAPE_KEY_VALUE", "Shape Key", "Drive a shape key value"),
            (
                "CONSTRAINT_INFLUENCE",
                "Constraint Influence",
                "Drive a pose-bone constraint influence",
            ),
        ),
        default="SHAPE_KEY_VALUE",
    )
    target_object: PointerProperty(type=bpy.types.Object)
    target_bone: StringProperty()
    target_name: StringProperty()
    generated_data_path: StringProperty()
    input_min: FloatProperty(default=0.0)
    input_max: FloatProperty(default=1.0)
    output_min: FloatProperty(default=0.0)
    output_max: FloatProperty(default=1.0)
    clamp: BoolProperty(default=True)
    enabled: BoolProperty(default=True)


class COATOOLS2_PG_RigValidationIssue(bpy.types.PropertyGroup):
    severity: EnumProperty(
        items=(
            ("ERROR", "Error", "Rig error"),
            ("WARNING", "Warning", "Rig warning"),
        ),
        default="ERROR",
    )
    code: StringProperty()
    message: StringProperty()
    control_uuid: StringProperty()
    binding_uuid: StringProperty()


class COATOOLS2_PG_RigStatePoint(bpy.types.PropertyGroup):
    schema_version: IntProperty(default=SCHEMA_VERSION)
    state_uuid: StringProperty()
    control_uuid: StringProperty()
    label: StringProperty(update=_mark_state_point_dirty)
    column: IntProperty(default=0, min=0)
    row: IntProperty(default=0, min=0)
    target_object: PointerProperty(type=bpy.types.Object)
    target_name: StringProperty()
    target_name_candidates: StringProperty(
        name="Shape Key Name Candidates",
        description="Comma-separated names suggested by a preset; no Shape Key is created",
    )
    phoneme_aliases: StringProperty(
        name="Phoneme Aliases",
        description="Comma-separated external phoneme tokens mapped to this named state",
    )
    generated_data_path: StringProperty()
    graph_position: FloatVectorProperty(
        name="Position",
        description="Normalized position inside the Graph State control",
        size=2,
        min=0.0,
        max=1.0,
        default=(0.0, 0.0),
        update=_mark_state_point_dirty,
    )
    point_shape: EnumProperty(
        name="Point Shape",
        items=(
            ("CIRCLE", "Circle", "Use the standard circular State Rig node"),
            ("DIAMOND", "Diamond", "Mark this named state with a diamond"),
            ("TRIANGLE", "Triangle", "Mark this named state with a triangle"),
            ("SQUARE", "Square", "Mark this named state with a square"),
            (
                "CUSTOM_OBJECT",
                "Custom Object",
                "Use an existing object as this point's presentation reference",
            ),
        ),
        default="CIRCLE",
        update=_mark_state_point_dirty,
    )
    custom_object: PointerProperty(
        name="Point Object",
        description="Optional custom presentation object for this named point",
        type=bpy.types.Object,
        update=_mark_state_point_dirty,
    )
    fallback_state_uuid: StringProperty(
        name="Fallback State",
        description="Stable UUID of the state joined by this point's fallback edge",
        update=_mark_state_point_dirty,
    )
    is_empty: BoolProperty(
        name="Empty State",
        description="Keep this point intentionally empty without a validation warning",
        default=False,
    )
    enabled: BoolProperty(default=True)


class COATOOLS2_PG_RigStateCell(bpy.types.PropertyGroup):
    schema_version: IntProperty(default=SCHEMA_VERSION)
    cell_uuid: StringProperty()
    control_uuid: StringProperty()
    column: IntProperty(default=0, min=0)
    row: IntProperty(default=0, min=0)
    mix_enabled: BoolProperty(
        name="Allow Mix",
        description="Allow free bilinear mixing inside this four-point cell",
        default=True,
    )


class COATOOLS2_PG_RigComponentBoneRef(bpy.types.PropertyGroup):
    bone_name: StringProperty()


class COATOOLS2_PG_RigWidgetPresentation(bpy.types.PropertyGroup):
    """Solver-independent custom-shape presentation shared by rig controls."""

    align_to_source_rest: BoolProperty(
        name="Align to Hand Rest",
        description="Align generated IK hand shapes to the source effector rest direction in the art plane",
        default=True,
        update=_mark_widget_presentation_dirty,
    )

    shape: EnumProperty(
        name="Shape",
        items=(
            ("NONE", "None", "Do not generate a custom shape"),
            ("ARROW_1D", "1D Double Arrow", "Flat double-ended arrow"),
            ("ARROW_2D", "2D Four-way Arrow", "Flat four-way arrow"),
            (
                "CYLINDER_ARROW_1D",
                "Cylindrical 1D Arrow",
                "Wrap the 1D double arrow around a cylinder",
            ),
            (
                "SPHERE_ARROW_2D",
                "Spherical 2D Arrow",
                "Wrap the 2D four-way arrow around a sphere",
            ),
            ("TOMBSTONE", "Tombstone", "Rounded hand or foot silhouette"),
            ("ELLIPSE", "Ellipse", "Ellipse outline"),
            ("TRIANGLE", "Triangle", "Rounded triangle outline"),
            ("RECTANGLE", "Rectangle", "Rounded rectangle outline"),
            ("DIAMOND", "Diamond", "Rounded diamond outline"),
            ("SECTOR", "Sector", "Circular sector or annular sector outline"),
            (
                "CUSTOM_OBJECT",
                "Custom Object",
                "Use an existing Blender object as the custom shape",
            ),
        ),
        default="NONE",
        update=_mark_widget_presentation_dirty,
    )
    custom_object: PointerProperty(
        name="Object",
        description="Existing object used directly as the bone custom shape",
        type=bpy.types.Object,
        update=_mark_widget_presentation_dirty,
    )
    width: FloatProperty(
        name="Width",
        default=2.0,
        min=0.001,
        update=_mark_widget_presentation_dirty,
    )
    height: FloatProperty(
        name="Height",
        default=1.0,
        min=0.001,
        update=_mark_widget_presentation_dirty,
    )
    corner_radius: FloatProperty(
        name="Corner Radius",
        default=0.15,
        min=0.0,
        update=_mark_widget_presentation_dirty,
    )
    bar_width: FloatProperty(
        name="Bar Width",
        default=0.18,
        min=0.001,
        update=_mark_widget_presentation_dirty,
    )
    head_length: FloatProperty(
        name="Head Length",
        default=0.35,
        min=0.001,
        update=_mark_widget_presentation_dirty,
    )
    head_width: FloatProperty(
        name="Head Width",
        default=0.6,
        min=0.001,
        update=_mark_widget_presentation_dirty,
    )
    radius: FloatProperty(
        name="Radius",
        default=1.0,
        min=0.001,
        update=_mark_widget_presentation_dirty,
    )
    arc_angle: FloatProperty(
        name="Arc Angle",
        subtype="ANGLE",
        default=math.pi,
        min=0.001,
        max=math.tau,
        update=_mark_widget_presentation_dirty,
    )
    sector_inner_radius: FloatProperty(
        name="Inner Radius",
        default=0.0,
        min=0.0,
        update=_mark_widget_presentation_dirty,
    )
    sector_outer_radius: FloatProperty(
        name="Outer Radius",
        default=1.0,
        min=0.001,
        update=_mark_widget_presentation_dirty,
    )
    sector_start_angle: FloatProperty(
        name="Start Angle",
        subtype="ANGLE",
        default=0.0,
        update=_mark_widget_presentation_dirty,
    )
    sector_sweep_angle: FloatProperty(
        name="Sweep Angle",
        subtype="ANGLE",
        default=math.pi * 0.5,
        min=-math.tau,
        max=math.tau,
        update=_mark_widget_presentation_dirty,
    )
    segments: IntProperty(
        name="Resolution",
        description="Number of segments used by curved and spatial shapes",
        default=96,
        min=3,
        max=256,
        update=_mark_widget_presentation_dirty,
    )
    wire_width: FloatProperty(
        name="Wire Width",
        description="Viewport line width; does not change procedural geometry",
        default=1.0,
        min=0.5,
        max=16.0,
        update=_mark_widget_presentation_dirty,
    )
    live_preview: BoolProperty(
        name="Live Preview",
        description=(
            "Apply presentation changes automatically when compiler preview "
            "support is available"
        ),
        default=True,
        update=_update_widget_presentation_live_preview,
    )
    needs_rebuild: BoolProperty(default=False)
    last_error: StringProperty()


class COATOOLS2_PG_SemanticInputTerm(bpy.types.PropertyGroup):
    """One Blender value contributing to a normalized semantic channel."""

    term_uuid: StringProperty()
    source_stage_uuid: StringProperty(
        name="Source Stage UUID",
        description=(
            "Direct dependency stage that supplies this automatically wired input; "
            "leave empty for an explicit Object/Bone source"
        ),
    )
    source_object: PointerProperty(type=bpy.types.Object)
    source_bone: StringProperty()
    source_kind: EnumProperty(
        items=(
            ("TRANSFORM", "Transform", "Read a local transform component"),
            ("CUSTOM_PROPERTY", "Property", "Read an ID or pose-bone property"),
        ),
        default="TRANSFORM",
    )
    transform_type: EnumProperty(
        items=tuple(
            (identifier, label, label)
            for identifier, label in (
                ("LOC_X", "Location X"),
                ("LOC_Y", "Location Y"),
                ("LOC_Z", "Location Z"),
                ("ROT_X", "Rotation X"),
                ("ROT_Y", "Rotation Y"),
                ("ROT_Z", "Rotation Z"),
                ("SCALE_X", "Scale X"),
                ("SCALE_Y", "Scale Y"),
                ("SCALE_Z", "Scale Z"),
            )
        ),
        default="LOC_X",
    )
    transform_space: EnumProperty(
        items=(
            ("LOCAL_SPACE", "Local", "Read the transform in local space"),
            ("WORLD_SPACE", "World", "Read the transform in world space"),
            ("TRANSFORM_SPACE", "Transform", "Read transform space"),
        ),
        default="LOCAL_SPACE",
    )
    data_path: StringProperty()
    array_index: IntProperty(default=-1, min=-1)
    coefficient: FloatProperty(default=1.0)


class COATOOLS2_PG_SemanticInputChannel(bpy.types.PropertyGroup):
    channel_uuid: StringProperty()
    channel_id: StringProperty()
    label: StringProperty(default="Input")
    kind: EnumProperty(
        items=(
            ("CONTINUOUS", "Continuous", "Numerically interpolate this channel"),
            ("DISCRETE", "Discrete", "Use nearest-sample selection"),
        ),
        default="CONTINUOUS",
    )
    scale: FloatProperty(
        name="Distance Scale",
        description="Meaningful size of one unit in the pose field",
        default=1.0,
        min=1.0e-8,
    )
    offset: FloatProperty(default=0.0)
    terms: CollectionProperty(type=COATOOLS2_PG_SemanticInputTerm)
    terms_index: IntProperty(default=0, min=0)


class COATOOLS2_PG_SemanticOutputChannel(bpy.types.PropertyGroup):
    output_uuid: StringProperty()
    output_id: StringProperty()
    label: StringProperty(default="Output")
    target_kind: EnumProperty(
        items=(
            ("SHAPE_KEY", "Shape Key", "Drive a Shape Key value"),
            (
                "CONSTRAINT_INFLUENCE",
                "Constraint Influence",
                "Drive a pose-bone constraint influence",
            ),
            ("BONE_LOCATION", "Bone Location", "Drive one pose-bone location axis"),
            ("BONE_ROTATION", "Bone Rotation", "Drive one pose-bone rotation axis"),
            ("CUSTOM_PROPERTY", "Property", "Drive an arbitrary scalar property"),
            ("SLOT_INDEX", "Sprite Slot", "Drive a discrete sprite slot"),
            ("Z_VALUE", "Draw Order", "Drive COA draw order"),
        ),
        default="SHAPE_KEY",
    )
    target_object: PointerProperty(type=bpy.types.Object)
    target_bone: StringProperty()
    target_name: StringProperty()
    data_path: StringProperty()
    array_index: IntProperty(default=-1, min=-1, max=3)
    policy: EnumProperty(
        items=(
            ("DIRECT", "Direct", "Apply the recorded value directly"),
            (
                "PROJECT_TO_ART_PLANE",
                "Project to Art Plane",
                "Discard motion normal to the configured art plane",
            ),
            ("PARAMETRIC", "Parametric", "Drive artwork parameters only"),
            ("HYBRID", "Hybrid", "Combine projected transform and artwork output"),
        ),
        default="PARAMETRIC",
    )
    value_arity: IntProperty(default=1, min=1, max=4)
    discrete: BoolProperty(default=False)
    enabled: BoolProperty(default=True)


class COATOOLS2_PG_SemanticSampleInput(bpy.types.PropertyGroup):
    channel_id: StringProperty()
    value: FloatProperty()


class COATOOLS2_PG_SemanticSampleOutput(bpy.types.PropertyGroup):
    output_uuid: StringProperty()
    value: FloatVectorProperty(size=4)
    value_arity: IntProperty(default=1, min=1, max=4)
    discrete_value: StringProperty()


class COATOOLS2_PG_SemanticPoseSample(bpy.types.PropertyGroup):
    sample_uuid: StringProperty()
    label: StringProperty(default="Pose Sample")
    enabled: BoolProperty(default=True)
    inputs: CollectionProperty(type=COATOOLS2_PG_SemanticSampleInput)
    outputs: CollectionProperty(type=COATOOLS2_PG_SemanticSampleOutput)


class COATOOLS2_PG_SemanticStage(bpy.types.PropertyGroup):
    """One ordered, composable solver or mapping layer."""

    stage_uuid: StringProperty()
    semantic_id: StringProperty()
    label: StringProperty(default="Semantic Stage")
    stage_type: EnumProperty(
        items=(
            (
                "PROJECTED_TRANSFORM",
                "Projected Transform",
                "Decode a displayed 3D direction into art-plane values",
            ),
            (
                "POSE_MAP",
                "Recorded Pose Map",
                "Interpolate recorded outputs in an N-dimensional pose field",
            ),
            (
                "CHAIN_FK",
                "FK Chain",
                "Rotate a generated FK control chain as a composable solver stage",
            ),
            ("CHAIN_IK", "Kinematic Chain", "Solve a managed IK mechanism chain"),
            (
                "CONTACT_PIN",
                "Contact / Pin",
                "Constrain a control over an explicit frame range",
            ),
            ("SPLINE", "Spline Chain", "Solve a chain along a generated curve"),
            (
                "BBONE_BEZIER",
                "B-Bone Bezier",
                "Drive one B-Bone through point and tangent-handle controls",
            ),
            (
                "SECONDARY_MOTION",
                "Secondary Motion",
                "Bake deterministic spring and lag motion",
            ),
        ),
        default="PROJECTED_TRANSFORM",
    )
    enabled: BoolProperty(default=True)
    order: IntProperty(default=0, min=0)
    depends_on: StringProperty(
        description="Comma-separated stage UUIDs; normalized by the compiler"
    )
    source_bones: CollectionProperty(type=COATOOLS2_PG_RigComponentBoneRef)
    source_bones_index: IntProperty(default=0, min=0)
    presentation: PointerProperty(type=COATOOLS2_PG_RigWidgetPresentation)
    fk_presentation: PointerProperty(type=COATOOLS2_PG_RigWidgetPresentation)
    pole_presentation: PointerProperty(type=COATOOLS2_PG_RigWidgetPresentation)
    handle_presentation: PointerProperty(type=COATOOLS2_PG_RigWidgetPresentation)

    projection_mode: EnumProperty(
        items=(
            ("SCREEN_PLANE", "Screen Plane", "Use the configured screen plane"),
            ("ART_PLANE", "Art Plane", "Project onto the artwork plane"),
            (
                "VISUAL_NORMAL",
                "Apparent Normal",
                "Decode motion along the displayed apparent normal",
            ),
        ),
        default="ART_PLANE",
    )
    preserve_art_plane: BoolProperty(default=True)
    art_plane_normal: FloatVectorProperty(
        size=3,
        subtype="DIRECTION",
        default=(0.0, 1.0, 0.0),
    )
    visual_axis: FloatVectorProperty(
        size=3,
        subtype="DIRECTION",
        default=(0.0, 0.0, 1.0),
    )
    control_bone: StringProperty()
    display_frame_bone: StringProperty()
    mechanism_frame_bone: StringProperty()
    art_frame_bone: StringProperty()

    inputs: CollectionProperty(type=COATOOLS2_PG_SemanticInputChannel)
    inputs_index: IntProperty(default=0, min=0)
    outputs: CollectionProperty(type=COATOOLS2_PG_SemanticOutputChannel)
    outputs_index: IntProperty(default=0, min=0)
    samples: CollectionProperty(type=COATOOLS2_PG_SemanticPoseSample)
    samples_index: IntProperty(default=0, min=0)
    neighborhood_size: IntProperty(default=8, min=1, max=64)
    kernel_radius: FloatProperty(default=2.0, min=1.0e-6)
    exact_epsilon: FloatProperty(default=1.0e-8, min=1.0e-12)

    use_pole: BoolProperty(default=True)
    pole_bone: StringProperty()
    chain_length: IntProperty(default=2, min=1, max=64)
    allow_stretch: BoolProperty(default=False)
    fk_widget_defaults_initialized: BoolProperty(
        default=False,
        options={"HIDDEN"},
    )
    rig_mode: EnumProperty(
        name="Mode",
        description="Discrete animator-facing FK/IK state; switch through Pose Match",
        items=(
            ("FK", "FK", "Rotate the generated FK controls"),
            ("IK", "IK", "Move the generated IK handle and optional pole"),
        ),
        default="IK",
        options={"ANIMATABLE"},
    )
    switch_advanced_expanded: BoolProperty(
        name="Advanced",
        default=False,
        options={"SKIP_SAVE"},
    )
    pin_target_object: PointerProperty(type=bpy.types.Object)
    pin_target_bone: StringProperty()
    pin_driven_bone: StringProperty(update=_mark_pin_driven_explicit)
    pin_driven_stage_uuid: StringProperty(
        description="Internal dependency UUID used for automatic pin wiring",
        options={"HIDDEN"},
    )
    pin_space: EnumProperty(
        items=(
            ("WORLD", "World", "Keep the contact in world space"),
            ("CHARACTER", "Character", "Keep the contact relative to the rig"),
            ("TARGET", "Target", "Keep the contact relative to a target"),
        ),
        default="WORLD",
    )
    pin_position: BoolProperty(default=True)
    pin_orientation: BoolProperty(default=False)
    pin_start: IntProperty(default=1)
    pin_end: IntProperty(default=24)
    blend_in: IntProperty(default=2, min=1)
    blend_out: IntProperty(default=2, min=1)
    pin_property: StringProperty()
    contact_mode: EnumProperty(
        name="Contact Pin",
        description="Discrete animator-facing contact state",
        items=(
            ("OFF", "Off", "Release the contact with compensation"),
            ("ON", "On", "Capture and maintain the current contact"),
        ),
        default="OFF",
        options={"ANIMATABLE"},
    )
    contact_transition_frames: IntProperty(
        name="Transition Frames",
        description="Private compensation ramp length used by Contact Pin",
        default=2,
        min=1,
        max=120,
    )

    curve_object: PointerProperty(type=bpy.types.Object)
    spline_control_count: IntProperty(default=3, min=2, max=32)
    root_pin: BoolProperty(default=True)
    tip_pin: BoolProperty(default=False)

    bbone_segments: IntProperty(default=8, min=2, max=32)
    bbone_handle_length: FloatProperty(default=0.33, min=0.05, max=2.0)
    bbone_use_mid_control: BoolProperty(default=False)
    bbone_mid_influence: FloatProperty(default=0.5, min=0.0, max=1.0)
    bbone_ease_in: FloatProperty(default=1.0, min=0.0, max=10.0)
    bbone_ease_out: FloatProperty(default=1.0, min=0.0, max=10.0)
    bbone_roll_in: FloatProperty(default=0.0, subtype="ANGLE")
    bbone_roll_out: FloatProperty(default=0.0, subtype="ANGLE")
    bbone_use_scale: BoolProperty(default=False)
    bbone_scale_in: FloatVectorProperty(
        size=3,
        subtype="XYZ",
        default=(1.0, 1.0, 1.0),
        min=0.01,
        max=10.0,
    )
    bbone_scale_out: FloatVectorProperty(
        size=3,
        subtype="XYZ",
        default=(1.0, 1.0, 1.0),
        min=0.01,
        max=10.0,
    )
    bbone_start_bone: StringProperty(options={"HIDDEN"})
    bbone_end_bone: StringProperty(options={"HIDDEN"})
    bbone_handle_out_bone: StringProperty(options={"HIDDEN"})
    bbone_handle_in_bone: StringProperty(options={"HIDDEN"})
    bbone_mid_bone: StringProperty(options={"HIDDEN"})
    bbone_widget_defaults_initialized: BoolProperty(
        default=False,
        options={"HIDDEN"},
    )
    bbone_show_advanced: BoolProperty(default=False, options={"SKIP_SAVE"})

    frequency_hz: FloatProperty(default=3.0, min=0.001)
    damping_ratio: FloatProperty(default=0.65, min=0.0)
    substeps: IntProperty(default=2, min=1, max=64)
    pre_roll: IntProperty(default=8, min=0, max=250)
    bake_start: IntProperty(default=1)
    bake_end: IntProperty(default=24)
    secondary_baked: BoolProperty(default=False)
    secondary_source_signature: StringProperty()


class COATOOLS2_PG_RigComponentArtifact(bpy.types.PropertyGroup):
    artifact_uuid: StringProperty()
    role: StringProperty()
    data_type: StringProperty()
    object_name: StringProperty()
    bone_name: StringProperty()
    constraint_name: StringProperty()
    data_path: StringProperty()
    binding_uuid: StringProperty()
    owned: BoolProperty(default=True)


class COATOOLS2_PG_RigComponent(bpy.types.PropertyGroup):
    schema_version: IntProperty(default=RIG_COMPONENT_SCHEMA_VERSION)
    component_uuid: StringProperty()
    semantic_id: StringProperty()
    label: StringProperty(default="Pose Component", update=_mark_component_dirty)
    component_type: EnumProperty(
        items=(
            ("ROOT", "Root / Body", "Root or body parameter control"),
            ("FK_CHAIN", "Part Rotation", "Part-oriented parameter or direct FK control"),
            (
                "LIMB_IK",
                "Limb Target / IK",
                "Parametric limb target or legacy three-bone direct IK",
            ),
            ("SPINE_FK", "Spine / Body", "Body parameter or direct FK component"),
            (
                "SEMANTIC",
                "Semantic Character Rig",
                "Compose projected input, pose maps, kinematics, contact, and motion layers",
            ),
        ),
        default="LIMB_IK",
        update=_mark_component_dirty,
    )
    side: EnumProperty(
        items=(
            ("CENTER", "Center", "Center component"),
            ("LEFT", "Left", "Left-side component"),
            ("RIGHT", "Right", "Right-side component"),
        ),
        default="CENTER",
        update=_mark_component_dirty,
    )
    deformation_mode: EnumProperty(
        name="Artwork Deformation",
        items=(
            (
                "PARAMETRIC",
                "Parametric (Shape Keys)",
                "Use generated controls only as parameter inputs; keep source bones unchanged",
            ),
            (
                "DIRECT_BONES",
                "Direct Bones (Legacy)",
                "Apply FK or IK directly to source bones and their artwork",
            ),
        ),
        # Version 1 files did not store this field and used direct deformation.
        # New components explicitly opt into PARAMETRIC in the Add operator.
        default="DIRECT_BONES",
        update=_mark_component_dirty,
    )
    compiled_deformation_mode: StringProperty(
        description=(
            "Internal record used to prevent unsafe in-place conversion "
            "between parameter and direct-bone rigs"
        ),
        options={"HIDDEN"},
    )
    source_bones: CollectionProperty(type=COATOOLS2_PG_RigComponentBoneRef)
    source_bones_index: IntProperty(default=0, min=0)
    build_mode: EnumProperty(
        items=(
            (
                "IN_PLACE",
                "In Place",
                "Use existing source bones without replacing their animation paths",
            ),
            (
                "GENERATED",
                "Generated Control",
                "Generate separate control and mechanism bones",
            ),
        ),
        default="IN_PLACE",
        update=_mark_component_dirty,
    )
    orientation_mode: EnumProperty(
        items=(
            (
                "WORLD_VIEW",
                "World View Plane",
                "Use armature X/Z as the art plane and Y as depth",
            ),
            (
                "SOURCE_BONE",
                "Source Bone",
                "Copy the visual axes from the orientation reference bone",
            ),
            (
                "CUSTOM",
                "Custom Offset",
                "Apply a custom rotation offset to the reference frame",
            ),
        ),
        default="SOURCE_BONE",
        update=_mark_component_dirty,
    )
    orientation_reference: StringProperty(update=_mark_component_dirty)
    orientation_euler: FloatVectorProperty(
        name="Orientation Offset",
        size=3,
        subtype="EULER",
        update=_mark_component_dirty,
    )
    depth_mode: EnumProperty(
        items=(
            (
                "LOCKED",
                "Plane",
                "Keep control-local Z fixed to the artwork plane",
            ),
            (
                "LIMITED",
                "Limited Depth",
                "Allow control-local Z only inside a bounded slab",
            ),
            ("FREE", "Free 3D", "Do not constrain control-local depth"),
        ),
        default="LIMITED",
        update=_mark_component_dirty,
    )
    depth_min: FloatProperty(
        name="Depth Back",
        default=-0.25,
        update=_mark_component_dirty,
    )
    depth_max: FloatProperty(
        name="Depth Front",
        default=0.25,
        update=_mark_component_dirty,
    )
    allow_translation: BoolVectorProperty(
        name="Translation Axes",
        size=3,
        subtype="XYZ",
        default=(True, True, True),
        update=_mark_component_dirty,
    )
    allow_rotation: BoolVectorProperty(
        name="Rotation Axes",
        size=3,
        subtype="XYZ",
        default=(True, True, True),
        update=_mark_component_dirty,
    )
    widget: EnumProperty(
        items=(
            ("ROOT", "Root", "Three-dimensional root control"),
            ("FK", "FK", "All-axis FK rotation control"),
            ("HAND", "Hand", "Palm-oriented hand IK control"),
            ("FOOT", "Foot", "Sole-oriented foot IK control"),
            ("SQUARE", "Square", "Neutral oriented IK control"),
        ),
        default="SQUARE",
        update=_mark_component_dirty,
    )
    widget_size: FloatProperty(
        default=1.0,
        min=0.01,
        update=_mark_component_dirty,
    )
    presentation: PointerProperty(type=COATOOLS2_PG_RigWidgetPresentation)
    ik_chain_length: IntProperty(
        default=2,
        min=1,
        max=32,
        update=_mark_component_dirty,
    )
    ik_solver_mode: EnumProperty(
        items=(
            (
                "SPATIAL",
                "Spatial",
                "Allow the limb to solve in three dimensions",
            ),
            (
                "PLANAR",
                "Planar",
                "Keep the limb on an explicit local bend plane",
            ),
        ),
        default="SPATIAL",
        update=_mark_component_dirty,
    )
    bend_axis: EnumProperty(
        items=(
            ("AUTO", "Automatic", "Infer the bend direction from the rest pose"),
            ("X", "Local X", "Use local X as the bend axis"),
            ("Y", "Local Y", "Use local Y as the bend axis"),
            ("Z", "Local Z", "Use local Z as the bend axis"),
        ),
        default="AUTO",
        update=_mark_component_dirty,
    )
    use_bend_hint: BoolProperty(
        name="Bend Hint",
        description="Generate a pole control that stabilizes spatial IK bending",
        default=True,
        update=_mark_component_dirty,
    )
    pole_distance: FloatProperty(
        name="Bend Distance",
        description="Distance of the bend hint relative to the limb length",
        default=1.0,
        min=0.05,
        update=_mark_component_dirty,
    )
    use_stretch: BoolProperty(default=False, update=_mark_component_dirty)
    end_rotation_mode: EnumProperty(
        items=(
            ("COPY_WORLD", "Follow Target", "End bone follows target rotation"),
            (
                "COPY_LOCAL",
                "Follow Target Local",
                "End bone follows target in local space",
            ),
            ("NONE", "Position Only", "Do not copy target rotation to the end bone"),
        ),
        default="COPY_WORLD",
        update=_mark_component_dirty,
    )
    frame_bone: StringProperty()
    control_bone: StringProperty()
    pole_bone: StringProperty()
    pole_angle: FloatProperty(subtype="ANGLE")
    pole_angle_valid: BoolProperty(default=False)
    constraint_bone: StringProperty()
    constraint_name: StringProperty()
    bindings: CollectionProperty(type=COATOOLS2_PG_RigBinding)
    bindings_index: IntProperty(default=0, min=0)
    artifacts: CollectionProperty(type=COATOOLS2_PG_RigComponentArtifact)
    artifacts_index: IntProperty(default=0, min=0)
    semantic_schema_version: IntProperty(default=SEMANTIC_RIG_SCHEMA_VERSION)
    semantic_stages: CollectionProperty(type=COATOOLS2_PG_SemanticStage)
    semantic_stages_index: IntProperty(default=0, min=0)
    semantic_edit_sample_uuid: StringProperty()
    semantic_edit_stage_uuid: StringProperty()
    enabled: BoolProperty(default=True, update=_mark_component_dirty)
    needs_rebuild: BoolProperty(default=False)
    last_error: StringProperty()


class COATOOLS2_PG_RigControl(bpy.types.PropertyGroup):
    schema_version: IntProperty(default=SCHEMA_VERSION)
    control_uuid: StringProperty()
    semantic_id: StringProperty()
    label: StringProperty(default="Rig Control", update=_mark_control_dirty)
    control_type: EnumProperty(
        items=(
            ("SLIDER_1D", "1D Slider", "One-dimensional slider"),
            ("POINT_2D_RECT", "2D Rectangle", "Rectangular 2D slider"),
            ("POINT_2D_CIRCLE", "2D Circle", "Circular 2D slider"),
            ("DIAL", "Dial", "Angular slider constrained to a visible rail"),
        ),
        default="SLIDER_1D",
        update=_mark_control_dirty,
    )
    axis: EnumProperty(
        items=(
            ("X", "Horizontal", "Move along local X"),
            ("Y", "Vertical", "Move along local Y"),
            ("ROTATION", "Angle", "Position along the dial rail"),
        ),
        default="X",
        update=_mark_control_dirty,
    )
    control_bone: StringProperty()
    display_bone: StringProperty()
    name_bone: StringProperty()
    name_text_object: StringProperty()
    show_name: BoolProperty(
        name="Show Rig Name",
        description="Show the control name below the widget",
        default=True,
        update=_mark_control_dirty,
    )
    name_offset: FloatProperty(
        name="Name Offset",
        description="Distance between the widget bottom and its name",
        default=0.75,
        min=0.0,
        update=_mark_control_dirty,
    )
    name_size: FloatProperty(
        name="Name Size",
        description="Viewport text size for the rig control name",
        default=0.4,
        min=0.05,
        update=_mark_control_dirty,
    )
    tip_widget_uuid: StringProperty()
    base_widget_uuid: StringProperty()
    width: FloatProperty(default=4.0, min=0.1, update=_mark_control_dirty)
    height: FloatProperty(default=2.0, min=0.1, update=_mark_control_dirty)
    radius: FloatProperty(default=2.0, min=0.1, update=_mark_control_dirty)
    rectangle_mode: EnumProperty(
        items=(
            (
                "FREE",
                "Free Interior",
                "Move freely anywhere inside the rectangular area",
            ),
            (
                "GRID",
                "Grid Rails",
                "Draw internal rails and keep the tip on the grid",
            ),
        ),
        default="FREE",
        update=_mark_control_dirty,
    )
    grid_columns: IntProperty(default=3, min=2, max=32, update=_mark_control_dirty)
    grid_rows: IntProperty(default=3, min=2, max=32, update=_mark_control_dirty)
    angle_min: FloatProperty(
        default=-math.pi * 0.5,
        subtype="ANGLE",
        update=_mark_control_dirty,
    )
    angle_max: FloatProperty(
        default=math.pi * 0.5,
        subtype="ANGLE",
        update=_mark_control_dirty,
    )
    tip_radius: FloatProperty(default=0.68, min=0.01, update=_mark_control_dirty)
    node_radius: FloatProperty(default=0.34, min=0.01, update=_mark_control_dirty)
    bar_width: FloatProperty(default=0.28, min=0.01, update=_mark_control_dirty)
    stroke_radius: FloatProperty(
        default=0.035,
        min=0.001,
        update=_mark_control_dirty,
    )
    input_min: FloatProperty(default=0.0)
    input_max: FloatProperty(default=4.0)
    widget_backend: EnumProperty(
        items=(
            (
                "EVALUATED_MESH_CACHE",
                "Evaluated Mesh Cache",
                "Use a cached Mesh generated from Geometry Nodes",
            ),
            (
                "LIVE_MODIFIER",
                "Live Modifier",
                "Use the Geometry Nodes modifier object directly",
            ),
        ),
        default="EVALUATED_MESH_CACHE",
        update=_mark_control_dirty,
    )
    live_preview: BoolProperty(
        name="Live Preview",
        description=(
            "Automatically rebuild shortly after a Rig Control parameter changes"
        ),
        default=True,
        update=_update_live_preview,
    )
    bindings: CollectionProperty(type=COATOOLS2_PG_RigBinding)
    bindings_index: IntProperty(default=0, min=0)
    state_mode: EnumProperty(
        name="State Mode",
        items=(
            ("NONE", "None", "Use ordinary bindings only"),
            (
                "LINEAR_1D",
                "1D States",
                "Interpolate Shape Key states along a 1D slider",
            ),
            (
                "MATRIX_2D",
                "2D State Matrix",
                "Interpolate Shape Key states on an arbitrary grid",
            ),
            (
                "GRAPH_2D",
                "2D State Graph",
                "Interpolate arbitrary named points and fallback edges",
            ),
        ),
        default="NONE",
        update=_mark_control_dirty,
    )
    state_mix_policy: EnumProperty(
        name="Mix Domain",
        items=(
            ("FULL", "Full", "Allow continuous mixing in every cell"),
            ("NO_MIX", "Grid Only", "Keep the handle on state grid rails"),
            (
                "PARTIAL",
                "Per Cell",
                "Allow mixing only in selected four-point cells",
            ),
        ),
        default="FULL",
    )
    state_columns: IntProperty(default=2, min=2, max=32, update=_mark_control_dirty)
    state_rows: IntProperty(default=2, min=1, max=32, update=_mark_control_dirty)
    state_points: CollectionProperty(type=COATOOLS2_PG_RigStatePoint)
    state_points_index: IntProperty(default=0, min=0)
    state_cells: CollectionProperty(type=COATOOLS2_PG_RigStateCell)
    state_cells_index: IntProperty(default=0, min=0)
    graph_interpolation: EnumProperty(
        name="Graph Behavior",
        items=(
            (
                "NAMED_GRAPH",
                "Named Graph",
                "Keep the manual handle on fallback edges and blend their endpoints",
            ),
            (
                "MAP_2D",
                "2D Mouth Map",
                "Blend nearby named points anywhere inside the 2D control",
            ),
            (
                "HYBRID",
                "Hybrid",
                "Use the 2D map inside the point hull and fallback edges outside it",
            ),
        ),
        default="MAP_2D",
        update=_mark_control_dirty,
    )
    graph_radius: FloatProperty(
        name="Blend Radius",
        description="Normalized influence radius used by 2D Graph State interpolation",
        default=0.75,
        min=0.01,
        max=4.0,
        update=_mark_control_dirty,
    )
    lip_sync_preset: EnumProperty(
        name="Lip Sync Preset",
        items=(
            ("NONE", "None", "Generic named Graph State"),
            ("MINIMAL", "Minimal", "REST, A/E, I, and U/O"),
            ("JP_VOWELS", "JP Vowels", "REST plus A, I, U, E, O"),
            ("JP_VOWELS_MBP", "JP Vowels + MBP", "Japanese vowels plus closed lips"),
            ("STANDARD_2D", "Standard 2D", "Common seven-state 2D mouth map"),
            (
                "ADVANCED_PHONEME",
                "Advanced Phoneme",
                "Named visemes with phoneme aliases and safe fallbacks",
            ),
        ),
        default="NONE",
    )
    graph_custom_object: PointerProperty(
        name="Graph Base Object",
        description="Optional object replacing the generated graph base custom shape",
        type=bpy.types.Object,
        update=_mark_control_dirty,
    )
    origin: FloatVectorProperty(size=3, subtype="XYZ")
    needs_rebuild: BoolProperty(default=False)
    auto_rebuild_error: StringProperty()


class COATOOLS2_PG_RigObjectProperties(bpy.types.PropertyGroup):
    """Rig-only object data kept outside the shared COA ObjectProperties."""

    rig_instance_id: StringProperty()
    rig_controls: CollectionProperty(type=COATOOLS2_PG_RigControl)
    rig_controls_index: IntProperty(default=0, min=0)
    rig_components: CollectionProperty(type=COATOOLS2_PG_RigComponent)
    rig_components_index: IntProperty(default=0, min=0)
    rig_validation_issues: CollectionProperty(type=COATOOLS2_PG_RigValidationIssue)
    rig_validation_issues_index: IntProperty(default=0, min=0)
    legacy_migration_checked: BoolProperty(default=False, options={"HIDDEN"})


_CONTROL_FIELDS = (
    "schema_version",
    "control_uuid",
    "semantic_id",
    "label",
    "control_type",
    "axis",
    "control_bone",
    "display_bone",
    "name_bone",
    "name_text_object",
    "show_name",
    "name_offset",
    "name_size",
    "tip_widget_uuid",
    "base_widget_uuid",
    "width",
    "height",
    "radius",
    "rectangle_mode",
    "grid_columns",
    "grid_rows",
    "angle_min",
    "angle_max",
    "tip_radius",
    "node_radius",
    "bar_width",
    "stroke_radius",
    "input_min",
    "input_max",
    "widget_backend",
    "live_preview",
    "bindings_index",
    "state_mode",
    "state_mix_policy",
    "state_columns",
    "state_rows",
    "state_points_index",
    "state_cells_index",
    "graph_interpolation",
    "graph_radius",
    "lip_sync_preset",
    "graph_custom_object",
    "origin",
    "needs_rebuild",
    "auto_rebuild_error",
)
_BINDING_FIELDS = (
    "schema_version",
    "binding_uuid",
    "control_uuid",
    "source_component",
    "target_kind",
    "target_object",
    "target_bone",
    "target_name",
    "generated_data_path",
    "input_min",
    "input_max",
    "output_min",
    "output_max",
    "clamp",
    "enabled",
)
_ISSUE_FIELDS = (
    "severity",
    "code",
    "message",
    "control_uuid",
    "binding_uuid",
)
_STATE_POINT_FIELDS = (
    "schema_version",
    "state_uuid",
    "control_uuid",
    "label",
    "column",
    "row",
    "target_object",
    "target_name",
    "target_name_candidates",
    "phoneme_aliases",
    "generated_data_path",
    "graph_position",
    "point_shape",
    "custom_object",
    "fallback_state_uuid",
    "is_empty",
    "enabled",
)
_STATE_CELL_FIELDS = (
    "schema_version",
    "cell_uuid",
    "control_uuid",
    "column",
    "row",
    "mix_enabled",
)
_MISSING = object()


def _copy_fields(source, target, field_names):
    for field_name in field_names:
        value = getattr(source, field_name, _MISSING)
        if value is _MISSING and hasattr(source, "get"):
            value = source.get(field_name, _MISSING)
        if value is _MISSING:
            continue
        rna_property = target.bl_rna.properties.get(field_name)
        if (
            rna_property is not None
            and rna_property.type == "ENUM"
            and isinstance(value, int)
        ):
            value = next(
                (
                    item.identifier
                    for item in rna_property.enum_items
                    if item.value == value
                ),
                _MISSING,
            )
            if value is _MISSING:
                continue
        setattr(target, field_name, value)


def _legacy_collection(owner, field_name):
    collection = getattr(owner, field_name, _MISSING)
    if collection is _MISSING and hasattr(owner, "get"):
        collection = owner.get(field_name, _MISSING)
    return None if collection is _MISSING else collection


def _legacy_value(owner, field_name, default=None):
    value = getattr(owner, field_name, _MISSING)
    if value is _MISSING and hasattr(owner, "get"):
        value = owner.get(field_name, _MISSING)
    return default if value is _MISSING else value


def _migrate_legacy_rig_data(obj, rig_data):
    """Copy definitions stored by commits before the dedicated RNA namespace."""

    if rig_data.legacy_migration_checked:
        return

    legacy = getattr(obj, "coa_tools2", None)
    legacy_controls = (
        _legacy_collection(legacy, "rig_controls") if legacy is not None else None
    )
    if legacy is None or legacy_controls is None:
        rig_data.legacy_migration_checked = True
        return
    if not rig_data.rig_instance_id:
        rig_data.rig_instance_id = _legacy_value(legacy, "rig_instance_id", "")

    if not rig_data.rig_controls:
        for legacy_control in legacy_controls:
            control = rig_data.rig_controls.add()
            _copy_fields(legacy_control, control, _CONTROL_FIELDS)
            for legacy_binding in _legacy_collection(
                legacy_control, "bindings"
            ) or ():
                binding = control.bindings.add()
                _copy_fields(legacy_binding, binding, _BINDING_FIELDS)
            for legacy_state in _legacy_collection(
                legacy_control, "state_points"
            ) or ():
                state = control.state_points.add()
                _copy_fields(legacy_state, state, _STATE_POINT_FIELDS)
            for legacy_cell in _legacy_collection(
                legacy_control, "state_cells"
            ) or ():
                cell = control.state_cells.add()
                _copy_fields(legacy_cell, cell, _STATE_CELL_FIELDS)
        if rig_data.rig_controls:
            rig_data.rig_controls_index = min(
                _legacy_value(legacy, "rig_controls_index", 0),
                len(rig_data.rig_controls) - 1,
            )

    legacy_issues = _legacy_collection(legacy, "rig_validation_issues")
    if not rig_data.rig_validation_issues and legacy_issues is not None:
        for legacy_issue in legacy_issues:
            issue = rig_data.rig_validation_issues.add()
            _copy_fields(legacy_issue, issue, _ISSUE_FIELDS)
    rig_data.legacy_migration_checked = True


def get_rig_data(obj, *, migrate=True):
    """Return collision-free rig data, optionally migrating the legacy layout.

    Blender operator and panel ``poll`` callbacks run in a read-only RNA
    context.  Callers in those callbacks must pass ``migrate=False``; the
    corresponding ``execute`` path keeps the default and performs migration in
    a writable context before it mutates rig definitions.
    """

    rig_data = getattr(obj, "coa_tools2_rig", None)
    if rig_data is None:
        raise RuntimeError(
            "COA Tools 2 rig properties are not registered. "
            "Disable duplicate add-on installations and reload the add-on."
        )
    if migrate:
        _migrate_legacy_rig_data(obj, rig_data)
    return rig_data


def component_to_spec(component) -> RigComponentSpec:
    """Convert a persisted Blender component into the pure validated schema."""

    return RigComponentSpec.from_dict(
        {
            "schema_version": component.schema_version,
            "component_uuid": component.component_uuid,
            "semantic_id": component.semantic_id,
            "display_name": component.label,
            "component_type": component.component_type,
            "source_bones": tuple(ref.bone_name for ref in component.source_bones),
            "side": component.side,
            "deformation_mode": component.deformation_mode,
            "orientation_mode": component.orientation_mode,
            "orientation_reference": component.orientation_reference,
            "orientation_euler": tuple(component.orientation_euler),
            "depth_mode": component.depth_mode,
            "depth_min": component.depth_min,
            "depth_max": component.depth_max,
            "allow_translation": tuple(component.allow_translation),
            "allow_rotation": tuple(component.allow_rotation),
            "widget": component.widget,
            "widget_size": component.widget_size,
            "presentation": widget_presentation_to_spec(
                component.presentation
            ).to_dict(),
            "ik_chain_length": component.ik_chain_length,
            "solver_mode": component.ik_solver_mode,
            "bend_axis": component.bend_axis,
            "use_bend_hint": component.use_bend_hint,
            "pole_distance": component.pole_distance,
            "use_stretch": component.use_stretch,
            "end_rotation_mode": component.end_rotation_mode,
            "bindings": tuple(
                {
                    "binding_uuid": binding.binding_uuid,
                    "source_component": binding.source_component,
                    "target_kind": binding.target_kind,
                    "target_object_name": (
                        binding.target_object.name
                        if binding.target_object is not None
                        else ""
                    ),
                    "target_bone": binding.target_bone,
                    "target_name": binding.target_name,
                    "input_min": binding.input_min,
                    "input_max": binding.input_max,
                    "output_min": binding.output_min,
                    "output_max": binding.output_max,
                    "clamp": binding.clamp,
                    "enabled": binding.enabled,
                }
                for binding in component.bindings
            ),
            "enabled": component.enabled,
        }
    )


def widget_presentation_to_spec(presentation) -> RigWidgetPresentationSpec:
    """Convert a persisted Blender presentation into its pure schema value."""

    return RigWidgetPresentationSpec.from_dict(
        {
            "shape": presentation.shape,
            "custom_object_name": (
                presentation.custom_object.name
                if presentation.custom_object is not None
                else ""
            ),
            "width": presentation.width,
            "height": presentation.height,
            "corner_radius": presentation.corner_radius,
            "bar_width": presentation.bar_width,
            "head_length": presentation.head_length,
            "head_width": presentation.head_width,
            "radius": presentation.radius,
            "arc_angle": presentation.arc_angle,
            "sector_inner_radius": presentation.sector_inner_radius,
            "sector_outer_radius": presentation.sector_outer_radius,
            "sector_start_angle": presentation.sector_start_angle,
            "sector_sweep_angle": presentation.sector_sweep_angle,
            "segments": presentation.segments,
            "wire_width": presentation.wire_width,
            "live_preview": presentation.live_preview,
            "align_to_source_rest": presentation.align_to_source_rest,
        }
    )


CLASSES = (
    COATOOLS2_PG_RigBinding,
    COATOOLS2_PG_RigValidationIssue,
    COATOOLS2_PG_RigStatePoint,
    COATOOLS2_PG_RigStateCell,
    COATOOLS2_PG_RigComponentBoneRef,
    COATOOLS2_PG_RigWidgetPresentation,
    COATOOLS2_PG_SemanticInputTerm,
    COATOOLS2_PG_SemanticInputChannel,
    COATOOLS2_PG_SemanticOutputChannel,
    COATOOLS2_PG_SemanticSampleInput,
    COATOOLS2_PG_SemanticSampleOutput,
    COATOOLS2_PG_SemanticPoseSample,
    COATOOLS2_PG_SemanticStage,
    COATOOLS2_PG_RigComponentArtifact,
    COATOOLS2_PG_RigComponent,
    COATOOLS2_PG_RigControl,
    COATOOLS2_PG_RigObjectProperties,
)

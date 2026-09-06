"""Blender integration coverage for Animate/Setup and state-weight readouts."""

from pathlib import Path
from types import SimpleNamespace
import sys

import bpy


class Layout:
    def __init__(self):
        self.operators = []
        self.progresses = []
        self.labels = []

    def row(self, **_kwargs):
        return self

    def panel(self, *_args, **_kwargs):
        return self, self

    def prop(self, *_args, **_kwargs):
        pass

    def label(self, **kwargs):
        self.labels.append(kwargs.get("text", ""))

    def operator(self, name, **_kwargs):
        result = SimpleNamespace(operator=name)
        self.operators.append(result)
        return result

    def progress(self, **kwargs):
        self.progresses.append(kwargs)


def activate(armature, bone_name):
    from coa_tools2.rig_control.blender.selection import select_pose_bone
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="POSE")
    select_pose_bone(armature, bone_name)


def draw():
    from coa_tools2.rig_control.blender.workspace_ui import COATOOLS2_PT_RigWorkspace
    layout = Layout()
    COATOOLS2_PT_RigWorkspace.draw(SimpleNamespace(layout=layout), bpy.context)
    return layout


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    import coa_tools2
    from coa_tools2.rig_control.blender import workspace_ui as ui
    from coa_tools2.rig_control.blender.ui import COATOOLS2_PT_RigControls
    from coa_tools2.rig_control.blender.component_ui import COATOOLS2_PT_RigComponents
    from coa_tools2.rig_control.blender.viewport_display import apply_animator_display, restore_animator_display
    coa_tools2.register()
    bpy.ops.wm.open_mainfile(filepath=str(root / "samples/semantic_animation_controls_demo.blend"))
    assert bpy.context.window_manager.coa_tools2.rig_workspace == "ANIMATE"
    coa_tools2.set_shading(None)
    assert all(area.spaces.active.shading.type == "SOLID"
               for screen in bpy.data.screens for area in screen.areas
               if area.type == "VIEW_3D")
    graph = bpy.data.objects["DEMO_A_GraphLipSync"]
    control = graph.coa_tools2_rig.rig_controls[0]
    activate(graph, control.control_bone)
    assert not COATOOLS2_PT_RigControls.poll(bpy.context)
    assert not COATOOLS2_PT_RigComponents.poll(bpy.context)
    if graph.animation_data:
        graph.animation_data.action = None
    pose = graph.pose.bones[control.control_bone]
    # Includes a mixed point and an out-of-range input constrained by the rig.
    for x, y in ((.44, .55), (.62, .36), (-.3, 1.3)):
        pose.location = (x * control.width, y * control.height, 0)
        bpy.context.view_layer.update()
        values = ui.state_weight_values(graph, control)
        assert abs(sum(weight for _point, weight in values) - 1.0) < 1.0e-5
        if x == .44:
            assert sum(weight > .01 for _point, weight in values) > 1
        for point, weight in values:
            actual = point.target_object.data.shape_keys.key_blocks[point.target_name].value
            assert abs(weight - actual) < 1.0e-5, (point.label, weight, actual)
        layout = draw()
        assert len(layout.progresses) == len(control.state_points)
        assert all(op.operator == "coa_tools2.key_rig_control" for op in layout.operators)
    assert bpy.ops.coa_tools2.key_rig_control(control_uuid=control.control_uuid) == {"FINISHED"}
    assert ui.has_current_key(graph, pose, "location", bpy.context.scene.frame_current)
    before = tuple(tuple(row) for row in pose.matrix)
    bpy.context.window_manager.coa_tools2.rig_workspace = "SETUP"
    assert COATOOLS2_PT_RigControls.poll(bpy.context)
    assert COATOOLS2_PT_RigComponents.poll(bpy.context)
    layout = draw()
    assert any(op.operator == "coa_tools2.apply_animator_display" for op in layout.operators)
    bpy.context.window_manager.coa_tools2.rig_workspace = "ANIMATE"
    assert before == tuple(tuple(row) for row in pose.matrix)
    assert apply_animator_display(graph) > 0
    assert not pose.bone.hide
    restore_animator_display(graph)

    arm = bpy.data.objects["DEMO_B_FKIKContact"]
    component = arm.coa_tools2_rig.rig_components[0]
    ik = next(s for s in component.semantic_stages if s.stage_type == "CHAIN_IK")
    pin = next(s for s in component.semantic_stages if s.stage_type == "CONTACT_PIN")
    activate(arm, ik.control_bone)
    bpy.context.scene.frame_set(70)
    # An unrelated layer selection must not retarget the Animate operations.
    component.semantic_stages_index = 0
    layout = draw()
    switches = [op for op in layout.operators if op.operator == "coa_tools2.animate_rig_switch"]
    assert {(op.mode, op.stage_uuid) for op in switches} == {
        ("FK", ik.stage_uuid), ("IK", ik.stage_uuid),
        ("ON", pin.stage_uuid), ("OFF", pin.stage_uuid),
    }
    for mode in ("FK", "IK"):
        assert bpy.ops.coa_tools2.animate_rig_switch(
            component_uuid=component.component_uuid, stage_uuid=ik.stage_uuid,
            mode=mode) == {"FINISHED"}
        assert ik.rig_mode == mode
        assert ui.has_current_key(arm, ik, "rig_mode", 70)
    bpy.context.scene.frame_set(71)
    assert bpy.ops.coa_tools2.animate_rig_switch(
        component_uuid=component.component_uuid, stage_uuid=pin.stage_uuid,
        mode="ON") == {"FINISHED"}
    assert pin.contact_mode == "ON" and ui.has_current_key(arm, pin, "contact_mode", 71)
    # Another chain in the same component cannot inherit this hand's contact.
    ik_uuid, pin_uuid = ik.stage_uuid, pin.stage_uuid
    other = component.semantic_stages.add()
    other.stage_uuid = "workspace-other-chain"
    other.stage_type = "CHAIN_IK"
    assert not ui.animation_pair(component, other)[1]
    component.semantic_stages.remove(len(component.semantic_stages) - 1)
    ik = next(s for s in component.semantic_stages if s.stage_uuid == ik_uuid)
    assert tuple(s.stage_uuid for s in ui.animation_pair(component, ik)[1]) == (pin_uuid,)

    # Named input choices must resolve the target by UUID and reject cycles
    # atomically, even while another component is selected in Setup.
    data = arm.coa_tools2_rig
    dependency_component = data.rig_components.add()
    dependency_component.component_uuid = "workspace-dependency-test"
    for name in ("a", "b", "c"):
        item = dependency_component.semantic_stages.add()
        item.stage_uuid = "workspace-" + name
        item.label = name.upper()
    data.rig_components_index = 0
    for target, source in (("b", "a"), ("c", "b")):
        assert bpy.ops.coa_tools2.edit_rig_dependencies(
            stage_uuid="workspace-" + target,
            choices=[{"name": source, "label": source, "stage_uuid": "workspace-" + source, "selected": True}],
        ) == {"FINISHED"}
    assert dependency_component.needs_rebuild
    for source in ("workspace-c", "missing-layer"):
        try:
            bpy.ops.coa_tools2.edit_rig_dependencies(
                stage_uuid="workspace-a",
                choices=[{"name": source, "label": source, "stage_uuid": source, "selected": True}],
            )
        except RuntimeError as error:
            assert "cycle or refer to missing layers" in str(error)
        else:
            raise AssertionError("Invalid dependency was accepted")
        assert dependency_component.semantic_stages[0].depends_on == ""
    data.rig_components.remove(len(data.rig_components) - 1)
    print("RIG_WORKSPACE_UI_OK")


if __name__ == "__main__":
    main()

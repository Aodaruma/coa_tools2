# In-review Manual Checks (2026-06-13)

This memo lists manual verification steps for issues currently marked `In review` in project `coa_tools2 tasks`.

## Common setup

- Blender target: `Blender 5.1.x`
- Recommended sample file: `samples/sprite_example/test.blend`
- If testing local source directly, use the latest `coa_tools2` from this repository.

## #6 Automesh from image alpha

Goal: confirm `Automesh from Texture` runs and generates a mesh in Blender 5.1.

Steps:

1. Open `samples/sprite_example/test.blend`.
2. Select a sprite mesh such as `body.png`.
3. Enter the COA Tools2 mesh editing workflow so `Automesh from Texture` is available.
4. Run `Automesh from Texture`.
5. Optionally adjust `Resolution`, `Threshold`, and `Margin`, then run again.

Expected:

- No traceback or hard error.
- The mesh updates from the source image alpha.
- The operator can complete in Blender 5.1.

## #18 Copy mesh / weight / shapekey between sprites

Goal: confirm the current copy workflow works at least for copy behavior.

Steps:

1. Open `samples/sprite_example/test.blend`.
2. Duplicate a mesh sprite such as `body.png` to create a target copy.
3. In Object Mode, make the original sprite the active object.
4. Keep the duplicated mesh selected as the target.
5. Run `Copy Mesh Data`.

Expected:

- The operator finishes without error.
- Vertex groups are copied to the target mesh.
- Mesh data is reprojected to the target mesh.

Notes:

- This does **not** verify a true live-link workflow.
- If only copy works but link/sync does not, keep the issue open.

## #70 GIMP 3.0.x export

Goal: confirm the exporter works in GIMP 3.x and does not fail on Python syntax/runtime startup.

Prerequisite:

- GIMP 3.x installed
- The exporter script from this repository installed into the GIMP plugin path

Steps:

1. Install the GIMP exporter from `GIMP/coatools_exporter.py`.
2. Open `samples/sprite_example/sprite_example.xcf` in GIMP 3.x.
3. Run the COA Tools exporter.
4. Export to a temporary output folder.

Expected:

- The exporter loads in GIMP 3.x.
- No Python syntax error on startup.
- Export produces JSON and sprite images, or at minimum reaches export logic without immediate crash.

## #74 Krita export exception

Goal: confirm Krita export no longer hits the `setPixelData(..., 0.0, 0.0, ...)` type error.

Prerequisite:

- Krita installed
- The Krita plugin from `Krita/coa_tools2_exporter` installed into Krita

Steps:

1. Install the Krita exporter plugin.
2. Open a layered sample file that the plugin can export, such as `samples/sprite_example/sprite_example.psd` if compatible in your setup.
3. Run the COA Tools exporter from the Krita docker/panel.
4. Export to a temporary output folder.

Expected:

- Export does not fail with `TypeError: setPixelData ... argument 2 has unexpected type 'float'`.
- Export proceeds normally or fails for some different reason.

## #92 Edit Weights in Blender 5.0 / 5.1

Goal: confirm `Edit Weights` enters a usable weight-paint workflow in Blender 5.1.

Steps:

1. Open `samples/sprite_example/test.blend`.
2. Select `body.png` or another mesh sprite bound to the armature.
3. In the COA Tools2 panel, click `Edit Weights`.

Expected:

- Blender switches into Weight Paint mode.
- No error about `Bone.select`, `Bone object has no attribute select`, or similar Blender 5.x bone API issues.
- COA Tools2 overlay / weight workflow remains usable.

## #94 Missing numpy / cv2 guidance for Automesh

Goal: confirm missing dependencies produce guided feedback instead of only a raw failure.

Prerequisite:

- Test in an environment where `numpy` / `cv2` are not available to COA Tools2,
  or temporarily move the add-on vendor dependency folder aside before the test.

Steps:

1. Open `samples/sprite_example/test.blend`.
2. Select a sprite mesh such as `body.png`.
3. Open the mesh editing workflow.
4. Run `Automesh from Texture` without dependencies installed.

Expected:

- A friendly error/guidance path appears.
- The user is directed to Preferences and the `Install numpy / opencv` action.
- No raw uncaught traceback is shown as the only feedback.

Then install dependencies and re-test:

1. Use the add-on dependency installer.
2. Re-run `Automesh from Texture`.

Expected:

- Automesh can run successfully after dependencies are installed.

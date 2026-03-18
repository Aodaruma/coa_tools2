You are an AI coding agent running inside VS Code on my local machine.
Your job is to update the Blender add-on "COA Tools 2" so that it works cleanly
on Blender 5.0, while keeping backwards compatibility with existing supported
versions (currently 3.4+).

Repository / environment
------------------------
- Repo: Aodaruma/coa_tools2
- Current branch: fix-support-blender-#84
- The `coa_tools2` folder is symlinked into Blender's addons directory, so any
  edits you make in the repo are immediately visible inside Blender.
- Blender 5.0 is already installed.
- I use "Blender Debugger for VSCode" (or an equivalent debug config) to run
  Blender from VS Code and debug Python add-ons.

Reference
---------
Use the official Blender 5.0 Python API release notes as the main reference
for API changes and breaking changes:

- Blender 5.0 Python API release notes:
  https://developer.blender.org/docs/release_notes/5.0/python_api/

Pay special attention to:
- Removal of dict-style access to properties defined with `bpy.props`:
  properties defined by `bpy.props` are no longer accessible via
  `obj['prop_name']`.
- New `get_transform` / `set_transform` accessors for `bpy.props`.
- BGL removal and GPU / EEVEE related changes.

Overall goal
------------
1. Make COA Tools 2 load and run on Blender 5.0 without errors.
2. Keep it working on the older supported versions (3.4+).
3. Keep the codebase clean and consistent with Blender's current best practices.
4. At the end, the add-on should:
   - Enable successfully in Blender 5.0.
   - Perform its basic workflows (creating sprite objects, switching 2D/3D
     view, playing animations, exporting, etc.) without tracebacks in the console.

PART 1: Known necessary edits
-----------------------------

Apply the following concrete edits first.

(1) Update supported Blender version in bl_info
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
File:
- `coa_tools2/__init__.py`

Current `bl_info` contains something like:

- `"blender": (3, 40, 0),`

Change it to target Blender 5.0:

- `"blender": (5, 0, 0),`

Keep the other metadata as-is (name, version, author, etc.).
If needed, also bump the add-on version from `(2, 0, 1)` to `(2, 0, 2)` to
indicate this compatibility update.

(2) Fix dict-style access to bpy.props-based properties
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Blender 5.0 no longer allows accessing `bpy.props`-defined properties via
dict-style syntax `obj['prop']`. Instead, the code must use attribute access
or, in complex cases, the new helpers described in the 5.0 release notes.

File:
- `coa_tools2/properties.py`

Spot A: SceneProperties.view / lock_view
- In `def lock_view(self, context):` there is code that uses
  `scene.coa_tools2["view"] = self["view"]` inside a loop over scenes.
- Here, both `"view"` keys refer to `EnumProperty` fields defined via
  `bpy.props` on `SceneProperties`.

Change logic to attribute access, roughly:

- Replace the dict-style assignment
    `scene.coa_tools2["view"] = self["view"]`
  with something equivalent to
    `scene.coa_tools2.view = self.view`

- Make sure the rest of the function continues to call the appropriate
  helpers:
    - `functions.set_view(scene, "3D" / "2D")`
    - `functions.set_middle_mouse_move(...)`
  and that the behavior (propagation of the view mode to other scenes)
  stays the same.

Spot B: SlotData.active / change_slot_mesh
- In `class SlotData(bpy.types.PropertyGroup)`, the method
  `def change_slot_mesh(self, context):` uses dict-style access:
    - `self["active"] = True`
    - and inside the loop, `slot["active"] = False` for other slots.
- Here `active` is also defined as a `BoolProperty` on `SlotData`.

Change this to attribute access:

- Use:
    - `self.active = True`
    - `slot.active = False`
  instead of the dict-style syntax.

After these edits, search through `coa_tools2/` for any remaining usage of
`["view"]`, `["active"]`, or similar dict-style access on property groups
that are defined with `bpy.props`. For each such occurrence:
- If the key corresponds to a declared property (BoolProperty, EnumProperty,
  etc.), switch to attribute access (`obj.prop_name`).
- If the key is meant to be a true custom property that is not declared
  via `bpy.props`, then leave it as `obj["custom_prop"]`, but double-check
  it is not covered by the new Blender 5.0 constraints.

PART 2: Systematic search for possible Blender 5.0 breakages
------------------------------------------------------------

After applying the known edits above, run a systematic search in the repo:

1. Search for dict-style property access patterns that might hit bpy.props:
   - Global text search for `["` inside `coa_tools2/*.py`.
   - For each hit, identify whether the LHS is:
     - A Blender RNA type with properties defined via `bpy.props`
       (`ObjectProperties`, `SceneProperties`, etc.), or
     - A plain IDProperty / custom property on an object, scene, etc.
   - If it is in the first category (bpy.props-defined), convert it to
     attribute access.
   - If it is a genuine custom property and Blender 5.0 still allows this,
     leave it as is.

2. Search for uses of removed or deprecated APIs:
   - Search for `bgl` imports: `import bgl`.
   - Search for `Image.bindcode`, or other APIs mentioned as removed in
     the Blender 5.x notes.
   - Search for EEVEE engine identifiers:
     - `BLENDER_EEVEE_NEXT`
   - If none of these exist, no changes are needed.
   - If any of these appear, update them to the recommended alternatives
     in the 5.0 Python API docs.

3. Search for `bpy.context.scene[...]` style access:
   - For example, `bpy.context.scene['something']` where `something`
     might be an RNA property rather than a custom property.
   - If it is pointing at a real property, change to attribute access,
     possibly using `bl_system_properties_get()` when the 5.0 docs recommend it.

PART 3: Debugging loop with Blender 5.0
---------------------------------------

Use the existing "Blender Debugger for VSCode" configuration (or create one)
so you can:

- Launch Blender 5.0 from VS Code with this add-on enabled,
  OR attach the debugger to a running Blender 5.0 process that has this
  `coa_tools2` add-on installed via the symlink.

Then perform the following manual test workflows while watching the console:

1. Enable the add-on
   - In Blender 5.0, open Preferences → Add-ons.
   - Enable "COA Tools 2".
   - If it fails, fix the traceback first (most critical path).

2. Basic sprite workflow
   - In a new file, try:
     - Creating a sprite object using COA Tools 2.
     - Switching between 2D and 3D view modes.
     - Adjusting z-value, alpha, modulate color.
   - Watch for errors coming from:
     - Handlers like `update_properties`, `set_shading`, etc.
   - For each error:
     - Navigate to the referenced line.
     - Consult the Blender 5.0 Python API docs when needed.
     - Apply minimal, compatible changes.
     - Re-run the same actions until they succeed without tracebacks.

3. Animation / NLA workflow
   - Create a simple animation using the COA animation collections.
   - Toggle between NLA and Action modes.
   - Make sure the properties involved (frame_start/frame_end, etc.)
     are still valid in Blender 5.0.

4. Exporters (DragonBones / Creature)
   - Trigger the exporter operators once to ensure they still register and
     run without immediate Python errors.
   - It is acceptable that the resulting JSON or assets are not fully
     validated, but there must be no Python exceptions.

During debugging:
- Prefer small, targeted fixes that keep backward compatibility.
- If an API has changed in a way that requires version branching, use:
    `if bpy.app.version >= (5, 0, 0):`
  to choose the appropriate code path.
- Keep code style consistent with the rest of the project.

PART 4: Final cleanup
---------------------

Once the add-on runs cleanly in Blender 5.0 and the main workflows pass
without errors:

1. Update metadata:
   - Ensure `bl_info['blender']` is `(5, 0, 0)`.
   - Optionally bump `bl_info['version']` to `(2, 0, 2)` or similar.

2. Code quality:
   - Make sure there are no leftover debug prints.
   - Optionally run a formatter (black) or linter (flake8) if configured
     in this project, but do not reformat the entire project unless it
     already follows such a standard.

3. Document the change:
   - Prepare a concise summary of what changed for Blender 5.0 support,
     especially mentioning:
       - Replacement of dict-style access to bpy.props-based properties.
       - Any API changes you had to apply.

4. Leave a short comment in the code near the updated spots referencing
   Blender 5.0 API changes if that helps future maintenance.

Your output for me
------------------
At the end, provide:

1. A short summary of changes you made (files and high-level description).
2. Any remaining caveats or TODOs.
3. If possible, a suggested commit message and PR title, e.g.:
   - Title: "Support Blender 5.0 in COA Tools 2"
   - Commit message: "Update bl_info for Blender 5.0 and replace dict-style
     access to bpy.props-defined properties with attribute access to comply
     with Blender 5.0 Python API breaking changes."

# COA Tools 2 dev document (overview)

## Table of Contents

- [COA Tools 2 dev document (overview)](#coa-tools-2-dev-document-overview)
  - [Table of Contents](#table-of-contents)
  - [Directory Structure](#directory-structure)
  - [Blender Addon (`/coa_tools2`)](#blender-addon-coa_tools2)
    - [Core Functionality](#core-functionality)
    - [Operators](#operators)
    - [UI Components](#ui-components)
    - [Animation System](#animation-system)
    - [Utility Classes](#utility-classes)
  - [Exporters](#exporters)
    - [Photoshop Exporter (`/Photoshop/BlenderExporter.jsx`)](#photoshop-exporter-photoshopblenderexporterjsx)
    - [GIMP Exporter (`/GIMP/coatools_exporter.py`)](#gimp-exporter-gimpcoatools_exporterpy)
    - [Krita Exporter (`/Krita/coa_tools2_exporter`)](#krita-exporter-kritacoa_tools2_exporter)
  - [Sample Files \& Assets](#sample-files--assets)
    - [Sample Project (`/samples/stip.blend`)](#sample-project-samplesstipblend)
    - [Sample Sprites (`/samples/sprites/`)](#sample-sprites-samplessprites)
    - [Sample JSON (`/samples/stip.json`)](#sample-json-samplesstipjson)

## Directory Structure

```
.
├── .gitignore
├── LICENSE
├── Pipfile
├── Pipfile.lock
├── README.md
├── assets/
│   ├── GIMP_exporter.png
│   ├── icon.png
│   ├── Krita_exporter.png
│   ├── logo_dark.png
│   ├── logo_white.png
│   └── PS_exporter.png
├── coa_tools2/
│   ├── __init__.py
│   ├── addon_updater_ops.py
│   ├── addon_updater.py
│   ├── constants.py
│   ├── developer_utils.py
│   ├── functions_draw.py
│   ├── functions.py
│   ├── outliner.py
│   ├── properties.py
│   ├── pyproject.toml
│   ├── ui.py
│   ├── coa_tools2_updater/
│   ├── icons/
│   └── operators/
│       ├── advanced_settings.py
│       ├── animation_handling.py
│       ├── change_alpha_mode.py
│       ├── convert_from_old.py
│       ├── create_ortho_cam.py
│       ├── create_spritesheet_preview.py
│       ├── create_sprite_object.py
│       ├── draw_bone_shape.py
│       ├── edit_armature.py
│       ├── edit_mesh.py
│       ├── edit_shapekey.py
│       ├── edit_weights.py
│       ├── export_json.py
│       ├── help_display.py
│       ├── import_sprites.py
│       ├── material_converter.py
│       ├── pie_menu.py
│       ├── slot_handling.py
│       ├── toggle_animation_area.py
│       ├── version_converter.py
│       └── view_sprites.py
├── GIMP/
│   ├── coatools_exporter.py
│   └── README.md
├── Godot/
│   └── coa_importer/
│       ├── import_dialog.tscn
│       ├── importer.gd
│       └── plugin.cfg
├── Krita/
│   ├── coa_tools2_exporter.desktop
│   └── coa_tools2_exporter/
│       ├── __init__.py
│       └── coa_tools2_docker.py
├── Photoshop/
│   └── BlenderExporter.jsx
└── samples/
    ├── stip.blend
    ├── stip.blend1
    ├── stip.json
    └── sprites/
        ├── Arm_L.png
        ├── Arm_R.png
        ├── Ear_L.png
        ├── Ear_R.png
        ├── Foot_L.png
        ├── Foot_R_01.png
        ├── Foot_R_02.png
        ├── Forearm_L.png
        ├── Forearm_R.png
        ├── Hand_L.png
        ├── Hand_R.png
        ├── Head.png
        ├── Hip.png
        ├── Leg_L.png
        ├── Leg_R.png
        ├── Shin_L.png
        ├── Shin_R.png
        ├── Tail_01.png
        ├── Tail_02.png
        ├── Tail_03.png
        ├── UpperBody_01.png
        └── UpperBody_02.png
```

## Blender Addon (`/coa_tools2`)

### Core Functionality

- **[Singleton_updater](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/addon_updater.py#L56)**: Manages addon updates and version control
- **[COATools2Preferences](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/__init__.py#L85)**: Handles addon preferences and settings
- **[COAOutliner](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/outliner.py#L118)**: Manages object hierarchy and visibility in outliner
- **[ObjectProperties](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/properties.py#L367)**: Stores and manages object-specific properties
- **[SceneProperties](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/properties.py#L424)**: Manages scene-wide properties and settings

### Operators

- **[COATOOLS2_OT_CreateSpriteObject](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/create_sprite_object.py#L47)**: Creates new sprite objects with proper setup
- **[COATOOLS2_OT_EditArmature](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/edit_armature.py#L49)**: Provides tools for armature creation and editing
- **[COATOOLS2_OT_EditMesh](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/edit_mesh.py#L203)**: Offers mesh editing and cleanup tools
- **[ExportToJson](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/export_json.py#L42)**: Exports sprite and animation data to JSON format
- **[COATOOLS2_OT_ImportSprites](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/import_sprites.py#L540)**: Imports sprite assets and sets up materials
- **[COATOOLS2_OT_ShapekeyAdd](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/edit_shapekey.py#L65)/[Remove](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/edit_shapekey.py#L98)/[Rename](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/edit_shapekey.py#L123)**: Manages shape key creation and editing
- **[COATOOLS2_OT_EditWeights](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/edit_weights.py#L53)**: Manages vertex weight painting

### UI Components

- **[COATOOLS2_PT_ObjectProperties](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/ui.py#L130)**: UI panel for object properties
- **[COATOOLS2_PT_Tools](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/ui.py#L423)**: Main tools panel
- **[COATOOLS2_UL_Outliner](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/outliner.py#L134)**: Custom outliner UI list
- **[COATOOLS2_MT_menu](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/pie_menu.py#L9)**: Main pie menu for quick access to tools

### Animation System

- **[COATOOLS2_OT_AddKeyframe](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/animation_handling.py#L46)**: Adds animation keyframes to selected properties
- **[COATOOLS2_OT_AddAnimationCollection](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/animation_handling.py#L259)**: Creates new animation collections
- **[COATOOLS2_OT_CreateNlaTrack](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/animation_handling.py#L454)**: Creates NLA tracks for animation management
- **[COATOOLS2_OT_BatchRender](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/animation_handling.py#L597)**: Handles batch rendering of animations

### Utility Classes

- **[BitbucketEngine](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/addon_updater.py#L1356)/[GithubEngine](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/addon_updater.py#L1384)/[GitlabEngine](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/addon_updater.py#L1409)**: Version control engines
- **[addon_updater_install_popup](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/addon_updater_ops.py#L56)**: Handles addon installation
- **[COATOOLS2_OT_VersionConverter](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/version_converter.py#L5)**: Converts between versions
- **[COATOOLS2_OT_ConvertMaterials](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/material_converter.py#L5)**: Converts materials between render engines

## Exporters

### Photoshop Exporter (`/Photoshop/BlenderExporter.jsx`)

- Exports Photoshop layers to Blender-compatible format
- Maintains layer hierarchy and naming
- Supports PSD file format with transparency
- Generates JSON metadata for sprite setup

### GIMP Exporter (`/GIMP/coatools_exporter.py`)

- Exports GIMP layers to Blender format
- Handles layer groups and visibility
- Supports XCF file format
- Generates optimized texture atlases

### Krita Exporter (`/Krita/coa_tools2_exporter`)

- Exports Krita documents with layer structure
- Maintains layer blending modes
- Supports KRA file format
- Includes metadata for animation setup

## Sample Files & Assets

### Sample Project (`/samples/stip.blend`)

- Demonstrates complete sprite setup
- Includes example animations
- Shows proper armature structure
- Contains material setup examples

### Sample Sprites (`/samples/sprites/`)

- Contains individual sprite parts
- Organized by body parts
- Includes multiple variations
- Demonstrates proper naming conventions

### Sample JSON (`/samples/stip.json`)

- Example of exported sprite data
- Shows proper JSON structure
- Includes animation data
- Contains material references

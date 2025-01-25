# COA Tools 2 Blender addon Specification

## Table of Contents

- [COA Tools 2 Blender addon Specification](#coa-tools-2-blender-addon-specification)
  - [Table of Contents](#table-of-contents)
  - [Core Features](#core-features)
  - [Core Features](#core-features-1)
    - [Sprite Management](#sprite-management)
    - [Armature System](#armature-system)
    - [Animation System](#animation-system)
    - [Material System](#material-system)
    - [Export System](#export-system)
  - [UI Components](#ui-components)
    - [Main Interface](#main-interface)
    - [Pie Menus](#pie-menus)
  - [Utility Features](#utility-features)
    - [Version Management](#version-management)
    - [Developer Tools](#developer-tools)

## Core Features

**Related Files**

- [coa_tools2/\_\_init\_\_.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/__init__.py)
- [coa_tools2/functions.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/functions.py)
- [coa_tools2/operators/\_\_init\_\_.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/__init__.py)

## Core Features

### Sprite Management

- **Sprite Object Creation**: Create and configure sprite objects with proper setup
- **Sprite Import**: Import sprite assets with automatic material setup
- **Sprite Organization**: Manage sprite hierarchy and visibility

**Related Files**

- [coa_tools2/operators/create_sprite_object.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/create_sprite_object.py)
- [coa_tools2/operators/import_sprites.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/import_sprites.py)
- [coa_tools2/operators/view_sprites.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/view_sprites.py)

### Armature System

- **Armature Creation**: Create and configure armatures for sprite animation
- **Bone Editing**: Edit bone properties and shapes
- **Weight Painting**: Manage vertex weights for mesh deformation

**Related Files**

- [coa_tools2/operators/edit_armature.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/edit_armature.py)
- [coa_tools2/operators/draw_bone_shape.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/draw_bone_shape.py)
- [coa_tools2/operators/edit_weights.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/edit_weights.py)

### Animation System

- **Keyframe Management**: Add and edit animation keyframes
- **Animation Collections**: Organize animations into collections
- **NLA Tracks**: Manage Non-Linear Animation tracks

**Related Files**

- [coa_tools2/operators/animation_handling.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/animation_handling.py)
- [coa_tools2/operators/toggle_animation_area.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/toggle_animation_area.py)
- [coa_tools2/operators/create_spritesheet_preview.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/create_spritesheet_preview.py)

### Material System

- **Material Conversion**: Convert materials between render engines
- **Alpha Mode Management**: Configure material transparency settings
- **Texture Handling**: Manage texture assignments and UV mapping

**Related Files**

- [coa_tools2/operators/material_converter.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/material_converter.py)
- [coa_tools2/operators/change_alpha_mode.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/change_alpha_mode.py)
- [coa_tools2/operators/edit_mesh.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/edit_mesh.py)

### Export System

- **JSON Export**: Export sprite and animation data to JSON format
- **Texture Atlas Generation**: Generate optimized texture atlases
- **External Tool Integration**: Export to Photoshop, GIMP, and Krita

**Related Files**

- [coa_tools2/operators/export_json.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/export_json.py)
- [coa_tools2/operators/exporter/export_dragonbones.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/exporter/export_dragonbones.py)
- [coa_tools2/operators/exporter/texture_atlas_generator.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/exporter/texture_atlas_generator.py)

## UI Components

**Related Files**

- [coa_tools2/ui.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/ui.py)
- [coa_tools2/outliner.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/outliner.py)
- [coa_tools2/properties.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/properties.py)

### Main Interface

- **Tool Panel**: Main tools and settings panel
- **Object Properties**: Custom properties panel for sprite objects
- **Outliner**: Custom outliner view for sprite hierarchy

**Related Files**

- [coa_tools2/ui.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/ui.py)
- [coa_tools2/properties.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/properties.py)

### Pie Menus

- **Quick Access**: Context-sensitive pie menus for common operations
- **Animation Controls**: Quick access to animation tools
- **Sprite Editing**: Fast access to sprite manipulation tools

**Related Files**

- [coa_tools2/operators/pie_menu.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/pie_menu.py)

## Utility Features

**Related Files**

- [coa_tools2/addon_updater.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/addon_updater.py)
- [coa_tools2/addon_updater_ops.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/addon_updater_ops.py)
- [coa_tools2/developer_utils.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/developer_utils.py)

### Version Management

- **Version Conversion**: Convert between different versions of the addon
- **Update System**: Manage addon updates and version control
- **Backup System**: Create and restore backups of project data

**Related Files**

- [coa_tools2/addon_updater.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/addon_updater.py)
- [coa_tools2/addon_updater_ops.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/addon_updater_ops.py)
- [coa_tools2/operators/version_converter.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/version_converter.py)

### Developer Tools

- **Debug Utilities**: Tools for debugging and testing
- **Performance Monitoring**: Monitor addon performance
- **Error Reporting**: Handle and report errors

**Related Files**

- [coa_tools2/developer_utils.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/developer_utils.py)
- [coa_tools2/operators/help_display.py](https://github.com/Aodaruma/coa_tools2/blob/master/coa_tools2/operators/help_display.py)

# COA Tools 2 Properties Reference

## Table of Contents

- [COA Tools 2 Properties Reference](#coa-tools-2-properties-reference)
  - [Table of Contents](#table-of-contents)
  - [Sprite Properties](#sprite-properties)
    - [Sprite Object Properties](#sprite-object-properties)
    - [Sprite Material Properties](#sprite-material-properties)
  - [Armature Properties](#armature-properties)
    - [Bone Properties](#bone-properties)
    - [Weight Painting Properties](#weight-painting-properties)
  - [Animation Properties](#animation-properties)
    - [Keyframe Properties](#keyframe-properties)
    - [Animation Collection Properties](#animation-collection-properties)
  - [Material Properties](#material-properties)
    - [Material Conversion Properties](#material-conversion-properties)
    - [Texture Properties](#texture-properties)
  - [Export Properties](#export-properties)
    - [JSON Export Properties](#json-export-properties)
    - [Texture Atlas Properties](#texture-atlas-properties)

## Sprite Properties

Properties related to sprite objects and their display in 2D animation.

### Sprite Object Properties
- **sprite_type**: `enum` - Type of sprite object  
  - Values: `['IMAGE', 'MESH', 'EMPTY']`
- **sprite_scale**: `float` - Scale factor for sprite display
- **sprite_offset**: `float[2]` - Offset position from bone origin
- **sprite_alpha**: `float` - Transparency value `(0.0 - 1.0)`

### Sprite Material Properties
Properties controlling sprite material appearance and blending.

- **material_type**: `enum` - Type of material  
  - Values: `['PRINCIPLED', 'EMISSION']`
- **blend_mode**: `enum` - Material blending mode  
  - Values: `['OPAQUE', 'ALPHA', 'ADD']`
- **use_shadeless**: `bool` - Enable/disable shading
- **texture_slot**: `int` - Index of active texture slot

## Armature Properties

Properties related to armature and bone configuration.

### Bone Properties
- **bone_shape**: `enum` - Display shape of bones  
  - Values: `['DEFAULT', 'CIRCLE', 'SQUARE']`
- **bone_size**: `float` - Display size of bones
- **use_deform**: `bool` - Enable/disable deformation
- **inherit_rotation**: `bool` - Enable/disable rotation inheritance

### Weight Painting Properties
Properties for weight painting and vertex group influence.

- **weight_value**: `float` - Current weight value `(0.0 - 1.0)`
- **weight_radius**: `float` - Brush radius for weight painting
- **weight_strength**: `float` - Brush strength for weight painting

## Animation Properties

Properties controlling animation playback and keyframing.

### Keyframe Properties
- **keyframe_type**: `enum` - Keyframe interpolation type  
  - Values: `['LINEAR', 'BEZIER', 'CONSTANT']`
- **keyframe_easing**: `enum` - Keyframe easing type
- **use_auto_keyframe**: `bool` - Enable/disable auto keyframing

### Animation Collection Properties
Properties for managing animation collections.

- **animation_name**: `string` - Name of animation collection
- **animation_length**: `int` - Total frames in animation
- **animation_fps**: `int` - Frame rate of animation
- **use_loop**: `bool` - Enable/disable animation looping

## Material Properties

Properties for material configuration and conversion.

### Material Conversion Properties
- **target_engine**: `enum` - Target rendering engine  
  - Values: `['CYCLES', 'EEVEE']`
- **preserve_alpha**: `bool` - Preserve alpha settings during conversion
- **convert_textures**: `bool` - Enable/disable texture conversion

### Texture Properties
Properties for texture mapping and UV settings.

- **texture_scale**: `float[2]` - UV scaling factors
- **texture_offset**: `float[2]` - UV offset values
- **use_mipmaps**: `bool` - Enable/disable mipmap generation

## Export Properties

Properties controlling export settings and output formats.

### JSON Export Properties
- **export_version**: `string` - JSON format version
- **export_scale**: `float` - Global export scale factor
- **export_path**: `string` - Output directory path
- **use_compression**: `bool` - Enable/disable JSON compression

### Texture Atlas Properties
Properties for texture atlas generation.

- **atlas_size**: `enum` - Maximum atlas texture size  
  - Values: `[1024, 2048, 4096]`
- **atlas_padding**: `int` - Padding between sprites in atlas
- **use_power_of_two**: `bool` - Force power-of-two texture sizes
- **atlas_format**: `enum` - Texture format  
  - Values: `['PNG', 'JPEG']`

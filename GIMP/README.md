# Using the GIMP exporter for COA Tools 


## Installation

### GIMP 3.0.x

Copy the `coatools_exporter_gimp3` folder into the GIMP plug-ins folder. The
folder name and Python file name must stay the same:

```
plug-ins/
  coatools_exporter_gimp3/
    coatools_exporter_gimp3.py
```

On Linux and macOS, make `coatools_exporter_gimp3.py` executable if GIMP does
not detect it.

### GIMP 2.x

Copy `coatools_exporter.py` into the GIMP plug-ins folder.

- on Linux this is /home/YOU/.gimp2.8/plug-ins/
- on Windows this is C:\Users\YOU\.gimp2.8\plug-ins

You should find it under File>Export to CoaTools... after restarting GIMP.

Note that the .gimp2.8 folder may be hidden.


## Usage

Start by drawing a character or object you want to animate using GIMP. Divide the movable parts up on different layers, like arms, legs, head and so on. If you want to use multiple frames for some parts, such as different mouth shapes, simply create a Layer Group with one child layer for each frame.

Run File>Export to CoaTools... and choose a destination folder and name and hit OK.

Each visible layer will be exported to a a separate .png file. The child layers of a Layer Group are exported as a single sprite sheet to a .png file. In addition a writes out a .json file use by CoaTools to put everything back together agani in Blender.

Note that the exporter will overwrite previous exports without asking, only outputting a warning in GIMP's Error Console.


## Limitations

The script uses the Layer>Autocrop Layer function in GIMP to crop the layers down to the size of it's content, rather than looking at the actual alpha channel of the layer. This works fine in almost all cases, except if your layer has a flat color all the way to edge of the image, such as a white border around an old style photograph. You can test this by simply running Layer>Autocrop Layer on your layer. A simple workaround for this would be to add a 1 pixel transparent border around your layer, or just add slight noise to the layer.

In addition nested Layer Groups are not supported.

The GIMP export has not been tested on OSX, but there is no reason why it shouldn't work.

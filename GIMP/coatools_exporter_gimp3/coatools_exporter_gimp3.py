#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# CoaTools Exporter for GIMP 3
#  based on the original GIMP 2 exporter by Ragnar Brynjulfsson

import json
import os
import sys
from math import ceil, floor, sqrt

import gi

gi.require_version("Gimp", "3.0")
from gi.repository import Gimp

gi.require_version("GimpUi", "3.0")
from gi.repository import GimpUi
from gi.repository import Gio
from gi.repository import GLib
from gi.repository import GObject


PLUGIN_PROC = "python-fu-coatools-gimp3"
PLUGIN_BINARY = "coatools_exporter_gimp3"
PLUGIN_LABEL = "Export to CoaTools..."


class Sprite:
    """Store file and transform data for each sprite."""

    def __init__(self, name):
        self.name = name
        self.path = "sprites/{name}".format(name=self.name)
        self.offset = [0.0, 0.0]
        self.position = [0.0, 0.0]
        self.opacity = 1.0
        self.z = 0
        self.tiles_x = 1
        self.tiles_y = 1

    def get_data(self):
        """Return sprite info as JSON encodable data."""
        return {
            "name": self.name,
            "type": "SPRITE",
            "resource_path": self.path,
            "node_path": self.name,
            "pivot_offset": [0.0, 0.0],
            "offset": self.offset,
            "position": self.position,
            "rotation": 0.0,
            "scale": [1.0, 1.0],
            "opacity": self.opacity,
            "z": self.z,
            "tiles_x": self.tiles_x,
            "tiles_y": self.tiles_y,
            "frame_index": 0,
            "children": [],
        }


class CoaExport:
    def __init__(self, image, path, name):
        self.name = name
        self.path = path
        self.original_image = image
        self.offset = [
            image.get_width() / 2 * -1,
            image.get_height() / 2,
        ]
        self.sprites = []
        self.json = os.path.join(self.path, self.name, "{name}.json".format(name=self.name))
        self.sprite_path = os.path.join(self.path, self.name, "sprites")
        self.export()

    def export(self):
        """Export visible root layers and layer groups to CoaSprite."""
        if os.path.isfile(os.path.join(self.path, self.name)):
            raise RuntimeError(
                "ABORTING!\nDestination is not a folder.\n {path}/{name}".format(
                    path=self.path, name=self.name
                )
            )
        if not os.access(self.path, os.W_OK):
            raise RuntimeError(
                "ABORTING!\nDestination is not writable.\n {path}".format(path=self.path)
            )
        self.mkdir()

        self.image = self.original_image.duplicate()
        self.image.undo_group_start()
        try:
            for layer in list(self.image.get_layers()):
                if not layer.get_visible():
                    continue

                self.autocrop_layer(layer)
                name = "{name}.png".format(name=layer.get_name())
                position = self.get_offsets(layer)
                z = 0 - self.image.get_item_position(layer)

                if layer.is_group():
                    children = [child for child in layer.get_children() if child.get_visible()]
                    if children:
                        self.sprites.append(
                            self.export_sprite_sheet(layer, name, position, z)
                        )
                else:
                    self.sprites.append(self.export_sprite(layer, name, position, z))

            self.write_json()
        finally:
            self.image.undo_group_end()
            self.image.delete()

    def autocrop_layer(self, layer):
        self.image.set_selected_layers([layer])
        self.image.autocrop_selected_layers(layer)

    def export_sprite(self, layer, name, position, z):
        """Export a single layer to PNG."""
        if not Gimp.edit_copy([layer]):
            raise RuntimeError("Failed to copy layer: {name}".format(name=layer.get_name()))

        image_tmp = Gimp.edit_paste_as_new_image()
        if image_tmp is None:
            raise RuntimeError("Failed to paste layer as new image: {name}".format(name=name))

        sprite_path = os.path.join(self.sprite_path, name)
        self.save_png(image_tmp, sprite_path)
        image_tmp.delete()

        sprite = Sprite(name)
        sprite.resource_path = "sprites/{name}".format(name=name)
        sprite.offset = self.offset
        sprite.position = position
        sprite.opacity = layer.get_opacity() / 100
        sprite.z = z
        return sprite

    def export_sprite_sheet(self, layer, name, position, z):
        """Export child layers of a layer group to a sprite sheet."""
        children = [
            child
            for child in layer.get_children()
            if child.get_visible() and not child.is_group()
        ]
        if not children:
            raise RuntimeError(
                "Layer group has no visible non-group frames: {name}".format(
                    name=layer.get_name()
                )
            )

        frames = len(children)
        gridx = max(1, floor(sqrt(frames)))
        gridy = ceil(frames / gridx)

        sheet_width = int(layer.get_width() * gridx)
        sheet_height = int(layer.get_height() * gridy)
        sheet = Gimp.Image.new(sheet_width, sheet_height, Gimp.ImageBaseType.RGB)
        background = Gimp.Layer.new(
            sheet,
            "background",
            sheet_width,
            sheet_height,
            Gimp.ImageType.RGBA_IMAGE,
            100,
            Gimp.LayerMode.NORMAL,
        )
        sheet.insert_layer(background, None, 0)

        col = 1
        row = 1
        name = "{name}.png".format(name=layer.get_name())
        layer_x, layer_y = self.get_offsets(layer)

        for child in children:
            self.autocrop_layer(child)
            child_x, child_y = self.get_offsets(child)
            x_delta = child_x - layer_x
            y_delta = child_y - layer_y

            if not Gimp.edit_copy([child]):
                raise RuntimeError(
                    "Failed to copy child layer: {name}".format(name=child.get_name())
                )

            pasted_layers = Gimp.edit_paste(background, False)
            if not pasted_layers:
                raise RuntimeError(
                    "Failed to paste child layer: {name}".format(name=child.get_name())
                )
            pasted_layer = pasted_layers[0]
            pasted_layer.set_offsets(
                int(layer.get_width() * (col - 1) + x_delta),
                int(layer.get_height() * (row - 1) + y_delta),
            )

            if col % gridx > 0:
                col += 1
            else:
                col = 1
                row += 1

        sheet.merge_visible_layers(Gimp.MergeType.EXPAND_AS_NECESSARY)
        sprite_path = os.path.join(self.sprite_path, name)
        self.save_png(sheet, sprite_path)
        sheet.delete()

        sprite = Sprite(name)
        sprite.resource_path = "sprites/{name}".format(name=name)
        sprite.offset = self.offset
        sprite.position = position
        sprite.opacity = layer.get_opacity() / 100
        sprite.z = z
        sprite.tiles_x = int(gridx)
        sprite.tiles_y = int(gridy)
        return sprite

    def mkdir(self):
        if not os.path.isdir(self.sprite_path):
            os.makedirs(self.sprite_path)

    def save_png(self, image, path):
        file = Gio.File.new_for_path(path)
        if not Gimp.file_save(Gimp.RunMode.NONINTERACTIVE, image, file, None):
            raise RuntimeError("Failed to save PNG: {path}".format(path=path))

    def write_json(self):
        sprites = [sprite.get_data() for sprite in self.sprites]
        data = {"name": self.name, "nodes": sprites}
        json_data = json.dumps(data, sort_keys=True, indent=4, separators=(",", ": "))
        with open(self.json, "w") as sprite_file:
            sprite_file.write(json_data)

    @staticmethod
    def get_offsets(layer):
        success, x, y = layer.get_offsets()
        if not success:
            return [0, 0]
        return [x, y]


class CoaToolsExporter(Gimp.PlugIn):
    def do_query_procedures(self):
        return [PLUGIN_PROC]

    def do_set_i18n(self, name):
        return False

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self, name, Gimp.PDBProcType.PLUGIN, self.run, None
        )
        procedure.set_image_types("RGB*, GRAY*, INDEXED*")
        procedure.set_menu_label(PLUGIN_LABEL)
        procedure.add_menu_path("<Image>/File/Export")
        procedure.set_documentation(
            "Export layered characters and objects to COA Tools.",
            "Exports visible root layers and layer groups to PNG sprites and a COA Tools JSON file.",
            name,
        )
        procedure.set_attribution(
            "Ragnar Brynjulfsson, Aodaruma",
            "Ragnar Brynjulfsson",
            "2016, 2026",
        )
        procedure.add_file_argument(
            "path",
            "Export to",
            "Folder where the COA Tools export folder will be created.",
            Gimp.FileChooserAction.SELECT_FOLDER,
            False,
            Gio.File.new_for_path(os.getcwd()),
            GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "name",
            "Name",
            "Export folder and JSON file name.",
            "enter_name",
            GObject.ParamFlags.READWRITE,
        )
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        if run_mode == Gimp.RunMode.INTERACTIVE:
            GimpUi.init(PLUGIN_BINARY)
            dialog = GimpUi.ProcedureDialog.new(procedure, config, PLUGIN_LABEL)
            dialog.fill(["path", "name"])
            if not dialog.run():
                dialog.destroy()
                return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)
            dialog.destroy()

        folder = config.get_property("path")
        name = config.get_property("name")
        path = folder.get_path() if folder is not None else ""

        if not name:
            return self.error_return(procedure, "Please enter a file name.")
        if not path:
            return self.error_return(procedure, "Please select an export folder.")

        try:
            CoaExport(image, path, name)
        except Exception as exc:
            return self.error_return(procedure, str(exc))

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)

    @staticmethod
    def error_return(procedure, message):
        Gimp.message(message)
        return procedure.new_return_values(
            Gimp.PDBStatusType.EXECUTION_ERROR, GLib.Error(message)
        )


Gimp.main(CoaToolsExporter.__gtype__, sys.argv)

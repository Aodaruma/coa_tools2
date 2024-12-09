#target Photoshop

var doc = app.activeDocument;
var layers = doc.layers;
var coords = [];
var exporter_version = "v2.0.0";

//Save Options for PNGs
var options = new ExportOptionsSaveForWeb();
options.format = SaveDocumentType.PNG;
options.PNG8 = false;
options.transparency = true;
options.optimized = true;

function deselect_all_layers() {
    var desc01 = new ActionDescriptor();
    var ref01 = new ActionReference();
    ref01.putEnumerated(charIDToTypeID('Lyr '), charIDToTypeID('Ordn'), charIDToTypeID('Trgt'));
    desc01.putReference(charIDToTypeID('null'), ref01);
    executeAction(stringIDToTypeID('selectNoLayers'), desc01, DialogModes.NO);
}

function write_dict_entry(tabs, key, value, comma) {
    if (typeof (comma) === 'undefined') var comma = true;

    var line = '';
    for (var i = 0; i < tabs * 4; i++) {
        line += ' ';
    }
    line += '"' + key + '": ';

    if (typeof (value) == "string") {
        line += '"';
    } else if (typeof (value) == "object") {
        line += '[';
    }

    line += value;

    if (typeof (value) == "string") {
        line += '"';
    } else if (typeof (value) == "object") {
        line += ']';
    }
    if (comma) {
        line += ',';
    }
    return line;
}

function write_line(tabs, text) {
    var line = '';
    for (var i = 0; i < tabs * 4; i++) {
        line += ' ';
    }
    line += text;
    return line;
}

function save_coords(center_sprites, export_path, export_name) {
    if (center_sprites == true) {
        var offset = [doc.width.as("px") * -.5 + ',' + doc.height.as("px") * .5];
    } else {
        var offset = [0, 0];
    }

    var json_file = new File(export_path + "/" + export_name + ".json");
    json_file.encoding = "UTF8";
    json_file.open('w');

    json_file.writeln(write_line(tabs = 0, '{'));
    json_file.writeln(write_dict_entry(tabs = 1, "name", export_name));
    json_file.writeln(write_line(tabs = 1, '"nodes": ['));

    for (var i = 0; i < coords.length; i++) {
        json_file.writeln('        {');
        json_file.writeln(write_dict_entry(tabs = 3, key = "name", value = coords[i][0]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "type", value = "SPRITE"));
        json_file.writeln(write_dict_entry(tabs = 3, key = "node_path", value = coords[i][0]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "resource_path", value = "sprites/" + coords[i][0]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "pivot_offset", value = [0, 0]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "offset", value = offset));
        json_file.writeln(write_dict_entry(tabs = 3, key = "position", value = [coords[i][1][0], coords[i][1][2]]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "rotation", value = 0.0));
        json_file.writeln(write_dict_entry(tabs = 3, key = "scale", value = [1.0, 1.0]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "opacity", value = 1.0));
        json_file.writeln(write_dict_entry(tabs = 3, key = "z", value = coords[i][1][1]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "tiles_x", value = coords[i][2][0]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "tiles_y", value = coords[i][2][1]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "frame_index", value = 0));
        json_file.writeln(write_dict_entry(tabs = 3, key = "children", value = []));
        json_file.writeln(write_dict_entry(tabs = 3, key = "blend_mode", value = coords[i][3], comma = false));
        if (i < coords.length - 1) {
            json_file.writeln(write_line(tabs = 2, '},'));
        } else {
            json_file.writeln(write_line(tabs = 2, '}'));
        }
    }
    json_file.writeln(write_line(tabs = 1, ']'));
    json_file.writeln(write_line(tabs = 0, '}'));
    json_file.close();
}

function flatten_layer(document, name) {
    // =======================================================
    var idMk = charIDToTypeID("Mk  ");
    var desc54 = new ActionDescriptor();
    var idnull = charIDToTypeID("null");
    var ref47 = new ActionReference();
    var idlayerSection = stringIDToTypeID("layerSection");
    ref47.putClass(idlayerSection);
    desc54.putReference(idnull, ref47);
    var idFrom = charIDToTypeID("From");
    var ref48 = new ActionReference();
    var idLyr = charIDToTypeID("Lyr ");
    var idOrdn = charIDToTypeID("Ordn");
    var idTrgt = charIDToTypeID("Trgt");
    ref48.putEnumerated(idLyr, idOrdn, idTrgt);
    desc54.putReference(idFrom, ref48);
    var idlayerSectionStart = stringIDToTypeID("layerSectionStart");
    desc54.putInteger(idlayerSectionStart, 161);
    var idlayerSectionEnd = stringIDToTypeID("layerSectionEnd");
    desc54.putInteger(idlayerSectionEnd, 162);
    var idNm = charIDToTypeID("Nm  ");
    desc54.putString(idNm, name);
    executeAction(idMk, desc54, DialogModes.NO);
    // =======================================================
    var idMrgtwo = charIDToTypeID("Mrg2");
    executeAction(idMrgtwo, undefined, DialogModes.NO);
    document.activeLayer.name = name;
}

function extend_document_size(size_x, size_y) {
    // =======================================================
    var idCnvS = charIDToTypeID("CnvS");
    var desc8 = new ActionDescriptor();
    var idWdth = charIDToTypeID("Wdth");
    var idPxl = charIDToTypeID("#Pxl");
    desc8.putUnitDouble(idWdth, idPxl, size_x);
    var idHght = charIDToTypeID("Hght");
    var idPxl = charIDToTypeID("#Pxl");
    desc8.putUnitDouble(idHght, idPxl, size_y);
    var idHrzn = charIDToTypeID("Hrzn");
    var idHrzL = charIDToTypeID("HrzL");
    var idLeft = charIDToTypeID("Left");
    desc8.putEnumerated(idHrzn, idHrzL, idLeft);
    var idVrtc = charIDToTypeID("Vrtc");
    var idVrtL = charIDToTypeID("VrtL");
    var idTop = charIDToTypeID("Top ");
    desc8.putEnumerated(idVrtc, idVrtL, idTop);
    executeAction(idCnvS, desc8, DialogModes.NO);
}

function is_same_layer(layer1, layer2) {
    // check name and the parents are same
    if (layer1.name != layer2.name)
        return false;

    var layer1_parents = get_parent_layersets(layer1);
    var layer2_parents = get_parent_layersets(layer2);

    if (layer1_parents.length != layer2_parents.length)
        return false;

    for (var i = 0; i < layer1_parents.length; i++) {
        if (layer1_parents[i].name != layer2_parents[i].name)
            return false;
    }

    // TODO: since photoshop allows same name layers(layersets) in the same layerset level, we need to check unique id of the layer whenever we compare in another document

    return true;
}

function duplicate_into_new_doc(choose_layer_type) {
    const layer_types = {
        selected: "selected",
        visible: "visible",
    }
    choose_layer_type = choose_layer_type || layer_types.selected;

    var sourceDoc = app.activeDocument;
    var layers = sourceDoc.layers;

    // search layers for selected or visible layers
    var target_layers = [];
    var search_queue = [];
    for (var i = 0; i < layers.length; i++)
        search_queue.push(layers[i]);

    while (search_queue.length > 0) {
        var layer = search_queue.pop();
        if (layer.typename == "LayerSet") {
            for (var j = 0; j < layer.layers.length; j++)
                search_queue.push(layer.layers[j]);
        } else {
            if (
                // (choose_layer_type == layer_types.all) ||
                (choose_layer_type == layer_types.visible && layer.visible === true) ||
                (choose_layer_type == layer_types.selected && layer.selected === true)
            ) {
                // layer.duplicate(newDoc, ElementPlacement.PLACEATEND);
                // duplicated_num++;
                target_layers.push(layer);
            }
        }
    }

    // if no layers were duplicated, throw an error
    if (target_layers.length == 0) {
        throw new Error("No layers were duplicated. Please select or set show at least one layer.");
    }

    // create new document
    var newDoc = app.documents.add(sourceDoc.width, sourceDoc.height, sourceDoc.resolution, "dupli_layers_doc", NewDocumentMode.RGB, DocumentFill.TRANSPARENT);
    newDocLayers = newDoc.layers;

    // switch back to source document
    app.activeDocument = sourceDoc;

    // duplicate all layers into new document, and delete them which is not in target_layers array (if locked, unlock it and delete)
    for (var i = 0; i < layers.length; i++) {
        var layer = layers[i];
        layer.duplicate(newDoc, ElementPlacement.PLACEATEND);
    }

    // switch back to new document
    app.activeDocument = newDoc;

    var search_queue = [];
    for (var i = 0; i < newDocLayers.length; i++)
        search_queue.push(newDocLayers[i]);

    while (search_queue.length > 0) {
        var layer = search_queue.pop();
        if (layer.allLocked == true) {
            layer.allLocked = false;
        }
        if (layer.typename == "LayerSet") {
            for (var j = 0; j < layer.layers.length; j++)
                search_queue.push(layer.layers[j]);
        } else {
            var is_target_layer = false;
            for (var j = 0; j < target_layers.length; j++) {
                var target_layer = target_layers[j];
                // if (layer.id == target_layer.id) {
                if (is_same_layer(layer, target_layer)) {
                    is_target_layer = true;
                    break;
                }
            }
            if (is_target_layer === false)
                layer.remove();
        }
    }

    // delete top layer (empty layer cteaetd by default)
    // newDocLayers[0].remove();
}

function get_parent_layersets(layer) {
    var parent_layersets = [];
    var parent_layer = layer.parent;
    while (parent_layer.typename == "LayerSet") {
        parent_layersets.push(parent_layer);
        parent_layer = parent_layer.parent;
    }
    return parent_layersets;
}

function get_target_layers(layers) {
    var target_layers = [];
    for (var i = 0; i < layers.length; i++) {
        var layer = layers[i];
        if (layer.typename == "LayerSet") {
            target_layers = target_layers.concat(get_target_layers(layer.layers));
        } else {
            target_layers.push(layer);
        }
    }
    return target_layers;
}

function process_prepending_layerset_name(layer, layer_name, is_omit_layer_name_if_only_one) {
    var parent_layersets = get_parent_layersets(layer);
    for (var j = 0; j < parent_layersets.length; j++) {
        layer_name = parent_layersets[j].name + "." + layer_name;
    }
    if (is_omit_layer_name_if_only_one == true) {
        // delete latest layer name
        var layer_name_split = layer_name.split(".");
        if (layer_name_split.length > 1) {
            layer_name = layer_name_split.slice(0, -1).join(".");
        }
    }
    return layer_name;
}

function process_reorder_layerset_name(layer_name) {
    // check the name contains these patterns and reorder them to the end of the name (name + sequence_number + mirror_name)
    // - sequence numbers (e.g. "1", "002", "03")
    // - mirror names (e.g. "left", "right", "L", "R")

    var sequence_regex = new RegExp(/\.?(\d+)/);
    var sequence_match = layer_name.match(sequence_regex);
    if (sequence_match != null) {
        var sequence_number = sequence_match[1];
        layer_name = layer_name.replace("." + sequence_number, "");
        // sequence_number must be padded with zeros to 3 digits
        // layer_name += "." + sequence_number.padStart(3, "0"); // cant use; not supported in extended script (locked at ES3)
        var seq_length = sequence_number.length;
        var seq_padding = 3 - seq_length;
        var seq_padding_str = "";
        if (seq_padding < 0) {
            seq_padding = 0;
        }
        for (var p = 0; p < seq_padding; p++) {
            seq_padding_str += "0";
        }
        layer_name += "." + seq_padding_str + sequence_number;
    }

    var mirror_names = ["left", "right", "L", "R", "Left", "Right"];
    for (var m = 0; m < mirror_names.length; m++) {
        var mname = mirror_names[m];
        if (layer_name.indexOf(mname) != -1) {
            layer_name = layer_name.replace("." + mname, "");
            layer_name += "." + mname;
        }
    }

    return layer_name;
}

function export_sprites(
    export_path,
    export_name,
    crop_to_dialog_bounds,
    center_sprites,
    crop_layers,
    export_json,
    layer_type,
    is_layerset_automerge,
    is_prepending_layerset_name,
    is_reorder_layerset_name,
    is_set_composite_mode_to_normal,
    is_omit_layer_name_if_only_one
) {
    // check
    if (export_path == "") {
        alert("Please select a folder to export the sprites.");
        return;
    }
    if (export_name == "") {
        alert("Please enter a name for the export.");
        return;
    }

    var layers = get_target_layers(doc.layers);
    if (layers.length == 0) {
        alert("No layers were found to export.");
        return;
    }
    var unique_layer_names = {};
    for (var i = 0; i < layers.length; i++) {
        var layer = layers[i];
        var layer_name = layer.name;
        if (is_prepending_layerset_name == true)
            layer_name = process_prepending_layerset_name(layer, layer_name, is_omit_layer_name_if_only_one);
        if (is_reorder_layerset_name == true)
            layer_name = process_reorder_layerset_name(layer_name);

        if (unique_layer_names[layer_name] == undefined) {
            unique_layer_names[layer_name] = 1;
        } else {
            unique_layer_names[layer_name] += 1;
        }
    }
    var duplicated_layer_names = [];
    for (var key in unique_layer_names) {
        if (unique_layer_names[key] > 1) {
            duplicated_layer_names.push(key);
        }
    }
    if (duplicated_layer_names.length > 0) {
        alert("There are multiple layers with the same name:\n\n" + duplicated_layer_names.join("\n") +
            "\n\n Please rename them to be unique.");
        return;
    }

    // initalize
    var init_units = app.preferences.rulerUnits;
    app.preferences.rulerUnits = Units.PIXELS;
    // check if folder exists. if not, create one
    var export_folder = new Folder(export_path + "/sprites");
    if (!export_folder.exists) export_folder.create();

    var tmp_layers = doc.layers;

    try {
        duplicate_into_new_doc(layer_type);
        var dupli_doc = app.activeDocument;
    } catch (e) {
        alert(e);
        // delete tmp doc if it exists
        if (dupli_doc) dupli_doc.close(SaveOptions.DONOTSAVECHANGES);
        win.close();
        return;
    }

    /// deselect all layers and select first with this hack of adding a new layer and then deleting it again
    var testlayer = dupli_doc.artLayers.add();
    testlayer.remove();
    ///

    // flatten layers
    if (is_layerset_automerge == true) {
        for (var i = 0; i < dupli_doc.layers.length; i++) {
            var layer = dupli_doc.layers[i];
            dupli_doc.activeLayer = layer;
            if (layer.name.indexOf("--sprites") == -1) {
                flatten_layer(dupli_doc, layer.name);
            } else if (layer.name.indexOf("--sprites") != -1 && layer.typename == "LayerSet") {
                for (var j = 0; j < layer.layers.length; j++) {
                    var sub_layer = layer.layers[j];
                    dupli_doc.activeLayer = sub_layer;
                    flatten_layer(dupli_doc, sub_layer.name);
                }
            }
        }
    }


    var target_layers = get_target_layers(dupli_doc.layers);
    for (var i = 0; i < target_layers.length; i++) {
        // deselect layers
        var layer = target_layers[i];

        dupli_doc.activeLayer = layer;
        var bounds = [layer.bounds[0].as("px"), layer.bounds[1].as("px"), layer.bounds[2].as("px"), layer.bounds[3].as("px")];
        var bounds_width = bounds[2] - bounds[0];
        var bounds_height = bounds[3] - bounds[1];

        var layer_name = String(layer.name).split(' ').join('_');
        // get layer margin settings
        var margin = 0;
        if (layer_name.indexOf("m=") != -1) {
            var margin_str_index = layer_name.indexOf("m=") + 2;
            margin = Math.ceil(layer_name.substring(margin_str_index, layer_name.length));
        }
        var layer_pos = Array(bounds[0] - margin, -i, bounds[1] - margin);
        var tmp_doc = app.activeDocument;
        var tile_size = [1, 1];
        var tmp_doc = app.documents.add(dupli_doc.width, dupli_doc.height, dupli_doc.resolution, layer_name, NewDocumentMode.RGB, DocumentFill.TRANSPARENT);

        var composite_mode = "" + layer.blendMode;
        composite_mode = composite_mode.replace("BlendMode.", "");

        // duplicate layer into new doc and crop to layerbounds with margin
        app.activeDocument = dupli_doc;
        layer.duplicate(tmp_doc, ElementPlacement.INSIDE);
        app.activeDocument = tmp_doc;
        var crop_bounds = bounds;

        if (crop_to_dialog_bounds == true) {
            if (crop_bounds[0] < 0) { crop_bounds[0] = 0 };
            if (crop_bounds[1] < 0) { crop_bounds[1] = 0 };
            if (crop_bounds[2] > doc.width.as("px")) { crop_bounds[2] = doc.width.as("px") };
            if (crop_bounds[3] > doc.height.as("px")) { crop_bounds[3] = doc.height.as("px") };
        }

        crop_bounds[0] -= margin;
        crop_bounds[1] -= margin;
        crop_bounds[2] += margin;
        crop_bounds[3] += margin;

        if (crop_layers == true) {
            tmp_doc.crop(crop_bounds);
        }

        // check if layer is a group with sprite setting
        if (layer_name.indexOf("--sprites") != -1) {
            var keyword_pos = layer_name.indexOf("--sprites");
            var sprites = tmp_doc.layers[0].layers;
            var sprite_count = sprites.length;
            if (column_str_index = layer_name.indexOf("c=") != -1) {
                var column_str_index = layer_name.indexOf("c=") + 2;
                var columns = Math.ceil(layer_name.substring(column_str_index, layer_name.length));
            } else {
                var columns = Math.ceil((Math.sqrt(sprite_count)));
            }
            tile_size = [columns, Math.ceil(sprite_count / columns)];
            var k = 0;
            for (var j = 0; j < sprites.length; j++) {
                if (j > 0 && j % columns == 0) {
                    k = k + 1;
                }
                sprites[j].translate(tmp_doc.width * (j % columns), tmp_doc.height * k);
            }


            extend_document_size(tmp_doc.width * columns, tmp_doc.height * (k + 1));
        }

        // create layer name -> cut off commands
        var keyword_pos = 100000;
        if (layer_name.indexOf("--sprites") != -1) {
            if (layer_name.indexOf("--sprites") < keyword_pos) {
                keyword_pos = layer_name.indexOf("--sprites");
            }
        }
        if (layer_name.indexOf("c=") != -1) {
            if (layer_name.indexOf("c=") < keyword_pos) {
                keyword_pos = layer_name.indexOf("c=");
            }
        }
        if (layer_name.indexOf("m=") != -1) {
            if (layer_name.indexOf("m=") < keyword_pos) {
                keyword_pos = layer_name.indexOf("m=");
            }
        }
        if (layer_name[keyword_pos - 1] == "_") {
            layer_name = layer_name.substring(0, keyword_pos - 1);
        } else {
            layer_name = layer_name.substring(0, keyword_pos);
        }

        // get layerset name that the layer is belonging to
        if (is_prepending_layerset_name == true)
            layer_name = process_prepending_layerset_name(layer, layer_name, is_omit_layer_name_if_only_one);

        if (is_reorder_layerset_name == true)
            layer_name = process_reorder_layerset_name(layer_name);

        // set all layer composite mode to normal
        if (is_set_composite_mode_to_normal == true) {
            for (var j = 0; j < tmp_doc.layers.length; j++) {
                var layer = tmp_doc.layers[j];
                tmp_doc.activeLayer = layer;
                layer.blendMode = BlendMode.NORMAL;
            }
        }

        // do save stuff
        tmp_doc.exportDocument(File(export_path + "/sprites/" + layer_name + ".png"), ExportType.SAVEFORWEB, options);

        // store coords
        coords.push([layer_name + ".png", layer_pos, tile_size, composite_mode]);

        // close tmp doc again
        tmp_doc.close(SaveOptions.DONOTSAVECHANGES);
    }
    dupli_doc.close(SaveOptions.DONOTSAVECHANGES);

    if (export_json == true) {
        save_coords(center_sprites, export_path, export_name);
    }
    app.preferences.rulerUnits = init_units;
}

function export_button() {

    win.export_name.text = String(win.export_name.text).split(' ').join('_');
    app.activeDocument.info.caption = win.export_path.export_path.text;
    app.activeDocument.info.captionWriter = win.export_name.export_name.text;
    // select_options
    app.activeDocument.info.layerType = win.options.ops01.select_options.layer_type_group.layer_type.selection.text;
    // convert_options
    app.activeDocument.info.cropLayers = win.options.ops01.convert_options.crop_layers.value;
    app.activeDocument.info.limitLayer = win.options.ops01.convert_options.limit_layer.value;
    app.activeDocument.info.isLayersetAutomerge = win.options.ops01.convert_options.is_layerset_automerge.value;
    app.activeDocument.info.isSetCompositeModeToNormal = win.options.ops01.convert_options.is_set_composite_mode_to_normal.value;
    // naming_options
    app.activeDocument.info.isPrependingLayersetName = win.options.ops02.naming_options.is_prepending_layerset_name.value;
    app.activeDocument.info.isReorderLayersetName = win.options.ops02.naming_options.is_reorder_layerset_name.value;
    app.activeDocument.info.isOmitLayerNameIfOnlyOne = win.options.ops02.naming_options.is_omit_layer_name_if_only_one.value;
    // export_options
    app.activeDocument.info.exportJson = win.options.ops02.export_options.export_json.value;
    app.activeDocument.info.centerSprites = win.options.ops02.export_options.center_sprites.value;

    app.activeDocument.suspendHistory(
        "Export selected Sprites",
        "export_sprites("
        + "win.export_path.export_path.text,"
        + "win.export_name.export_name.text,"
        + "win.options.ops01.convert_options.limit_layer.value,"
        + "win.options.ops02.export_options.center_sprites.value,"
        + "win.options.ops01.convert_options.crop_layers.value,"
        + "win.options.ops02.export_options.export_json.value,"
        + "win.options.ops01.select_options.layer_type_group.layer_type.selection.text,"
        + "win.options.ops01.convert_options.is_layerset_automerge.value,"
        + "win.options.ops02.naming_options.is_prepending_layerset_name.value,"
        + "win.options.ops02.naming_options.is_reorder_layerset_name.value,"
        + "win.options.ops01.convert_options.is_set_composite_mode_to_normal.value,"
        + "win.options.ops02.naming_options.is_omit_layer_name_if_only_one.value"
        + ")"
    );
    win.close();
}

function path_button() {
    var folder_path = Folder.selectDialog("Select Place to save");
    if (folder_path != null) {
        win.export_path.export_path.text = folder_path;
        app.activeDocument.info.caption = folder_path;
    }
}


var res = "dialog { \
    text: 'COA tools2 - Json Exporter " + exporter_version + "', \
    alignChildren: 'fill', \
    export_name: Group { \
        orientation: 'row', \
        alignChildren: 'left', \
        sText: StaticText { text: 'Export Name:', alignment: 'left', preferredSize: [70, 20] }, \
        export_name: EditText { preferredSize: [320, 20] } \
    }, \
    export_path: Group { \
        orientation: 'row', \
        alignChildren: 'left', \
        sText: StaticText { text: 'Export Path:', alignment: 'left', preferredSize: [70, 20] }, \
        export_path: EditText { preferredSize: [230, 20] }, \
        button_path: Button { text: 'select' } \
    }, \
    options: Group { \
        orientation: 'row', \
        align: 'center', \
        alignChildren: 'fill', \
        ops01: Group { \
            orientation: 'column', \
            align: 'top', \
            select_options: Panel { \
                text: 'Select Options', \
                orientation: 'column', \
                alignChildren: 'left', \
                layer_type_group: Group { \
                    orientation: 'row', \
                    sText: StaticText { text: 'Layer Type:', alignment: 'left' }, \
                    layer_type: DropDownList { text: 'Layer Type:', preferredSize: [100, 20] }, \
                }, \
            }, \
            convert_options: Panel { \
                text: 'Convert Options', \
                orientation: 'column', \
                alignChildren: 'left', \
                crop_layers: Checkbox { text: 'Crop Layers', value: true}, \
                limit_layer: Checkbox { text: 'Crop layer by Document size', value: true }, \
                is_layerset_automerge: Checkbox { text: 'Merge Layersets', value: true }, \
                is_set_composite_mode_to_normal: Checkbox { text: 'Set Composite Mode to Normal', value: true } \
            } \
        }, \
        ops02: Group { \
            orientation: 'column', \
            align: 'top', \
            naming_options: Panel { \
                text: 'Naming Options', \
                orientation: 'column', \
                alignChildren: 'left', \
                is_prepending_layerset_name: Checkbox { text: 'Prepend Layerset Name', value: true }, \
                is_reorder_layerset_name: Checkbox { text: 'Reorder Layerset Name', value: true } \
                is_omit_layer_name_if_only_one: Checkbox { text: 'Omit Layer Name if alone', value: true }, \
            }, \
            export_options: Panel { \
                text: 'Export Options', \
                orientation: 'column', \
                alignChildren: 'left', \
                export_json: Checkbox { text: 'Export Json File', value: true } \
                center_sprites: Checkbox { text: 'Center Sprites in Blender', value: true }, \
            } \
        } \
    }, \
    buttons : Group { \
        orientation: 'row', \
        alignment: 'right', \
        export_button: Button { text: 'Export', preferredSize: [100, 20], properties: { name: 'ok' } }, \
        cancel_button: Button { text: 'Cancel', preferredSize: [100, 20], properties: { name: 'cancel' } } \
    } \
}";

var win = new Window(res);

win.export_path.export_path.text = app.activeDocument.info.caption || "";
win.export_path.button_path.onClick = path_button;
win.export_name.export_name.text = app.activeDocument.info.captionWriter || app.activeDocument.name;

win.options.ops01.select_options.layer_type_group.layer_type.add("item", "selected");
win.options.ops01.select_options.layer_type_group.layer_type.add("item", "visible");
win.options.ops01.select_options.layer_type_group.layer_type.selection = app.activeDocument.info.layerType || "selected";

win.options.ops01.convert_options.crop_layers.value = app.activeDocument.info.cropLayers || true;
win.options.ops01.convert_options.crop_layers.onClick = function () {
    if (this.value === true) {
        this.parent.limit_layer.enabled = true;
    } else {
        this.parent.limit_layer.enabled = false;
    }
}
win.options.ops01.convert_options.limit_layer.value = app.activeDocument.info.limitLayer || true;
win.options.ops01.convert_options.is_layerset_automerge.value = app.activeDocument.info.isLayersetAutomerge || false;
win.options.ops01.convert_options.is_set_composite_mode_to_normal.value = app.activeDocument.info.isSetCompositeModeToNormal || true;

win.options.ops02.naming_options.is_prepending_layerset_name.value = app.activeDocument.info.isPrependingLayersetName || false;
win.options.ops02.naming_options.is_reorder_layerset_name.value = app.activeDocument.info.isReorderLayersetName || false;
win.options.ops02.naming_options.is_omit_layer_name_if_only_one.value = app.activeDocument.info.isOmitLayerNameIfOnlyOne || false;
win.options.ops02.naming_options.is_prepending_layerset_name.onClick = function () {
    if (this.value === true) {
        this.parent.is_omit_layer_name_if_only_one.enabled = true;
    } else {
        this.parent.is_omit_layer_name_if_only_one.enabled = false;
    }
}
// set is_omit_layer_name_if_only_one.enabled to is_prepending_layerset_name in initial state
win.options.ops02.naming_options.is_omit_layer_name_if_only_one.enabled = win.options.ops02.naming_options.is_prepending_layerset_name.value;

win.options.ops02.export_options.export_json.value = app.activeDocument.info.exportJson || true;
win.options.ops02.export_options.center_sprites.value = app.activeDocument.info.centerSprites || true;
win.options.ops02.export_options.export_json.onClick = function () {
    if (this.value === true) {
        this.parent.center_sprites.enabled = true;
    } else {
        this.parent.center_sprites.enabled = false;
    }
}

win.buttons.export_button.onClick = export_button;
win.buttons.cancel_button.onClick = function () { win.close(); }

win.center();
win.show();

#target Photoshop

var doc = app.activeDocument;
var layers = doc.layers;
var coords = [];
var exporter_version = "v2.0.1";

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

function create_export_progress_dialog(total_count) {
    var progress_win = new Window("palette", "COA Tools2 Export Progress");
    progress_win.orientation = "column";
    progress_win.alignChildren = "fill";

    var status_text = progress_win.add("statictext", undefined, "Preparing export...");
    var count_text = progress_win.add("statictext", undefined, "0 / " + total_count);
    var progress_bar = progress_win.add("progressbar", undefined, 0, 100);
    progress_bar.preferredSize = [360, 16];
    var percent_text = progress_win.add("statictext", undefined, "0%");

    progress_win.center();
    progress_win.show();

    return {
        window: progress_win,
        status_text: status_text,
        count_text: count_text,
        progress_bar: progress_bar,
        percent_text: percent_text,
        total_count: total_count,
        last_update_time_ms: 0,
        min_update_interval_ms: 150
    };
}

function update_export_progress_dialog(progress_ctx, completed_count, status_message, force_update) {
    if (!progress_ctx) {
        return;
    }
    if (typeof force_update === "undefined") {
        force_update = false;
    }

    var now_ms = (new Date()).getTime();
    if (
        force_update === false &&
        progress_ctx.last_update_time_ms > 0 &&
        (now_ms - progress_ctx.last_update_time_ms) < progress_ctx.min_update_interval_ms
    ) {
        return;
    }

    if (typeof status_message !== "undefined" && status_message !== null) {
        progress_ctx.status_text.text = String(status_message);
    }
    progress_ctx.count_text.text = completed_count + " / " + progress_ctx.total_count;

    var percent = 100;
    if (progress_ctx.total_count > 0) {
        percent = Math.floor((completed_count / progress_ctx.total_count) * 100);
    }
    if (percent < 0) {
        percent = 0;
    }
    if (percent > 100) {
        percent = 100;
    }

    progress_ctx.progress_bar.value = percent;
    progress_ctx.percent_text.text = percent + "%";

    try {
        progress_ctx.window.update();
    } catch (e) {
    }
    app.refresh();
    progress_ctx.last_update_time_ms = now_ms;
}

function close_export_progress_dialog(progress_ctx) {
    if (!progress_ctx) {
        return;
    }
    try {
        progress_ctx.window.close();
    } catch (e) {
    }
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
        json_file.writeln(write_dict_entry(tabs = 3, key = "name", value = coords[i].node_name));
        json_file.writeln(write_dict_entry(tabs = 3, key = "type", value = "SPRITE"));
        json_file.writeln(write_dict_entry(tabs = 3, key = "node_path", value = coords[i].node_name));
        json_file.writeln(write_dict_entry(tabs = 3, key = "resource_path", value = "sprites/" + coords[i].file_name));
        json_file.writeln(write_dict_entry(tabs = 3, key = "pivot_offset", value = [0, 0]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "offset", value = offset));
        json_file.writeln(write_dict_entry(tabs = 3, key = "position", value = [coords[i].layer_pos[0], coords[i].layer_pos[2]]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "rotation", value = 0.0));
        json_file.writeln(write_dict_entry(tabs = 3, key = "scale", value = [1.0, 1.0]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "opacity", value = 1.0));
        json_file.writeln(write_dict_entry(tabs = 3, key = "z", value = coords[i].layer_pos[1]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "tiles_x", value = coords[i].tile_size[0]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "tiles_y", value = coords[i].tile_size[1]));
        json_file.writeln(write_dict_entry(tabs = 3, key = "frame_index", value = 0));
        json_file.writeln(write_dict_entry(tabs = 3, key = "children", value = []));
        if (coords[i].clipping_mask_target) {
            json_file.writeln(write_dict_entry(tabs = 3, key = "blend_mode", value = coords[i].blend_mode));
            json_file.writeln(write_dict_entry(tabs = 3, key = "clipping_mask_target", value = coords[i].clipping_mask_target, comma = false));
        } else {
            json_file.writeln(write_dict_entry(tabs = 3, key = "blend_mode", value = coords[i].blend_mode, comma = false));
        }
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

function normalize_layer_name(layer_name) {
    layer_name = String(layer_name);
    layer_name = layer_name.split(' ').join('_');
    layer_name = layer_name.replace(/\.png$/i, "");
    layer_name = layer_name.replace(/\._/g, ".");
    layer_name = layer_name.replace(/_\./g, ".");
    layer_name = layer_name.replace(/_+/g, "_");
    layer_name = layer_name.replace(/^\.+/, "");
    layer_name = layer_name.replace(/\.+$/, "");
    layer_name = layer_name.replace(/^_+/, "");
    layer_name = layer_name.replace(/_+$/, "");
    layer_name = layer_name.replace(/\.\.+/g, ".");
    return layer_name;
}

function strip_layer_commands(layer_name) {
    var keyword_pos = 100000;
    if (layer_name.indexOf("--sprites") != -1 && layer_name.indexOf("--sprites") < keyword_pos) {
        keyword_pos = layer_name.indexOf("--sprites");
    }
    if (layer_name.indexOf("c=") != -1 && layer_name.indexOf("c=") < keyword_pos) {
        keyword_pos = layer_name.indexOf("c=");
    }
    if (layer_name.indexOf("m=") != -1 && layer_name.indexOf("m=") < keyword_pos) {
        keyword_pos = layer_name.indexOf("m=");
    }

    if (keyword_pos != 100000) {
        layer_name = layer_name.substring(0, keyword_pos);
    }
    return normalize_layer_name(layer_name);
}

function parse_int_option(layer_name, option_name) {
    var regex = new RegExp(option_name + "=(-?\\d+)");
    var match = layer_name.match(regex);
    if (match == null || match.length < 2) {
        return null;
    }
    var parsed = Number(match[1]);
    if (isNaN(parsed)) {
        return null;
    }
    return Math.ceil(parsed);
}

function pad_left_zeros(value, min_length) {
    value = String(value);
    while (value.length < min_length) {
        value = "0" + value;
    }
    return value;
}

function is_layer_clipping_mask(layer) {
    try {
        return layer != null && layer.typename != "LayerSet" && layer.grouped === true;
    } catch (e) {
        return false;
    }
}

function get_layer_document(layer) {
    try {
        var parent = layer;
        while (parent != null && parent.typename != "Document") {
            parent = parent.parent;
        }
        if (parent != null && parent.typename == "Document") {
            return parent;
        }
    } catch (e) {
    }
    return null;
}

function run_menu_event_string(event_name) {
    try {
        app.runMenuItem(stringIDToTypeID(event_name));
        return true;
    } catch (e) {
        return false;
    }
}

function run_menu_event_char(event_char_id) {
    try {
        executeAction(charIDToTypeID(event_char_id), undefined, DialogModes.NO);
        return true;
    } catch (e) {
        return false;
    }
}

function set_layer_clipping_mask(layer, enabled) {
    var layer_doc = get_layer_document(layer);
    var prev_doc = null;
    var prev_layer = null;
    try {
        prev_doc = app.activeDocument;
        prev_layer = prev_doc.activeLayer;
    } catch (e) {
    }

    try {
        if (layer == null || layer.typename == "LayerSet") {
            return false;
        }

        if (layer_doc != null) {
            app.activeDocument = layer_doc;
            layer_doc.activeLayer = layer;
        }

        try {
            layer.grouped = enabled;
        } catch (e) {
        }
        try {
            if (layer.grouped === enabled) {
                return true;
            }
        } catch (e) {
        }

        if (enabled) {
            if (run_menu_event_string("groupEvent") || run_menu_event_char("GrpL")) {
                try {
                    if (layer.grouped === true) {
                        return true;
                    }
                } catch (e) {
                }
            }
        } else {
            var ungrouped = false;
            ungrouped = ungrouped || run_menu_event_string("ungroup");
            ungrouped = ungrouped || run_menu_event_char("Ungr");
            // Compatibility fallback for older/newer builds.
            ungrouped = ungrouped || run_menu_event_string("ungroupEvent");
            if (ungrouped) {
                try {
                    if (layer.grouped === false) {
                        return true;
                    }
                } catch (e) {
                }
            }
        }

        try {
            return layer.grouped === enabled;
        } catch (e) {
            return false;
        }
    } catch (e) {
        return false;
    } finally {
        try {
            if (prev_doc != null) {
                app.activeDocument = prev_doc;
                if (prev_layer != null) {
                    prev_doc.activeLayer = prev_layer;
                }
            }
        } catch (e) {
        }
    }
}

function process_prepending_layerset_name(layer, layer_name, is_omit_layer_name_if_only_one) {
    layer_name = normalize_layer_name(layer_name);
    var parent_layersets = get_parent_layersets(layer);
    for (var j = 0; j < parent_layersets.length; j++) {
        var parent_name = strip_layer_commands(normalize_layer_name(parent_layersets[j].name));
        layer_name = parent_name + "." + layer_name;
    }
    if (is_omit_layer_name_if_only_one == true) {
        // delete latest layer name
        for (var j = 0; j < parent_layersets.length; j++) {
            var parent_layerset = parent_layersets[j];
            var group_layers = parent_layerset.layers;
            if (group_layers.length <= 1) {
                layer_name = layer_name.split(".").slice(0, -1).join(".");
            } else {
                break;
            }
        }
    }
    return normalize_layer_name(layer_name);
}

function process_reorder_layerset_name(layer_name) {
    // Normalize layer names like Blender's ".L/.R" convention.
    // Example:
    // "forearm.L.003.L" -> "forearm.003.L"
    layer_name = normalize_layer_name(layer_name);

    var tokens = layer_name.split(".");
    var sequence_token_index = -1;
    var side_token = "";

    for (var i = tokens.length - 1; i >= 0; i--) {
        var token_for_sequence = normalize_layer_name(tokens[i]);
        if (/^\d+$/.test(token_for_sequence)) {
            sequence_token_index = i;
            break;
        }
    }

    var output_tokens = [];
    for (var j = 0; j < tokens.length; j++) {
        var token = normalize_layer_name(tokens[j]);
        if (token == "") {
            continue;
        }

        var token_lower = token.toLowerCase();
        if (token_lower == "l" || token_lower == "left") {
            side_token = "L";
            continue;
        }
        if (token_lower == "r" || token_lower == "right") {
            side_token = "R";
            continue;
        }
        if (j == sequence_token_index && /^\d+$/.test(token)) {
            continue;
        }

        output_tokens.push(token);
    }

    if (sequence_token_index != -1) {
        var sequence_token = normalize_layer_name(tokens[sequence_token_index]);
        output_tokens.push(pad_left_zeros(sequence_token, 3));
    }

    if (side_token != "") {
        output_tokens.push(side_token);
    }

    return normalize_layer_name(output_tokens.join("."));
}

function build_export_layer_name(layer, is_prepending_layerset_name, is_reorder_layerset_name, is_omit_layer_name_if_only_one) {
    var export_layer_name = normalize_layer_name(layer.name);
    export_layer_name = strip_layer_commands(export_layer_name);

    if (is_prepending_layerset_name == true) {
        export_layer_name = process_prepending_layerset_name(layer, export_layer_name, is_omit_layer_name_if_only_one);
    }
    if (is_reorder_layerset_name == true) {
        export_layer_name = process_reorder_layerset_name(export_layer_name);
    }

    export_layer_name = normalize_layer_name(export_layer_name);
    if (export_layer_name == "") {
        export_layer_name = "layer";
    }
    return export_layer_name;
}

function get_clipping_mask_base_layer(layer) {
    if (!is_layer_clipping_mask(layer)) {
        return null;
    }

    var sibling_layers = layer.parent.layers;
    var layer_index = -1;
    for (var i = 0; i < sibling_layers.length; i++) {
        if (sibling_layers[i] == layer || is_same_layer(sibling_layers[i], layer)) {
            layer_index = i;
            break;
        }
    }
    if (layer_index == -1) {
        return null;
    }

    // Most documents have clipping base below the current layer.
    for (var j = layer_index + 1; j < sibling_layers.length; j++) {
        var down_layer = sibling_layers[j];
        if (down_layer.typename != "LayerSet" && !is_layer_clipping_mask(down_layer)) {
            return down_layer;
        }
    }
    // Fallback for reverse ordering.
    for (var k = layer_index - 1; k >= 0; k--) {
        var up_layer = sibling_layers[k];
        if (up_layer.typename != "LayerSet" && !is_layer_clipping_mask(up_layer)) {
            return up_layer;
        }
    }

    return null;
}

function create_temporary_clipping_base_layer(layer) {
    try {
        if (layer == null || layer.typename == "LayerSet") {
            return null;
        }
        var layer_doc = get_layer_document(layer);
        if (layer_doc == null) {
            return null;
        }

        var helper_layer = null;
        if (layer.parent != null && layer.parent.typename == "LayerSet") {
            helper_layer = layer.parent.artLayers.add();
        } else {
            helper_layer = layer_doc.artLayers.add();
        }
        helper_layer.name = "__coa_tmp_clip_base__";
        helper_layer.move(layer, ElementPlacement.PLACEAFTER);
        return helper_layer;
    } catch (e) {
        return null;
    }
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
    const layer_types = {
        selected: "selected",
        visible: "visible",
    }

    coords = [];

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
        if ((layer_type == layer_types.selected && layer.selected == false) || (layer_type == layer_types.visible && layer.visible == false))
            continue;
        var layer_name = build_export_layer_name(
            layer,
            is_prepending_layerset_name,
            is_reorder_layerset_name,
            is_omit_layer_name_if_only_one
        );

        if (unique_layer_names[layer_name] == undefined) {
            unique_layer_names[layer_name] = 1;
        } else {
            unique_layer_names[layer_name] += 1;
        }
    }
    var duplicated_layer_names = [];
    for (var key in unique_layer_names) {
        if (unique_layer_names[key] > 1) {
            duplicated_layer_names.push(key + " (" + unique_layer_names[key] + " times)");
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

    var progress_ctx = create_export_progress_dialog(1);
    update_export_progress_dialog(progress_ctx, 0, "Preparing duplicate document...", true);

    var target_layers = [];
    var exported_count = 0;
    var export_error = null;

    try {
        // flatten layers
        if (is_layerset_automerge == true) {
            update_export_progress_dialog(progress_ctx, 0, "Merging layer sets...", true);
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

        target_layers = get_target_layers(dupli_doc.layers);
        if (target_layers.length == 0) {
            throw new Error("No layers were found in duplicated document.");
        }
        progress_ctx.total_count = target_layers.length;
        update_export_progress_dialog(progress_ctx, 0, "Starting export...", true);

        for (var i = 0; i < target_layers.length; i++) {
            // deselect layers
            var layer = target_layers[i];

            dupli_doc.activeLayer = layer;

            var raw_layer_name = normalize_layer_name(layer.name);
            var layer_name = build_export_layer_name(
                layer,
                is_prepending_layerset_name,
                is_reorder_layerset_name,
                is_omit_layer_name_if_only_one
            );
            // get layer margin settings
            var margin = 0;
            var parsed_margin = parse_int_option(raw_layer_name, "m");
            if (parsed_margin != null) {
                margin = parsed_margin;
            }
            var layer_pos = null;
            var tile_size = [1, 1];
            var tmp_doc = null;

            try {
                tmp_doc = app.documents.add(dupli_doc.width, dupli_doc.height, dupli_doc.resolution, layer_name, NewDocumentMode.RGB, DocumentFill.TRANSPARENT);

                var composite_mode = "" + layer.blendMode;
                composite_mode = composite_mode.replace("BlendMode.", "");

                var clipping_mask_target_name = null;
                if (is_layer_clipping_mask(layer)) {
                    var clipping_mask_base_layer = get_clipping_mask_base_layer(layer);
                    if (clipping_mask_base_layer != null) {
                        clipping_mask_target_name = build_export_layer_name(
                            clipping_mask_base_layer,
                            is_prepending_layerset_name,
                            is_reorder_layerset_name,
                            is_omit_layer_name_if_only_one
                        );
                    }
                }

                // duplicate layer into new doc and crop to layerbounds with margin
                app.activeDocument = dupli_doc;
                var duplicated_layer = layer.duplicate(tmp_doc, ElementPlacement.INSIDE);
                app.activeDocument = tmp_doc;

                // Export clipped layers as independent sprites.
                if (is_layer_clipping_mask(duplicated_layer)) {
                    var temp_clip_base_layer = null;
                    if (get_clipping_mask_base_layer(duplicated_layer) == null) {
                        temp_clip_base_layer = create_temporary_clipping_base_layer(duplicated_layer);
                    }
                    if (!set_layer_clipping_mask(duplicated_layer, false)) {
                        throw new Error("Failed to release clipping mask: " + layer.name);
                    }
                    if (temp_clip_base_layer != null) {
                        try {
                            temp_clip_base_layer.remove();
                        } catch (e) {
                        }
                    }
                }

                // Bounds must be recalculated after clipping state changes.
                var bounds = [duplicated_layer.bounds[0].as("px"), duplicated_layer.bounds[1].as("px"), duplicated_layer.bounds[2].as("px"), duplicated_layer.bounds[3].as("px")];
                layer_pos = Array(bounds[0] - margin, -i, bounds[1] - margin);

                var crop_bounds = bounds.slice(0);

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
                if (raw_layer_name.indexOf("--sprites") != -1) {
                    var sprites = tmp_doc.layers[0].layers;
                    var sprite_count = sprites.length;
                    var parsed_columns = parse_int_option(raw_layer_name, "c");
                    var columns = parsed_columns == null ? Math.ceil((Math.sqrt(sprite_count))) : parsed_columns;
                    if (columns < 1) {
                        columns = 1;
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

                // set all layer composite mode to normal
                if (is_set_composite_mode_to_normal == true) {
                    for (var j = 0; j < tmp_doc.layers.length; j++) {
                        var tmp_layer = tmp_doc.layers[j];
                        tmp_doc.activeLayer = tmp_layer;
                        tmp_layer.blendMode = BlendMode.NORMAL;
                    }
                }

                // do save stuff
                var file_name = layer_name + ".png";
                tmp_doc.exportDocument(File(export_path + "/sprites/" + file_name), ExportType.SAVEFORWEB, options);

                // store coords
                coords.push({
                    node_name: layer_name,
                    file_name: file_name,
                    layer_pos: layer_pos,
                    tile_size: tile_size,
                    blend_mode: composite_mode,
                    clipping_mask_target: clipping_mask_target_name
                });
            } finally {
                if (tmp_doc) {
                    try {
                        tmp_doc.close(SaveOptions.DONOTSAVECHANGES);
                    } catch (e) {
                    }
                }
            }

            exported_count += 1;
            update_export_progress_dialog(
                progress_ctx,
                exported_count,
                "Exported " + exported_count + "/" + target_layers.length + ": " + layer_name,
                (i == target_layers.length - 1)
            );
        }
    } catch (e) {
        export_error = e;
    } finally {
        close_export_progress_dialog(progress_ctx);
        try {
            dupli_doc.close(SaveOptions.DONOTSAVECHANGES);
        } catch (e) {
        }
    }

    if (export_error != null) {
        app.preferences.rulerUnits = init_units;
        alert("Export failed:\n" + export_error);
        return;
    }

    if (export_json == true) {
        save_coords(center_sprites, export_path, export_name);
    }
    app.preferences.rulerUnits = init_units;

    alert(
        "Export completed.\n"
        + "Layers: " + exported_count + " / " + target_layers.length + "\n"
        + "Output: " + export_path
    );
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
                is_reorder_layerset_name: Checkbox { text: 'Blender Bone Style Naming', value: true } \
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

#target illustrator

    (function () {
        var doc = app.activeDocument;
        if (!doc) { alert("ドキュメントがありません。"); return; }

        // ---------- 基本ヘルパー ----------
        function unionBounds(a, b) {
            if (!a) return b;
            if (!b) return a;
            return [
                Math.min(a[0], b[0]),
                Math.max(a[1], b[1]),
                Math.max(a[2], b[2]),
                Math.min(a[3], b[3])
            ];
        }

        function getLayerVisibleBounds(layer) {
            if (!layer || layer.typename !== "Layer") {
                throw new Error("Argument 'layer' must be a top-level Layer.");
            }
            var items;
            try {
                items = layer.pageItems;
            } catch (e) {
                items = null;
            }
            if (!items || items.length === 0) {
                return null;
            }
            var u = null;
            for (var i = 0; i < items.length; i++) {
                var it = items[i];
                if (it.hidden || it.locked) { continue; }
                try {
                    u = unionBounds(u, it.visibleBounds);
                } catch (err) { }
            }
            return u;
        }

        function basenameWithoutExt(name) {
            var n = name || "export";
            return n.replace(/\.[^\.]+$/, "");
        }
        function pad3(n) {
            n = String(n);
            return ("000" + n).slice(-3);
        }
        function sanitizeBaseName(s) {
            if (!s) { return ""; }
            s = s.replace(/[ \t]+/g, "_").replace(/[\/\\:\*\?"<>\|]/g, "-");
            return s;
        }
        function isDefaultGroupName(s) {
            if (!s) { return true; }
            var t = s.replace(/\s+/g, "").toLowerCase();
            return (t === "group" || t === "グループ" || t === "layer" || t === "レイヤー" || t === "path" || t === "パス");
        }
    function makeUniqueName(raw, usedMap) {
        var base = sanitizeBaseName(raw);
        var defaultLike = isDefaultGroupName(base) || base === "";
        if (defaultLike) { base = "sprite"; }
        var count = usedMap[base] || 0;
            var finalName;
            if (defaultLike || count > 0) {
                finalName = base + "." + pad3(count + 1);
                usedMap[base] = count + 1;
            } else {
                finalName = base;
                usedMap[base] = 1;
        }
        return finalName;
    }

    function isExportableItem(item) {
        if (!item) { return false; }
        var t = item.typename;
        return (
            t === "GroupItem" ||
            t === "CompoundPathItem" ||
            t === "PathItem" ||
            t === "TextFrame" ||
            t === "LegacyTextItem"
        );
    }

        function repeatString(str, count) {
            var out = "";
            for (var i = 0; i < count; i++) {
                out += str;
            }
            return out;
        }
        function escapeJSONString(str) {
            return str.replace(/\\/g, "\\\\")
                .replace(/\"/g, "\\\"")
                .replace(/\r/g, "\\r")
                .replace(/\n/g, "\\n")
                .replace(/\t/g, "\\t");
        }
        function jsonStringify(value, indent, depth) {
            if (indent === undefined) { indent = "    "; }
            if (depth === undefined) { depth = 0; }
            if (value === null) { return "null"; }
            var type = typeof value;
            if (type === "number") {
                return isFinite(value) ? String(value) : "null";
            }
            if (type === "boolean") {
                return value ? "true" : "false";
            }
            if (type === "string") {
                return "\"" + escapeJSONString(value) + "\"";
            }
            var pad = repeatString(indent, depth);
            var padNext = repeatString(indent, depth + 1);
            if (value instanceof Array) {
                if (value.length === 0) { return "[]"; }
                var arrLines = [];
                for (var i = 0; i < value.length; i++) {
                    arrLines.push(padNext + jsonStringify(value[i], indent, depth + 1));
                }
                return "[\n" + arrLines.join(",\n") + "\n" + pad + "]";
            }
            var keys = [];
            for (var k in value) {
                if (value.hasOwnProperty(k) && value[k] !== undefined) {
                    keys.push(k);
                }
            }
            if (keys.length === 0) { return "{}"; }
            var lines = [];
            for (var j = 0; j < keys.length; j++) {
                var key = keys[j];
                lines.push(padNext + "\"" + escapeJSONString(key) + "\": " + jsonStringify(value[key], indent, depth + 1));
            }
            return "{\n" + lines.join(",\n") + "\n" + pad + "}";
        }

        function writeJSON(exportFolder, exportName, nodes) {
            var f = new File(exportFolder.fsName + "/" + exportName + ".json");
            f.encoding = "UTF8";
            f.open("w");
            var root = {
                name: exportName,
                nodes: nodes
            };
            f.write(jsonStringify(root, "    ", 0));
            f.close();
        }

        function roundTo(value, decimals) {
            if (decimals === undefined) { decimals = 3; }
            var pow = Math.pow(10, decimals);
            return Math.round(value * pow) / pow;
        }
        function almostEqual(a, b) {
            return Math.abs(a - b) < 0.001;
        }
        function pointsAlmostEqual(a, b) {
            return almostEqual(a[0], b[0]) && almostEqual(a[1], b[1]);
        }
        function pushUnique(arr, item) {
            if (!arr) { return; }
            for (var i = 0; i < arr.length; i++) {
                if (arr[i] === item) { return; }
            }
            arr.push(item);
        }
        function isDescendantOfLayer(item, layer) {
            if (!item || !layer) { return false; }
            var cur = item;
            while (cur) {
                if (cur === layer) { return true; }
                if (!cur.parent) { break; }
                cur = cur.parent;
            }
            return false;
        }
        function isItemSelected(item, selectionSet) {
            if (!selectionSet || !item) { return false; }
            for (var i = 0; i < selectionSet.length; i++) {
                if (selectionSet[i] === item) { return true; }
            }
            return false;
        }
        function hasSelectedDescendant(item, selectionSet) {
            if (!item) { return false; }
            if (isItemSelected(item, selectionSet)) { return true; }
            var kids;
            try { kids = item.pageItems; } catch (e) { kids = null; }
            if (!kids || kids.length === 0) { return false; }
            for (var i = 0; i < kids.length; i++) {
                if (hasSelectedDescendant(kids[i], selectionSet)) { return true; }
            }
            return false;
        }
        function hideUnselectedChildren(root, selectionSet, hiddenRecords) {
            if (!root) { return; }
            var kids;
            try { kids = root.pageItems; } catch (e) { kids = null; }
            if (!kids || kids.length === 0) { return; }
            for (var i = 0; i < kids.length; i++) {
                var child = kids[i];
                if (!child) { continue; }
                if (isItemSelected(child, selectionSet)) {
                    if (child.typename === "GroupItem" || child.typename === "CompoundPathItem") {
                        hideUnselectedChildren(child, selectionSet, hiddenRecords);
                    }
                    continue;
                }
                if (hasSelectedDescendant(child, selectionSet)) {
                    if (child.typename === "GroupItem" || child.typename === "CompoundPathItem") {
                        hideUnselectedChildren(child, selectionSet, hiddenRecords);
                    }
                    continue;
                }
                hiddenRecords.push({ item: child, prevHidden: child.hidden });
                try { child.hidden = true; } catch (eHide) { }
            }
        }
        function restoreHiddenRecords(hiddenRecords) {
            if (!hiddenRecords) { return; }
            for (var i = 0; i < hiddenRecords.length; i++) {
                var rec = hiddenRecords[i];
                if (!rec || !rec.item) { continue; }
                try { rec.item.hidden = rec.prevHidden; } catch (e) { }
            }
        }
        function buildSelectionSet(doc, layer) {
            var selection = doc.selection;
            if (!selection || selection.length === 0) { return []; }
            var filtered = [];
            for (var i = 0; i < selection.length; i++) {
                var item = selection[i];
                if (!item || !item.typename) { continue; }
                var typeName = item.typename;
                var target = item;
                if (typeName === "PathPoint") {
                    try { target = item.parent; } catch (eP) { target = null; }
                    if (!target && item.path) { target = item.path; }
                    if (target && target.typename === "PathItem") {
                        if (target.parent && target.parent.typename === "CompoundPathItem") {
                            target = target.parent;
                        }
                    }
                } else if (typeName === "PathItem") {
                    if (item.parent && item.parent.typename === "CompoundPathItem") {
                        target = item.parent;
                    }
                }
                if (!target || !target.typename) { continue; }
                if (!isDescendantOfLayer(target, layer)) { continue; }
                var tName = target.typename;
                if (tName === "GroupItem" || tName === "CompoundPathItem" || tName === "PathItem" ||
                    tName === "TextFrame" || tName === "LegacyTextItem") {
                    pushUnique(filtered, target);
                }
            }
            return filtered;
        }
        function fillRuleToString(fillRule) {
            try {
                if (typeof PathFillRule !== "undefined" && fillRule === PathFillRule.EVENODD) {
                    return "evenodd";
                }
            } catch (e) { }
            var txt = fillRule !== undefined ? String(fillRule).toLowerCase() : "";
            if (txt.indexOf("even") !== -1) {
                return "evenodd";
            }
            return "nonzero";
        }

    function convertTextsToOutlines(container) {
        if (!container) { return; }
        if (container.typename === "TextFrame") {
            try { container.createOutline(); } catch (e0) { }
            return;
        }
        var kids;
        try { kids = container.pageItems; } catch (e) { kids = null; }
        if (!kids || kids.length === 0) { return; }
        for (var i = kids.length - 1; i >= 0; i--) {
            var item = kids[i];
            if (!item) { continue; }
            if (item.typename === "TextFrame") {
                try { item.createOutline(); } catch (e1) { }
            } else if (item.typename === "GroupItem" || item.typename === "Layer" || item.typename === "CompoundPathItem") {
                convertTextsToOutlines(item);
            }
        }
    }

        function matrixToArray(matrix) {
            if (!matrix) { return null; }
            return [
                roundTo(matrix.mValueA || 0, 6),
                roundTo(matrix.mValueB || 0, 6),
                roundTo(matrix.mValueC || 0, 6),
                roundTo(matrix.mValueD || 0, 6),
                roundTo(matrix.mValueTX || 0, 6),
                roundTo(matrix.mValueTY || 0, 6)
            ];
        }

        function colorToJSON(color, mapPoint, gradientStore) {
            if (!color) { return null; }
            var typeName = color.typename;
            if (typeName === "NoColor") {
                return null;
            }
            if (typeName === "RGBColor") {
                return {
                    type: "rgb",
                    r: roundTo(color.red, 3),
                    g: roundTo(color.green, 3),
                    b: roundTo(color.blue, 3)
                };
            }
            if (typeName === "GrayColor") {
                return {
                    type: "gray",
                    gray: roundTo(color.gray, 3)
                };
            }
            if (typeName === "CMYKColor") {
                return {
                    type: "cmyk",
                    c: roundTo(color.cyan, 3),
                    m: roundTo(color.magenta, 3),
                    y: roundTo(color.yellow, 3),
                    k: roundTo(color.black, 3)
                };
            }
            if (typeName === "SpotColor") {
                return {
                    type: "spot",
                    name: color.spot ? color.spot.name : "",
                    tint: roundTo(color.tint, 3),
                    baseColor: color.spot ? colorToJSON(color.spot.color, mapPoint, gradientStore) : null
                };
            }
            if (typeName === "PatternColor") {
                return {
                    type: "pattern",
                    name: color.pattern ? color.pattern.name : ""
                };
            }
            if (typeName === "GradientColor") {
                return registerGradient(color, mapPoint, gradientStore);
            }
            return { type: "unknown", name: typeName };
        }

        function registerGradient(gradientColor, mapPoint, gradientStore) {
            if (!gradientColor) { return null; }
            var key = "";
            try {
                key = (gradientColor.gradient ? gradientColor.gradient.name : "") + "|" +
                    roundTo(gradientColor.angle, 6) + "|" +
                    roundTo(gradientColor.length, 6) + "|" +
                    matrixToArray(gradientColor.matrix);
            } catch (e) {
                key = "grad|" + (gradientStore.list.length + 1);
            }
            var existing = gradientStore.map[key];
            if (existing) {
                return { type: "gradient", gradientId: existing.id };
            }

            var stops = [];
            var gradient = gradientColor.gradient;
            if (gradient && gradient.gradientStops) {
                for (var i = 0; i < gradient.gradientStops.length; i++) {
                    var gs = gradient.gradientStops[i];
                    var stopColor = gs.color ? colorToJSON(gs.color, mapPoint, gradientStore) : null;
                    stops.push({
                        offset: roundTo(gs.rampPoint / 100, 6),
                        midpoint: roundTo(gs.midPoint / 100, 6),
                        color: stopColor
                    });
                }
            }

            var originPoint = null;
            try {
                if (gradientColor.origin) {
                    originPoint = mapPoint(gradientColor.origin);
                }
            } catch (e2) { }

            var gradEntry = {
                id: "grad" + (gradientStore.list.length + 1),
                name: gradient ? gradient.name : "",
                kind: (gradient && gradient.type === GradientType.RADIAL) ? "radial" : "linear",
                angle: roundTo(gradientColor.angle, 6),
                length: roundTo(gradientColor.length, 6),
                hiliteAngle: roundTo(gradientColor.hiliteAngle || 0, 6),
                hiliteLength: roundTo(gradientColor.hiliteLength || 0, 6),
                matrix: matrixToArray(gradientColor.matrix),
                origin: originPoint,
                stops: stops
            };
            gradientStore.map[key] = gradEntry;
            gradientStore.list.push(gradEntry);
            return { type: "gradient", gradientId: gradEntry.id };
        }

        function strokeToJSON(item, mapPoint, gradientStore) {
            if (!item || !item.stroked) { return null; }
            var col = colorToJSON(item.strokeColor, mapPoint, gradientStore);
            if (!col) { return null; }
            var dashArray = null;
            if (item.strokeDashes && item.strokeDashes.length > 0) {
                dashArray = [];
                for (var i = 0; i < item.strokeDashes.length; i++) {
                    dashArray.push(roundTo(item.strokeDashes[i], 3));
                }
            }
            var strokeEntry = {
                color: col,
                width: roundTo(item.strokeWidth, 3),
                cap: item.strokeCap || "",
                join: item.strokeJoin || "",
                miterLimit: roundTo(item.strokeMiterLimit || 0, 3),
                dashArray: dashArray,
                dashOffset: item.strokeDashOffset ? roundTo(item.strokeDashOffset, 3) : 0
            };
            if (item.strokeAlignment !== undefined) {
                strokeEntry.alignment = item.strokeAlignment;
            }
            return strokeEntry;
        }

        function fillToJSON(item, mapPoint, gradientStore) {
            if (!item || !item.filled) { return null; }
            return colorToJSON(item.fillColor, mapPoint, gradientStore);
        }

        function pathPointsToPathData(pathItem, mapPoint, decimals) {
            var pts = pathItem.pathPoints;
            if (!pts || pts.length === 0) { return ""; }
            if (decimals === undefined) { decimals = 3; }
            var fmtPow = Math.pow(10, decimals);
            function fmt(num) {
                return Math.round(num * fmtPow) / fmtPow;
            }
            var commands = [];
            var first = mapPoint(pts[0].anchor);
            commands.push("M " + fmt(first[0]) + " " + fmt(first[1]));
            var limit = pathItem.closed ? pts.length : pts.length - 1;
            for (var i = 0; i < limit; i++) {
                var currentIndex = (i + 1) % pts.length;
                var prev = pts[i];
                var current = pts[currentIndex];
                var prevAnchor = mapPoint(prev.anchor);
                var prevRight = mapPoint(prev.rightDirection);
                var currLeft = mapPoint(current.leftDirection);
                var currAnchor = mapPoint(current.anchor);
                var handlesAreStraight = pointsAlmostEqual(prevAnchor, prevRight) && pointsAlmostEqual(currAnchor, currLeft);
                if (!pathItem.closed && i === pts.length - 1) {
                    break;
                }
                if (handlesAreStraight) {
                    commands.push("L " + fmt(currAnchor[0]) + " " + fmt(currAnchor[1]));
                } else {
                    commands.push(
                        "C " +
                        fmt(prevRight[0]) + " " + fmt(prevRight[1]) + " " +
                        fmt(currLeft[0]) + " " + fmt(currLeft[1]) + " " +
                        fmt(currAnchor[0]) + " " + fmt(currAnchor[1])
                    );
                }
            }
            if (pathItem.closed) {
                commands.push("Z");
            }
            return commands.join(" ");
        }

        function collectSVGMeta(root, artRect) {
            var width = artRect[2] - artRect[0];
            var height = artRect[1] - artRect[3];
            var gradientStore = { list: [], map: {} };
            var paths = [];
            var pathCounter = 0;
            function mapPoint(pt) {
                return [
                    roundTo((pt[0] - artRect[0]), 6),
                    roundTo((artRect[1] - pt[1]), 6)
                ];
            }
            function pushPath(styleSource, pathItems) {
                if (!styleSource || styleSource.clipping) { return; }
                if (!pathItems || pathItems.length === 0) { return; }
                var combined = [];
                for (var i = 0; i < pathItems.length; i++) {
                    var pi = pathItems[i];
                    if (!pi || pi.guides || pi.hidden) { continue; }
                    var d = pathPointsToPathData(pi, mapPoint, 3);
                    if (d && d !== "") {
                        combined.push(d);
                    }
                }
                if (combined.length === 0) { return; }
                var entry = {
                    id: "path" + (++pathCounter),
                    d: combined.join(" "),
                    fill: fillToJSON(styleSource, mapPoint, gradientStore),
                    stroke: strokeToJSON(styleSource, mapPoint, gradientStore),
                    opacity: roundTo((styleSource.opacity !== undefined ? styleSource.opacity : 100) / 100, 4),
                    fillRule: fillRuleToString(styleSource.fillRule),
                    blendMode: String(styleSource.blendingMode || "normal"),
                    evenOdd: fillRuleToString(styleSource.fillRule) === "evenodd"
                };
                paths.push(entry);
            }

            function traverse(item) {
                if (!item) { return; }
                if (item.hidden || item.locked) { return; }
                var typeName = item.typename;
                if (typeName === "GroupItem") {
                    var kids = item.pageItems;
                    for (var i = 0; i < kids.length; i++) {
                        traverse(kids[i]);
                    }
                    return;
                }
                if (typeName === "CompoundPathItem") {
                    if (item.pathItems && item.pathItems.length > 0) {
                        pushPath(item, item.pathItems);
                    }
                    return;
                }
                if (typeName === "PathItem") {
                    pushPath(item, [item]);
                    return;
                }
                if (typeName === "LegacyTextItem" || typeName === "TextFrame") {
                    // 念のため残存テキストがあればアウトライン化
                    try { item.createOutline(); } catch (e1) { }
                    return;
                }
                if (typeName === "PlacedItem" || typeName === "RasterItem") {
                    // ビットマップは SVG では扱えないので無視
                    return;
                }
                // その他は再帰せず無視
            }

            traverse(root);

            return {
                width: roundTo(width, 3),
                height: roundTo(height, 3),
                viewBox: [0, 0, roundTo(width, 3), roundTo(height, 3)],
                gradients: gradientStore.list,
                paths: paths
            };
        }

    function exportItemToSVG_(item, outFile) {
        var vb = item.visibleBounds;
        var left = vb[0], top = vb[1], right = vb[2], bottom = vb[3];
        var w = right - left;
        var h = top - bottom;
        if (w <= 0 || h <= 0) { return { ok: false, reason: "Empty bounds." }; }
        var tmp = app.documents.add(DocumentColorSpace.RGB, w, h);
        var dup = item.duplicate(tmp.layers[0], ElementPlacement.PLACEATBEGINNING);
        try { dup.left = 0; dup.top = h; } catch (e1) {
            try { dup.position = [0, h]; } catch (e2) { }
        }
        convertTextsToOutlines(tmp.layers[0]);

        var artRect = tmp.artboards[0].artboardRect; // [left, top, right, bottom]
        var meta = collectSVGMeta(tmp.layers[0], artRect);

        var opt = new ExportOptionsSVG();
        opt.coordinatePrecision = 3;
        opt.embedRasterImages = false;
        opt.fontType = SVGFontType.OUTLINEFONT;
            opt.cssProperties = SVGCSSPropertyLocation.PRESENTATIONATTRIBUTES;
            opt.documentEncoding = SVGDocumentEncoding.UTF8;
            opt.preserveEditability = false;
            opt.svgId = SVGIdType.SVGIDREGULAR;
            opt.svgMinify = false;

        tmp.exportFile(outFile, ExportType.SVG, opt);
        tmp.close(SaveOptions.DONOTSAVECHANGES);
        return { ok: true, meta: meta };
    }

        // ---------- UI ----------
        var w = new Window("dialog", "COA tools2 - Illustrator SVG Exporter");
        w.orientation = "column";
        w.alignChildren = "fill";

        var g1 = w.add("group");
        g1.add("statictext", undefined, "Export Name:");
        var edName = g1.add("edittext", undefined, basenameWithoutExt(doc.name));
        edName.characters = 30;

        var g2 = w.add("group");
        g2.add("statictext", undefined, "Export Path:");
        var defaultPath = (function () {
            try { return doc.path.fsName; } catch (e) { return Folder.myDocuments.fsName; }
        })();
        var edPath = g2.add("edittext", undefined, defaultPath);
        edPath.characters = 40;
        var btSel = g2.add("button", undefined, "select");
        btSel.onClick = function () {
            var f = Folder.selectDialog("エクスポート先を選択");
            if (f) { edPath.text = f.fsName; }
        };

        var g3 = w.add("group");
        g3.add("statictext", undefined, "Target Layer:");
        var ddLayer = g3.add("dropdownlist", undefined, []);
        for (var i = 0; i < doc.layers.length; i++) {
            ddLayer.add("item", doc.layers[i].name);
        }
        function getTopLevelLayerOf(layer) {
            var cur = layer;
            while (cur && cur.parent && cur.parent.typename !== "Document") {
                cur = cur.parent;
            }
            return cur && cur.typename === "Layer" ? cur : null;
        }
        var topLayer = getTopLevelLayerOf(doc.activeLayer) || doc.layers[0];
        var activeIdx = 0;
        for (var j = 0; j < doc.layers.length; j++) {
            if (doc.layers[j].name === topLayer.name) { activeIdx = j; break; }
        }
        ddLayer.selection = ddLayer.items[activeIdx];

        var g4 = w.add("group");
        var cbJSON = g4.add("checkbox", undefined, "Export JSON");
        cbJSON.value = true;

        var g5 = w.add("group");
        var cbCenter = g5.add("checkbox", undefined, "Center bounds at origin");
        cbCenter.value = false;

        var g6 = w.add("group");
        var cbSelectionOnly = g6.add("checkbox", undefined, "Export selected paths only");
        cbSelectionOnly.value = false;

        var gBtn = w.add("group");
        gBtn.alignment = "right";
        var okButton = gBtn.add("button", undefined, "Export", { name: "ok" });
        gBtn.add("button", undefined, "Cancel", { name: "cancel" });

        okButton.onClick = function () {
            if (!ddLayer.selection) { alert("対象レイヤーが選択されていません。"); return; }
            var layer = doc.layers[ddLayer.selection.index];
            if (!layer || layer.typename !== "Layer") {
                alert("トップレベルのレイヤーを選択してください。");
                return;
            }
            try {
                var exportName = String(edName.text || "export").replace(/\s+/g, "_");
                var baseFolder = new Folder(edPath.text);
                if (!baseFolder.exists) { alert("エクスポート先フォルダーが存在しません。"); return; }

                var spritesFolder = new Folder(baseFolder.fsName + "/sprites");
                if (!spritesFolder.exists) { spritesFolder.create(); }

                var layerVB = getLayerVisibleBounds(layer);
                if (!layerVB) { alert("対象レイヤーに可視オブジェクトがありません。"); return; }

            var selectionOnly = cbSelectionOnly.value;
            var selectionSet = selectionOnly ? buildSelectionSet(doc, layer) : [];
            if (selectionOnly && selectionSet.length === 0) {
                alert("選択されているパスがありません。");
                return;
            }

            var activeArtboard = doc.artboards[doc.artboards.getActiveArtboardIndex()];
            var artRect = activeArtboard.artboardRect; // [left, top, right, bottom]
            var artLeft = artRect[0];
            var artTop = artRect[1];
            var layerCenterX = (layerVB[0] + layerVB[2]) / 2;
            var layerCenterY = (layerVB[1] + layerVB[3]) / 2;
            var centerOffsetX = 0;
            var centerOffsetY = 0;
            if (cbCenter.value) {
                centerOffsetX = (layerCenterX - artLeft);
                centerOffsetY = (artTop - layerCenterY);
            }

            var targets = [];
            var pageItems = layer.pageItems;
            for (var pi = 0; pi < pageItems.length; pi++) {
                var item = pageItems[pi];
                if (!item || item.parent !== layer) { continue; }
                if (!isExportableItem(item)) { continue; }
                targets.push(item);
            }
            if (targets.length === 0) {
                alert("選択レイヤー直下にエクスポート可能なオブジェクトがありません。");
                return;
            }

            var used = {};
            var nodes = [];
            for (var idx = 0; idx < targets.length; idx++) {
                var targetItem = targets[idx];
                if (targetItem.hidden || targetItem.locked) { continue; }

                var hiddenRecords = [];
                if (selectionOnly) {
                    var hasRelevantSelection = hasSelectedDescendant(targetItem, selectionSet);
                    var isDirectlySelected = isItemSelected(targetItem, selectionSet);
                    if (!hasRelevantSelection) {
                        continue;
                    }
                    if (!isDirectlySelected) {
                        hideUnselectedChildren(targetItem, selectionSet, hiddenRecords);
                    }
                }

                try {
                    var safeName = makeUniqueName(targetItem.name, used);
                    var outFile = new File(spritesFolder.fsName + "/" + safeName + ".svg");

                    var vb = targetItem.visibleBounds;
                    var gl = vb[0], gt = vb[1];
                    var baseX = (gl - artLeft);
                    var baseY = (artTop - gt);
                    var dx = Math.round(baseX - centerOffsetX);
                    var dy = Math.round(baseY - centerOffsetY);

                    var result = exportItemToSVG_(targetItem, outFile);
                    if (result.ok) {
                        var node = {
                            name: safeName + ".svg",
                            type: "SPRITE",
                            node_path: safeName + ".svg",
                            resource_path: "sprites/" + safeName + ".svg",
                            pivot_offset: [0, 0],
                            offset: [0, 0],
                            position: [dx, dy],
                            rotation: 0.0,
                            scale: [1.0, 1.0],
                            opacity: 1.0,
                            z: -idx,
                            pos: [dx, -idx, dy],
                            tiles: [1, 1],
                            tiles_x: 1,
                            tiles_y: 1,
                            frame_index: 0,
                            children: [],
                            svg: {
                                width: result.meta.width,
                                height: result.meta.height,
                                viewBox: result.meta.viewBox,
                                paths: result.meta.paths,
                                gradients: result.meta.gradients
                            }
                        };
                        nodes.push(node);
                    }
                } finally {
                    if (hiddenRecords.length > 0) {
                        restoreHiddenRecords(hiddenRecords);
                    }
                }
            }

                if (cbJSON.value) {
                    writeJSON(baseFolder, exportName, nodes);
                }
                alert("SVGエクスポートが完了しました。");
                w.close();
            } catch (err) {
                alert("Error: " + err);
            }
        };

        w.center();
        w.show();
    })();

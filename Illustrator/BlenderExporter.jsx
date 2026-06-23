#target illustrator

    (function () {
        var doc = app.activeDocument;
        if (!doc) { alert("No active document."); return; }

        // ---------- Helpers ----------
        // NEW: bounds utilities for layer center origin
        function unionBounds(a, b) {
            if (!a) return b;
            if (!b) return a;
            // [left, top, right, bottom]
            return [
                Math.min(a[0], b[0]),
                Math.max(a[1], b[1]),
                Math.max(a[2], b[2]),
                Math.min(a[3], b[3])
            ];
        }

        // bounds utilities はそのまま使用（unionBounds が上にある前提）

        function getLayerVisibleBounds(layer) {
            if (!layer || layer.typename !== "Layer") {
                throw new Error("Argument 'layer' must be a top-level Layer.");
            }
            var u = null;
            var items;
            try {
                items = layer.pageItems; // Illustrator の Layer は pageItems を持つ
            } catch (e) {
                items = null;
            }
            if (!items || items.length === 0) {
                return null; // 呼び出し側で null チェックしてメッセージを出す
            }
            for (var i = 0; i < items.length; i++) {
                var it = items[i];
                if (it.hidden || it.locked) continue;
                try {
                    u = unionBounds(u, it.visibleBounds); // [L, T, R, B]
                } catch (e) {
                    // 特定アイテムで visibleBounds 取得に失敗してもスキップ
                }
            }
            return u; // 何もなければ null
        }


        function getLayerCenter(layer) {
            var vb = getLayerVisibleBounds(layer);
            if (!vb) throw new Error("Target layer has no visible path bounds.");
            return {
                cx: (vb[0] + vb[2]) / 2,
                cy: (vb[1] + vb[3]) / 2,
                vb: vb
            };
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
            if (!s) return "";
            // スペースは '_'、不可な文字は '-' に
            s = s.replace(/[ \t]+/g, "_").replace(/[\/\\:\*\?"<>\|]/g, "-");
            return s;
        }
        function isDefaultGroupName(s) {
            if (!s) return true;
            var t = s.replace(/\s+/g, "").toLowerCase();
            return (t === "group" || t === "グループ" || t === "layer" || t === "レイヤー" || t === "path" || t === "パス");
        }
        function makeUniqueName(raw, usedMap) {
            var base = sanitizeBaseName(raw);
            var defaultLike = isDefaultGroupName(base) || base === "";
            if (defaultLike) base = "sprite";
            var count = usedMap[base] || 0;

            // デフォルト名は常に .001 から開始。重複も .001 から。
            var finalName;
            if (defaultLike || count > 0) {
                finalName = base + "." + pad3(count + 1);
                usedMap[base] = count + 1;
            } else {
                finalName = base;
                usedMap[base] = 1; // 次回は .002 相当
            }
            return finalName;
        }

        function writeJSON(exportFolder, exportName, nodes) {
            var f = new File(exportFolder.fsName + "/" + exportName + ".json");
            f.encoding = "UTF8";
            f.open("w");

            // Photoshop 版の構造に合わせて出力
            f.writeln("{");
            f.writeln('    "name": "' + exportName + '",');
            f.writeln('    "nodes": [');
            for (var i = 0; i < nodes.length; i++) {
                var n = nodes[i]; // {name, pos:[x, z, y], tiles:[1,1]}
                f.writeln("        {");
                f.writeln('            "name": "' + n.name + '",');
                f.writeln('            "type": "SPRITE",');
                f.writeln('            "node_path": "' + n.name + '",');
                f.writeln('            "resource_path": "sprites/' + n.name + '",');
                f.writeln('            "pivot_offset": [0, 0],');
                f.writeln('            "offset": [0, 0],');
                f.writeln('            "position": [' + n.pos[0] + ', ' + n.pos[2] + '],');
                f.writeln('            "rotation": 0.0,');
                f.writeln('            "scale": [1.0, 1.0],');
                f.writeln('            "opacity": 1.0,');
                f.writeln('            "z": ' + n.pos[1] + ',');
                f.writeln('            "tiles_x": ' + n.tiles[0] + ',');
                f.writeln('            "tiles_y": ' + n.tiles[1] + ',');
                f.writeln('            "frame_index": 0,');
                f.writeln('            "children": []');
                f.writeln(i < nodes.length - 1 ? "        }," : "        }");
            }
            f.writeln("    ]");
            f.writeln("}");
            f.close();
        }

        function exportGroupToPNG_(grp, outFile, resScale) {
            var opt = new ExportOptionsPNG24();
            opt.antiAliasing = true;
            opt.transparency = true;
            opt.artBoardClipping = true;

            // NEW: export scale (100% * resScale)
            opt.horizontalScale = 100.0 * resScale;
            opt.verticalScale = 100.0 * resScale;

            // 以降は現行のまま
            var vb = grp.visibleBounds; // [left, top, right, bottom]
            var left = vb[0], top = vb[1], right = vb[2], bottom = vb[3];
            var w = right - left;
            var h = top - bottom;
            if (w <= 0 || h <= 0) return false;

            var tmp = app.documents.add(DocumentColorSpace.RGB, w, h);
            var dup = grp.duplicate(tmp.layers[0], ElementPlacement.PLACEATBEGINNING);
            try { dup.left = 0; dup.top = h; } catch (e) { try { dup.position = [0, h]; } catch (_) { } }
            tmp.exportFile(outFile, ExportType.PNG24, opt);
            tmp.close(SaveOptions.DONOTSAVECHANGES);
            return true;
        }


        // ---------- UI ----------
        var w = new Window("dialog", "COA tools2 - Illustrator Exporter v0.1");
        w.orientation = "column";
        w.alignChildren = "fill";

        var g1 = w.add("group");
        g1.add("statictext", undefined, "Export Name:");
        var edName = g1.add("edittext", undefined, basenameWithoutExt(doc.name));
        edName.characters = 30;

        var g2 = w.add("group");
        g2.add("statictext", undefined, "Export Path:");
        // SAFE: use doc.path with try/catch (unsaved doc throws on .path/.fullName)
        var defaultPath = (function () {
            try { return doc.path.fsName; } catch (e) { return Folder.myDocuments.fsName; }
        })();
        var edPath = g2.add("edittext", undefined, defaultPath);

        edPath.characters = 40;
        var btSel = g2.add("button", undefined, "select");
        btSel.onClick = function () {
            var f = Folder.selectDialog("Select folder to export");
            if (f) edPath.text = f.fsName;
        };

        var g3 = w.add("group");
        g3.add("statictext", undefined, "Target Layer:");
        var ddLayer = g3.add("dropdownlist", undefined, []);
        for (var i = 0; i < doc.layers.length; i++) ddLayer.add("item", doc.layers[i].name);
        // 既定はアクティブレイヤー
        // pick top-level layer even if activeLayer is nested
        function getTopLevelLayerOf(layer) {
            var cur = layer;
            while (cur && cur.parent && cur.parent.typename !== "Document") cur = cur.parent;
            return cur && cur.typename === "Layer" ? cur : null;
        }
        var top = getTopLevelLayerOf(doc.activeLayer) || doc.layers[0];
        var activeIdx = 0;
        for (var j = 0; j < doc.layers.length; j++) { if (doc.layers[j].name === top.name) { activeIdx = j; break; } }
        ddLayer.selection = ddLayer.items[activeIdx];


        var g4 = w.add("group");
        var cbJSON = g4.add("checkbox", undefined, "Export JSON");
        cbJSON.value = true;


        // NEW: Resolution scale (x1..x4)
        var g5 = w.add("group");
        g5.add("statictext", undefined, "Resolution:");
        var ddScale = g5.add("dropdownlist", undefined, ["x1", "x2", "x3", "x4"]);
        ddScale.selection = 0; // default x1

        var g6 = w.add("group");
        var cbCenter = g6.add("checkbox", undefined, "Center bounds at origin");
        cbCenter.value = false;


        var gBtn = w.add("group");
        gBtn.alignment = "right";
        var ok = gBtn.add("button", undefined, "Export", { name: "ok" });
        gBtn.add("button", undefined, "Cancel", { name: "cancel" });

        ok.onClick = function () {
            $.level = 1;
            // debugger; // VSCode の attach で確実に止める
            $.writeln("[coa] start");
            $.writeln("[coa] layer count=" + doc.layers.length);
            $.writeln("[coa] selected index=" + ddLayer.selection.index + ", name=" + doc.layers[ddLayer.selection.index].name);

            var layer = doc.layers[ddLayer.selection.index];
            $.writeln("[coa] ddLayer.selection? " + (ddLayer.selection !== null));
            $.writeln("[coa] target layer name=" + layer.name + ", typename=" + layer.typename);


            if (!ddLayer.selection) { alert("No target layer selected."); return; }
            if (!layer || layer.typename !== "Layer") {
                alert("Selected entry is not a top-level Layer.");
                return;
            }

            // NEW: selected resolution scale
            var scaleMap = [1, 2, 3, 4];
            var resScale = scaleMap[ddScale.selection ? ddScale.selection.index : 0];
            $.writeln("[coa] resScale = x" + resScale);

            var centerAtOrigin = cbCenter.value;


            try {
                var exportName = String(edName.text || "export").replace(/\s+/g, "_");
                var baseFolder = new Folder(edPath.text);
                if (!baseFolder.exists) { alert("Export folder does not exist."); return; }

                var spritesFolder = new Folder(baseFolder.fsName + "/sprites");
                if (!spritesFolder.exists) spritesFolder.create();

                if (!layer) { alert("No target layer selected."); return; }

                var layerVB = getLayerVisibleBounds(layer);
                if (!layerVB) { alert("Target layer has no visible pageItems."); return; }

                // アートボード左上を原点とした座標系をImporterと合わせる
                var activeArtboard = doc.artboards[doc.artboards.getActiveArtboardIndex()];
                var artRect = activeArtboard.artboardRect; // [left, top, right, bottom]
                var artLeft = artRect[0];
                var artTop = artRect[1];
                var layerCenterX = (layerVB[0] + layerVB[2]) / 2;
                var layerCenterY = (layerVB[1] + layerVB[3]) / 2;
                var centerOffsetX = 0;
                var centerOffsetY = 0;
                if (centerAtOrigin) {
                    centerOffsetX = (layerCenterX - artLeft) * resScale;
                    centerOffsetY = (artTop - layerCenterY) * resScale;
                }


                // collect only immediate child GroupItems
                var allGroups = layer.groupItems;
                var groups = [];
                for (var gi = 0; gi < allGroups.length; gi++) {
                    var g = allGroups[gi];
                    if (g.parent === layer) groups.push(g);
                }
                if (groups.length === 0) { alert("No group directly under the selected layer."); return; }


                // 収集
                var used = {};
                var nodes = [];
                // Illustrator は座標が pt。PNG 100%/72ppi の前提で pt≈px
                for (var i = 0; i < groups.length; i++) {
                    var g = groups[i];
                    if (g.hidden || g.locked) continue;

                    // ファイル名ユニーク化
                    var safeName = makeUniqueName(g.name, used);
                    var outFile = new File(spritesFolder.fsName + "/" + safeName + ".png");

                    // 可視境界での原点座標（左, 上）
                    var vb = g.visibleBounds; // [left, top, right, bottom]
                    var gl = vb[0], gt = vb[1];

                    // JSON は左上(=gl,gt)を期待。アートボード左上を原点として扱う。
                    // 拡大倍率 resScale を position にも反映する（PNG の拡大と一致させるため）
                    var baseX = (gl - artLeft) * resScale;
                    var baseY = (artTop - gt) * resScale;
                    var dx = Math.round(baseX - centerOffsetX);
                    var dy = Math.round(baseY - centerOffsetY);

                    // 垂直方向の符号反転は importer 側で -position.y を取るため不要。
                    // もし上下が逆に見える場合のみ、ここで dy = -dy; にする。

                    var ok = exportGroupToPNG_(g, outFile, resScale);
                    if (ok) {
                        nodes.push({
                            name: safeName + ".png",
                            pos: [dx, -i, dy], // [x, z, y]
                            tiles: [1, 1]
                        });
                    }

                }

                if (cbJSON.value) {
                    writeJSON(baseFolder, exportName, nodes);
                }
                alert("Export finished.");
                w.close();
            } catch (e) {
                alert("Error: " + e);
            }
        };

        w.center();
        w.show();
    })();

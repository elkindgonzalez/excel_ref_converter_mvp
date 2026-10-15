#!/usr/bin/env node
/* eslint-disable no-console */
const assert = require("assert");
const path = require("path");
const Ops = require(path.join(__dirname, "..", "static", "purchase_ops.js"));

const HEADERS = [
  "ID SUBSIDIARIA",
  "iDENTIFICAR",
  "FECHA DE AJUSTE",
  "TIPO DE AJUSTE",
  "UBICACIÓN DE AJUSTE",
  "NOTA",
  "ID INTERNO ARTICULO",
  "NOMBRE DE ARTICULO",
  "AJUSTE DE CANTIDAD",
  "ESTADO",
  "CENTRO DE COSTOS",
  "SUBCENTRO DE COSTOS",
  "AREA",
  "SOLICITANTE",
];

function baseRow(id, overrides = {}) {
  const row = Ops.emptyRow(HEADERS, id);
  row.data["ID SUBSIDIARIA"] = "2";
  row.data.iDENTIFICAR = "A";
  row.data["FECHA DE AJUSTE"] = "15/10/2026";
  row.data["TIPO DE AJUSTE"] = "17";
  row.data["UBICACIÓN DE AJUSTE"] = "5";
  row.data["AJUSTE DE CANTIDAD"] = "-1";
  row.data.ESTADO = "Disponible";
  Object.assign(row.data, overrides.data || {});
  if (overrides.article) {
    return Ops.applyArticle(row, overrides.article);
  }
  return row;
}

const article = { internal_id: "21999", name: "MOTOR X", ref: "12948087" };
const article2 = { internal_id: "475", name: "CINTA", ref: "100002" };

let rows = [baseRow(1, { article }), baseRow(2, { data: { iDENTIFICAR: "B" } })];

// 1-3 duplicate
let dup = Ops.duplicateRow(rows, 0, 3);
assert.strictEqual(dup.newIndex, 1);
assert.strictEqual(dup.rows.length, 3);
assert.strictEqual(dup.newRow.data["ID INTERNO ARTICULO"], "21999");
assert.strictEqual(dup.newRow.data["NOMBRE DE ARTICULO"], "MOTOR X");
assert.strictEqual(dup.newRow.selectedArticle.ref, "12948087");
assert.ok(Ops.rowIdsUnique(dup.rows));
assert.notStrictEqual(dup.newRow.id, rows[0].id);
rows = dup.rows;

// 4 copy from previous
let copy = Ops.copyFieldFromPrevious(rows, 2, "ID SUBSIDIARIA");
assert.ok(copy.ok);
assert.strictEqual(copy.rows[2].data["ID SUBSIDIARIA"], "2");
copy = Ops.copyFieldFromPrevious(rows, 2, Ops.ARTICLE_COL);
assert.ok(copy.ok);
assert.strictEqual(copy.rows[2].data["ID INTERNO ARTICULO"], "21999");
assert.ok(Ops.articleConsistent(copy.rows[2]));
rows = copy.rows;

// 5 fill down
rows = [
  Ops.applyArticle(baseRow(1), article),
  baseRow(2),
  baseRow(3),
];
rows = Ops.fillDown(rows, "ESTADO", 0, 2);
assert.strictEqual(rows[1].data.ESTADO, "Disponible");
assert.strictEqual(rows[2].data.ESTADO, "Disponible");
rows = Ops.fillDown(rows, Ops.ARTICLE_COL, 0, 2);
assert.strictEqual(rows[2].data["ID INTERNO ARTICULO"], "21999");
assert.ok(Ops.articleConsistent(rows[1]));

// 6-7 clipboard / excel paste
const grid = Ops.parseClipboardTSV("2\tTAG\t15/10/2026\n3\tTAG2\t16/10/2026");
assert.strictEqual(grid.length, 2);
assert.deepStrictEqual(grid[0], ["2", "TAG", "15/10/2026"]);
let pasteRows = [baseRow(1), baseRow(2)];
let pasted = Ops.applyPaste(pasteRows, 0, "ID SUBSIDIARIA", grid, HEADERS);
assert.strictEqual(pasted.rows[0].data["ID SUBSIDIARIA"], "2");
assert.strictEqual(pasted.rows[0].data.iDENTIFICAR, "TAG");
assert.strictEqual(pasted.rows[1].data.iDENTIFICAR, "TAG2");

// Pegado alineado al orden de plantilla: col 7/8 = ID/nombre (derivados → error), col 9 = cantidad
const plantillaLine = [
  "2", "TAGX", "15/10/2026", "17", "5", "NOTA-X",
  "21999", "MOTOR X", "-9", "Disponible", "707", "7070", "TEATRO", "ANA",
];
pasted = Ops.applyPaste([baseRow(1)], 0, "ID SUBSIDIARIA", [plantillaLine], HEADERS);
assert.strictEqual(pasted.rows[0].data["NOTA"], "NOTA-X");
assert.strictEqual(pasted.rows[0].data["AJUSTE DE CANTIDAD"], "-9");
assert.strictEqual(pasted.rows[0].data.ESTADO, "Disponible");
assert.strictEqual(pasted.rows[0].data.SOLICITANTE, "ANA");
assert.ok(pasted.errors.some((e) => e.field === "ID INTERNO ARTICULO"));
assert.ok(pasted.errors.some((e) => e.field === "NOMBRE DE ARTICULO"));

// paste into derived article fields reports errors
pasted = Ops.applyPaste([baseRow(1)], 0, Ops.ARTICLE_ID, [["999"]], HEADERS);
assert.ok(pasted.errors.length >= 1);

// 8-10 article integrity after duplicate + change
rows = [Ops.applyArticle(baseRow(1), article)];
dup = Ops.duplicateRow(rows, 0, 2);
assert.ok(Ops.articleConsistent(dup.newRow));
const changed = Ops.applyArticle(dup.newRow, article2);
assert.strictEqual(changed.data["ID INTERNO ARTICULO"], "475");
assert.strictEqual(changed.data["NOMBRE DE ARTICULO"], "CINTA");
assert.ok(Ops.articleConsistent(changed));
const inconsistent = {
  id: 9,
  data: { ...changed.data, "NOMBRE DE ARTICULO": "WRONG" },
  selectedArticle: article2,
};
assert.strictEqual(Ops.articleConsistent(inconsistent), false);

// 11-12 export order and 14 columns — exact plantilla order (no alphabetical, no UI reorder)
const EXPECTED_PLANTILLA = [
  "ID SUBSIDIARIA",
  "iDENTIFICAR",
  "FECHA DE AJUSTE",
  "TIPO DE AJUSTE",
  "UBICACIÓN DE AJUSTE",
  "NOTA",
  "ID INTERNO ARTICULO",
  "NOMBRE DE ARTICULO",
  "AJUSTE DE CANTIDAD",
  "ESTADO",
  "CENTRO DE COSTOS",
  "SUBCENTRO DE COSTOS",
  "AREA",
  "SOLICITANTE",
];
assert.deepStrictEqual(HEADERS, EXPECTED_PLANTILLA);
assert.deepStrictEqual(Ops.plantillaColumns(HEADERS), EXPECTED_PLANTILLA);

const uiCols = Ops.visibleColumns(HEADERS);
assert.strictEqual(uiCols[0], Ops.ARTICLE_COL);
assert.deepStrictEqual(uiCols.slice(1), EXPECTED_PLANTILLA);
assert.strictEqual(uiCols.indexOf("ID INTERNO ARTICULO"), 7); // helper + 6 before
assert.strictEqual(uiCols.indexOf("NOMBRE DE ARTICULO"), 8);
assert.ok(uiCols.indexOf("ID INTERNO ARTICULO") < uiCols.indexOf("AJUSTE DE CANTIDAD"));
assert.ok(uiCols.indexOf("NOMBRE DE ARTICULO") < uiCols.indexOf("AJUSTE DE CANTIDAD"));

const ordered = Ops.exportOrder([
  Ops.applyArticle(baseRow(1, { data: { iDENTIFICAR: "FIRST" } }), article),
  Ops.applyArticle(baseRow(2, { data: { iDENTIFICAR: "SECOND" } }), article2),
], HEADERS);
assert.strictEqual(ordered[0].length, 14);
assert.strictEqual(HEADERS.length, 14);
assert.strictEqual(ordered[0][1], "FIRST");
assert.strictEqual(ordered[1][1], "SECOND");
assert.strictEqual(HEADERS[1], "iDENTIFICAR");
assert.strictEqual(ordered[0][6], "21999");
assert.strictEqual(ordered[0][7], "MOTOR X");
assert.strictEqual(ordered[0][8], "-1");
assert.strictEqual(ordered[1][6], "475");
assert.strictEqual(ordered[1][7], "CINTA");

// 14 no data loss on clone
const original = Ops.applyArticle(baseRow(1, { data: { NOTA: "ÁÉÍ" } }), article);
const cloned = Ops.cloneRow(original, 99);
assert.strictEqual(cloned.data.NOTA, "ÁÉÍ");
assert.strictEqual(original.data.NOTA, "ÁÉÍ");

// 15/16 widths resize
let widths = Ops.defaultColumnWidthsPx(HEADERS, 1920, 78);
assert.ok(widths[Ops.ARTICLE_COL] >= Ops.MIN_COL_PX[Ops.ARTICLE_COL]);
const before = widths["NOTA"];
widths = Ops.resizeColumn(widths, "NOTA", 40);
assert.strictEqual(widths.NOTA, before + 40);
widths = Ops.autoFitColumn(widths, "NOTA", 200);
assert.ok(widths.NOTA >= Ops.MIN_COL_PX.NOTA);

// responsive width distributions exist for smaller screens
for (const w of [1920, 1440, 1366, 1024]) {
  const dist = Ops.defaultColumnWidthsPx(HEADERS, w, 78);
  const sum = Object.values(dist).reduce((a, b) => a + b, 0);
  assert.ok(sum > 0);
  // At wide screens, prefer fitting; mins may force scroll on narrow.
  if (w >= 1440) {
    assert.ok(sum <= w - 78 + 200, `unexpected overflow at ${w}: ${sum}`);
  }
}

console.log("OK purchase UX ops tests");

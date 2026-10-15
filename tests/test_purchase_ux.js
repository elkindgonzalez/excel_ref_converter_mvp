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
copy = Ops.copyFieldFromPrevious(rows, 2, Ops.ARTICLE_ID);
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
rows = Ops.fillDown(rows, Ops.ARTICLE_ID, 0, 2);
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

// Pegado alineado al orden de plantilla (14 cols)
const plantillaLine = [
  "2", "TAGX", "15/10/2026", "17", "5", "NOTA-X",
  "21999", "MOTOR X", "-9", "Disponible", "707", "7070", "TEATRO", "ANA",
];
pasted = Ops.applyPaste([baseRow(1)], 0, "ID SUBSIDIARIA", [plantillaLine], HEADERS);
assert.strictEqual(pasted.rows[0].data["NOTA"], "NOTA-X");
assert.strictEqual(pasted.rows[0].data["AJUSTE DE CANTIDAD"], "-9");
assert.strictEqual(pasted.rows[0].data.ESTADO, "Disponible");
assert.strictEqual(pasted.rows[0].data.SOLICITANTE, "ANA");
// ID INTERNO recibe consulta de búsqueda (no fija ID sin selección)
assert.strictEqual(pasted.rows[0]._articleQuery, "21999");
assert.strictEqual(pasted.rows[0].data["ID INTERNO ARTICULO"], "");
assert.ok(pasted.errors.some((e) => e.field === "NOMBRE DE ARTICULO"));

// paste into nombre derivado reports errors
pasted = Ops.applyPaste([baseRow(1)], 0, Ops.ARTICLE_NAME, [["WRONG"]], HEADERS);
assert.ok(pasted.errors.length >= 1);

// paste into ID INTERNO starts search query
pasted = Ops.applyPaste([baseRow(1, { article })], 0, Ops.ARTICLE_ID, [["12948087"]], HEADERS);
assert.strictEqual(pasted.rows[0]._articleQuery, "12948087");
assert.strictEqual(pasted.rows[0].selectedArticle, null);

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

// 11-12: exactamente 14 columnas, sin auxiliar, orden plantilla
assert.deepStrictEqual(HEADERS, Ops.plantillaColumns(HEADERS));
assert.deepStrictEqual(Ops.visibleColumns(HEADERS), HEADERS);
assert.strictEqual(Ops.visibleColumns(HEADERS).length, 14);
assert.ok(!Ops.visibleColumns(HEADERS).includes(Ops.ARTICLE_COL));
assert.strictEqual(Ops.visibleColumns(HEADERS)[6], "ID INTERNO ARTICULO");
assert.strictEqual(Ops.visibleColumns(HEADERS)[7], "NOMBRE DE ARTICULO");
assert.strictEqual(Ops.visibleColumns(HEADERS)[8], "AJUSTE DE CANTIDAD");
assert.notDeepStrictEqual(Ops.visibleColumns(HEADERS), [...HEADERS].sort());

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

// 15/16 widths resize — sin columna auxiliar
let widths = Ops.defaultColumnWidthsPx(HEADERS, 1920, 78);
assert.strictEqual(Object.keys(widths).length, 14);
assert.ok(widths["ID INTERNO ARTICULO"] >= Ops.MIN_COL_PX["ID INTERNO ARTICULO"]);
const before = widths["NOTA"];
widths = Ops.resizeColumn(widths, "NOTA", 40);
assert.strictEqual(widths.NOTA, before + 40);
widths = Ops.autoFitColumn(widths, "NOTA", 200);
assert.ok(widths.NOTA >= Ops.MIN_COL_PX.NOTA);

for (const w of [1920, 1440, 1366, 1024]) {
  const dist = Ops.defaultColumnWidthsPx(HEADERS, w, 78);
  const sum = Object.values(dist).reduce((a, b) => a + b, 0);
  assert.ok(sum > 0);
  if (w >= 1440) {
    assert.ok(sum <= w - 78 + 200, `unexpected overflow at ${w}: ${sum}`);
  }
}

// Date validation + mask (FECHA DE AJUSTE only)
assert.deepStrictEqual(Ops.DATE_FIELDS, ["FECHA DE AJUSTE"]);
assert.strictEqual(Ops.DATE_FORMAT, "DD/MM/AAAA");
assert.ok(Ops.isDateField("FECHA DE AJUSTE"));
assert.ok(!Ops.isDateField("NOTA"));
assert.ok(Ops.isValidPurchaseDate("30/09/2026"));
assert.ok(Ops.isValidPurchaseDate("29/02/2024"));
assert.ok(!Ops.isValidPurchaseDate("29/02/2023"));
assert.ok(!Ops.isValidPurchaseDate("31/04/2026"));
assert.ok(!Ops.isValidPurchaseDate("2026-09-30"));
assert.strictEqual(Ops.isoToPurchaseDate("2026-09-30"), "30/09/2026");
assert.strictEqual(Ops.purchaseDateToIso("30/09/2026"), "2026-09-30");
assert.strictEqual(Ops.coercePurchaseDateInput("2026-09-30").value, "30/09/2026");
assert.strictEqual(Ops.coercePurchaseDateInput("31/02/2026").ok, false);

// Escritura continua sin barras
assert.strictEqual(Ops.maskPurchaseDateDigits("11102026"), "11/10/2026");
assert.strictEqual(Ops.maskPurchaseDateDigits("11"), "11");
assert.strictEqual(Ops.maskPurchaseDateDigits("1110"), "11/10");
assert.strictEqual(Ops.maskPurchaseDateDigits("111020"), "11/10/20");
assert.strictEqual(Ops.coercePurchaseDateInput("11102026").value, "11/10/2026");
assert.ok(Ops.coercePurchaseDateInput("11102026").ok);
assert.ok(Ops.isValidPurchaseDate(Ops.coercePurchaseDateInput("11102026").value));
assert.strictEqual(Ops.coercePurchaseDateInput("31022026").ok, false); // 31/02 inválido
assert.strictEqual(Ops.coercePurchaseDateInput("29022024").value, "29/02/2024");
assert.ok(Ops.coercePurchaseDateInput("29022024").ok);
assert.strictEqual(Ops.coercePurchaseDateInput("29022023").ok, false);

// Cursor coherente al enmascarar
const typed = Ops.maskPurchaseDateInput("11102026", 8);
assert.strictEqual(typed.value, "11/10/2026");
assert.strictEqual(typed.cursor, 10);
const mid = Ops.maskPurchaseDateInput("11/102026", 5); // after "11/10"
assert.strictEqual(mid.value, "11/10/2026");
assert.strictEqual(mid.cursor, 5);
const partial = Ops.maskPurchaseDateInput("1110", 4);
assert.strictEqual(partial.value, "11/10");
assert.strictEqual(partial.cursor, 5);
// Borrado: quitar último dígito de fecha completa
const deleted = Ops.maskPurchaseDateInput("11/10/202", 9);
assert.strictEqual(deleted.value, "11/10/202");
assert.ok(deleted.cursor <= deleted.value.length);
// Edición parcial con barras ya presentes
assert.strictEqual(Ops.maskPurchaseDateInput("11/10/2026", 10).value, "11/10/2026");
assert.strictEqual(Ops.coercePurchaseDateInput("11/10/2026").value, "11/10/2026");

const datePaste = Ops.applyPaste(
  [baseRow(1)],
  0,
  "FECHA DE AJUSTE",
  [["2026-10-15"], ["31/02/2026"], ["11102026"]],
  HEADERS,
);
assert.strictEqual(datePaste.rows[0].data["FECHA DE AJUSTE"], "15/10/2026");
assert.strictEqual(datePaste.rows[1].data["FECHA DE AJUSTE"], "31/02/2026");
assert.strictEqual(datePaste.rows[2].data["FECHA DE AJUSTE"], "11/10/2026");
assert.ok(datePaste.errors.some((e) => e.field === "FECHA DE AJUSTE"));

let filled = [
  Ops.applyArticle(baseRow(1, { data: { "FECHA DE AJUSTE": "30/09/2026" } }), article),
  baseRow(2),
];
filled = Ops.fillDown(filled, "FECHA DE AJUSTE", 0, 1);
assert.strictEqual(filled[1].data["FECHA DE AJUSTE"], "30/09/2026");
const dupDate = Ops.duplicateRow(filled, 0, 9);
assert.strictEqual(dupDate.newRow.data["FECHA DE AJUSTE"], "30/09/2026");

const dateErrors = Ops.validateDateFields(
  [baseRow(1, { data: { "FECHA DE AJUSTE": "31/02/2026" } })],
  ["FECHA DE AJUSTE"],
);
assert.ok(dateErrors.length >= 1);
assert.strictEqual(dateErrors[0].field, "FECHA DE AJUSTE");

// Article apply + change after resolve + nombre filled
let artRow = Ops.applyArticle(baseRow(1), article);
assert.strictEqual(artRow.data["ID INTERNO ARTICULO"], "21999");
assert.strictEqual(artRow.data["NOMBRE DE ARTICULO"], "MOTOR X");
artRow = Ops.applyArticle(artRow, article2);
assert.strictEqual(artRow.data["ID INTERNO ARTICULO"], "475");
assert.strictEqual(artRow.data["NOMBRE DE ARTICULO"], "CINTA");
const cleared = Ops.clearArticle(artRow);
assert.strictEqual(cleared.data["ID INTERNO ARTICULO"], "");
assert.strictEqual(cleared.data["NOMBRE DE ARTICULO"], "");
assert.strictEqual(cleared.selectedArticle, null);

const dupResolved = Ops.duplicateRow([Ops.applyArticle(baseRow(1), article)], 0, 77);
assert.strictEqual(dupResolved.newRow.data["ID INTERNO ARTICULO"], "21999");
assert.strictEqual(dupResolved.newRow.selectedArticle.ref, "12948087");
const copyArt = Ops.copyFieldFromPrevious(
  [Ops.applyArticle(baseRow(1), article), baseRow(2)],
  1,
  Ops.ARTICLE_ID,
);
assert.ok(copyArt.ok);
assert.strictEqual(copyArt.rows[1].data["ID INTERNO ARTICULO"], "21999");
assert.strictEqual(copyArt.rows[1].data["NOMBRE DE ARTICULO"], "MOTOR X");

console.log("OK purchase UX ops tests");

"""Abrir CSV de compras: parseo, edición, round-trip y catálogo intacto."""
from __future__ import annotations

import csv
import hashlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


def sample_row(**overrides) -> dict:
    row = {
        "ID SUBSIDIARIA": "2",
        "iDENTIFICAR": "280926-PRUEBA",
        "FECHA DE AJUSTE": "30/09/2025",
        "TIPO DE AJUSTE": "17",
        "UBICACIÓN DE AJUSTE": "5",
        "NOTA": "CONSUMO DE ASEO; con; punto y coma",
        "ID INTERNO ARTICULO": "21999",
        "NOMBRE DE ARTICULO": "MOTOR GENERATOR CÓD: HEC (REF-12948087)",
        "AJUSTE DE CANTIDAD": "-1",
        "ESTADO": "Disponible",
        "CENTRO DE COSTOS": "707",
        "SUBCENTRO DE COSTOS": "7070",
        "AREA": "TEATRO",
        "SOLICITANTE": "ANA TRUJILLO",
    }
    row.update(overrides)
    return row


class OpenPurchaseCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="open_csv_"))
        self.catalog_path = self.tmp / "catalogo_articulos.csv"
        self.backup_dir = self.tmp / "backups"
        self.backup_dir.mkdir()
        self._write_catalog([
            ("21999", "MOTOR GENERATOR CÓD: HEC (REF-12948087)", "12948087"),
            ("475", "CINTA AISLANTE ÁÉÍ (REF-100002)", "100002"),
            ("999", "ZERO PAD (REF-00123)", "00123"),
        ])
        self.patches = [
            mock.patch.object(app, "CATALOG_PATH", self.catalog_path),
            mock.patch.object(app, "BACKUP_DIR", self.backup_dir),
            mock.patch.object(app, "DATA_DIR", self.tmp),
            mock.patch.object(app, "CATALOG_META_PATH", self.tmp / "catalog_meta.json"),
        ]
        for p in self.patches:
            p.start()
        app.DOWNLOADS.clear()
        self.catalog_fp_before = self._catalog_digest()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_catalog(self, rows: list[tuple[str, str, str]]) -> None:
        with self.catalog_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=app.CATALOG_CSV_FIELDS)
            writer.writeheader()
            for internal_id, name, ref in rows:
                writer.writerow({"ID interno": internal_id, "Nombre": name, "Ref": ref})

    def _catalog_digest(self) -> str:
        data = self.catalog_path.read_bytes()
        return hashlib.sha256(data).hexdigest()

    def _assert_catalog_untouched(self) -> None:
        self.assertEqual(self._catalog_digest(), self.catalog_fp_before)

    def test_01_open_generated_csv_recovers_all_rows(self):
        data, filename, errors = app.export_purchase_csv([
            sample_row(),
            sample_row(**{
                "iDENTIFICAR": "SEGUNDA",
                "ID INTERNO ARTICULO": "475",
                "NOMBRE DE ARTICULO": "CINTA AISLANTE ÁÉÍ (REF-100002)",
                "NOTA": 'Texto con "comillas" y\nsalto',
            }),
        ])
        self.assertFalse(errors)
        self.assertTrue(filename.endswith(".csv"))

        parsed = app.parse_purchase_csv_bytes(data)
        self.assertTrue(parsed["ok"], parsed.get("errors"))
        self.assertEqual(parsed["row_count"], 2)
        self.assertEqual(parsed["headers"], app.PURCHASE_HEADERS)
        self.assertEqual(parsed["rows"][0]["ID INTERNO ARTICULO"], "21999")
        self.assertEqual(parsed["rows"][1]["iDENTIFICAR"], "SEGUNDA")
        # Semicolon inside quoted field preserved
        self.assertIn("punto y coma", parsed["rows"][0]["NOTA"])
        self._assert_catalog_untouched()

    def test_02_preserve_original_values_and_order(self):
        rows_in = [
            sample_row(**{"iDENTIFICAR": "A", "AJUSTE DE CANTIDAD": "-3"}),
            sample_row(**{"iDENTIFICAR": "B", "ID INTERNO ARTICULO": "475",
                          "NOMBRE DE ARTICULO": "CINTA AISLANTE ÁÉÍ (REF-100002)"}),
            sample_row(**{"iDENTIFICAR": "C", "NOTA": ""}),
        ]
        data, _, errors = app.export_purchase_csv(rows_in)
        self.assertFalse(errors)
        parsed = app.parse_purchase_csv_bytes(data)
        self.assertTrue(parsed["ok"])
        self.assertEqual([r["iDENTIFICAR"] for r in parsed["rows"]], ["A", "B", "C"])
        self.assertEqual(parsed["rows"][2]["NOTA"], "")
        self.assertEqual(parsed["rows"][0]["AJUSTE DE CANTIDAD"], "-3")

    def test_03_edit_add_delete_duplicate_flow(self):
        data, _, _ = app.export_purchase_csv([sample_row(), sample_row(**{"iDENTIFICAR": "B"})])
        parsed = app.parse_purchase_csv_bytes(data)
        rows = [dict(r) for r in parsed["rows"]]
        # Edit
        rows[0]["NOTA"] = "EDITADO"
        # Add
        rows.append(sample_row(**{"iDENTIFICAR": "NUEVA", "ID INTERNO ARTICULO": "999",
                                  "NOMBRE DE ARTICULO": "ZERO PAD (REF-00123)"}))
        # Delete middle
        del rows[1]
        # Duplicate first
        rows.insert(1, dict(rows[0]))
        out, filename, errors = app.export_purchase_csv(rows, source_filename="compras_origen.csv")
        self.assertFalse(errors)
        self.assertEqual(filename, "compras_origen_editado.csv")
        reparsed = app.parse_purchase_csv_bytes(out)
        self.assertEqual(reparsed["row_count"], 3)
        self.assertEqual(reparsed["rows"][0]["NOTA"], "EDITADO")
        self.assertEqual(reparsed["rows"][1]["NOTA"], "EDITADO")
        self.assertEqual(reparsed["rows"][2]["iDENTIFICAR"], "NUEVA")
        self._assert_catalog_untouched()

    def test_04_copy_field_semantics_via_ops_not_required_server(self):
        # Server keeps row dicts; copy is client-side. Ensure export of copied values works.
        a = sample_row(**{"CENTRO DE COSTOS": "111"})
        b = sample_row(**{"iDENTIFICAR": "B", "CENTRO DE COSTOS": ""})
        b["CENTRO DE COSTOS"] = a["CENTRO DE COSTOS"]
        data, _, errors = app.export_purchase_csv([a, b])
        self.assertFalse(errors)
        parsed = app.parse_purchase_csv_bytes(data)
        self.assertEqual(parsed["rows"][1]["CENTRO DE COSTOS"], "111")

    def test_05_article_association_and_unknown_id(self):
        data, _, _ = app.export_purchase_csv([sample_row()])
        parsed = app.parse_purchase_csv_bytes(data)
        rows = list(parsed["rows"])
        rows.append(sample_row(**{
            "iDENTIFICAR": "X",
            "ID INTERNO ARTICULO": "88888",
            "NOMBRE DE ARTICULO": "DESCONOCIDO",
        }))
        annotated, warnings = app.annotate_purchase_rows_with_catalog(rows)
        self.assertIsNotNone(annotated[0]["selectedArticle"])
        self.assertEqual(annotated[0]["selectedArticle"]["internal_id"], "21999")
        self.assertIsNone(annotated[1]["selectedArticle"])
        self.assertEqual(annotated[1]["data"]["ID INTERNO ARTICULO"], "88888")
        self.assertTrue(any("88888" in w["message"] for w in warnings))
        # Unknown ID still present — export must fail validation, not silently drop
        _out, _fn, errors = app.export_purchase_csv([r["data"] for r in annotated])
        self.assertTrue(errors)
        self.assertTrue(any(e["field"] == "ID INTERNO ARTICULO" for e in errors))
        self._assert_catalog_untouched()

    def test_06_dates_valid_kept_invalid_warned(self):
        good = sample_row(**{"FECHA DE AJUSTE": "11/10/2026"})
        data, _, errors = app.export_purchase_csv([good])
        self.assertFalse(errors)
        parsed = app.parse_purchase_csv_bytes(data)
        self.assertEqual(parsed["rows"][0]["FECHA DE AJUSTE"], "11/10/2026")

        bad_rows = [dict(parsed["rows"][0])]
        bad_rows[0]["FECHA DE AJUSTE"] = "31/02/2026"
        annotated, warnings = app.annotate_purchase_rows_with_catalog(bad_rows)
        self.assertEqual(annotated[0]["data"]["FECHA DE AJUSTE"], "31/02/2026")
        self.assertTrue(any(w["field"] == "FECHA DE AJUSTE" for w in warnings))
        # Fix and re-export
        fixed = dict(annotated[0]["data"])
        fixed["FECHA DE AJUSTE"] = "28/02/2026"
        out, _, err2 = app.export_purchase_csv([fixed])
        self.assertFalse(err2)
        again = app.parse_purchase_csv_bytes(out)
        self.assertEqual(again["rows"][0]["FECHA DE AJUSTE"], "28/02/2026")

    def test_07_reject_incompatible_headers(self):
        bad = "COL1;COL2\r\na;b\r\n".encode("utf-8-sig")
        parsed = app.parse_purchase_csv_bytes(bad)
        self.assertFalse(parsed["ok"])
        self.assertTrue(any(e["type"] in ("header_missing", "header_count") for e in parsed["errors"]))

        # Wrong order
        shuffled = list(app.PURCHASE_HEADERS)
        shuffled[0], shuffled[1] = shuffled[1], shuffled[0]
        buf = io.StringIO(newline="")
        writer = csv.writer(buf, delimiter=";", lineterminator="\r\n")
        writer.writerow(shuffled)
        writer.writerow([sample_row().get(h, "") for h in shuffled])
        parsed2 = app.parse_purchase_csv_bytes(buf.getvalue().encode("utf-8-sig"))
        self.assertFalse(parsed2["ok"])
        self.assertTrue(any(e["type"] == "header_order" for e in parsed2["errors"]))

    def test_08_round_trip_create_open_edit_download(self):
        original_path = self.tmp / "compras_original.csv"
        data1, fn1, err1 = app.export_purchase_csv([
            sample_row(),
            sample_row(**{
                "iDENTIFICAR": "DOS",
                "ID INTERNO ARTICULO": "475",
                "NOMBRE DE ARTICULO": "CINTA AISLANTE ÁÉÍ (REF-100002)",
            }),
        ])
        self.assertFalse(err1)
        original_path.write_bytes(data1)
        # Simulate "open" — read bytes, do not overwrite original on export
        opened = app.parse_purchase_csv_bytes(original_path.read_bytes())
        self.assertTrue(opened["ok"])
        rows = [dict(r) for r in opened["rows"]]
        rows[0]["NOTA"] = "DESPUES DE EDITAR"
        rows.append(sample_row(**{
            "iDENTIFICAR": "TRES",
            "ID INTERNO ARTICULO": "999",
            "NOMBRE DE ARTICULO": "ZERO PAD (REF-00123)",
        }))
        data2, fn2, err2 = app.export_purchase_csv(rows, source_filename=original_path.name)
        self.assertFalse(err2)
        self.assertEqual(fn2, "compras_original_editado.csv")
        # Original file on disk unchanged
        self.assertEqual(original_path.read_bytes(), data1)
        final = app.parse_purchase_csv_bytes(data2)
        self.assertEqual(final["row_count"], 3)
        self.assertEqual(final["rows"][0]["NOTA"], "DESPUES DE EDITAR")
        self.assertEqual(final["rows"][2]["iDENTIFICAR"], "TRES")
        # Compare import vs export for unchanged row
        self.assertEqual(final["rows"][1]["ID INTERNO ARTICULO"], "475")
        self._assert_catalog_untouched()

    def test_09_edited_filename_helper(self):
        self.assertEqual(app.edited_purchase_filename("foo.csv"), "foo_editado.csv")
        self.assertEqual(app.edited_purchase_filename("path/to/bar.CSV"), "bar_editado.csv")
        self.assertTrue(app.edited_purchase_filename("").endswith("_editado.csv"))

    def test_10_ref_not_auto_replaced_with_id_on_annotate(self):
        rows = [sample_row(**{
            "ID INTERNO ARTICULO": "12948087",  # commercial Ref
            "NOMBRE DE ARTICULO": "",
        })]
        annotated, warnings = app.annotate_purchase_rows_with_catalog(rows)
        self.assertEqual(annotated[0]["data"]["ID INTERNO ARTICULO"], "12948087")
        self.assertIsNone(annotated[0]["selectedArticle"])
        self.assertTrue(any("Ref comercial" in w["message"] for w in warnings))

    def test_11_quoted_multiline_and_special_chars(self):
        row = sample_row(**{
            "NOTA": "línea1\nlínea2;más",
            "NOMBRE DE ARTICULO": "MOTOR GENERATOR CÓD: HEC (REF-12948087)",
        })
        data, _, errors = app.export_purchase_csv([row])
        self.assertFalse(errors)
        parsed = app.parse_purchase_csv_bytes(data)
        self.assertTrue(parsed["ok"])
        self.assertIn("línea1", parsed["rows"][0]["NOTA"])
        self.assertIn("línea2;más", parsed["rows"][0]["NOTA"])
        self.assertIn("ÁÉÍ" if False else "CÓD", parsed["rows"][0]["NOMBRE DE ARTICULO"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import io
import shutil
import tempfile
import time
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
        "NOTA": "CONSUMO DE ASEO",
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


class PurchaseFormTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="purchase_test_"))
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
        ]
        for p in self.patches:
            p.start()
        app.DOWNLOADS.clear()

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

    def test_01_create_without_input_file(self):
        data, filename, errors = app.export_purchase_csv([sample_row()])
        self.assertEqual(errors, [])
        self.assertTrue(filename.endswith(".csv"))
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))

    def test_02_03_04_suggest_and_assign_id_name(self):
        result = app.suggest_catalog("12948087", limit=10)
        self.assertEqual(len(result["items"]), 1)
        item = result["items"][0]
        self.assertEqual(item["internal_id"], "21999")
        self.assertEqual(item["ref"], "12948087")
        self.assertIn("MOTOR", item["name"])

        data, _filename, errors = app.export_purchase_csv([sample_row(
            **{
                "ID INTERNO ARTICULO": item["internal_id"],
                "NOMBRE DE ARTICULO": item["name"],
            }
        )])
        self.assertEqual(errors, [])
        text = data.decode("utf-8-sig")
        self.assertIn("21999", text)
        self.assertIn("MOTOR GENERATOR", text)

    def test_05_add_edit_delete_rows_logic(self):
        rows = [sample_row(), sample_row(**{"iDENTIFICAR": "B", "ID INTERNO ARTICULO": "475",
                                            "NOMBRE DE ARTICULO": "CINTA AISLANTE ÁÉÍ (REF-100002)"})]
        # "delete" second row by exporting only first
        data, _, errors = app.export_purchase_csv(rows[:1])
        self.assertEqual(errors, [])
        parsed = list(csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(len(parsed), 2)  # header + 1
        # edit quantity
        edited = sample_row(**{"AJUSTE DE CANTIDAD": "-3"})
        data2, _, errors2 = app.export_purchase_csv([edited])
        self.assertEqual(errors2, [])
        self.assertIn("-3", data2.decode("utf-8-sig"))

    def test_06_07_headers_order_and_template_compat(self):
        expected = [
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
        ]
        self.assertEqual(app.PURCHASE_HEADERS, expected)
        self.assertEqual(len(app.PURCHASE_HEADERS), 14)
        # Must not be alphabetical (regression guard for iDENTIFICAR / ID INTERNO placement).
        self.assertNotEqual(app.PURCHASE_HEADERS, sorted(app.PURCHASE_HEADERS))
        self.assertEqual(app.PURCHASE_HEADERS.index("ID INTERNO ARTICULO"), 6)
        self.assertEqual(app.PURCHASE_HEADERS.index("NOMBRE DE ARTICULO"), 7)
        self.assertLess(
            app.PURCHASE_HEADERS.index("NOMBRE DE ARTICULO"),
            app.PURCHASE_HEADERS.index("AJUSTE DE CANTIDAD"),
        )

        contract = app.purchase_template_contract()
        self.assertEqual(contract["headers"], expected)
        self.assertEqual(contract["delimiter"], ";")
        self.assertEqual(contract["encoding"], "utf-8-sig")
        self.assertEqual(contract["line_terminator"], "CRLF")

        row = sample_row()
        data, _, errors = app.export_purchase_csv([row])
        self.assertEqual(errors, [])
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
        raw = data.decode("utf-8-sig")
        self.assertIn("\r\n", raw)
        parsed = list(csv.reader(io.StringIO(raw), delimiter=";"))
        self.assertEqual(parsed[0], expected)
        self.assertEqual(parsed[0][1], "iDENTIFICAR")
        # Diligenced values land in the same positions as the plantilla headers.
        for idx, header in enumerate(expected):
            self.assertEqual(parsed[1][idx], row[header], msg=f"mismatch at col {header}")

    def test_fecha_formato_y_calendario(self):
        contract = app.purchase_template_contract()
        self.assertEqual(contract["date_fields"], ["FECHA DE AJUSTE"])
        self.assertEqual(contract["date_format"], "DD/MM/AAAA")
        self.assertEqual(app.PURCHASE_DATE_FIELDS, ["FECHA DE AJUSTE"])

        self.assertTrue(app.is_valid_purchase_date("30/09/2026"))
        self.assertTrue(app.is_valid_purchase_date("29/02/2024"))  # bisiesto
        self.assertFalse(app.is_valid_purchase_date("29/02/2023"))
        self.assertFalse(app.is_valid_purchase_date("31/04/2026"))
        self.assertFalse(app.is_valid_purchase_date("00/01/2026"))
        self.assertFalse(app.is_valid_purchase_date("2026-09-30"))  # ISO year-first
        self.assertFalse(app.is_valid_purchase_date("32/01/2026"))
        self.assertTrue(app.is_valid_purchase_date("15-10-2026"))  # separadores alternativos → válido
        # Máscara de 8 dígitos continuos
        self.assertEqual(app.mask_purchase_date_digits("11102026"), "11/10/2026")
        self.assertTrue(app.is_valid_purchase_date("11102026"))
        self.assertFalse(app.is_valid_purchase_date("31022026"))

        ok_data, _, ok_errors = app.export_purchase_csv([sample_row(**{"FECHA DE AJUSTE": "30/09/2026"})])
        self.assertEqual(ok_errors, [])
        parsed = list(csv.reader(io.StringIO(ok_data.decode("utf-8-sig")), delimiter=";"))
        fecha_idx = app.PURCHASE_HEADERS.index("FECHA DE AJUSTE")
        self.assertEqual(parsed[1][fecha_idx], "30/09/2026")
        self.assertNotIn("2026-09-30", ok_data.decode("utf-8-sig"))

        digits_data, _, digits_errors = app.export_purchase_csv([
            sample_row(**{"FECHA DE AJUSTE": "11102026"}),
        ])
        self.assertEqual(digits_errors, [])
        digits_parsed = list(csv.reader(io.StringIO(digits_data.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(digits_parsed[1][fecha_idx], "11/10/2026")

        _bad, _fn, bad_errors = app.export_purchase_csv([sample_row(**{"FECHA DE AJUSTE": "31/02/2026"})])
        self.assertTrue(any(e.get("field") == "FECHA DE AJUSTE" for e in bad_errors))
        self.assertTrue(any("Fecha inválida" in e["message"] for e in bad_errors))

        _bad2, _fn2, empty_errors = app.export_purchase_csv([sample_row(**{"FECHA DE AJUSTE": ""})])
        self.assertTrue(any(e["field"] == "FECHA DE AJUSTE" for e in empty_errors))

    def test_08_special_chars_and_empty_optional(self):
        row = sample_row(
            **{
                "NOTA": "CONSUMO ÁÉÍÑ — “especial”",
                "CENTRO DE COSTOS": "",
                "SUBCENTRO DE COSTOS": "",
                "AREA": "",
                "SOLICITANTE": "",
            }
        )
        data, _, errors = app.export_purchase_csv([row])
        self.assertEqual(errors, [])
        text = data.decode("utf-8-sig")
        self.assertIn("ÁÉÍÑ", text)

    def test_09_nonexistent_article(self):
        _data, _filename, errors = app.export_purchase_csv([
            sample_row(**{"ID INTERNO ARTICULO": "999999", "NOMBRE DE ARTICULO": "X"}),
        ])
        self.assertTrue(errors)
        self.assertTrue(any(
            "no existe" in e["message"] or "No hay coincidencia" in e["message"]
            for e in errors
        ))

    def test_09b_mismatched_name(self):
        _data, _filename, errors = app.export_purchase_csv([
            sample_row(**{"NOMBRE DE ARTICULO": "NOMBRE INCORRECTO"}),
        ])
        self.assertTrue(any("no corresponde" in e["message"] for e in errors))

    def test_resolve_ref_id_ambiguous_and_nombre_opcional(self):
        # 1-4: Ref → ID + nombre; ID directo; nombre vacío ok
        resolved_ref = app.resolve_article_code("12948087")
        self.assertEqual(resolved_ref["status"], "resolved")
        self.assertEqual(resolved_ref["item"]["internal_id"], "21999")
        self.assertEqual(resolved_ref["item"]["match"], "ref")

        resolved_id = app.resolve_article_code("21999")
        self.assertEqual(resolved_id["status"], "resolved")
        self.assertEqual(resolved_id["item"]["internal_id"], "21999")

        data, _, errors = app.export_purchase_csv([
            sample_row(**{
                "ID INTERNO ARTICULO": "12948087",
                "NOMBRE DE ARTICULO": "",
            }),
        ])
        self.assertEqual(errors, [])
        parsed = list(csv.reader(io.StringIO(data.decode("utf-8-sig")), delimiter=";"))
        id_idx = app.PURCHASE_HEADERS.index("ID INTERNO ARTICULO")
        name_idx = app.PURCHASE_HEADERS.index("NOMBRE DE ARTICULO")
        self.assertEqual(parsed[1][id_idx], "21999")
        self.assertIn("MOTOR GENERATOR", parsed[1][name_idx])
        self.assertNotIn("NOMBRE DE ARTICULO", app.PURCHASE_REQUIRED_FIELDS)
        self.assertIn("NOMBRE DE ARTICULO", app.PURCHASE_OPTIONAL_FIELDS)

        # 5: inexistente
        missing = app.resolve_article_code("REF-INEXISTENTE")
        self.assertEqual(missing["status"], "not_found")

        # 6: ambigüedad — Ref de A e ID de B
        catalog = app.load_persistent_catalog()
        catalog["12948087"] = app.CatalogItem(
            "12948087",
            "ARTICULO CUYO ID ES LA REF DE OTRO",
            "OTRA-REF-999",
        )
        with mock.patch.object(app, "load_persistent_catalog", return_value=catalog):
            amb = app.resolve_article_code("12948087")
        self.assertEqual(amb["status"], "ambiguous")
        self.assertEqual(len(amb["candidates"]), 2)

        # 7: cambio de artículo (exportar otra Ref)
        data2, _, err2 = app.export_purchase_csv([
            sample_row(**{
                "ID INTERNO ARTICULO": "100002",
                "NOMBRE DE ARTICULO": "",
            }),
        ])
        self.assertEqual(err2, [])
        parsed2 = list(csv.reader(io.StringIO(data2.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(parsed2[1][id_idx], "475")

        # 8: duplicación lógica — dos filas resueltas
        rows = [
            sample_row(**{"iDENTIFICAR": "A", "ID INTERNO ARTICULO": "12948087", "NOMBRE DE ARTICULO": ""}),
            sample_row(**{"iDENTIFICAR": "A-COPY", "ID INTERNO ARTICULO": "12948087", "NOMBRE DE ARTICULO": ""}),
        ]
        data3, _, err3 = app.export_purchase_csv(rows)
        self.assertEqual(err3, [])
        parsed3 = list(csv.reader(io.StringIO(data3.decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(parsed3[1][id_idx], "21999")
        self.assertEqual(parsed3[2][id_idx], "21999")

        # 10: preview == export payload
        preview = app.preview_purchase_rows([
            sample_row(**{"ID INTERNO ARTICULO": "12948087", "NOMBRE DE ARTICULO": ""}),
        ])
        self.assertTrue(preview["ok"])
        self.assertEqual(preview["headers"], app.PURCHASE_HEADERS)
        export_data, _, export_errors = app.export_purchase_csv([
            sample_row(**{"ID INTERNO ARTICULO": "12948087", "NOMBRE DE ARTICULO": ""}),
        ])
        self.assertEqual(export_errors, [])
        export_rows = list(csv.reader(io.StringIO(export_data.decode("utf-8-sig")), delimiter=";"))
        for idx, header in enumerate(preview["headers"]):
            self.assertEqual(preview["rows"][0][header], export_rows[1][idx])

        # 13: 14 columnas
        self.assertEqual(len(preview["headers"]), 14)
        self.assertEqual(preview["headers"][1], "iDENTIFICAR")

    def test_10_large_catalog_suggest(self):
        big = {str(i): app.CatalogItem(str(i), f"ARTICULO {i} REF-{i}", str(100000 + i)) for i in range(1, 20001)}
        big["21999"] = app.CatalogItem("21999", "TARGET NAME", "12948087")
        with mock.patch.object(app, "load_persistent_catalog", return_value=big):
            with mock.patch.object(app, "catalog_count", return_value=len(big)):
                started = time.perf_counter()
                result = app.suggest_catalog("12948087", limit=20)
                elapsed = time.perf_counter() - started
        self.assertEqual(result["items"][0]["internal_id"], "21999")
        self.assertLess(elapsed, 2.0)
        self.assertLessEqual(len(result["items"]), 20)

    def test_11_catalog_import_still_works(self):
        inv = "ID interno,Nombre,Nombre para mostrar\n88001,NUEVO,555\n".encode("utf-8-sig")
        preview = app.build_import_preview(inv, "inv.csv", self.catalog_path)
        self.assertEqual(preview.new_count, 1)
        result = app.apply_import_preview(preview, self.catalog_path)
        self.assertEqual(result["applied_new"], 1)
        catalog = app.load_persistent_catalog(self.catalog_path)
        self.assertIn("88001", catalog)
        self.assertIn("21999", catalog)

    def test_12_no_persistence_of_generated_files(self):
        data, filename, errors = app.export_purchase_csv([sample_row()])
        self.assertEqual(errors, [])
        token = app.store_download(filename, data, "text/csv; charset=utf-8")
        self.assertIn(token, app.DOWNLOADS)
        # Ensure nothing written under DATA_DIR except catalog/backups scaffolding
        generated = [p for p in self.tmp.rglob("*") if p.is_file() and p.name.startswith("compras_")]
        self.assertEqual(generated, [])
        # Token download is ephemeral memory only
        with app.DOWNLOADS_LOCK:
            stored = app.DOWNLOADS[token]
        self.assertEqual(stored[1], filename)
        self.assertEqual(stored[2], data)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import csv
import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import app
from tests.xlsx_util import build_xlsx


class IsolatedCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="catalog_test_"))
        self.catalog_path = self.tmp / "catalogo_articulos.csv"
        self.backup_dir = self.tmp / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._write_catalog([])
        self.patches = [
            mock.patch.object(app, "CATALOG_PATH", self.catalog_path),
            mock.patch.object(app, "BACKUP_DIR", self.backup_dir),
            mock.patch.object(app, "DATA_DIR", self.tmp),
            mock.patch.object(app, "CATALOG_META_PATH", self.tmp / "catalog_meta.json"),
        ]
        for p in self.patches:
            p.start()

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

    def _read_catalog(self) -> dict[str, app.CatalogItem]:
        return app.load_persistent_catalog(self.catalog_path)

    def _inventory_csv(self, rows: list[list[str]], delimiter: str = ",") -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue().encode("utf-8-sig")

    def _purchase_csv(self, rows: list[list[str]], delimiter: str = ",") -> bytes:
        return self._inventory_csv(rows, delimiter=delimiter)


class CatalogImportTests(IsolatedCatalogTest):
    def test_01_import_new_articles(self):
        data = self._inventory_csv([
            ["ID interno", "Nombre", "Nombre para mostrar"],
            ["21999", "MOTOR GENERATOR CÓD: HEC-200-100 UND(REF-12948087)", "12948087"],
            ["22000", "OTRO ARTÍCULO (REF-99001)", "99001"],
        ])
        preview = app.build_import_preview(data, "inv.csv", self.catalog_path)
        self.assertEqual(preview.new_count, 2)
        result = app.apply_import_preview(preview, self.catalog_path)
        self.assertEqual(result["applied_new"], 2)
        catalog = self._read_catalog()
        self.assertEqual(catalog["21999"].ref, "12948087")
        self.assertIn("MOTOR GENERATOR", catalog["21999"].name)

    def test_02_update_existing_articles(self):
        self._write_catalog([
            ("21999", "NOMBRE VIEJO", "12948087"),
        ])
        data = self._inventory_csv([
            ["ID interno", "Nombre", "Nombre para mostrar"],
            ["21999", "MOTOR GENERATOR NUEVO (REF-12948087)", "12948087"],
        ])
        preview = app.build_import_preview(data, "inv.csv", self.catalog_path)
        self.assertEqual(preview.update_count, 1)
        app.apply_import_preview(preview, self.catalog_path)
        catalog = self._read_catalog()
        self.assertEqual(catalog["21999"].name, "MOTOR GENERATOR NUEVO (REF-12948087)")

    def test_03_preserve_absent_articles(self):
        self._write_catalog([
            ("100", "KEEP ME", "111"),
            ("200", "ALSO KEEP", "222"),
        ])
        data = self._inventory_csv([
            ["ID interno", "Nombre", "Nombre para mostrar"],
            ["300", "NEW ITEM", "333"],
        ])
        preview = app.build_import_preview(data, "inv.csv", self.catalog_path)
        app.apply_import_preview(preview, self.catalog_path)
        catalog = self._read_catalog()
        self.assertIn("100", catalog)
        self.assertIn("200", catalog)
        self.assertIn("300", catalog)
        self.assertEqual(len(catalog), 3)

    def test_04_keep_fields_when_empty(self):
        self._write_catalog([
            ("21999", "NOMBRE ORIGINAL", "12948087"),
        ])
        data = self._inventory_csv([
            ["ID interno", "Nombre", "Nombre para mostrar"],
            ["21999", "", "12948087"],
        ])
        preview = app.build_import_preview(data, "inv.csv", self.catalog_path)
        self.assertEqual(preview.update_count, 0)
        self.assertEqual(preview.unchanged_count, 1)
        app.apply_import_preview(preview, self.catalog_path)
        catalog = self._read_catalog()
        self.assertEqual(catalog["21999"].name, "NOMBRE ORIGINAL")

    def test_05_duplicate_refs_in_file(self):
        data = self._inventory_csv([
            ["ID interno", "Nombre", "Nombre para mostrar"],
            ["1", "A", "REFX"],
            ["2", "B", "REFX"],
        ])
        preview = app.build_import_preview(data, "inv.csv", self.catalog_path)
        self.assertGreaterEqual(preview.conflict_count, 1)
        self.assertEqual(preview.new_count, 1)

    def test_06_ref_belongs_to_other_id(self):
        self._write_catalog([
            ("1", "EXISTENTE", "SHARED"),
        ])
        data = self._inventory_csv([
            ["ID interno", "Nombre", "Nombre para mostrar"],
            ["2", "NUEVO", "SHARED"],
        ])
        preview = app.build_import_preview(data, "inv.csv", self.catalog_path)
        self.assertEqual(preview.conflict_count, 1)
        self.assertEqual(preview.new_count, 0)
        app.apply_import_preview(preview, self.catalog_path)
        catalog = self._read_catalog()
        self.assertNotIn("2", catalog)
        self.assertEqual(catalog["1"].ref, "SHARED")

    def test_07_update_existing_ref(self):
        self._write_catalog([
            ("21999", "MOTOR", "OLDREF"),
        ])
        data = self._inventory_csv([
            ["ID interno", "Nombre", "Nombre para mostrar"],
            ["21999", "MOTOR", "12948087"],
        ])
        preview = app.build_import_preview(data, "inv.csv", self.catalog_path)
        self.assertEqual(preview.update_count, 1)
        app.apply_import_preview(preview, self.catalog_path)
        catalog = self._read_catalog()
        self.assertEqual(catalog["21999"].ref, "12948087")

    def test_15_backup_and_recovery(self):
        self._write_catalog([("1", "A", "10")])
        data = self._inventory_csv([
            ["ID interno", "Nombre", "Nombre para mostrar"],
            ["2", "B", "20"],
        ])
        preview = app.build_import_preview(data, "inv.csv", self.catalog_path)
        with mock.patch.object(app, "save_persistent_catalog", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                app.apply_import_preview(preview, self.catalog_path)
        catalog = self._read_catalog()
        self.assertEqual(list(catalog.keys()), ["1"])
        self.assertTrue(any(self.backup_dir.glob("catalogo_articulos_*.csv")))


class ConversionTests(IsolatedCatalogTest):
    def setUp(self) -> None:
        super().setUp()
        self._write_catalog([
            (
                "21999",
                "MOTOR GENERATOR CÓD: HEC-200-100 UND(REF-12948087)",
                "12948087",
            ),
            ("475", "CINTA AISLANTE (REF-100002)", "100002"),
            ("999", "ZERO PAD (REF-00123)", "00123"),
        ])

    def test_08_convert_ref_to_internal_id(self):
        data = self._purchase_csv([
            ["ID INTERNO ARTICULO", "NOMBRE DE ARTICULO", "CANTIDAD"],
            ["12948087", "", "2"],
        ])
        result = app.process_csv_bytes(data, "compra.csv")
        text = result.data.decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[1][0], "21999")
        self.assertEqual(result.summary.converted, 1)

    def test_09_assign_name(self):
        data = self._purchase_csv([
            ["ID INTERNO ARTICULO", "NOMBRE DE ARTICULO"],
            ["12948087", ""],
        ])
        result = app.process_csv_bytes(data, "compra.csv")
        rows = list(csv.reader(io.StringIO(result.data.decode("utf-8-sig"))))
        self.assertIn("MOTOR GENERATOR", rows[1][1])

    def test_10_refs_not_found(self):
        data = self._purchase_csv([
            ["ID INTERNO ARTICULO", "NOMBRE DE ARTICULO"],
            ["99999999", ""],
            ["12948087", ""],
        ])
        result = app.process_csv_bytes(data, "compra.csv")
        rows = list(csv.reader(io.StringIO(result.data.decode("utf-8-sig"))))
        self.assertEqual(rows[1][0], "99999999")
        self.assertEqual(rows[1][1], "")
        self.assertEqual(rows[2][0], "21999")
        self.assertEqual(result.summary.not_found, 1)
        self.assertEqual(result.summary.converted, 1)

    def test_11_preserve_rows_and_columns(self):
        data = self._purchase_csv([
            ["FOO", "ID INTERNO ARTICULO", "BAR", "NOMBRE DE ARTICULO"],
            ["x", "12948087", "y", ""],
        ])
        result = app.process_csv_bytes(data, "compra.csv")
        rows = list(csv.reader(io.StringIO(result.data.decode("utf-8-sig"))))
        self.assertEqual(rows[0], ["FOO", "ID INTERNO ARTICULO", "BAR", "NOMBRE DE ARTICULO"])
        self.assertEqual(rows[1][0], "x")
        self.assertEqual(rows[1][1], "21999")
        self.assertEqual(rows[1][2], "y")

    def test_12_multi_sheet_zip(self):
        xlsx = build_xlsx({
            "Hoja1": [
                ["ID INTERNO ARTICULO", "NOMBRE DE ARTICULO"],
                ["12948087", ""],
            ],
            "Hoja2": [
                ["ID INTERNO ARTICULO", "NOMBRE DE ARTICULO"],
                ["100002", ""],
            ],
        })
        result = app.process_workbook_bytes(xlsx, "multi.xlsx")
        self.assertTrue(result.filename.endswith(".zip"))
        self.assertEqual(result.summary.sheets_processed, 2)
        self.assertEqual(result.summary.converted, 2)
        with zipfile.ZipFile(io.BytesIO(result.data)) as zf:
            names = zf.namelist()
            self.assertEqual(len(names), 2)

    def test_13_csv_separators(self):
        for delimiter in (",", ";", "\t"):
            data = self._purchase_csv(
                [
                    ["ID INTERNO ARTICULO", "NOMBRE DE ARTICULO"],
                    ["12948087", ""],
                ],
                delimiter=delimiter,
            )
            result = app.process_csv_bytes(data, f"sep{ord(delimiter)}.csv")
            rows = list(csv.reader(io.StringIO(result.data.decode("utf-8-sig"))))
            self.assertEqual(rows[1][0], "21999", msg=f"delimiter={delimiter!r}")

    def test_14_special_chars_and_leading_zeros(self):
        data = self._purchase_csv([
            ["ID INTERNO ARTICULO", "NOMBRE DE ARTICULO"],
            ["00123", ""],
        ])
        result = app.process_csv_bytes(data, "zeros.csv")
        rows = list(csv.reader(io.StringIO(result.data.decode("utf-8-sig"))))
        self.assertEqual(rows[1][0], "999")
        self.assertIn("ZERO PAD", rows[1][1])

    def test_16_conversion_does_not_mutate_catalog(self):
        before = app.catalog_fingerprint(self.catalog_path)
        data = self._purchase_csv([
            ["ID INTERNO ARTICULO", "NOMBRE DE ARTICULO"],
            ["12948087", ""],
            ["missing", ""],
        ])
        app.process_csv_bytes(data, "compra.csv")
        after = app.catalog_fingerprint(self.catalog_path)
        self.assertEqual(before, after)

    def test_all_failed_is_not_success(self):
        data = self._purchase_csv([
            ["ID INTERNO ARTICULO", "NOMBRE DE ARTICULO"],
            ["no-existe-1", ""],
            ["no-existe-2", ""],
        ])
        with self.assertRaises(ValueError):
            app.process_csv_bytes(data, "fail.csv")

    def test_ref_from_name_pattern_on_import(self):
        data = self._inventory_csv([
            ["ID interno", "Nombre", "Nombre para mostrar"],
            ["55001", "BOMBA AGUA UND(REF-778899)", ""],
        ])
        preview = app.build_import_preview(data, "inv.csv", self.catalog_path)
        self.assertEqual(preview.new_count, 1)
        app.apply_import_preview(preview, self.catalog_path)
        catalog = self._read_catalog()
        self.assertEqual(catalog["55001"].ref, "778899")

    def test_inventory_xlsx_headers(self):
        xlsx = build_xlsx({
            "Artículos": [
                ["ID interno", "Nombre", "Nombre para mostrar"],
                ["88001", "ITEM ESPECIAL ÁÉÍ (REF-555)", "555"],
            ],
        })
        preview = app.build_import_preview(xlsx, "Artículos779.xlsx", self.catalog_path)
        self.assertEqual(preview.new_count, 1)
        app.apply_import_preview(preview, self.catalog_path)
        catalog = self._read_catalog()
        self.assertEqual(catalog["88001"].ref, "555")
        self.assertIn("ÁÉÍ", catalog["88001"].name)


if __name__ == "__main__":
    unittest.main()

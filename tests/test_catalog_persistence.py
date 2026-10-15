"""Persistencia permanente del catálogo: env path, seed, reinicio y redeploy."""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import app


def _write_catalog(path: Path, rows: list[tuple[str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=app.CATALOG_CSV_FIELDS)
        writer.writeheader()
        for internal_id, name, ref in rows:
            writer.writerow({"ID interno": internal_id, "Nombre": name, "Ref": ref})


def _inventory_csv(rows: list[list[str]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=",", lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")


class CatalogPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="persist_test_"))
        self.data_dir = self.root / "var" / "catalog"
        self.code_data = self.root / "app_data"
        self.code_data.mkdir(parents=True)
        self.seed = self.code_data / "catalogo_articulos.seed.csv"
        self.legacy = self.code_data / "catalogo_articulos.csv"
        _write_catalog(self.seed, [("1", "SEED ITEM", "SEED1")])
        self._env = mock.patch.dict(os.environ, {app.CATALOG_DATA_DIR_ENV: str(self.data_dir)}, clear=False)
        self._env.start()
        app.rebind_data_paths()
        self._seed_patch = mock.patch.object(app, "SEED_CATALOG_PATH", self.seed)
        self._legacy_patch = mock.patch.object(app, "LEGACY_CATALOG_PATH", self.legacy)
        self._seed_patch.start()
        self._legacy_patch.start()

    def tearDown(self) -> None:
        self._seed_patch.stop()
        self._legacy_patch.stop()
        self._env.stop()
        app.rebind_data_paths()
        shutil.rmtree(self.root, ignore_errors=True)

    def test_01_bootstrap_from_seed_only_when_missing(self):
        self.assertFalse(app.CATALOG_PATH.exists())
        app.ensure_catalog_file()
        self.assertTrue(app.CATALOG_PATH.exists())
        catalog = app.load_persistent_catalog()
        self.assertIn("1", catalog)
        self.assertEqual(catalog["1"].ref, "SEED1")
        meta = app.read_catalog_meta()
        self.assertEqual(meta.get("source"), "seed")
        self.assertEqual(meta.get("article_count"), 1)

    def test_02_seed_never_overwrites_existing(self):
        app.ensure_catalog_file()
        _write_catalog(app.CATALOG_PATH, [("99", "LIVE", "LIVE99")])
        app.write_catalog_meta(source="manual", article_count=1)
        # Simulate deploy: seed replaced with different content
        _write_catalog(self.seed, [("1", "NEW SEED", "NEWSEED")])
        app.ensure_catalog_file()
        catalog = app.load_persistent_catalog()
        self.assertIn("99", catalog)
        self.assertNotIn("1", catalog)
        self.assertEqual(catalog["99"].ref, "LIVE99")

    def test_03_cumulative_import_survives_rebind_restart(self):
        app.ensure_catalog_file()
        _write_catalog(app.CATALOG_PATH, [("10", "OLD", "OLD10")])
        inventory = _inventory_csv([
            ["ID interno", "Nombre", "Ref"],
            ["20", "NEW", "NEW20"],
            ["10", "OLD UPDATED", "OLD10"],
        ])
        preview = app.build_import_preview(inventory, "inv.csv")
        result = app.apply_import_preview(preview)
        self.assertTrue(result["ok"])
        self.assertEqual(result["applied_new"], 1)
        self.assertEqual(result["applied_update"], 1)
        self.assertTrue((self.data_dir / "catalog_meta.json").exists())
        before = app.load_persistent_catalog()
        self.assertEqual(set(before.keys()), {"10", "20"})
        self.assertEqual(before["10"].name, "OLD UPDATED")
        updated_at = app.read_catalog_meta().get("updated_at")
        self.assertTrue(updated_at)

        # Simulate process restart: rebind paths from same env
        app.rebind_data_paths()
        after = app.load_persistent_catalog()
        self.assertEqual(set(after.keys()), {"10", "20"})
        self.assertEqual(after["10"].name, "OLD UPDATED")
        self.assertEqual(app.read_catalog_meta().get("updated_at"), updated_at)
        status = app.catalog_status()
        self.assertEqual(status["catalog_total"], 2)
        self.assertTrue(status["catalog_data_dir_configured"])
        self.assertEqual(status["catalog_updated_at"], updated_at)

    def test_04_redeploy_code_does_not_wipe_persistent_volume(self):
        app.ensure_catalog_file()
        ok, _, item = app.add_catalog_item("55", "Persistente", "REF55")
        self.assertTrue(ok)
        self.assertIsNotNone(item)
        # Deploy simulation: wipe/replace code data dir (seed only), volume untouched
        shutil.rmtree(self.code_data)
        self.code_data.mkdir()
        _write_catalog(self.seed, [("1", "FRESH SEED", "SEED1")])
        app.SEED_CATALOG_PATH = self.seed
        app.rebind_data_paths(self.data_dir)
        app.ensure_catalog_file()
        catalog = app.load_persistent_catalog()
        self.assertIn("55", catalog)
        self.assertEqual(catalog["55"].ref, "REF55")
        # El seed fresco del "despliegue" no debe reemplazar el catálogo del volumen.
        if "1" in catalog:
            self.assertNotEqual(catalog["1"].name, "FRESH SEED")
        self.assertEqual(app.catalog_count(), len(catalog))
        self.assertGreaterEqual(len(catalog), 1)

    def test_05_legacy_migrate_once_never_overwrite(self):
        # Empty volume + legacy catalog in old location
        _write_catalog(self.legacy, [("77", "LEGACY", "LEG77")])
        self.assertFalse(app.CATALOG_PATH.exists())
        migrated = app.maybe_migrate_legacy_catalog()
        self.assertTrue(migrated)
        catalog = app.load_persistent_catalog()
        self.assertIn("77", catalog)
        # Second call must not overwrite live updates
        _write_catalog(app.CATALOG_PATH, [("88", "LIVE", "LIVE88")])
        _write_catalog(self.legacy, [("77", "LEGACY AGAIN", "LEG77")])
        self.assertFalse(app.maybe_migrate_legacy_catalog())
        catalog = app.load_persistent_catalog()
        self.assertIn("88", catalog)
        self.assertNotIn("77", catalog)

    def test_06_articles_absent_from_new_excel_are_kept(self):
        app.ensure_catalog_file()
        _write_catalog(app.CATALOG_PATH, [
            ("1", "Keep Me", "K1"),
            ("2", "Also Keep", "K2"),
        ])
        inventory = _inventory_csv([
            ["ID interno", "Nombre", "Ref"],
            ["3", "Only New", "K3"],
        ])
        preview = app.build_import_preview(inventory, "partial.csv")
        result = app.apply_import_preview(preview)
        self.assertTrue(result["ok"])
        catalog = app.load_persistent_catalog()
        self.assertEqual(set(catalog.keys()), {"1", "2", "3"})

    def test_07_backup_created_on_confirm(self):
        app.ensure_catalog_file()
        _write_catalog(app.CATALOG_PATH, [("1", "A", "R1")])
        inventory = _inventory_csv([
            ["ID interno", "Nombre", "Ref"],
            ["2", "B", "R2"],
        ])
        preview = app.build_import_preview(inventory, "b.csv")
        result = app.apply_import_preview(preview)
        self.assertTrue(result["ok"])
        self.assertTrue(result.get("backup"))
        backups = list(app.BACKUP_DIR.glob("catalogo_articulos_*.csv"))
        self.assertTrue(backups)

    def test_08_resolve_data_paths_default_without_env(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(app.CATALOG_DATA_DIR_ENV, None)
            data_dir, catalog, backups, meta = app.resolve_data_paths()
        self.assertEqual(data_dir, (app.APP_DIR / "data").resolve())
        self.assertEqual(catalog.name, "catalogo_articulos.csv")
        self.assertEqual(backups.name, "backups")
        self.assertEqual(meta.name, "catalog_meta.json")


if __name__ == "__main__":
    unittest.main()

import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from contextlib import closing

import app_paths
import cli
import data_migration
from functional_core import LocalStore, hash_password, encrypt_api_key, decrypt_api_key
from onboarding import create_administrator


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.binary = self.root / 'Programa con espacios Unicode-ñ'
        self.binary.mkdir()
        self.local = self.root / 'AppData'
        self.patchers = [patch.object(app_paths.sys, 'frozen', True, create=True),
                         patch.object(app_paths.sys, 'executable', str(self.binary / 'SemaforoIA.exe')),
                         patch.dict(os.environ, {'LOCALAPPDATA': str(self.local)})]
        for item in self.patchers:
            item.start()

    def tearDown(self):
        for item in reversed(self.patchers):
            item.stop()
        self.temporary.cleanup()

    def test_installed_and_portable_policy_does_not_depend_on_cwd(self):
        self.assertEqual(app_paths.data_root(), self.local / 'SemaforoIA')
        (self.binary / 'portable.flag').touch()
        self.assertEqual(app_paths.data_root(), self.binary / 'userdata')
        self.assertNotIn('_MEIPASS', str(app_paths.data_root()))
        with patch.object(app_paths.sys, 'executable', str(self.binary / 'SemaforoCLI.exe')):
            self.assertEqual(cli.build_parser().parse_args(['history']).database, str(self.binary / 'userdata' / 'semaforo.sqlite3'))
        import db
        with patch.dict(os.environ, {}, clear=False):
            with patch.dict(os.environ, {'DB_PATH': str(self.root / 'explicit.sqlite3')}):
                self.assertEqual(db._sqlite_path(), str(self.root / 'explicit.sqlite3'))

    def test_readonly_portable_reports_error_without_appdata_fallback(self):
        (self.binary / 'portable.flag').touch()
        with patch.object(app_paths.tempfile, 'TemporaryFile', side_effect=PermissionError('readonly')):
            with self.assertRaisesRegex(OSError, 'portable'):
                app_paths.initialize_user_data()
        self.assertFalse(self.local.exists())

    def test_defaults_are_sanitized_and_never_overwrite_existing_files(self):
        root = app_paths.initialize_user_data()
        config = json.loads((root / 'config.json').read_text())
        self.assertEqual(config['users'], [])
        self.assertEqual(json.loads((root / 'models.json').read_text()), [])
        (root / 'config.json').write_text('{"users":[{"username":"existing"}]}')
        (root / 'semaforo.sqlite3').write_bytes(b'preserve database')
        app_paths.initialize_user_data()
        self.assertEqual(json.loads((root / 'config.json').read_text())['users'][0]['username'], 'existing')
        self.assertEqual((root / 'semaforo.sqlite3').read_bytes(), b'preserve database')

    def test_first_administrator_requires_a_password_and_cannot_replace_accounts(self):
        with self.assertRaises(ValueError):
            create_administrator('owner', 'weak', 'weak')
        profile = create_administrator('owner', 'StrongPassword1@', 'StrongPassword1@')
        self.assertEqual(profile['role'], 'Administrador')
        self.assertNotIn('StrongPassword1@', (app_paths.data_root() / 'config.json').read_text())
        with self.assertRaises(ValueError):
            create_administrator('second', 'StrongPassword2@', 'StrongPassword2@')
        store = LocalStore(app_paths.data_root() / 'semaforo.sqlite3')
        try:
            self.assertIsNotNone(store.authenticate('owner', 'StrongPassword1@'))
        finally:
            store.close()

    def make_legacy(self):
        legacy = self.root / 'old'
        legacy.mkdir()
        config = {'users': [{'username': 'legacy', 'password_hash': hash_password('LegacyPassword1@'), 'role': 'Administrador'}]}
        (legacy / 'config.json').write_text(json.dumps(config))
        store = LocalStore(legacy / 'semaforo.sqlite3')
        store.add_project('Existing project')
        store.close()
        encrypted = encrypt_api_key('test-credential-123', legacy / 'secrets' / 'financial_api.key')
        config['financial_api_key'] = encrypted
        (legacy / 'config.json').write_text(json.dumps(config))
        return legacy

    def test_migration_preserves_originals_validates_database_and_moves_fernet_keys(self):
        legacy = self.make_legacy()
        original = (legacy / 'config.json').read_bytes()
        backup = Path(data_migration.migrate_legacy(legacy))
        self.assertTrue((backup / 'COMPLETED').is_file())
        self.assertEqual((legacy / 'config.json').read_bytes(), original)
        root = app_paths.data_root()
        config = json.loads((root / 'config.json').read_text())
        self.assertEqual(decrypt_api_key(config['financial_api_key'], root / 'secrets' / 'financial_api.key'), 'test-credential-123')
        moved = self.root / 'another drive'
        shutil.copytree(root, moved)
        self.assertEqual(decrypt_api_key(config['financial_api_key'], moved / 'secrets' / 'financial_api.key'), 'test-credential-123')
        with self.assertRaises(ValueError):
            data_migration.migrate_legacy(legacy)

    def test_corrupt_legacy_database_does_not_become_live(self):
        legacy = self.make_legacy()
        (legacy / 'semaforo.sqlite3').write_bytes(b'invalid sqlite')
        with self.assertRaises((ValueError, sqlite3.DatabaseError)):
            data_migration.migrate_legacy(legacy)
        self.assertFalse((app_paths.data_root() / 'semaforo.sqlite3').exists())

    def test_migration_copies_only_referenced_legacy_bundled_photos(self):
        legacy = self.make_legacy()
        photos = legacy / '_internal' / 'img'
        photos.mkdir(parents=True)
        (photos / 'owner.png').write_bytes(b'referenced-image-fixture')
        (photos / 'other-person.png').write_bytes(b'not-to-import')
        config = json.loads((legacy / 'config.json').read_text())
        config['users'][0]['profile_photo'] = 'img/owner.png'
        (legacy / 'config.json').write_text(json.dumps(config))
        data_migration.migrate_legacy(legacy)
        self.assertEqual((app_paths.data_root() / 'img' / 'owner.png').read_bytes(), b'referenced-image-fixture')
        self.assertFalse((app_paths.data_root() / 'img' / 'other-person.png').exists())

    def test_schema_change_creates_valid_backup_and_rejects_future_schema(self):
        database = self.root / 'old.sqlite3'
        with closing(sqlite3.connect(database)) as connection:
            connection.execute('CREATE TABLE custom_data(value TEXT)')
            connection.execute("INSERT INTO custom_data VALUES ('preserved')")
            connection.commit()
        store = LocalStore(database)
        store.close()
        backup = next((self.root / 'backups').glob('*.sqlite3'))
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute('SELECT value FROM custom_data').fetchone()[0], 'preserved')
        with closing(sqlite3.connect(database)) as connection:
            connection.execute('PRAGMA user_version = 999')
        with self.assertRaises(ValueError):
            LocalStore(database)

    def test_distribution_allowlist_excludes_personal_assets_and_demo_accounts(self):
        root = Path(__file__).parent
        manifest = json.loads((root / 'packaging/distribution-files.json').read_text())
        for relative in manifest['files']:
            self.assertTrue((root / relative).is_file())
            self.assertNotIn(relative, ('config.json', 'models.json', 'img/nacha.png', 'img/maxine.jpg'))
        self.assertFalse(json.loads((root / 'defaults/config.json').read_text())['users'])

    def test_frozen_mlflow_never_relaunches_the_application(self):
        import mlflow_integration
        with patch.object(mlflow_integration, '_is_reachable', return_value=False), patch.object(mlflow_integration.subprocess, 'Popen') as launch:
            mlflow_integration.start_local_server_if_needed({})
        launch.assert_not_called()

    def test_user_path_cannot_escape_its_root(self):
        with self.assertRaises(ValueError):
            app_paths.writable_path('..', 'another-user', 'secret')

    def test_server_rejects_an_occupied_port_without_affecting_its_owner(self):
        from server import SemaforoHTTPServer, SimpleHandler
        with SemaforoHTTPServer(('127.0.0.1', 0), SimpleHandler) as original:
            with self.assertRaises(OSError):
                with SemaforoHTTPServer(original.server_address, SimpleHandler):
                    self.fail('An occupied listening port must not be shared')
            self.assertGreater(original.fileno(), -1)

    def test_portable_archive_rejects_tampering(self):
        from scripts.bundle_manifest import inventory
        from scripts.verify_artifacts import verify
        bundle = self.root / 'SemaforoIA'
        bundle.mkdir()
        (bundle / 'portable.flag').touch()
        (bundle / 'SemaforoIA.exe').write_bytes(b'fixture-binary')
        (bundle / 'distribution-manifest.json').write_text(json.dumps(inventory(bundle)))
        archive = self.root / 'portable.zip'
        def write_archive():
            with zipfile.ZipFile(archive, 'w') as output:
                for path in bundle.iterdir():
                    output.write(path, 'SemaforoIA/' + path.name)
        write_archive()
        verify(archive)
        (bundle / 'SemaforoIA.exe').write_bytes(b'modified-after-signing')
        write_archive()
        with self.assertRaises(ValueError):
            verify(archive)


if __name__ == '__main__':
    unittest.main()

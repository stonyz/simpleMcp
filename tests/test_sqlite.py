import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SQLiteTests(unittest.TestCase):
    def run_isolated(self, code, database_url=None):
        with tempfile.TemporaryDirectory() as directory:
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith("MYSQL_") and key != "DATABASE_URL"}
            env["PYTHONPATH"] = str(PROJECT_ROOT)
            if database_url is not None:
                env["DATABASE_URL"] = database_url
            result = subprocess.run(
                [sys.executable, "-c", textwrap.dedent(code)],
                cwd=directory, env=env, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_default_database_crud_timestamps_and_persistence(self):
        self.run_isolated("""
            from datetime import datetime
            from pathlib import Path
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            from app.db import Base, engine, get_db_context
            from app.db import crud

            Base.metadata.create_all(engine)
            assert Path('data/mcp.db').is_file()
            data = {'info': {'title': '示例服务', 'version': '1.0'}, 'paths': {}}
            with get_db_context() as db:
                row, updated = crud.upsert_openapi_file(
                    db, 'tenant', 'org', 'app', 'file', 'api.yaml', data, 'secret')
                assert not updated
                assert row.id == 1 and row.title == '示例服务'
                assert row.create_at is not None and row.update_at is not None
                row.update_at = datetime(2000, 1, 1)

            with get_db_context() as db:
                changed = {'info': data['info'], 'paths': {'/new': {}}}
                row, updated = crud.upsert_openapi_file(
                    db, 'tenant', 'org', 'app', 'file', 'api.yaml', changed)
                assert updated and '/new' in row.openapi_yaml
                assert row.auth == 'secret'
                assert row.update_at > datetime(2000, 1, 1)
                assert len(crud.get_openapi_files(db, tenant='tenant')) == 1

            engine.dispose()
            reopened = create_engine('sqlite:///./data/mcp.db')
            with Session(reopened) as db:
                row = crud.get_one_openapi(db, 'tenant', 'org', 'app', 'file')
                assert row is not None and '/new' in row.openapi_yaml
                assert crud.delete_openapi_file(db, 'tenant', 'org', 'app', 'file') == 1
                assert crud.get_openapi_files(db) == []
            reopened.dispose()
        """)

    def test_custom_database_directory_and_worker_thread(self):
        self.run_isolated("""
            from concurrent.futures import ThreadPoolExecutor
            from pathlib import Path
            from sqlalchemy import text
            from app.db import Base, engine, get_db_context
            from app.db.models import OpenAPIFile

            Base.metadata.create_all(engine)
            assert Path('nested/storage/custom.db').is_file()
            # Reuse a pooled connection created by the main thread.
            with engine.connect() as connection:
                connection.execute(text('SELECT 1'))
            def read_from_worker():
                with get_db_context() as db:
                    return db.execute(text('SELECT count(*) FROM openapi_files')).scalar_one()
            with ThreadPoolExecutor(max_workers=1) as workers:
                assert workers.submit(read_from_worker).result() == 0
            engine.dispose()
        """, "sqlite:///./nested/storage/custom.db")

    def test_transaction_rollback_and_unique_file_constraint(self):
        self.run_isolated("""
            from datetime import datetime
            from sqlalchemy.exc import IntegrityError
            from app.db import Base, engine, get_db_context
            from app.db.models import OpenAPIFile
            from app.db import crud

            Base.metadata.create_all(engine)
            def row():
                return OpenAPIFile(tenant='tenant', orgid='org', appid='app',
                    fileId='file', fileName='api.yaml', title='API',
                    create_at=datetime.now(), openapi_yaml='paths: {}')
            try:
                with get_db_context() as db:
                    db.add(row())
                    db.add(row())
            except IntegrityError:
                pass
            else:
                raise AssertionError('Duplicate file should violate the unique constraint')
            with get_db_context() as db:
                assert crud.get_openapi_files(db) == []
                db.add(row())
            with get_db_context() as db:
                assert len(crud.get_openapi_files(db)) == 1
            engine.dispose()
        """)

    def test_operation_timeout_survives_document_reload(self):
        self.run_isolated("""
            import yaml
            from app.db import Base, engine, get_db_context, crud
            from app.mcp.tenant_manager import TenantManager

            Base.metadata.create_all(engine)
            data = {
                'info': {'title': 'API', 'version': '1'},
                'servers': [{'url': 'https://example.com'}],
                'paths': {'/report': {'get': {
                    'operationId': 'report', 'x-request-timeout-seconds': 120,
                }}},
            }
            with get_db_context() as db:
                crud.upsert_openapi_file(db, 'tenant', 'org', 'app', 'file', 'api.yaml', data)
            manager = TenantManager()
            with get_db_context() as db:
                row = crud.get_one_openapi(db, 'tenant', 'org', 'app', 'file')
                manager.register_tools_from_openapi(
                    row.tenant, row.orgid, row.appid, yaml.safe_load(row.openapi_yaml),
                    row.fileId, row.fileName, row.auth)
            metadata = manager.get_tenant_registry('tenant').get_tool_metadata('report')
            assert metadata['request_timeout_seconds'] == 120
            engine.dispose()
        """)


if __name__ == "__main__":
    unittest.main()

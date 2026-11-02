import json
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import yaml

from app.db import Base, crud
from app.mcp.tenant_manager import TenantManager
from app.routers.services import router


def specification(*names):
    return {
        "openapi": "3.0.3", "info": {"title": "API", "version": "1"},
        "paths": {f"/{name}": {"get": {"operationId": name}} for name in names},
    }


class OpenAPIRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.manager = TenantManager()

        @contextmanager
        def database():
            with Session(self.engine) as db:
                yield db
                db.commit()

        self.database = database
        self.enterContext(patch("app.routers.services.get_db_context", database))
        self.enterContext(patch("app.routers.services.tenant_manager", self.manager))
        app = FastAPI()
        app.include_router(router, prefix="/services")
        self.client = self.enterContext(TestClient(app))

    def register(self, *names, tenant="one", file_id="file", org="org", app="app"):
        body = {"org": org, "app": app, "fileName": "api.yaml",
                "yaml_content": json.dumps(specification(*names))}
        if file_id is not None:
            body["fileId"] = file_id
        return self.client.post(f"/services/register?tenant={tenant}", json=body)

    def names(self, tenant="one", org="org", app="app"):
        return {item["name"] for item in self.manager.list_functions(tenant, org, app)}

    def test_json_generated_id_can_update_and_delete_document(self):
        response = self.register("old", file_id=None)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        file_id = body["fileId"]
        self.assertTrue(file_id)
        self.assertLessEqual(len(file_id), 64)
        self.assertFalse(body["updated"])
        response = self.register("new", file_id=file_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["updated"])
        self.assertEqual(self.names(), {"new"})
        with self.database() as db:
            self.assertEqual(len(crud.get_openapi_files(db)), 1)
        response = self.client.delete(
            "/services/delete", params={"tenant": "one", "org": "org", "app": "app", "fileId": file_id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["deleted"], 1)
        self.assertEqual(self.names(), set())

    def test_form_upload_without_id_generates_persisted_id(self):
        response = self.client.post(
            "/services/register-form?tenant=one",
            data={"org": "org", "app": "app", "fileName": "api.yaml"},
            files={"file": ("api.yaml", yaml.safe_dump(specification("upload")), "application/yaml")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        with self.database() as db:
            row = crud.get_one_openapi(db, "one", "org", "app", response.json()["fileId"])
            self.assertIsNotNone(row)
        self.assertEqual(self.names(), {"upload"})

    def test_omitted_ids_create_distinct_documents(self):
        first = self.register("first", file_id=None)
        second = self.register("second", file_id=None)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertNotEqual(first.json()["fileId"], second.json()["fileId"])
        self.assertEqual(self.names(), {"first", "second"})
        with self.database() as db:
            self.assertEqual(len(crud.get_openapi_files(db)), 2)

    def test_same_id_is_isolated_by_tenant(self):
        first = self.register("first", tenant="one")
        second = self.register("second", tenant="two")
        self.assertFalse(first.json()["updated"])
        self.assertFalse(second.json()["updated"])
        response = self.register("changed", tenant="two")
        self.assertTrue(response.json()["updated"])
        with self.database() as db:
            rows = {row.tenant: yaml.safe_load(row.openapi_yaml)["paths"]
                    for row in crud.get_openapi_files(db)}
        self.assertEqual(set(rows), {"one", "two"})
        self.assertEqual(set(rows["one"]), {"/first"})
        self.assertEqual(set(rows["two"]), {"/changed"})
        self.assertEqual(self.names("one"), {"first"})
        self.assertEqual(self.names("two"), {"changed"})

    def test_update_removes_old_tools_preserving_other_origins_and_indexes(self):
        self.register("removed", "renamed", "kept")
        self.register("other", file_id="another")
        self.register("removed", tenant="two")
        self.register("removed", org="another")
        self.register("removed", app="another")
        response = self.register("new_name", "kept")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["updated"])
        self.assertEqual(self.names(), {"new_name", "kept", "other"})
        self.assertEqual(self.names("two"), {"removed"})
        self.assertEqual(self.names(org="another"), {"removed"})
        self.assertEqual(self.names(app="another"), {"removed"})
        registry = self.manager.get_tenant_registry("one")
        self.assertIsNone(registry.get_tool_metadata("removed", "org", "app"))
        self.assertEqual(registry.list_functions("org", "app", "renamed"), [])
        self.assertEqual(len(registry.list_functions("org", "app", "kept")), 1)

    def test_empty_update_clears_only_its_document(self):
        self.register("removed")
        self.register("other", file_id="another")
        response = self.register()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.names(), {"other"})

    def test_update_does_not_remove_tool_currently_owned_by_another_document(self):
        self.register("shared", "old")
        self.register("shared", file_id="another")
        self.register("new")
        self.assertEqual(self.names(), {"shared", "new"})
        metadata = self.manager.get_tenant_registry("one").get_tool_metadata("shared", "org", "app")
        self.assertEqual(metadata["fileId"], "another")

    def test_invalid_update_preserves_database_and_live_tools(self):
        self.register("old")
        data = specification("new")
        data["paths"]["/new"]["get"]["x-request-timeout-seconds"] = 0
        response = self.client.post("/services/register?tenant=one", json={
            "org": "org", "app": "app", "fileId": "file", "fileName": "api.yaml",
            "yaml_content": json.dumps(data),
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.names(), {"old"})
        with self.database() as db:
            row = crud.get_one_openapi(db, "one", "org", "app", "file")
            self.assertEqual(set(yaml.safe_load(row.openapi_yaml)["paths"]), {"/old"})

    def test_form_explicit_id_remains_usable_for_updates(self):
        self.register("old")
        response = self.client.post("/services/register-form?tenant=one", data={
            "org": "org", "app": "app", "fileId": "file", "fileName": "api.yaml",
            "yaml_content": json.dumps(specification("new")),
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["updated"])
        self.assertEqual(response.json()["fileId"], "file")
        self.assertEqual(self.names(), {"new"})

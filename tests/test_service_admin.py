import json

import unittest
import test_openapi_registration as registration
from app.db import crud
from app.midware.TenantMiddleware import TenantMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routers.services import router
import yaml
from app.common.exception_handlers import register_exception_handlers
from unittest.mock import patch


specification = registration.specification


class ServiceAdminTests(unittest.TestCase):
    # Share the isolated database/client fixture without rerunning its tests.
    setUp = registration.OpenAPIRegistrationTests.setUp
    register = registration.OpenAPIRegistrationTests.register
    names = registration.OpenAPIRegistrationTests.names
    scope = {"tenant": "one", "org": "org", "app": "app", "fileId": "file"}

    def payload(self, *names, **extra):
        return {"org": "org", "app": "app", "fileName": "api.yaml",
                "yaml_content": json.dumps(specification(*names)), **extra}

    def test_list_and_detail_are_scoped_and_hide_auth(self):
        self.register("one")
        self.register("two", tenant="two")
        with self.database() as db:
            row = crud.get_one_openapi(db, "one", "org", "app", "file")
            row.auth = "TOP_SECRET"
            db.commit()
        response = self.client.get("/services/", params={"tenant": "one", "q": "API"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["tool_count"], 1)
        detail = self.client.get("/services/detail", params=self.scope)
        self.assertEqual(detail.status_code, 200)
        self.assertTrue(detail.json()["auth_configured"])
        self.assertIn("document", detail.json())
        self.assertNotIn("TOP_SECRET", detail.text)
        self.assertEqual(self.client.get("/services/detail", params={**self.scope, "tenant": "missing"}).status_code, 404)
        self.assertEqual(self.client.get("/services/").status_code, 422)

    def test_preview_diff_does_not_write(self):
        self.register("old", "kept")
        response = self.client.post("/services/preview?tenant=one", json=self.payload("new", "kept", fileId="file"))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["changes"], {"added": ["new"], "removed": ["old"], "modified": [], "unchanged": ["kept"]})
        self.assertEqual(self.names(), {"old", "kept"})
        with self.database() as db:
            self.assertEqual(len(crud.get_openapi_files(db)), 1)

    def test_save_rejects_conflicts_and_missing_update(self):
        self.register("shared", file_id="another")
        payload = self.payload("shared")
        preview = self.client.post("/services/preview?tenant=one", json=payload)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["conflicts"][0]["name"], "shared")
        self.assertEqual(self.client.post("/services/save?tenant=one", json=payload).status_code, 409)
        self.assertEqual(self.client.post("/services/save?tenant=one", json=self.payload("new", fileId="missing")).status_code, 404)
        self.assertEqual(self.names(), {"shared"})

    def test_save_updates_metadata_and_auth_without_echo(self):
        secret = '{"access_token":"SECRET"}'
        created = self.client.post("/services/save?tenant=one", json=self.payload("one", auth_action="replace", auth=secret))
        self.assertEqual(created.status_code, 200, created.text)
        file_id = created.json()["fileId"]
        data = specification("two")
        data["info"] = {"title": "Renamed", "version": "2"}
        payload = self.payload(fileId=file_id, fileName="new.json", yaml_content=json.dumps(data))
        response = self.client.post("/services/save?tenant=one", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        with self.database() as db:
            row = crud.get_one_openapi(db, "one", "org", "app", file_id)
            self.assertEqual((row.title, row.version, row.fileName, row.auth), ("Renamed", "2", "new.json", secret))
        metadata = self.manager.get_tenant_registry("one").get_tool_metadata("two", "org", "app")
        self.assertEqual(metadata["auth"], secret)
        self.assertNotIn("SECRET", response.text)
        response = self.client.post("/services/save?tenant=one", json={**payload, "auth_action": "clear"})
        self.assertEqual(response.status_code, 200)
        with self.database() as db:
            self.assertEqual(crud.get_one_openapi(db, "one", "org", "app", file_id).auth, "")

    def test_invalid_documents_return_client_errors(self):
        for doc in [[], {"paths": []}, {"paths": {"/x": {"get": None}}},
                    {"paths": {}, "info": "oops"},
                    specification("same", "other") | {"paths": {"/a": {"get": {"operationId": "same"}}, "/b": {"get": {"operationId": "same"}}}}]:
            with self.subTest(doc=doc):
                response = self.client.post("/services/preview?tenant=one", json=self.payload(yaml_content=json.dumps(doc)))
                self.assertEqual(response.status_code, 400, response.text)

    def test_delete_preserves_overwritten_tool_owned_by_other_file(self):
        self.register("shared", "old")
        self.register("shared", file_id="another")
        response = self.client.delete("/services/delete", params=self.scope)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.names(), {"shared"})

    def test_pagination_and_search(self):
        self.register("one", file_id="first")
        self.register("two", file_id="second", org="different")
        response = self.client.get("/services/", params={"tenant": "one", "page_size": 1, "page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(self.client.get("/services/", params={"tenant": "one", "org": "different"}).json()["total"], 1)

    def test_invalid_auth_is_rejected_before_write(self):
        for auth in ["not-json", '"token"', "[]", "null"]:
            response = self.client.post("/services/save?tenant=one", json=self.payload("one", auth_action="replace", auth=auth))
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.names(), set())

    def test_typed_authorization_requires_matching_fields_in_preview_and_save(self):
        cases = [("basic", {"username": "admin"}), ("bearer", {"access_token": ""}),
                 ("oauth2", {"client_id": "id", "client_secret": "secret", "token_url": "invalid"}),
                 ("oauth2", {"client_id": "id", "client_secret": "secret", "token_url": "https://auth.example/token", "scopes": "read"})]
        for kind, auth in cases:
            for endpoint in ("preview", "save"):
                with self.subTest(kind=kind, endpoint=endpoint):
                    response = self.client.post(f"/services/{endpoint}?tenant=one", json=self.payload(
                        "one", auth_action="replace", auth_type=kind, auth=json.dumps(auth)))
                    self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.manager.tenant_registries, {})

    def test_authorization_type_is_visible_without_credentials(self):
        for kind, auth in [("basic", {"username": "PRIVATE_USER", "password": "PRIVATE_PASSWORD"}),
                           ("bearer", {"access_token": "PRIVATE_TOKEN"}),
                           ("oauth2", {"client_id": "PRIVATE_ID", "client_secret": "PRIVATE_SECRET", "token_url": "https://auth.example/token", "scopes": ["read"]})]:
            response = self.client.post("/services/save?tenant=one", json=self.payload(
                kind, auth_action="replace", auth_type=kind, auth=json.dumps(auth)))
            self.assertEqual(response.status_code, 200, response.text)
            detail = self.client.get("/services/detail", params={**self.scope, "fileId": response.json()["fileId"]})
            self.assertEqual(detail.json()["auth_type"], kind)
            self.assertNotIn("PRIVATE_", detail.text)

    def test_corrupt_document_can_be_deleted(self):
        self.register("old")
        with self.database() as db:
            row = crud.get_one_openapi(db, "one", "org", "app", "file")
            row.openapi_yaml = "paths: [broken]"
            db.commit()
        response = self.client.delete("/services/delete", params=self.scope)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.names(), set())

    def test_full_middleware_requires_explicit_management_tenant(self):
        app = FastAPI()
        app.add_middleware(TenantMiddleware)
        app.include_router(router, prefix="/services")
        with TestClient(app) as client:
            self.assertEqual(client.get("/services/").status_code, 422)
            self.assertEqual(client.post("/services/save", json=self.payload("one")).status_code, 422)
            self.assertEqual(client.post("/one/services/save", json=self.payload("one")).status_code, 200)

    def test_legacy_document_tools_are_still_conflicts(self):
        legacy = specification("shared")
        legacy.pop("openapi")
        created = self.client.post("/services/register?tenant=one", json=self.payload(fileId="legacy", yaml_content=json.dumps(legacy)))
        self.assertEqual(created.status_code, 200)
        preview = self.client.post("/services/preview?tenant=one", json=self.payload("shared"))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["conflicts"][0]["fileId"], "legacy")
        self.assertEqual(self.client.post("/services/save?tenant=one", json=self.payload("shared")).status_code, 409)

    def test_non_json_and_invalid_description_documents_are_rejected(self):
        cycle = {}
        cycle["child"] = cycle
        for summary in [{"bad": "object"}, float("nan"), float("inf"), cycle]:
            data = specification("one")
            data["paths"]["/one"]["get"]["summary"] = summary
            response = self.client.post("/services/preview?tenant=one", json=self.payload(yaml_content=yaml.safe_dump(data)))
            self.assertEqual(response.status_code, 400, response.text)

    def test_preview_does_not_create_tenant_registry(self):
        self.assertEqual(self.manager.tenant_registries, {})
        response = self.client.post("/services/preview?tenant=one", json=self.payload("one"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.manager.tenant_registries, {})

    def test_production_validation_errors_are_safe_and_serializable(self):
        app = FastAPI()
        app.include_router(router, prefix="/services")
        register_exception_handlers(app)
        with patch("app.common.exception_handlers.log") as logger, TestClient(app) as client:
            for extra in [{"auth": {"access_token": "SECRET_PROBE"}}, {"org": " "}]:
                response = client.post("/services/save?tenant=one&token=QUERY_SECRET", json=self.payload("one", **extra))
                self.assertEqual(response.status_code, 422)
                self.assertNotIn("SECRET_PROBE", response.text)
                self.assertNotIn("SECRET_PROBE", str(logger.mock_calls))
                self.assertNotIn("QUERY_SECRET", str(logger.mock_calls))

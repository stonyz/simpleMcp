import json
import unittest
from unittest.mock import patch

import httpx
from jsonschema import Draft202012Validator
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mcp.tenant_manager import TenantManager
from app.midware.RequestIdMiddleware import RequestIdMiddleware
from app.routers.mcp import router


class MCPProtocolTests(unittest.TestCase):
    def setUp(self):
        self.manager = TenantManager()
        app = FastAPI()
        app.include_router(router, prefix="/mcp")
        app.add_middleware(RequestIdMiddleware)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        patcher = patch("app.routers.mcp.tenant_manager", self.manager)
        patcher.start()
        self.addCleanup(patcher.stop)

    def register(self, schema, content_type="application/json"):
        self.manager.register_tools_from_openapi("test", "org", "app", {
            "openapi": "3.0.3", "info": {"title": "Test", "version": "1"},
            "servers": [{"url": "https://upstream.invalid"}],
            "paths": {"/value": {"get": {"operationId": "value", "responses": {
                "200": {"description": "OK", "content": {
                    content_type: {"schema": schema},
                }},
            }}}},
        })

    def rpc(self, method, params=None, rpc_id=1, **kwargs):
        return self.client.post("/mcp?tenant=test", json={
            "jsonrpc": "2.0", "id": rpc_id, "method": method,
            "params": {} if params is None else params,
        }, **kwargs)

    def output_schema(self):
        return self.rpc("tools/list").json()["result"]["tools"][0]["outputSchema"]

    def call_with(self, value, method="tools/call"):
        with patch("app.mcp.rest.executor.httpx.AsyncClient.request",
                   return_value=httpx.Response(200, content=json.dumps(value),
                                               headers={"Content-Type": "application/json"})):
            return self.rpc(method, {"name": "value", "arguments": {}})

    def test_non_object_schemas_and_results_use_same_data_wrapper(self):
        for schema, value in (
            ({"type": "array", "items": {"type": "integer"}}, [1, 2]),
            ({"type": "array", "items": {"type": "integer"}}, []),
            ({"type": "string"}, ""),
            ({"type": "number"}, 0),
            ({"type": "boolean"}, False),
            ({"type": "null"}, None),
            ({"oneOf": [{"type": "object"}, {"type": "array"}]}, {}),
        ):
            with self.subTest(schema=schema, value=value):
                self.register(schema)
                self.assertEqual(self.output_schema(), {
                    "type": "object", "properties": {"data": schema},
                    "required": ["data"],
                })
                for method in ("tools/call", "call_tool"):
                    result = self.call_with(value, method).json()["result"]
                    self.assertNotIn("isError", result)
                    self.assertEqual(result.get("structuredContent"), {"data": value})
                    self.assertEqual(json.loads(result["content"][0]["text"]), {"data": value})

    def test_plain_text_schema_is_wrapped_and_legacy_call_is_unchanged(self):
        self.register({"type": "string"}, "text/plain")
        self.assertEqual(self.output_schema()["type"], "object")
        with patch("app.mcp.rest.executor.httpx.AsyncClient.request",
                   return_value=httpx.Response(200, text="ready")):
            result = self.rpc("tools/call", {"name": "value"}).json()["result"]
            self.assertEqual(result.get("structuredContent"), {"data": "ready"})
            legacy = self.client.post("/mcp/call?tenant=test", json={
                "function_name": "value", "parameters": {},
            }).json()
            self.assertEqual(legacy["result"], "ready")
            self.assertIn("meta", legacy)

    def test_nullable_openapi_schema_is_converted_without_changing_examples(self):
        self.register({"type": "object", "properties": {
            "label": {"type": "string", "nullable": True},
            "config": {"type": "object", "example": {"nullable": True}},
        }, "required": ["label"]})
        field = self.output_schema()["properties"]["label"]
        self.assertNotIn("nullable", field)
        self.assertEqual(field, {"anyOf": [{"type": "string"}, {"type": "null"}]})
        self.assertEqual(self.output_schema()["properties"]["config"]["example"], {"nullable": True})
        result = self.call_with({"label": None}).json()["result"]
        self.assertNotIn("isError", result)
        self.assertEqual(result.get("structuredContent"), {"label": None})

    def test_nullable_root_object_is_wrapped(self):
        self.register({"type": "object", "nullable": True})
        self.assertEqual(self.output_schema()["type"], "object")
        result = self.call_with(None).json()["result"]
        self.assertEqual(result.get("structuredContent"), {"data": None})

    def test_schema_mismatch_is_tool_error_without_leaking_upstream_value(self):
        self.register({"type": "object", "properties": {"online": {"type": "boolean"}},
                       "required": ["online"]})
        for value in ({}, {"online": "private-secret"}, [], "private-secret"):
            with self.subTest(value=value):
                response = self.call_with(value)
                result = response.json()["result"]
                self.assertTrue(result.get("isError"))
                self.assertNotIn("structuredContent", result)
                self.assertEqual(result["_meta"]["error_details"]["type"], "output_validation_error")
                self.assertNotIn("private-secret", response.text)

    def test_nested_constraints_are_validated(self):
        self.register({"type": "object", "properties": {
            "values": {"type": "array", "items": {"type": "integer", "minimum": 1}},
        }, "required": ["values"], "additionalProperties": False})
        for value in ({"values": [0]}, {"values": [True]}, {"values": [1], "extra": 1}):
            with self.subTest(value=value):
                self.assertTrue(self.call_with(value).json()["result"].get("isError"))

    def test_external_refs_are_not_fetched(self):
        self.register({"type": "object", "properties": {
            "value": {"$ref": "https://schemas.invalid/private.json"},
        }})
        response = self.call_with({"value": "private-secret"})
        self.assertTrue(response.json()["result"].get("isError"))
        self.assertNotIn("private-secret", response.text)

    def test_metadata_uses_standard_meta_for_success_and_failure(self):
        self.register({"type": "object", "required": ["online"]})
        for value in ({"online": True}, {}):
            with self.subTest(value=value):
                response = self.call_with(value)
                result = response.json()["result"]
                self.assertNotIn("meta", result)
                self.assertEqual(result["_meta"]["tool_name"], "value")
                self.assertEqual(result["_meta"]["x-request-id"], response.headers["x-request-id"])

    def test_notifications_return_empty_202_and_never_execute_tools(self):
        for method in ("notifications/initialized", "notifications/cancelled", "notifications/unknown",
                       "tools/call"):
            with self.subTest(method=method):
                response = self.client.post("/mcp?tenant=test", json={
                    "jsonrpc": "2.0", "method": method,
                    "params": {"name": "missing", "arguments": {}},
                })
                self.assertEqual(response.status_code, 202)
                self.assertEqual(response.content, b"")

    def test_invalid_request_ids_are_rejected_without_echoing(self):
        for rpc_id in (None, True, False, [], {}, 1.5):
            with self.subTest(rpc_id=rpc_id):
                response = self.rpc("tools/list", rpc_id=rpc_id)
                self.assertEqual(response.status_code, 400)
                payload = response.json()
                self.assertEqual(payload["error"]["code"], -32600)
                self.assertIsNone(payload.get("id"))

    def test_valid_ids_round_trip(self):
        for rpc_id in (0, -1, 4, "request-1"):
            with self.subTest(rpc_id=rpc_id):
                payload = self.rpc("tools/list", rpc_id=rpc_id).json()
                self.assertEqual(payload["id"], rpc_id)
                self.assertIn("result", payload)

    def test_initialization_negotiates_only_supported_versions(self):
        for requested, expected in (("2025-06-18", "2025-06-18"),
                                    ("2025-11-25", "2025-11-25"),
                                    ("2024-11-05", "2025-11-25"),
                                    ("2099-01-01", "2025-11-25")):
            with self.subTest(requested=requested):
                response = self.rpc("initialize", {
                    "protocolVersion": requested, "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                })
                self.assertEqual(response.json()["result"]["protocolVersion"], expected)

    def test_invalid_initialize_params_are_rejected(self):
        for params in ({}, {"protocolVersion": 12}, {"protocolVersion": "2025-11-25"}):
            with self.subTest(params=params):
                self.assertEqual(self.rpc("initialize", params).json()["error"]["code"], -32602)

    def test_unsupported_protocol_headers_are_http_400(self):
        for method, params in (("tools/list", {}), ("initialize", {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        })):
            with self.subTest(method=method):
                response = self.rpc(method, params, headers={"MCP-Protocol-Version": "2099-01-01"})
                self.assertEqual(response.status_code, 400)
        for version in ("2025-06-18", "2025-11-25"):
            self.assertEqual(self.rpc("tools/list", headers={"MCP-Protocol-Version": version}).status_code, 200)

    def test_ping_returns_empty_result(self):
        self.assertEqual(self.rpc("ping").json(), {"jsonrpc": "2.0", "id": 1, "result": {}})

    def test_wrapped_output_preserves_local_reference_targets(self):
        for nullable in (False, True):
            with self.subTest(nullable=nullable):
                schema = {"type": "array", "$defs": {"item": {"type": "integer"}},
                          "items": {"$ref": "#/$defs/item"}}
                if nullable:
                    schema["nullable"] = True
                self.register(schema)
                result = self.call_with([1]).json()["result"]
                self.assertNotIn("isError", result)
                self.assertEqual(result["structuredContent"], {"data": [1]})
                Draft202012Validator(self.output_schema()).validate(result["structuredContent"])

    def test_openapi_boolean_exclusive_bounds_are_converted(self):
        for keyword, bound, value, exclusive, valid in (
            ("minimum", 0, 1, True, True), ("minimum", 0, 0, True, False),
            ("minimum", 0, 0, False, True), ("maximum", 2, 1, True, True),
            ("maximum", 2, 2, True, False), ("maximum", 2, 2, False, True),
        ):
            with self.subTest(keyword=keyword, value=value, exclusive=exclusive):
                self.register({"type": "number", keyword: bound,
                               "exclusive" + keyword.title(): exclusive})
                contract = self.output_schema()
                Draft202012Validator.check_schema(contract)
                result = self.call_with(value).json()["result"]
                self.assertEqual(not result.get("isError", False), valid)

    def test_declared_draft07_is_used_for_output_validation(self):
        self.register({"$schema": "http://json-schema.org/draft-07/schema#",
                       "type": "array", "items": [{"type": "integer"}],
                       "additionalItems": False})
        result = self.call_with([1]).json()["result"]
        self.assertNotIn("isError", result)
        self.assertEqual(result["structuredContent"], {"data": [1]})
        Draft202012Validator(self.output_schema()).validate(result["structuredContent"])
        self.assertTrue(self.call_with(["wrong"]).json()["result"].get("isError"))

    def test_unknown_schema_dialect_is_reported_explicitly(self):
        self.register({"$schema": "https://example.invalid/unknown-schema", "type": "object"})
        result = self.call_with({}).json()["result"]
        self.assertTrue(result.get("isError"))
        self.assertEqual(result["_meta"]["error_details"]["type"], "unsupported_schema_dialect")

    def test_vendor_json_success_is_parsed_before_output_validation(self):
        self.register({"type": "object"}, "application/vnd.example+json")
        with patch("app.mcp.rest.executor.httpx.AsyncClient.request", return_value=httpx.Response(
            200, content='{"online":true}', headers={"Content-Type": "Application/Vnd.Example+Json; charset=utf-8"},
        )):
            result = self.rpc("tools/call", {"name": "value"}).json()["result"]
            self.assertNotIn("isError", result)
            self.assertEqual(result["structuredContent"], {"online": True})

    def test_unreadable_request_ids_are_omitted_from_error_envelopes(self):
        for body in ("{", "[]", '{"jsonrpc":"2.0","id":true,"method":"ping"}'):
            with self.subTest(body=body):
                response = self.client.post("/mcp?tenant=test", content=body, headers={
                    "Content-Type": "application/json", "MCP-Protocol-Version": "2025-11-25",
                })
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.json())
                self.assertNotIn("id", response.json())


if __name__ == "__main__":
    unittest.main()

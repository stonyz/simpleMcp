import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mcp.tenant_manager import TenantManager
from app.midware.RequestIdMiddleware import RequestIdMiddleware
from app.routers.mcp import router


class ToolErrorTests(unittest.TestCase):
    def setUp(self):
        self.manager = TenantManager()
        self.metadata = {
            "type": "rest_api", "method": "get",
            "url_template": "http://upstream.invalid/api/watch/location?token=url-secret",
            "parameters": [{"name": "wait_time", "in": "query",
                            "schema": {"type": "integer", "minimum": 0}}],
            "body_schema": None, "security_schemes": [],
            "tool_name": "getWatchLocation", "orgid": "org", "appid": "app",
        }
        self.manager.get_tenant_registry("test").register_function(
            "getWatchLocation", self.metadata, {}, "org", "app")
        app = FastAPI()
        app.include_router(router, prefix="/mcp")
        app.add_middleware(RequestIdMiddleware)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        patcher = patch("app.routers.mcp.tenant_manager", self.manager)
        patcher.start()
        self.addCleanup(patcher.stop)

    def upstream(self, body, status=502, content_type="application/json"):
        return httpx.Response(status, content=body.encode("utf-8"),
                              headers={"Content-Type": content_type})

    def call(self, arguments=None, method="tools/call", **params):
        return self.client.post("/mcp?tenant=test", json={
            "jsonrpc": "2.0", "id": 7, "method": method,
            "params": {"name": "getWatchLocation",
                       "arguments": arguments if arguments is not None else {}, **params},
        })

    def assert_execution_error(self, response, error_type, status=None):
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["id"], 7)
        self.assertNotIn("error", payload)
        result = payload["result"]
        self.assertTrue(result["isError"])
        self.assertEqual(result["content"][0]["type"], "text")
        self.assertEqual(result["meta"]["tool_name"], "getWatchLocation")
        self.assertEqual(result["meta"]["x-request-id"], response.headers["x-request-id"])
        details = result["_meta"]["error_details"]
        self.assertEqual(details["type"], error_type)
        if status is None:
            self.assertNotIn("status_code", details)
        else:
            self.assertEqual(details["status_code"], status)
        self.assertNotIn("url-secret", response.text)
        return result["content"][0]["text"], details

    def test_chinese_http_error_is_visible_for_both_mcp_aliases(self):
        for method in ("tools/call", "call_tool"):
            with self.subTest(method=method), patch(
                "app.mcp.rest.executor.httpx.AsyncClient.request",
                return_value=self.upstream('{"error":"手表不在线，无法获取位置信息"}'),
            ):
                message, details = self.assert_execution_error(
                    self.call(method=method), "upstream_http_error", 502)
                self.assertIn("手表不在线，无法获取位置信息", message)
                self.assertIn("502", message)
                self.assertEqual(details["body"], {"error": "手表不在线，无法获取位置信息"})

    def test_legacy_endpoint_preserves_string_error_and_adds_details(self):
        with patch("app.mcp.rest.executor.httpx.AsyncClient.request",
                   return_value=self.upstream('{"error":"手表不在线"}')):
            response = self.client.post("/mcp/call?tenant=test", json={
                "function_name": "getWatchLocation", "parameters": {}})
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "error")
        self.assertIn("手表不在线", payload["error"])
        self.assertEqual(payload["error_details"]["status_code"], 502)
        self.assertEqual(payload["meta"]["x-request-id"], response.headers["x-request-id"])

    def test_error_body_fallbacks_and_json_suffix(self):
        fixtures = [
            ('{"message":"限流"}', "application/problem+json", "限流", {"message": "限流"}),
            ('{"detail":"无权限"}', "application/json", "无权限", {"detail": "无权限"}),
            ('{"detail":[{"msg":"字段错误"}]}', "application/json", "字段错误", {"detail": [{"msg": "字段错误"}]}),
            ('["错误"]', "application/json", "错误", ["错误"]),
            ('broken json', "application/json", "broken json", "broken json"),
            ('维护中', "text/plain", "维护中", "维护中"),
            ('', "application/json", "502", ""),
            ('<html>internal debug page</html>', "text/html", "502", None),
        ]
        for body, ctype, expected_message, expected_body in fixtures:
            with self.subTest(body=body), patch(
                "app.mcp.rest.executor.httpx.AsyncClient.request",
                return_value=self.upstream(body, content_type=ctype),
            ):
                message, details = self.assert_execution_error(self.call(), "upstream_http_error", 502)
                self.assertIn(expected_message, message)
                if expected_body is None:
                    self.assertNotIn("body", details)
                    self.assertNotIn("internal debug page", message)
                else:
                    self.assertEqual(details["body"], expected_body)

    def test_redacts_nested_credentials_before_extracting_message(self):
        body = json.dumps({"error": "failed: token=text-secret Authorization: Bearer bearer-secret",
                           "nested": [{"access_token": "access-secret", "password": "password-secret",
                                       "client_secret": "client-secret", "refresh_token": "refresh-secret",
                                       "Authorization": "header-secret", "api_key": "api-secret"}]})
        with patch("app.mcp.rest.executor.httpx.AsyncClient.request", return_value=self.upstream(body)):
            response = self.call()
        self.assert_execution_error(response, "upstream_http_error", 502)
        for secret in ("text-secret", "bearer-secret", "access-secret", "password-secret",
                       "client-secret", "refresh-secret", "header-secret", "api-secret"):
            self.assertNotIn(secret, response.text)

    def test_long_body_is_bounded_and_marked_truncated(self):
        with patch("app.mcp.rest.executor.httpx.AsyncClient.request",
                   return_value=self.upstream(json.dumps({"error": "长" * 6000}))):
            message, details = self.assert_execution_error(self.call(), "upstream_http_error", 502)
        self.assertTrue(details["truncated"])
        self.assertIsInstance(details["body"], str)
        self.assertLessEqual(len(details["body"]), 4096)
        self.assertLess(len(message), 4200)

    def test_basic_auth_and_text_assignments_are_redacted(self):
        text = 'Authorization: Basic dXNlcjpwYXNz password="plain secret" api_key=key-secret'
        for body, ctype in ((text, "text/plain"), (json.dumps({"error": text}), "application/json")):
            with self.subTest(ctype=ctype), patch("app.mcp.rest.executor.httpx.AsyncClient.request",
                                                return_value=self.upstream(body, content_type=ctype)):
                response = self.call()
                self.assert_execution_error(response, "upstream_http_error", 502)
                for secret in ("dXNlcjpwYXNz", "plain secret", "key-secret"):
                    self.assertNotIn(secret, response.text)

    def test_network_failures_have_no_invented_http_status(self):
        for exception, kind in [
            (httpx.ReadTimeout("url-secret"), "upstream_timeout"),
            (httpx.ConnectError("url-secret"), "upstream_connection_error"),
            (httpx.RequestError("url-secret"), "upstream_request_error"),
        ]:
            with self.subTest(kind=kind), patch("app.mcp.rest.executor.httpx.AsyncClient.request", side_effect=exception):
                self.assert_execution_error(self.call(), kind)

    def test_oauth_failure_keeps_message_without_full_body(self):
        self.metadata["auth"] = json.dumps({"client_id": "client", "client_secret": "secret",
                                            "token_url": "http://auth.invalid/token"})
        response = self.upstream('{"error":"invalid_client","client_secret":"oauth-secret","debug":"private-debug"}', 401)
        with patch("app.mcp.rest.auth_handler.requests.post", return_value=response):
            result = self.call()
        message, details = self.assert_execution_error(result, "upstream_http_error", 401)
        self.assertIn("invalid_client", message)
        self.assertNotIn("body", details)
        self.assertNotIn("oauth-secret", result.text)
        self.assertNotIn("private-debug", result.text)

    def test_parameter_value_error_is_execution_error(self):
        message, _ = self.assert_execution_error(self.call({"wait_time": -1}), "validation_error")
        self.assertIn("wait_time", message)

    def test_unexpected_execution_exception_is_generic(self):
        with self.assertLogs("app.mcp.tool_executor", level="ERROR") as logs, patch(
            "app.mcp.rest.executor.httpx.AsyncClient.request", side_effect=RuntimeError("private-stack-secret")
        ):
            response = self.call()
        self.assert_execution_error(response, "tool_execution_error")
        self.assertNotIn("private-stack-secret", response.text)
        self.assertIn("private-stack-secret", "\n".join(logs.output))

    def test_unknown_and_inaccessible_tools_remain_protocol_errors(self):
        for params in ({"name": "missing"}, {"orgid": "other", "appid": "app"}):
            with self.subTest(params=params):
                payload = self.call(**params).json()
                self.assertIn("error", payload)
                self.assertNotIn("result", payload)

    def test_malformed_requests_remain_protocol_errors(self):
        fixtures = [[], None]
        fixtures += [{"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": value}
                     for value in ([], "wrong", 0)]
        fixtures += [{"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": params}
                     for params in ({}, {"name": []}, {"name": 3}, {"name": "getWatchLocation", "arguments": []},
                                    {"name": "getWatchLocation", "arguments": False},
                                    {"name": "getWatchLocation", "arguments": "wrong"})]
        for fixture in fixtures:
            with self.subTest(fixture=fixture):
                # Use content so JSON null is sent rather than an empty HTTP body.
                response = self.client.post("/mcp?tenant=test", content=json.dumps(fixture),
                                            headers={"Content-Type": "application/json"})
                payload = response.json()
                self.assertIn("error", payload)
                self.assertNotIn("result", payload)
                self.assertIn(payload["error"]["code"], (-32600, -32602))

    def test_invalid_json_remains_parse_error(self):
        response = self.client.post("/mcp?tenant=test", content="{broken")
        self.assertEqual(response.json()["error"]["code"], -32700)

    def test_success_shapes_are_unchanged(self):
        for body, ctype, expected in [('{"online":true}', "application/json", {"online": True}),
                                      ("ready", "text/plain", "ready")]:
            with self.subTest(body=body), patch("app.mcp.rest.executor.httpx.AsyncClient.request",
                                              return_value=self.upstream(body, 200, ctype)):
                payload = self.call().json()
                self.assertNotIn("error", payload)
                result = payload["result"]
                self.assertNotIn("isError", result)
                text = result["content"][0]["text"]
                self.assertEqual(json.loads(text) if isinstance(expected, dict) else text, expected)
                legacy = self.client.post("/mcp/call?tenant=test", json={
                    "function_name": "getWatchLocation", "parameters": {}}).json()
                self.assertEqual(legacy["status"], "success")
                self.assertEqual(legacy["result"], expected)


if __name__ == "__main__":
    unittest.main()

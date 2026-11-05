import tempfile
import unittest
import logging
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.midware.AuthMiddleware import AuthMiddleware
from app.midware.LoggingMiddleware import LoggingMiddleware
from app.midware.TenantMiddleware import TenantMiddleware


class AdminHostingTests(unittest.TestCase):
    def test_unbuilt_admin_reserves_prefix_before_tenant_rewriting(self):
        from app.admin_hosting import mount_admin
        app = FastAPI()
        app.add_middleware(TenantMiddleware)
        app.add_middleware(AuthMiddleware)
        app.post("/services/save")(lambda: {"secret": "protected"})
        app.get("/services/detail")(lambda: {"secret": "protected"})
        with tempfile.TemporaryDirectory() as root:
            mount_admin(app, Path(root) / "does-not-exist")
            with patch("app.midware.AuthMiddleware.settings.AUTH_TOKENS", ["secret"]), TestClient(app) as client:
                self.assertEqual(client.get("/admin").status_code, 503)
                response = client.get("/admin/")
                self.assertEqual(response.status_code, 503)
                self.assertIn('<html lang="en">', response.text)
                self.assertIn("Admin UI has not been built", response.text)
                self.assertIn("npm ci", response.text)
                self.assertIn("npm run build", response.text)
                for method, path in [("POST", "/admin/services/save"), ("GET", "/admin/services/detail")]:
                    response = client.request(method, path)
                    self.assertIn(response.status_code, (404, 405))
                    self.assertNotIn("protected", response.text)

    def test_admin_assets_are_public_but_services_are_protected(self):
        from app.admin_hosting import mount_admin
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            (directory / "index.html").write_text("<html>admin entry</html>")
            (directory / "asset.js").write_text("console.log('admin');")
            app = FastAPI()
            app.add_middleware(TenantMiddleware)
            app.add_middleware(AuthMiddleware)
            app.get("/services/")(lambda: {"items": []})
            mount_admin(app, directory)
            with patch("app.midware.AuthMiddleware.settings.AUTH_TOKENS", ["expected"]), TestClient(app) as client:
                self.assertEqual(client.get("/admin").status_code, 200)
                self.assertIn("admin entry", client.get("/admin/").text)
                self.assertEqual(client.get("/admin/asset.js").status_code, 200)
                self.assertEqual(client.get("/admin/missing.js").status_code, 404)
                self.assertEqual(client.get("/services/").status_code, 401)
                self.assertEqual(client.get("/services/", headers={"Authorization": "Bearer expected"}).status_code, 200)
                self.assertEqual(client.get("/admin-api").status_code, 401)

    def test_info_logs_only_summary(self):
        app = FastAPI()
        app.add_middleware(LoggingMiddleware)
        app.post("/services/save")(lambda: {"document": "RESPONSE_SECRET"})
        logger = logging.Logger("test-request-info", level=logging.INFO)
        with patch("app.midware.LoggingMiddleware.request_logger", logger), self.assertLogs(logger, level="INFO") as captured, TestClient(app) as client:
            result = client.post("/services/save?tenant=one&token=QUERY_SECRET",
                                 headers={"Authorization": "Bearer HEADER_SECRET"},
                                 json={"auth": "BODY_SECRET", "yaml_content": "DOC_SECRET"})
            self.assertEqual(result.status_code, 200)
            logs = str(captured.output)
            self.assertIn("/services/save", logs)
            for secret in ["QUERY_SECRET", "HEADER_SECRET", "BODY_SECRET", "DOC_SECRET", "RESPONSE_SECRET"]:
                self.assertNotIn(secret, logs)

    def test_debug_logs_request_response_headers_and_query(self):
        app = FastAPI()
        app.add_middleware(LoggingMiddleware)

        @app.post("/echo")
        async def echo(request: Request):
            return {"received": await request.json()}

        logger = logging.Logger("test-request-debug", level=logging.DEBUG)
        with patch("app.midware.LoggingMiddleware.request_logger", logger), self.assertLogs(logger, level="DEBUG") as captured, TestClient(app) as client:
            response = client.post("/echo?q=QUERY", headers={"X-Debug": "HEADER"}, json={"message": "请求正文"})
        self.assertEqual(response.json(), {"received": {"message": "请求正文"}})
        logs = "\n".join(captured.output)
        for value in ["q=QUERY", "HEADER", "请求正文", "received", "Req:", "Resp:"]:
            self.assertIn(value, logs)

    def test_debug_credential_secrets_are_not_logged(self):
        app = FastAPI()
        app.add_middleware(LoggingMiddleware)
        app.post('/credentials/')(lambda: {'secret': 'ONCE_ONLY_SECRET'})
        logger = logging.Logger('test-credential-logging', level=logging.DEBUG)
        with patch('app.midware.LoggingMiddleware.request_logger', logger), self.assertLogs(logger, level='DEBUG') as captured, TestClient(app) as client:
            response = client.post('/credentials/?token=QUERY_SECRET', headers={'Authorization': 'Bearer HEADER_SECRET'})
            self.assertEqual(response.json()['secret'], 'ONCE_ONLY_SECRET')
        for secret in ['ONCE_ONLY_SECRET', 'QUERY_SECRET', 'HEADER_SECRET']:
            self.assertNotIn(secret, '\n'.join(captured.output))

    def test_debug_preserves_binary_cookies_and_streamed_response(self):
        from starlette.responses import Response, StreamingResponse
        app = FastAPI()
        app.add_middleware(LoggingMiddleware)

        @app.get("/binary")
        def binary():
            response = Response(b"\xff\x00\xfe", media_type="application/octet-stream")
            response.set_cookie("one", "1")
            response.set_cookie("two", "2")
            return response

        @app.get("/events")
        async def events():
            async def chunks():
                yield b"data: event-content\n\n"
            return StreamingResponse(chunks(), media_type="text/event-stream")

        logger = logging.Logger("test-request-binary", level=logging.DEBUG)
        with patch("app.midware.LoggingMiddleware.request_logger", logger), self.assertLogs(logger, level="DEBUG") as captured, TestClient(app) as client:
            response = client.get("/binary")
            self.assertEqual(response.content, b"\xff\x00\xfe")
            self.assertEqual(len(response.headers.get_list("set-cookie")), 2)
            self.assertEqual(client.get("/events").content, b"data: event-content\n\n")
        self.assertNotIn("event-content", "\n".join(captured.output))

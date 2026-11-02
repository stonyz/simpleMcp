import asyncio
import math
import json
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mcp.tenant_manager import TenantManager
from app.mcp.rest.executor import execute_rest_call
from app.mcp.tool_registry import parse_tools_from_openapi
from app.routers.services import router as services_router
from app.routers.mcp import router as mcp_router


def specification(timeout=5):
    return {
        "openapi": "3.0.3", "info": {"title": "Example", "version": "1"},
        "servers": [{"url": "https://upstream.invalid"}],
        "paths": {"/report": {"get": {
            "operationId": "report", "x-request-timeout-seconds": timeout,
            "responses": {"200": {"description": "OK"}},
        }}},
    }


class TimeoutRegistrationTests(unittest.TestCase):
    def test_operation_budget_and_default_are_independent(self):
        spec = specification(120)
        spec["paths"]["/quick"] = {"get": {"operationId": "quick"}}
        tools = parse_tools_from_openapi("org", "app", spec)
        self.assertEqual(tools[0]["metadata"]["request_timeout_seconds"], 120)
        self.assertEqual(tools[1]["metadata"]["request_timeout_seconds"], 30)
        self.assertNotIn("x-request-timeout-seconds", tools[0]["schema"]["input_schema"]["properties"])

    def test_invalid_budgets_are_rejected(self):
        for value in (0, -1, True, False, None, "5", [], {}, math.inf, math.nan, 10 ** 400):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "x-request-timeout-seconds"):
                parse_tools_from_openapi("org", "app", specification(value))

    def test_invalid_registration_does_not_write_database_or_registry(self):
        app = FastAPI()
        app.include_router(services_router, prefix="/services")
        with TestClient(app) as client, patch("app.routers.services.get_db_context") as db, patch(
            "app.routers.services.tenant_manager.register_tools_from_openapi"
        ) as register:
            response = client.post("/services/register?tenant=test", json={
                "org": "org", "app": "app", "fileId": "file", "fileName": "api.json",
                "yaml_content": json.dumps(specification(0)),
            })
        self.assertEqual(response.status_code, 400)
        self.assertIn("x-request-timeout-seconds", response.json()["detail"])
        db.assert_not_called()
        register.assert_not_called()


class RequestDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_keeps_existing_query_and_requests_parameter_encoding(self):
        async def handler(request):
            return httpx.Response(200, json={"query": str(request.url.query, "ascii")})
        client_type = httpx.AsyncClient
        def client_factory(**kwargs):
            return client_type(**kwargs, transport=httpx.MockTransport(handler))
        with patch("app.mcp.rest.executor.httpx.AsyncClient", side_effect=client_factory):
            for query, expected in (
                ({}, "fixed=1"),
                ({"q": "v", "omit": None, "flag": True, "ids": [1, 2]},
                 "fixed=1&q=v&flag=True&ids=1&ids=2"),
            ):
                result = await execute_rest_call("GET", "https://upstream.invalid/report?fixed=1",
                                                 {}, query, None)
                self.assertEqual(result["query"], expected)

    async def execute(self, timeout, handler):
        manager = TenantManager()
        manager.register_tools_from_openapi("test", "org", "app", specification(timeout))
        client_type = httpx.AsyncClient
        def client_factory(**kwargs):
            return client_type(**kwargs, transport=httpx.MockTransport(handler))
        with patch("app.mcp.rest.executor.httpx.AsyncClient", side_effect=client_factory):
            return await manager.execute_tool("test", "report")

    async def test_slow_headers_timeout_and_request_is_cancelled(self):
        cancelled = asyncio.Event()
        async def handler(request):
            try:
                await asyncio.sleep(2)
                return httpx.Response(200, json={"ok": True})
            finally:
                cancelled.set()
        error, result, _ = await self.execute(0.05, handler)
        self.assertEqual(error.details["type"], "upstream_timeout")
        self.assertIsNone(result)
        self.assertTrue(cancelled.is_set())

    async def test_continuous_response_data_cannot_extend_total_budget(self):
        closed = asyncio.Event()
        class Trickle(httpx.AsyncByteStream):
            async def __aiter__(self):
                for _ in range(100):
                    await asyncio.sleep(0.01)
                    yield b"x"
            async def aclose(self):
                closed.set()
        async def handler(request):
            return httpx.Response(200, stream=Trickle())
        start = asyncio.get_running_loop().time()
        error, _, _ = await self.execute(0.08, handler)
        self.assertEqual(error.details["type"], "upstream_timeout")
        self.assertLess(asyncio.get_running_loop().time() - start, 0.8)
        self.assertTrue(closed.is_set())

    async def test_larger_budget_allows_same_slow_api_to_succeed(self):
        async def handler(request):
            await asyncio.sleep(0.08)
            return httpx.Response(200, json={"ok": True})
        error, result, _ = await self.execute(0.5, handler)
        self.assertIsNone(error)
        self.assertEqual(result, {"ok": True})

    async def test_redirects_share_one_budget(self):
        async def handler(request):
            await asyncio.sleep(0.04)
            return httpx.Response(302, headers={"Location": "/next"})
        error, _, _ = await self.execute(0.09, handler)
        self.assertEqual(error.details["type"], "upstream_timeout")

    async def test_slow_call_does_not_block_a_fast_call(self):
        started = asyncio.Event()
        release = asyncio.Event()
        async def slow(request):
            started.set()
            await release.wait()
            return httpx.Response(200, text="slow")
        async def fast(request):
            return httpx.Response(200, text="fast")
        # One client factory dispatches by the API path to keep concurrent calls
        # on the same real HTTPX client implementation.
        manager = TenantManager()
        spec = specification(1)
        spec["paths"]["/fast"] = {"get": {"operationId": "fast"}}
        manager.register_tools_from_openapi("test", "org", "app", spec)
        async def handler(request):
            return await (fast(request) if request.url.path == "/fast" else slow(request))
        client_type = httpx.AsyncClient
        def client_factory(**kwargs):
            return client_type(**kwargs, transport=httpx.MockTransport(handler))
        with patch("app.mcp.rest.executor.httpx.AsyncClient", side_effect=client_factory):
            task = asyncio.create_task(manager.execute_tool("test", "report"))
            try:
                await asyncio.wait_for(started.wait(), 0.5)
                error, result, _ = await asyncio.wait_for(manager.execute_tool("test", "fast"), 0.5)
                self.assertIsNone(error)
                self.assertEqual(result, "fast")
                self.assertFalse(task.done())
            finally:
                release.set()
                await task


class TimeoutEndpointTests(unittest.TestCase):
    def test_actual_deadline_keeps_error_format_at_all_call_endpoints(self):
        manager = TenantManager()
        manager.register_tools_from_openapi("test", "org", "app", specification(0.02))
        app = FastAPI()
        app.include_router(mcp_router, prefix="/mcp")
        async def handler(request):
            await asyncio.sleep(1)
            return httpx.Response(200, text="too late")
        client_type = httpx.AsyncClient
        def client_factory(**kwargs):
            return client_type(**kwargs, transport=httpx.MockTransport(handler))
        with TestClient(app) as client, patch("app.routers.mcp.tenant_manager", manager), patch(
            "app.mcp.rest.executor.httpx.AsyncClient", side_effect=client_factory
        ):
            for method in ("tools/call", "call_tool"):
                response = client.post("/mcp?tenant=test", json={
                    "jsonrpc": "2.0", "id": 1, "method": method,
                    "params": {"name": "report", "arguments": {}},
                })
                self.assertEqual(response.status_code, 200)
                result = response.json()["result"]
                self.assertTrue(result["isError"])
                self.assertEqual(result["_meta"]["error_details"]["type"], "upstream_timeout")
            result = client.post("/mcp/call?tenant=test", json={
                "function_name": "report", "parameters": {},
            }).json()
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error_details"]["type"], "upstream_timeout")

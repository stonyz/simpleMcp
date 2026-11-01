from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
from app.mcp.tenant_manager import tenant_manager
# from app.mcp.registry import registry
from app.config import settings
# Import the request_id_context from RequestIdMiddleware
from app.midware.RequestIdMiddleware import request_id_context
import json
import logging
log = logging.getLogger(__name__)

router = APIRouter()

@router.get("/list")
async def mcp_list(
    tenant: str = Query(..., alias="tenant"),
    orgid: Optional[str] = Query(None),
    appid: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
):
    """
    MCP 风格的 list：返回 function schemas
    （你也可以保持与 /functions 一致）
    """
    return tenant_manager.list_functions(tenant=tenant, orgid=orgid, appid=appid, name=name)

@router.post("/call")
async def mcp_call(
    tenant: str = Query(..., alias="tenant"),
    function_name: str = Body(..., embed=True),
    parameters: Dict[str, Any] = Body(default_factory=dict, embed=True),
    orgid: Optional[str] = Body(None, embed=True),
    appid: Optional[str] = Body(None, embed=True)
):
    """
    MCP 风格的 call：执行实际的 REST 请求。
    Body 示例：
    {
      "function_name": "get_user",
      "parameters": {"user_id": "123"},
      "orgid": "org1",
      "appid": "app1"
    }
    """
    try:
        errorMessage, result, meta = tenant_manager.execute_tool(tenant=tenant, name=function_name, orgid=orgid, appid=appid, **parameters)
        
        # 获取request_id并添加到meta中
        meta["x-request-id"] = request_id_context.get("")
        
        if errorMessage:
            return {"status": "error", "error": str(errorMessage),
                    "error_details": errorMessage.details, "meta": meta}
        return {"status": "success", "result": result, "meta": meta}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("")
async def mcp_jsonrpc(
    request: Request,
    tenant: str = Query(..., alias="tenant")):

    """
    标准 MCP JSON-RPC 2.0 接口：支持 tools/list 与 tools/call（兼容 list_tools/call_tool），以及 initialize。
    - initialize: 返回协议版本、服务端能力与 serverInfo
    - tools/list 或 list_tools: params 可包含 orgid/appid/name 进行过滤
    - tools/call 或 call_tool: params 包含 name/function_name 与 arguments/parameters
    - 支持通过 HTTP Headers 传递 orgid/appid: X-Org-ID, X-App-ID
    返回严格的 JSON-RPC 2.0 格式。
    """
    log.info(f"Received request: {request.method} {request.url}")
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32700, "message": "Parse error"}
        })

    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={
            "jsonrpc": "2.0", "id": None,
            "error": {"code": -32600, "message": "Invalid Request"}
        })

    jsonrpc = body.get("jsonrpc")
    method = body.get("method")
    rpc_id = body.get("id")
    params = body.get("params", {})
    
    # 从 HTTP Headers 或 params 获取 orgid/appid
    header_orgid = request.headers.get("X-Org-ID")
    header_appid = request.headers.get("X-App-ID")

    if jsonrpc != "2.0" or not isinstance(method, str):
        return JSONResponse(status_code=400, content={
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32600, "message": "Invalid Request"}
        })

    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": -32602, "message": "params must be an object"}}

    try:
        if method == "initialize":
            client_protocol = params.get("protocolVersion")
            result = {
                "protocolVersion": client_protocol or "2024-11-05",
                "serverInfo": {
                    "name": settings.APP_NAME,
                    "version": getattr(settings, "APP_VERSION", "0.1.0")
                },
                "capabilities": {
                    "tools": {}
                }
            }
            return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

        if method in ("tools/list", "list_tools"):
            # 优先使用 params 中的值，其次使用 headers
            orgid = params.get("orgid") or header_orgid
            appid = params.get("appid") or header_appid
            name: Optional[str] = params.get("name")

            schemas = tenant_manager.list_functions(tenant=tenant, orgid=orgid, appid=appid, name=name)
            tools = []
            for s in schemas:
                tool = {
                    "name": s.get("name"),
                    "description": s.get("description", ""),
                    "inputSchema": s.get("input_schema") or {"type": "object", "properties": {}}
                }
                # 添加 outputSchema 如果存在
                if s.get("output_schema"):
                    tool["outputSchema"] = s["output_schema"]
                tools.append(tool)
            
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tools}}

        if method in ("tools/call", "call_tool"):
            name = params.get("name", params.get("function_name"))
            if not isinstance(name, str) or not name:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Missing 'name' or 'function_name'"}}
            arguments = params.get("arguments", params.get("parameters", {}))
            if not isinstance(arguments, dict):
                return {"jsonrpc": "2.0", "id": rpc_id,
                        "error": {"code": -32602, "message": "arguments must be an object"}}
            
            # 优先使用 params 中的值，其次使用 headers
            call_orgid = params.get("orgid") or header_orgid
            call_appid = params.get("appid") or header_appid
            
            try:
                errorMessage, result, meta = tenant_manager.execute_tool(tenant=tenant, name = name, orgid=call_orgid, appid=call_appid, **arguments)
                
                # 获取request_id并添加到meta中
                meta["x-request-id"] = request_id_context.get("")
                
                if errorMessage:
                    return {"jsonrpc": "2.0", "id": rpc_id, "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": str(errorMessage)}],
                        "_meta": {"error_details": errorMessage.details},
                        "meta": meta,
                    }}
            except Exception as e:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32000, "message": str(e)}}

            # 以 text 类型返回。如果结果非字符串，序列化为 JSON 文本
            if isinstance(result, str):
                text_payload = result
            else:
                try:
                    text_payload = json.dumps(result, ensure_ascii=False)
                except Exception:
                    text_payload = str(result)

            # Add extra information to the response
            response_content = {
                "content": [
                    {"type": "text", "text": text_payload}
                ]
            }
            if meta:
                response_content["meta"] = meta

            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": response_content
            }

        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Method not found"}}

    except Exception as e:
        # 未预期的服务器错误
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": str(e)}}

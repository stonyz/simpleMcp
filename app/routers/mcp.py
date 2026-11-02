from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from app.access import authorize_request, rpc_scope
from fastapi.responses import JSONResponse, Response
from typing import Dict, Any, Optional
from app.mcp.tenant_manager import tenant_manager
# from app.mcp.registry import registry
from app.config import settings
from app.mcp.errors import ToolExecutionError
from app.mcp.output import output_contract, structured_output
# Import the request_id_context from RequestIdMiddleware
from app.midware.RequestIdMiddleware import request_id_context
import json
import logging
log = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(authorize_request)])
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-11-25")


def _rpc_error(rpc_id, code: int, message: str, status_code: int = 200):
    content = {"jsonrpc": "2.0", "error": {"code": code, "message": message}}
    if rpc_id is not None:
        content["id"] = rpc_id
    return JSONResponse(status_code=status_code, content=content)


def _tool_error(rpc_id, error: ToolExecutionError, meta: dict):
    return {"jsonrpc": "2.0", "id": rpc_id, "result": {
        "isError": True,
        "content": [{"type": "text", "text": str(error)}],
        "_meta": {**meta, "error_details": error.details},
    }}

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
        errorMessage, result, meta = await tenant_manager.execute_tool(tenant=tenant, name=function_name, orgid=orgid, appid=appid, **parameters)
        
        # 获取request_id并添加到meta中
        meta["x-request-id"] = request_id_context.get("")
        
        if errorMessage:
            return {"status": "error", "error": str(errorMessage),
                    "error_details": errorMessage.details, "meta": meta}
        return {"status": "success", "result": result, "meta": meta}
    except HTTPException:
        raise
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
    log.info('Received request: %s %s', request.method, request.url.path)
    try:
        body = await request.json()
    except Exception:
        return _rpc_error(None, -32700, "Parse error", 400)

    if not isinstance(body, dict):
        return _rpc_error(None, -32600, "Invalid Request", 400)

    jsonrpc = body.get("jsonrpc")
    method = body.get("method")
    rpc_id = body.get("id")
    params = body.get("params", {})
    valid_id = isinstance(rpc_id, str) or type(rpc_id) is int
    
    if jsonrpc != "2.0" or not isinstance(method, str) or ("id" in body and not valid_id):
        return _rpc_error(rpc_id if valid_id else None, -32600, "Invalid Request", 400)

    protocol_header = request.headers.get("MCP-Protocol-Version")
    if protocol_header is not None and protocol_header not in SUPPORTED_PROTOCOL_VERSIONS:
        return _rpc_error(rpc_id if valid_id else None, -32600, "Unsupported MCP-Protocol-Version", 400)

    # Notifications have no ID and must never produce a JSON-RPC response or
    # accidentally execute a tool. This stateless server has no cancellation state.
    if "id" not in body:
        return Response(status_code=202 if isinstance(params, dict) else 400)

    if not isinstance(params, dict):
        return {"jsonrpc": "2.0", "id": rpc_id,
                "error": {"code": -32602, "message": "params must be an object"}}

    try:
        if method == "initialize":
            client_protocol = params.get("protocolVersion")
            client_info = params.get("clientInfo")
            if (not isinstance(client_protocol, str) or not client_protocol
                    or not isinstance(params.get("capabilities"), dict)
                    or not isinstance(client_info, dict)
                    or not isinstance(client_info.get("name"), str)
                    or not isinstance(client_info.get("version"), str)):
                return _rpc_error(rpc_id, -32602, "Invalid initialize parameters")
            result = {
                "protocolVersion": (client_protocol if client_protocol in SUPPORTED_PROTOCOL_VERSIONS
                                    else SUPPORTED_PROTOCOL_VERSIONS[-1]),
                "serverInfo": {
                    "name": settings.APP_NAME,
                    "version": getattr(settings, "APP_VERSION", "0.1.0")
                },
                "capabilities": {
                    "tools": {}
                }
            }
            return {"jsonrpc": "2.0", "id": rpc_id, "result": result}

        if method == "ping":
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

        if method in ("tools/list", "list_tools"):
            # 优先使用 params 中的值，其次使用 headers
            orgid, appid = rpc_scope(request, params)
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
                    tool["outputSchema"], _ = output_contract(s["output_schema"])
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
            call_orgid, call_appid = rpc_scope(request, params)
            
            try:
                errorMessage, result, meta = await tenant_manager.execute_tool(tenant=tenant, name = name, orgid=call_orgid, appid=call_appid, **arguments)
                
                # 获取request_id并添加到meta中
                meta["x-request-id"] = request_id_context.get("")
                
                if errorMessage:
                    return _tool_error(rpc_id, errorMessage, meta)
            except HTTPException:
                raise
            except Exception as e:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32000, "message": str(e)}}

            # Resolve the same schema advertised by tools/list for the executed tool.
            schemas = tenant_manager.list_functions(
                tenant=tenant, name=name, orgid=meta.get("orgid"), appid=meta.get("appid"), _operation='call')
            schema = schemas[0].get("output_schema") if schemas else None
            try:
                structured = structured_output(result, schema)
            except ToolExecutionError as exc:
                log.warning("Tool %s output rejected: %s", name, exc.details["type"])
                return _tool_error(rpc_id, exc, meta)

            # Keep the text copy consistent with the structured result, including wrappers.
            text_value = structured if structured is not None else result
            if isinstance(text_value, str):
                text_payload = text_value
            else:
                try:
                    text_payload = json.dumps(text_value, ensure_ascii=False)
                except Exception:
                    text_payload = str(text_value)

            # Add extra information to the response
            response_content = {
                "content": [
                    {"type": "text", "text": text_payload}
                ]
            }
            # 对象结果同时返回结构化数据，供声明了 outputSchema 的客户端校验。
            if structured is not None:
                response_content["structuredContent"] = structured
            if meta:
                response_content["_meta"] = meta

            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": response_content
            }

        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Method not found"}}

    except HTTPException:
        raise
    except Exception as e:
        # 未预期的服务器错误
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": str(e)}}

import os
import json
import logging
import requests
from typing import Dict, Any, List, Tuple

from app.mcp.registry import registry
from app.config import settings

log = logging.getLogger(__name__)

def _make_function_name(method: str, path: str) -> str:
    clean_path = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    return f"{method.lower()}_{clean_path or 'root'}"

def _collect_parameters(op: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    返回 (parameters_list, request_body_schema)
    """
    parameters = op.get("parameters", []) or []
    rb = op.get("requestBody", {}) or {}
    body_schema = rb.get("content", {}).get("application/json", {}).get("schema", {}) or {}
    return parameters, body_schema

def _build_llm_parameters_schema(parameters: List[Dict[str, Any]], body_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    组合 path/query/cookie/header 参数 + JSON body 的 properties
    → 生成 OpenAI/Function Calling 兼容的 JSON Schema: {type:"object",properties,required}
    """
    props: Dict[str, Any] = {}
    req: List[str] = []

    # URL/Query 参数
    for p in parameters:
        name = p.get("name")
        schema = p.get("schema", {}) or {}
        if not name:
            continue
        props[name] = {k: v for k, v in schema.items() if k in ("type", "enum", "format", "items")}
        if p.get("description"):
            props[name]["description"] = p["description"]
        if p.get("required"):
            req.append(name)

    # JSON Body
    if body_schema:
        t = body_schema.get("type")
        if t == "object":
            bprops = body_schema.get("properties", {}) or {}
            breq = body_schema.get("required", []) or []
            for k, v in bprops.items():
                if k not in props:
                    props[k] = {kk: vv for kk, vv in v.items() if kk in ("type", "enum", "format", "items")}
                    if v.get("description"):
                        props[k]["description"] = v["description"]
            for k in breq:
                if k not in req:
                    req.append(k)
        else:
            # 如果 body 是非 object（如 array/string），统一封装成一个 body 字段
            props["body"] = {k: v for k, v in body_schema.items() if k in ("type", "enum", "format", "items")}
            req.append("body")

    return {"type": "object", "properties": props, "required": req}

def _choose_server(openapi: Dict[str, Any]) -> str:
    servers = openapi.get("servers") or [{"url": ""}]
    base_url = servers[0].get("url", "")
    return base_url.rstrip("/")

def _build_headers(openapi: Dict[str, Any], orgid: str, appid: str) -> Dict[str, str]:
    """
    简化版：支持 http bearer；可扩展 apiKey/oauth2 等。默认从环境变量拿 token。
    若要按 org/app 细分 token，可接入你的 secrets 表进行查找。
    """
    components = (openapi.get("components") or {}).get("securitySchemes") or {}
    security = openapi.get("security") or []  # 全局生效
    headers: Dict[str, str] = {}

    token = os.environ.get("API_TOKEN") or settings.API_TOKEN
    if "bearerAuth" in components and token:
        headers["Authorization"] = f"Bearer {token}"
    # 你也可以在此扩展 apiKey in header/query 等
    return headers

def _make_rest_callable(method: str, url_template: str, headers: Dict[str, str], parameters: List[Dict[str, Any]], body_schema: Dict[str, Any]):
    """
    生成实际的可调用函数：将 kwargs 映射到 path / query / body
    """
    def func(**kwargs):
        # path 替换
        url = url_template
        query: Dict[str, Any] = {}
        for p in parameters:
            name = p.get("name")
            where = p.get("in")
            if where == "path":
                url = url.replace(f"{{{name}}}", str(kwargs.get(name, "")))
            elif where == "query":
                if name in kwargs:
                    query[name] = kwargs[name]
            # header/cookie 可按需扩展到 requests 参数，这里先由 _build_headers 统一处理公共 header

        # body
        body = None
        if body_schema:
            if body_schema.get("type") == "object":
                keys = body_schema.get("properties", {}).keys()
                body = {k: kwargs[k] for k in keys if k in kwargs}
            else:
                # 非 object 的 body，用专用字段接收
                if "body" in kwargs:
                    body = kwargs["body"]

        resp = requests.request(method.upper(), url, headers=headers, params=query, json=body, timeout=30)
        resp.raise_for_status()
        # 自动判定 json / text
        ctype = resp.headers.get("Content-Type", "")
        if "application/json" in ctype:
            return resp.json()
        return resp.text
    return func

def register_from_openapi(orgid: str, appid: str, openapi_data: Dict[str, Any]) -> List[str]:
    """
    从 OpenAPI 文档批量注册 functions。返回已注册的 function 名称列表。
    """
    base_url = _choose_server(openapi_data)
    paths = openapi_data.get("paths") or {}
    headers = _build_headers(openapi_data, orgid, appid)

    registered: List[str] = []

    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete", "head", "options"):
                continue

            name = op.get("operationId") or _make_function_name(method, path)
            parameters, body_schema = _collect_parameters(op)

            # 生成可调用
            call = _make_rest_callable(method, f"{base_url}{path}", headers, parameters, body_schema)

            # 生成 LLM function schema
            schema = {
                "name": name,
                "description": op.get("summary") or op.get("description") or "",
                "parameters": _build_llm_parameters_schema(parameters, body_schema)
            }

            registry.register_function(name, call, schema, orgid, appid)
            registered.append(name)
            log.info(f"Registered function: {name} ({method.upper()} {path}) for org={orgid} app={appid}")

    return registered

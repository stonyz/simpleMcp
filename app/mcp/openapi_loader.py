import os
import json
import logging
import copy
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import urljoin

from app.mcp.registry import registry
from app.config import settings
from app.mcp.rest.auth_handler import AuthHandler
from app.mcp.rest.executor import execute_rest_call

log = logging.getLogger(__name__)

def _resolve_ref(ref: str, openapi_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    解析 OpenAPI $ref 引用
    支持 #/components/schemas/ModelName 和 #/components/parameters/ParamName 等格式
    """
    if not ref.startswith("#/"):
        return None
    
    try:
        # 移除开头的 #/ 并分割路径
        path_parts = ref[2:].split("/")
        current = openapi_data
        
        for part in path_parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        
        return current
    except Exception as e:
        log.warning(f"Failed to resolve ref {ref}: {e}")
        return None

def _resolve_schema(schema: Dict[str, Any], openapi_data: Dict[str, Any], visited_refs: Optional[set] = None) -> Dict[str, Any]:
    """
    递归解析 schema 中的所有 $ref，支持嵌套引用
    使用 visited_refs 防止循环引用
    """
    if not isinstance(schema, dict):
        return schema
    
    # 初始化访问过的引用集合，防止循环引用
    if visited_refs is None:
        visited_refs = set()
    
    # 处理 $ref
    if "$ref" in schema:
        ref_path = schema["$ref"]
        
        # 检查是否已经访问过这个引用，防止循环引用
        if ref_path in visited_refs:
            log.warning(f"Circular reference detected: {ref_path}")
            return schema
        
        visited_refs.add(ref_path)
        
        ref_schema = _resolve_ref(ref_path, openapi_data)
        if ref_schema:
            # 递归解析引用的 schema
            resolved = _resolve_schema(ref_schema, openapi_data, visited_refs)
            
            # 创建新的 schema 对象，合并原始属性
            merged_schema = copy.deepcopy(resolved)
            for k, v in schema.items():
                if k != "$ref" and k not in merged_schema:
                    merged_schema[k] = v
            
            visited_refs.remove(ref_path)
            return merged_schema
        else:
            visited_refs.remove(ref_path)
            # 如果无法解析，返回原始 schema
            return schema
    
    # 创建 schema 的深拷贝，避免修改原对象
    resolved_schema = copy.deepcopy(schema)
    
    # 递归处理 properties
    if "properties" in resolved_schema:
        resolved_props = {}
        for prop_name, prop_schema in resolved_schema["properties"].items():
            resolved_props[prop_name] = _resolve_schema(prop_schema, openapi_data, visited_refs)
        resolved_schema["properties"] = resolved_props
    
    # 递归处理 items（数组类型）
    if "items" in resolved_schema:
        resolved_schema["items"] = _resolve_schema(resolved_schema["items"], openapi_data, visited_refs)
    
    # 递归处理 allOf, anyOf, oneOf
    for key in ["allOf", "anyOf", "oneOf"]:
        if key in resolved_schema:
            resolved_schema[key] = [
                _resolve_schema(item, openapi_data, visited_refs) 
                for item in resolved_schema[key]
            ]
    
    # 递归处理 additionalProperties
    if "additionalProperties" in resolved_schema:
        resolved_schema["additionalProperties"] = _resolve_schema(
            resolved_schema["additionalProperties"], openapi_data, visited_refs
        )
    
    return resolved_schema

def _make_function_name(method: str, path: str) -> str:
    clean_path = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    return f"{method.lower()}_{clean_path or 'root'}"

def _collect_parameters(op: Dict[str, Any], openapi_data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    返回 (parameters_list, request_body_schema)，解析所有 $ref
    """
    parameters = op.get("parameters", []) or []
    rb = op.get("requestBody", {}) or {}
    body_schema = rb.get("content", {}).get("application/json", {}).get("schema", {}) or {}
    
    # 解析参数的 $ref
    resolved_parameters = []
    for param in parameters:
        if "$ref" in param:
            resolved_param = _resolve_ref(param["$ref"], openapi_data)
            if resolved_param:
                # 合并原始参数的其他属性
                for k, v in param.items():
                    if k != "$ref" and k not in resolved_param:
                        resolved_param[k] = v
                resolved_parameters.append(resolved_param)
            else:
                resolved_parameters.append(param)
        else:
            resolved_parameters.append(param)
    
    # 解析 body schema 的 $ref
    resolved_body_schema = _resolve_schema(body_schema, openapi_data)
    
    return resolved_parameters, resolved_body_schema

def _extract_response_schema(op: Dict[str, Any], openapi_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    从 OpenAPI operation 提取响应 schema，解析所有 $ref
    """
    responses = op.get("responses", {}) or {}
    
    # 优先使用 200 响应，其次 201, 最后第一个可用响应
    for status in ["200", "201", "default"]:
        if status in responses:
            resp = responses[status]
            content = resp.get("content", {}) or {}
            
            # 优先 JSON 响应
            if "application/json" in content:
                schema = content["application/json"].get("schema")
                if schema:
                    return _resolve_schema(schema, openapi_data)
            
            # 其次 text 响应
            elif "text/plain" in content:
                return {"type": "string"}
            
            # 其他类型
            elif content:
                # 取第一个可用的 content type
                first_content = next(iter(content.values()))
                schema = first_content.get("schema")
                if schema:
                    return _resolve_schema(schema, openapi_data)
    
    return None

def _build_llm_parameters_schema(parameters: List[Dict[str, Any]], body_schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    组合 path/query/cookie/header 参数 + JSON body 的 properties
    → 生成 OpenAI/Function Calling 兼容的 JSON Schema: {type:"object",properties,required}
    注意：此函数接收的 schema 应该已经通过 _resolve_schema 解析过 $ref
    """
    props: Dict[str, Any] = {}
    req: List[str] = []

    # URL/Query 参数
    for p in parameters:
        name = p.get("name")
        schema = p.get("schema", {}) or {}
        if not name:
            continue
        
        # 构建参数 schema，保留关键属性
        param_schema = {}
        for k, v in schema.items():
            if k in ("type", "enum", "format", "items", "minItems", "maxItems", "minLength", "maxLength", "pattern"):
                param_schema[k] = v
        
        # 处理数组类型的 items
        if "items" in param_schema and isinstance(param_schema["items"], dict):
            items_schema = {}
            for k, v in param_schema["items"].items():
                if k in ("type", "enum", "format", "pattern"):
                    items_schema[k] = v
            if items_schema:
                param_schema["items"] = items_schema
        
        props[name] = param_schema
        
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
                    # 构建属性 schema，保留关键属性
                    prop_schema = {}
                    for prop_k, prop_v in v.items():
                        if prop_k in ("type", "enum", "format", "items", "minItems", "maxItems", "minLength", "maxLength", "pattern"):
                            prop_schema[prop_k] = prop_v
                    
                    # 处理数组类型的 items
                    if "items" in prop_schema and isinstance(prop_schema["items"], dict):
                        items_schema = {}
                        for items_k, items_v in prop_schema["items"].items():
                            if items_k in ("type", "enum", "format", "pattern"):
                                items_schema[items_k] = v
                        if items_schema:
                            prop_schema["items"] = items_schema
                    
                    props[k] = prop_schema
                    
                    if v.get("description"):
                        props[k]["description"] = v["description"]
            for k in breq:
                if k not in req:
                    req.append(k)
        else:
            # 如果 body 是非 object（如 array/string），统一封装成一个 body 字段
            body_prop = {}
            for k, v in body_schema.items():
                if k in ("type", "enum", "format", "items", "minItems", "maxItems", "minLength", "maxLength", "pattern"):
                    body_prop[k] = v
            
            # 处理数组类型的 items
            if "items" in body_prop and isinstance(body_prop["items"], dict):
                items_schema = {}
                for items_k, items_v in body_prop["items"].items():
                    if items_k in ("type", "enum", "format", "pattern"):
                        items_schema[items_k] = items_v
                if items_schema:
                    body_prop["items"] = items_schema
            
            props["body"] = body_prop
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
        # Create a copy of headers to avoid modifying the original
        final_headers = headers.copy()
        
        # Check if auth information is provided in arguments
        # For basic auth: {"auth": {"username": "admin", "password": "secret"}}
        if "auth" in kwargs:
            auth_info = kwargs["auth"]
            final_headers = AuthHandler.process_auth_headers(final_headers, auth_info)
            # Remove auth from kwargs so it's not passed as a parameter
            del kwargs["auth"]
        
        # path 替换
        url = url_template
        query: Dict[str, Any] = {}
        for p in parameters:
            name = p.get("name")
            where = p.get("in")
            if name and where == "path":
                url = url.replace(f"{{{name}}}", str(kwargs.get(name, "")))
            elif name and where == "query":
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

        # Execute the REST call
        return execute_rest_call(method, url, final_headers, query, body)
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
            parameters, body_schema = _collect_parameters(op, openapi_data)
            response_schema = _extract_response_schema(op, openapi_data)

            # 生成可调用
            call = _make_rest_callable(method, f"{base_url}{path}", headers, parameters, body_schema)

            # 生成 LLM function schema
            schema = {
                "name": name,
                "description": op.get("summary") or op.get("description") or "",
                "parameters": _build_llm_parameters_schema(parameters, body_schema),
                "output_schema": response_schema
            }

            registry.register_function(name, call, schema, orgid, appid)
            registered.append(name)
            log.info(f"Registered function: {name} ({method.upper()} {path}) for org={orgid} app={appid}")

    return registered

import logging
import copy
import os
from typing import Dict, Any, List, Tuple, Optional
from app.config import settings

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
    
    # 解析参数的 $ref，并且对参数的 schema 也进行完整解析
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
    
    # 对每个参数的 schema 进行完整解析，确保所有嵌套的 $ref 都被解析
    for param in resolved_parameters:
        if "schema" in param:
            param["schema"] = _resolve_schema(param["schema"], openapi_data)
    
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


def _build_llm_parameters_schema(parameters: List[Dict[str, Any]], body_schema: Dict[str, Any], security_schemes: List[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        
        # 直接使用完整的 schema，类似于 response 处理方式
        param_schema = copy.deepcopy(schema)
        props[name] = param_schema
        
        if p.get("description") and "description" not in props[name]:
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
                    props[k] = copy.deepcopy(v)
            for k in breq:
                if k not in req:
                    req.append(k)
        else:
            # 如果 body 是非 object（如 array/string），统一封装成一个 body 字段
            props["body"] = copy.deepcopy(body_schema)
            req.append("body")
            
    # 添加安全认证参数
    if security_schemes:
        # 添加一个通用的 auth 参数来支持不同的认证方式
        props["auth"] = {
            "type": "object",
            "description": "Authentication information for the request",
            "properties": {},
            "required": []
        }
        req.append("auth")

        # 根据不同的安全方案类型，添加相应的属性
        for scheme in security_schemes:
            scheme_type = scheme.get("type")
            if scheme_type == "http":
                scheme_name = scheme.get("scheme")
                if scheme_name == "basic":
                    # Basic Auth
                    props["auth"]["properties"]["username"] = {
                        "type": "string",
                        "description": "Username for basic authentication"
                    }
                    props["auth"]["properties"]["password"] = {
                        "type": "string",
                        "description": "Password for basic authentication"
                    }
                    props["auth"]["required"].extend(["username", "password"])
                elif scheme_name == "bearer":
                    # Bearer Token
                    props["auth"]["properties"]["access_token"] = {
                        "type": "string",
                        "description": "Bearer token for authentication"
                    }
                    props["auth"]["required"].append("access_token")
            elif scheme_type == "oauth2":
                # OAuth2 Client Credentials
                props["auth"]["properties"]["client_id"] = {
                    "type": "string",
                    "description": "Client ID for OAuth2 authentication"
                }
                props["auth"]["properties"]["client_secret"] = {
                    "type": "string",
                    "description": "Client secret for OAuth2 authentication"
                }
                props["auth"]["properties"]["token_url"] = {
                    "type": "string",
                    "description": "Token URL for OAuth2 authentication"
                }
                props["auth"]["properties"]["scopes"] = {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Scopes for OAuth2 authentication"
                }
                props["auth"]["required"].extend(["client_id", "client_secret"])

    return {"type": "object", "properties": props, "required": req}


def _choose_server(openapi: Dict[str, Any]) -> str:
    servers = openapi.get("servers") or [{"url": ""}]
    base_url = servers[0].get("url", "")
    return base_url.rstrip("/")


def _extract_security_schemes(openapi: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    提取 OpenAPI 规范中的安全方案信息
    """
    components = (openapi.get("components") or {}).get("securitySchemes") or {}
    security_schemes = []
    
    for scheme_name, scheme_def in components.items():
        scheme_info = {
            "name": scheme_name,
            "type": scheme_def.get("type"),
            "scheme": scheme_def.get("scheme"),
            "bearerFormat": scheme_def.get("bearerFormat"),
            "flows": scheme_def.get("flows"),
            "description": scheme_def.get("description", "")
        }
        security_schemes.append(scheme_info)
    
    return security_schemes


def _build_headers(openapi: Dict[str, Any], orgid: str, appid: str) -> Dict[str, str]:
    """
    简化版：支持 http bearer；可扩展 apiKey/oauth2 等。默认从环境变量拿 token。
    若要按 org/app 细分 token，可接入你的 secrets 表进行查找。
    """
    components = (openapi.get("components") or {}).get("securitySchemes") or {}
    security = openapi.get("security") or []  # 全局生效
    headers: Dict[str, Any] = {}

    token = os.environ.get("API_TOKEN") or settings.API_TOKEN
    if "bearerAuth" in components and token:
        headers["Authorization"] = f"Bearer {token}"
    # 你也可以在此扩展 apiKey in header/query 等
    return headers



"""
ToolRegistry handles the registration and loading of tools from various sources.
This separates the registration/loading logic from the execution logic.
"""

def parse_tools_from_openapi(orgid: str, appid: str, openapi_data: Dict[str, Any], fileId: str = None, fileName: str = None) -> List[Dict[str, Any]]:
    """
    从 OpenAPI 文档解析工具信息。返回工具注册所需的数据列表。
    每个元素包含工具元数据和 schema 信息。
    """
    base_url = _choose_server(openapi_data)
    paths = openapi_data.get("paths") or {}
    headers = _build_headers(openapi_data, orgid, appid)

    tools_data: List[Dict[str, Any]] = []

    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() not in ("get", "post", "put", "patch", "delete", "head", "options"):
                continue

            name = op.get("operationId") or _make_function_name(method, path)
            parameters, request_body_schema = _collect_parameters(op, openapi_data)
            response_schema = _extract_response_schema(op, openapi_data)
            security_schemes = _extract_security_schemes(openapi_data)
            
            # 生成工具元数据而不是可执行函数
            tool_metadata = {
                "type": "rest_api",
                "method": method,
                "url_template": f"{base_url}{path}",
                "headers": headers,
                "parameters": parameters,
                "body_schema": request_body_schema,
                "security_schemes": security_schemes,
                "orgid": orgid,
                "appid": appid,
                "tool_name": name,
                "fileId": fileId,  # 添加 fileId 到元数据
                "fileName": fileName  # 添加 fileName 到元数据
            }

            # 生成 LLM tool schema
            base_description = op.get("summary") or op.get("description") or ""
            # 将安全方案信息整合到描述中
            if security_schemes:
                security_types = [scheme.get("type") for scheme in security_schemes if scheme.get("type")]
                if security_types:
                    security_info = ", ".join(security_types)
                    base_description = f"{base_description} (Supports: {security_info})".strip()
            
            schema = {
                "name": name,
                "description": base_description,
                "input_schema": _build_llm_parameters_schema(parameters, request_body_schema, security_schemes),
                "output_schema": response_schema
            }

            tools_data.append({
                "name": name,
                "metadata": tool_metadata,
                "schema": schema,
                "orgid": orgid,
                "appid": appid
            })
            log.info(f"Parsed tool: {name} ({method.upper()} {path}) for org={orgid} app={appid}")

    return tools_data

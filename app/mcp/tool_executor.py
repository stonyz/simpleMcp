import logging
from typing import Dict, Any, Optional, List
from app.mcp.registry import registry
from app.mcp.rest.executor import execute_rest_call
from app.mcp.rest.auth_handler import AuthHandler

log = logging.getLogger(__name__)


def _make_rest_callable(method: str, url_template: str, headers: Dict[str, str], parameters: List[Dict[str, Any]], body_schema: Dict[str, Any]):
    """
    生成实际的可调用函数：将 kwargs 映射到 path / query / body
    添加了参数验证功能，确保必需参数存在且符合 OpenAPI 规范
    """
    def func(**kwargs):
        # Validate all parameters including auth according to OpenAPI specification
        _validate_parameters(kwargs, parameters, body_schema)
        
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


def _validate_parameters(kwargs: Dict[str, Any], parameters: List[Dict[str, Any]], body_schema: Dict[str, Any]):
    """
    验证参数是否符合 OpenAPI 规范
    检查必需参数是否存在以及参数值是否符合 schema 定义
    """
    # Validate all parameters including auth
    for param in parameters:
        name = param.get("name")
        where = param.get("in")
        required = param.get("required", False)
        schema = param.get("schema", {})
        
        # Check if required parameters are provided
        if required and name not in kwargs:
            raise ValueError(f"Missing required parameter: {name}")
        
        # Validate parameter value against schema if provided
        if name in kwargs and schema:
            _validate_value_against_schema(kwargs[name], schema, name)
    
    # Validate body parameters
    if body_schema:
        _validate_value_against_schema(kwargs, body_schema, "request body")


def _validate_value_against_schema(value: Any, schema: Dict[str, Any], param_name: str):
    """
    根据 OpenAPI schema 验证单个参数值
    支持递归验证嵌套对象和数组
    """
    if not schema:
        return
        
    # Get schema properties
    schema_type = schema.get("type")
    enum_values = schema.get("enum")
    pattern = schema.get("pattern")
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    
    # Handle nullable values
    if value is None:
        if schema.get("nullable", False):
            return
        # If not nullable, continue with validation which should fail for None values
    
    # Type validation
    if schema_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"Parameter {param_name} must be a string")
        
        # Pattern validation
        if pattern:
            import re
            if not re.match(pattern, value):
                raise ValueError(f"Parameter {param_name} does not match pattern: {pattern}")
                
    elif schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):  # bool is subclass of int in Python
            raise ValueError(f"Parameter {param_name} must be an integer")
            
        # Range validation
        if minimum is not None and value < minimum:
            raise ValueError(f"Parameter {param_name} must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"Parameter {param_name} must be <= {maximum}")
            
    elif schema_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"Parameter {param_name} must be a number")
            
        # Range validation
        if minimum is not None and value < minimum:
            raise ValueError(f"Parameter {param_name} must be >= {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"Parameter {param_name} must be <= {maximum}")
            
    elif schema_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError(f"Parameter {param_name} must be a boolean")
            
    elif schema_type == "array":
        if not isinstance(value, list):
            raise ValueError(f"Parameter {param_name} must be an array")
            
        # Validate array items if items schema is provided
        items_schema = schema.get("items", {})
        if items_schema:
            for i, item in enumerate(value):
                _validate_value_against_schema(item, items_schema, f"{param_name}[{i}]")
                
    elif schema_type == "object":
        if not isinstance(value, dict):
            raise ValueError(f"Parameter {param_name} must be an object")
            
        # Validate object properties
        properties = schema.get("properties", {})
        required_fields = schema.get("required", [])
        
        # Check required fields
        for field in required_fields:
            if field not in value:
                raise ValueError(f"Missing required field in {param_name}: {field}")
        
        # Validate each property against its schema
        for prop_name, prop_value in value.items():
            if prop_name in properties:
                prop_schema = properties[prop_name]
                _validate_value_against_schema(prop_value, prop_schema, f"{param_name}.{prop_name}")
    
    # Enum validation (applies to all types)
    if enum_values and value not in enum_values:
        raise ValueError(f"Parameter {param_name} must be one of {enum_values}")


class ToolExecutor:
    """
    ToolExecutor handles the actual execution of registered tools.
    This separates the execution logic from the registration/loading logic.
    """
    
    @staticmethod
    def execute_tool(name: str, orgid: Optional[str] = None, appid: Optional[str] = None, **kwargs) -> Any:
        """
        Execute a tool by name with the given parameters.
        This method retrieves the tool metadata from the registry and creates an executable function.
        """
        # First, get the tool metadata from the registry
        tool_metadata = registry.get_tool_metadata(name)
        
        if not tool_metadata:
            raise ValueError(f"Tool '{name}' not found")
        
        # Perform orgid/appid permission check (only when these parameters are provided)
        with registry._lock:
            item = registry._registry.get(name)
        
        if item:
            # 进行 orgid/appid 权限检查（只有当提供了这些参数时才检查）
            if orgid and item["orgid"] != orgid:
                raise ValueError(f"Tool '{name}' not accessible for orgid '{orgid}'. Tool belongs to orgid '{item['orgid']}'")
            if appid and item["appid"] != appid:
                raise ValueError(f"Tool '{name}' not accessible for appid '{appid}'. Tool belongs to appid '{item['appid']}'")
            
        # Based on the tool type, create and execute the appropriate function
        if tool_metadata["type"] == "rest_api":
            # Create the executable function
            executable_func = _make_rest_callable(
                tool_metadata["method"],
                tool_metadata["url_template"],
                tool_metadata["headers"],
                tool_metadata["parameters"],
                tool_metadata["body_schema"]
            )
            # Execute the function with the provided arguments
            return executable_func(**kwargs)
        else:
            raise ValueError(f"Unsupported tool type: {tool_metadata['type']}")


# Global instance
tool_executor = ToolExecutor()
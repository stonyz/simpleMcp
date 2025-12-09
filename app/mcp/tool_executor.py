import logging
from typing import Dict, Any, Optional, List
from app.mcp.registry import registry
from app.mcp.rest.executor import execute_rest_call
from app.mcp.rest.auth_handler import AuthHandler

log = logging.getLogger(__name__)


def _make_rest_callable(method: str, url_template: str, headers: Dict[str, str], parameters: List[Dict[str, Any]], body_schema: Dict[str, Any], security_schemes: List[Dict[str, Any]]):
    """
    生成实际的可调用函数：将 kwargs 映射到 path / query / body
    添加了参数验证功能，确保必需参数存在且符合 OpenAPI 规范
    """
    def func(**kwargs):
        # Validate all parameters including auth according to OpenAPI specification
        _validate_parameters(kwargs, parameters, body_schema, security_schemes)
        
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


def _validate_parameters(kwargs: Dict[str, Any], parameters: List[Dict[str, Any]], body_schema: Dict[str, Any], security_schemes: List[Dict[str, Any]]):
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
    if security_schemes: 
        if 'auth' not in kwargs:
            raise ValueError("Missing required parameter: auth")
        
        # Validate auth against security schemes - at least one must pass
        auth_validation_passed = False
        validation_errors = []
        
        for i, security_scheme in enumerate(security_schemes):
            try:
                _validate_auth_against_security_scheme(kwargs["auth"], security_scheme)
                auth_validation_passed = True
                break  # If one scheme passes, we're good
            except ValueError as e:
                validation_errors.append(f"Security scheme {i+1} - {str(e)}")
                continue  # Try the next scheme
        
        if not auth_validation_passed:
            # Provide more precise error message when there's only one security scheme
            if len(security_schemes) == 1:
                raise ValueError(f"Auth validation failed: {validation_errors[0]}")
            else:
                error_details = '; '.join(validation_errors)
                raise ValueError(f"Auth validation failed against all security schemes: {error_details}")


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


def _validate_auth_against_security_scheme(auth_value: Any, security_scheme: Dict[str, Any]):
    """
    Specialized validation for auth parameter against a security scheme.
    Unlike general parameter validation, this handles the specific requirements
    of authentication where at least one security scheme must be satisfied.
    """
    if not isinstance(auth_value, dict):
        raise ValueError("Auth parameter must be a dictionary/object")
    
    # Get the security scheme type
    scheme_type = security_scheme.get("type")
    
    if scheme_type == "oauth2":
        # For OAuth2, we expect client credentials or access_token
        flows = security_scheme.get("flows", {})
        client_credentials_flow = flows.get("clientCredentials", {})
        
        # Check if we have either direct access_token or client credentials
        if "access_token" in auth_value:
            # Direct access token provided
            if not isinstance(auth_value["access_token"], str):
                raise ValueError("access_token must be a string")
        elif "client_id" in auth_value and "client_secret" in auth_value:
            # Client credentials provided
            if not isinstance(auth_value["client_id"], str):
                raise ValueError("client_id must be a string")
            if not isinstance(auth_value["client_secret"], str):
                raise ValueError("client_secret must be a string")
            
            # Scopes are optional but if provided, must be a list
            if "scopes" in auth_value and not isinstance(auth_value["scopes"], list):
                raise ValueError("scopes must be a list")
        else:
            raise ValueError("For OAuth2, either access_token or client_id/client_secret must be provided")
            
    elif scheme_type == "http":
        # For HTTP auth schemes like basic auth
        auth_scheme = security_scheme.get("scheme", "")
        
        if auth_scheme.lower() == "basic":
            # For basic auth, we expect username and password
            if "username" not in auth_value:
                raise ValueError("username is required for basic authentication")
            if "password" not in auth_value:
                raise ValueError("password is required for basic authentication")
            
            if not isinstance(auth_value["username"], str):
                raise ValueError("username must be a string")
            if not isinstance(auth_value["password"], str):
                raise ValueError("password must be a string")
        elif auth_scheme.lower() == "bearer":
            # For bearer token, we expect a token
            if "access_token" not in auth_value:
                raise ValueError("access_token is required for bearer authentication")
            
            if not isinstance(auth_value["access_token"], str):
                raise ValueError("access_token must be a string")
        else:
            raise ValueError(f"Unsupported HTTP authentication scheme: {auth_scheme}")
    else:
        raise ValueError(f"Unsupported security scheme type: {scheme_type}")


class ToolExecutor:
    """
    ToolExecutor handles the actual execution of registered tools.
    This separates the execution logic from the registration/loading logic.
    """
    
    @staticmethod
    def execute_tool(name: str, orgid: Optional[str] = None, appid: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Execute a tool by name with the given parameters.
        This method retrieves the tool metadata from the registry and creates an executable function.
        Returns a dictionary with the result and extra identity information.
        """
        # First, get the tool metadata from the registry
        tool_identity, tool_metadata = registry.get_tool_metadata(name, orgid, appid)
        
        if not tool_metadata:
            raise ValueError(f"Tool '{name}' not found")
        
        # Based on the tool type, create and execute the appropriate function
        if tool_metadata["type"] == "rest_api":
            # Create the executable function
            executable_func = _make_rest_callable(
                tool_metadata["method"],
                tool_metadata["url_template"],
                tool_metadata["headers"],
                tool_metadata["parameters"],
                tool_metadata["body_schema"],
                tool_metadata["security_schemes"]
            )
            # Execute the function with the provided arguments
            identity = dict(zip(["orgid", "appid", "name"], tool_identity))
            try:
                result = executable_func(**kwargs)
                return None, result, identity
            except Exception as e:
                return str(e), None, identity

            
            
        else:
            raise ValueError(f"Unsupported tool type: {tool_metadata['type']}")


# Global instance
tool_executor = ToolExecutor()
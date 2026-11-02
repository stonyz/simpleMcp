from typing import Dict, Any, List, Optional, Tuple
from app.mcp.errors import ToolExecutionError

from app.mcp.tool_executor import execute_tool
from app.mcp.tool_registry import parse_tools_from_openapi
from app.mcp.registry import MCPRegistry

class TenantManager:
    """
    A simple tenant manager that provides tenant-aware access to registry and tool execution.
    """
    
    def __init__(self):
        self.default_tenant = "default"
        # Dictionary to store tenant-specific registries
        self.tenant_registries: Dict[str, MCPRegistry] = {}
    
    def _get_tenant_name(self, tenant: Optional[str] = None) -> str:
        """Get tenant name, using default if none provided"""
        return tenant if tenant else self.default_tenant

    def get_tenant_registry(self, tenant: Optional[str] = None) -> MCPRegistry:
        """Get tenant-specific registry, using default if none provided"""
        tenant_name = self._get_tenant_name(tenant)
        # Return the appropriate tenant-specific registry
        if tenant_name not in self.tenant_registries:
            self.tenant_registries[tenant_name] = MCPRegistry()
        return self.tenant_registries[tenant_name]

    def list_all_tenants(self) -> List[str]:
        return list(self.tenant_registries.keys()) #FIX ME
    
    def register_all_tools(self):

        pass

    def register_tools_from_openapi(self, tenant: str, orgid: str, appid: str, openapi_data: Dict[str, Any], fileId: str = None, fileName: str = None, auth: Optional[str] = None) -> List[str]:
        # Get tools data from parsing the OpenAPI spec
        tools_data = parse_tools_from_openapi(orgid, appid, openapi_data, fileId, fileName)
        
        # Register each tool with the tenant registry
        tenant_registry = self.get_tenant_registry(tenant)
        for tool_data in tools_data:
            if auth is not None:
                tool_data["metadata"]["auth"] = auth

        if fileId is not None:
            tenant_registry.replace_file_functions(orgid, appid, fileId, tools_data)
            return [tool_data["name"] for tool_data in tools_data]

        # Internal callers without document identity retain additive registration.
        registered_names = []
        for tool_data in tools_data:
            tenant_registry.register_function(
                tool_data["name"],
                tool_data["metadata"],
                tool_data["schema"],
                tool_data["orgid"],
                tool_data["appid"]
            )
            registered_names.append(tool_data["name"])
        
        return registered_names

    def unregister_tools_by_origin(self, tenant: str, orgid: str, appid: str, names: List[str]):  
        tenant_registry = self.get_tenant_registry(tenant)
        tenant_registry.unregister_by_origin(orgid, appid, names)


    def list_functions(self, tenant: Optional[str] = None, orgid: Optional[str] = None, 
                      appid: Optional[str] = None, name: Optional[str] = None) -> List[dict]:
        """
        List functions from tenant-specific registry.
        """
        tenant_registry = self.get_tenant_registry(tenant)
        return tenant_registry.list_functions(orgid=orgid, appid=appid, name=name)
    
    async def execute_tool(self, tenant: str, name: str, orgid: Optional[str] = None,
                    appid: Optional[str] = None, **kwargs) -> Tuple[Optional[ToolExecutionError], Any, Dict[str, Any]]:
        """
        Execute a tenant's tool, preserving execution errors and identity metadata.
        """
        tenant_registry = self.get_tenant_registry(tenant)
        tool_metadata = tenant_registry.get_tool_metadata(name, orgid=orgid, appid=appid)
        if not tool_metadata:
            raise ValueError(f"Tool '{name}' not found")

        # 从工具元数据中获取身份信息并添加到 meta
        identity = {
            field: tool_metadata[field] 
            for field in ["orgid", "appid", "fileId", "fileName", "tool_name"] 
            if field in tool_metadata and tool_metadata[field] is not None
        }
        
        error, response = await execute_tool(tool_metadata, **kwargs)
        return error, response, identity

# Global instance
tenant_manager = TenantManager()

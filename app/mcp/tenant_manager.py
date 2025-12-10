from typing import Dict, Any, List, Optional

from app.mcp.tool_executor import execute_tool
from app.mcp.tool_registry import register_tools_from_openapi, unregister_tools_by_origin
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

    def register_tools_from_openapi(self, tenant: str, orgid: str, appid: str, openapi_data: Dict[str, Any], fileId: str = None, fileName: str = None) -> List[str]:
        tenant_registry = self.get_tenant_registry(tenant)
        return register_tools_from_openapi(tenant_registry, orgid, appid, openapi_data, fileId, fileName)

    def unregister_tools_by_origin(self, tenant: str, orgid: str, appid: str, names: List[str]):  
        tenant_registry = self.get_tenant_registry(tenant)
        unregister_tools_by_origin(tenant_registry, orgid, appid, names)  

    def register_function(self, name: str, metadata: Dict[str, Any], schema: dict, 
                         orgid: str, appid: str, tenant: Optional[str] = None):
        """
        Register a function with tenant-specific registry.
        """
        tenant_registry = self.get_tenant_registry(tenant)
        return tenant_registry.register_function(name, metadata, schema, orgid, appid)
    
    def list_functions(self, tenant: Optional[str] = None, orgid: Optional[str] = None, 
                      appid: Optional[str] = None, name: Optional[str] = None) -> List[dict]:
        """
        List functions from tenant-specific registry.
        """
        tenant_registry = self.get_tenant_registry(tenant)
        return tenant_registry.list_functions(orgid=orgid, appid=appid, name=name)
    
    def execute_tool(self, tenant: str, name: str, orgid: Optional[str] = None, 
                    appid: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """
        Execute a tool. Tenant parameter is accepted but not used in current implementation.
        """
        tenant_registry = self.get_tenant_registry(tenant)
        return execute_tool(tenant_registry, name, orgid=orgid, appid=appid, **kwargs)

# Global instance
tenant_manager = TenantManager()
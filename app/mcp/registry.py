from typing import Dict, Any, List, Optional
import threading


class MCPRegistry:
    """
    动态函数注册表。支持按 orgid/appid 过滤查询，并提供调用入口。
    现在存储的是工具元数据而不是可执行函数。
    使用复合键 (orgid, appid, name) 来支持多租户隔离。
    """
    def __init__(self):
        self._lock = threading.RLock()
        # key: (orgid, appid, tool_name) tuple, value: dict(metadata, schema)
        self._registry: Dict[tuple, Dict[str, Any]] = {}
        # Secondary index for name-based lookup with org/app filtering
        self._name_index: Dict[str, List[tuple]] = {}

    def register_function(self, name: str, metadata: Dict[str, Any], schema: dict, orgid: str, appid: str):
        with self._lock:
            key = (orgid, appid, name)
            self._registry[key] = {"func": metadata, "schema": schema}
            
            # Update name index
            if name not in self._name_index:
                self._name_index[name] = []
            if key not in self._name_index[name]:
                self._name_index[name].append(key)

    def _remove_entry_from_index(self, key: tuple, name: str):
        """
        Remove an entry from both registry and name index.
        """
        # Remove from registry
        self._registry.pop(key, None)
        
        # Update name index
        if name in self._name_index:
            if key in self._name_index[name]:
                self._name_index[name].remove(key)
            if not self._name_index[name]:
                del self._name_index[name]

    def unregister_function(self, name: str, orgid: Optional[str] = None, appid: Optional[str] = None):
        with self._lock:
            if orgid is not None and appid is not None:
                # Unregister specific org/app combination
                key = (orgid, appid, name)
                if key in self._registry:
                    self._remove_entry_from_index(key, name)
            else:
                # Unregister all instances of the tool name
                if name in self._name_index:
                    keys_to_remove = self._name_index[name][:]  # Copy to avoid modification during iteration
                    for key in keys_to_remove:
                        self._remove_entry_from_index(key, name)

    def unregister_by_origin(self, orgid: str, appid: str, names: List[str]):
        with self._lock:
            for name in names:
                key = (orgid, appid, name)
                if key in self._registry:
                    self._remove_entry_from_index(key, name)

    def _matches_filters(self, key: tuple, orgid: Optional[str], appid: Optional[str]) -> bool:
        """
        Check if a registry key matches the given orgid/appid filters.
        """
        key_orgid, key_appid, key_name = key
        if orgid and key_orgid != orgid:
            return False
        if appid and key_appid != appid:
            return False
        return True

    def list_functions(self, orgid: Optional[str] = None, appid: Optional[str] = None, name: Optional[str] = None) -> List[dict]:
        with self._lock:
            out = []
            
            # If a specific name is requested, use the name index
            if name:
                if name in self._name_index:
                    for key in self._name_index[name]:
                        # Apply org/app filters
                        if self._matches_filters(key, orgid, appid):
                            # Found matching tool
                            item = self._registry.get(key)
                            if item:
                                out.append(item["schema"])
            else:
                # No specific name requested, iterate through all tools
                for key, item in self._registry.items():
                    # Apply org/app filters
                    if self._matches_filters(key, orgid, appid):
                        out.append(item["schema"])
            return out

    def _find_matching_key(self, name: str, orgid: Optional[str] = None, appid: Optional[str] = None) -> Optional[tuple]:
        """
        Find a registry key that matches the given name and optional orgid/appid filters.
        """
        if orgid is not None and appid is not None:
            # Look for exact match
            key = (orgid, appid, name)
            if key in self._registry:
                return key
        else:
            # Look for any matching tool
            if name in self._name_index and self._name_index[name]:
                # Return the first matching tool
                return self._name_index[name][0]
        return None

    def get_tool_metadata(self, name: str, orgid: Optional[str] = None, appid: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get the metadata for a tool by name, with optional org/app filtering.
        If orgid and appid are provided, only returns the tool if it belongs to that org/app.
        If multiple tools exist with the same name, returns the one matching the org/app filter.
        """
        with self._lock:
            # Find the matching key
            key = self._find_matching_key(name, orgid, appid)
            
            if key:
                item = self._registry.get(key)
                if item:
                    return key, item["func"]
            
            return None, None


# 全局单例
registry = MCPRegistry()
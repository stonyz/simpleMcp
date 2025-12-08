from typing import Dict, Any, List, Optional
import threading


class MCPRegistry:
    """
    动态函数注册表。支持按 orgid/appid 过滤查询，并提供调用入口。
    现在存储的是工具元数据而不是可执行函数。
    """
    def __init__(self):
        self._lock = threading.RLock()
        # key: tool name（全局唯一），value: dict(metadata, schema, orgid, appid)
        self._registry: Dict[str, Dict[str, Any]] = {}

    def register_function(self, name: str, metadata: Dict[str, Any], schema: dict, orgid: str, appid: str):
        with self._lock:
            self._registry[name] = {"func": metadata, "schema": schema, "orgid": orgid, "appid": appid}

    def unregister_function(self, name: str):
        with self._lock:
            self._registry.pop(name, None)

    def unregister_by_origin(self, orgid: str, appid: str, names: List[str]):
        with self._lock:
            for n in names:
                d = self._registry.get(n)
                if d and d["orgid"] == orgid and d["appid"] == appid:
                    self._registry.pop(n, None)

    def list_functions(self, orgid: Optional[str] = None, appid: Optional[str] = None, name: Optional[str] = None) -> List[dict]:
        with self._lock:
            out = []
            for n, d in self._registry.items():
                if orgid and d["orgid"] != orgid:
                    continue
                if appid and d["appid"] != appid:
                    continue
                if name and n != name:
                    continue
                # 返回大模型可直接使用的 function schema
                out.append(d["schema"])
            return out

    def get_tool_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get the metadata for a tool by name.
        This is used by the executor to retrieve tool information.
        """
        with self._lock:
            item = self._registry.get(name)
            return item["func"] if item else None


# 全局单例
registry = MCPRegistry()
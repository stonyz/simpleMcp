from typing import Dict, Callable, Any, List, Optional
import threading

class MCPRegistry:
    """
    动态函数注册表。支持按 orgid/appid 过滤查询，并提供调用入口。
    """
    def __init__(self):
        self._lock = threading.RLock()
        # key: function name（全局唯一），value: dict(func, schema, orgid, appid)
        self._registry: Dict[str, Dict[str, Any]] = {}

    def register_function(self, name: str, func: Callable, schema: dict, orgid: str, appid: str):
        with self._lock:
            self._registry[name] = {"func": func, "schema": schema, "orgid": orgid, "appid": appid}

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

    def call_function(self, name: str, **kwargs):
        with self._lock:
            item = self._registry.get(name)
        if not item:
            raise ValueError(f"Function '{name}' not found")
        return item["func"](**kwargs)

# 全局单例
registry = MCPRegistry()

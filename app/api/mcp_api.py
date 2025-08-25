from fastapi import APIRouter, Body, HTTPException, Query
from typing import Dict, Any, Optional
from app.mcp.registry import registry

router = APIRouter()

@router.get("/mcp/list")
def mcp_list(
    orgid: Optional[str] = Query(None),
    appid: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
):
    """
    MCP 风格的 list：返回 function schemas
    （你也可以保持与 /functions 一致）
    """
    return registry.list_functions(orgid=orgid, appid=appid, name=name)

@router.post("/mcp/call")
def mcp_call(
    function_name: str = Body(..., embed=True),
    parameters: Dict[str, Any] = Body(default_factory=dict, embed=True)
):
    """
    MCP 风格的 call：执行实际的 REST 请求。
    Body 示例：
    {
      "function_name": "get_user",
      "parameters": {"user_id": "123"}
    }
    """
    try:
        result = registry.call_function(function_name, **parameters)
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

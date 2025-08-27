from fastapi import APIRouter, Query
from typing import Optional
from app.mcp.registry import registry

router = APIRouter()

@router.get("/")
async def list_functions(
    orgid: str = Query(...),
    appid: str = Query(...),
    name: Optional[str] = Query(None)
):
    """
    返回大模型可直接使用的 function schema：
    [{"name": "...", "description": "...", "parameters": {...}} ...]
    """
    return registry.list_functions(orgid=orgid, appid=appid, name=name)

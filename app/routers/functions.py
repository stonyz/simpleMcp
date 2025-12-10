from fastapi import APIRouter, Query
from typing import Optional
from app.mcp.tenant_manager import tenant_manager

router = APIRouter()

@router.get("/")
async def list_functions(
    tenant: str = Query(..., alias="tenant"),
    orgid: str = Query(...),
    appid: str = Query(...),
    name: Optional[str] = Query(None)
):
    """
    返回大模型可直接使用的 function schema：
    [{"name": "...", "description": "...", "parameters": {...}} ...]
    """
    return tenant_manager.list_functions(tenant=tenant, orgid=orgid, appid=appid, name=name)

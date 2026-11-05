from fastapi import APIRouter, Query, Depends
from app.access import authorize_request
from typing import Optional
from app.mcp.tenant_manager import tenant_manager

router = APIRouter(dependencies=[Depends(authorize_request)])

@router.get("/")
async def list_functions(
    tenant: str = Query(..., alias="tenant"),
    orgid: str = Query(...),
    appid: str = Query(...),
    name: Optional[str] = Query(None)
):
    """
    Return function schemas ready for use by language models:
    [{"name": "...", "description": "...", "parameters": {...}} ...]
    """
    return tenant_manager.list_functions(tenant=tenant, orgid=orgid, appid=appid, name=name)

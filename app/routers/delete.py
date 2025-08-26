from fastapi import APIRouter, Query, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
import json

from app.db import get_db, crud
from app.db.models import OpenAPIFile
from app.mcp.registry import registry

router = APIRouter()

@router.delete("/delete")
def delete_openapi(
    orgid: str = Query(...),
    appid: str = Query(...),
    title: str = Query(...),
    version: Optional[str] = Query(None),
):
    """
    按 orgid + appid + title（可选 version）删除：
    1) 反注册所有由该 OpenAPI 生成的 functions
    2) 从数据库删除对应 OpenAPI 记录
    """
    with next(get_db()) as db:
        obj = crud.get_one_openapi(db, orgid, appid, title, version)
        if not obj:
            raise HTTPException(status_code=404, detail="OpenAPI record not found")

        openapi_data = json.loads(obj.openapi_yaml)
        # 收集所有 function 名称
        names = []
        for path, methods in (openapi_data.get("paths") or {}).items():
            for method, op in (methods or {}).items():
                if method.lower() not in ("get", "post", "put", "patch", "delete", "head", "options"):
                    continue
                fname = op.get("operationId")
                if not fname:
                    # 回退规则
                    clean = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
                    fname = f"{method.lower()}_{clean or 'root'}"
                names.append(fname)

        # 从注册表卸载
        registry.unregister_by_origin(orgid, appid, names)

        # 从数据库删除
        count = crud.delete_openapi_file(db, orgid, appid, title, version)

    return {"deleted": count, "unregistered_functions": names}

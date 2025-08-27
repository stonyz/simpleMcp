from fastapi import APIRouter, UploadFile, Query, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
import yaml, json
from app.db import get_db
from app.db import crud
from app.mcp.openapi_loader import register_from_openapi
import logging

from app.mcp.registry import registry

router = APIRouter()
log = logging.getLogger(__name__)

@router.post("/register")
async def register_openapi(
    org: str = Form(...),
    app: str = Form(...),
    fileId: str = Form(...),
    fileName: str = Form(...),
    file: Optional[UploadFile] = None,
    yaml_content: Optional[str] = Form(None)
):

    if file:
        content_bytes = await file.read()
        openapi_data = parse_file_content(file.filename, content_bytes)
    elif yaml_content:
        openapi_data = parse_yaml_string(yaml_content)
    else:
        raise HTTPException(status_code=400, detail="No file or YAML string provided")

    # 基本校验
    if not isinstance(openapi_data, dict) or "paths" not in openapi_data:
        raise HTTPException(status_code=400, detail="OpenAPI content missing 'paths'")

    with next(get_db()) as db:  # 直接使用依赖函数提供的生成器
        obj, updated = crud.upsert_openapi_file(db, org, app, fileId, fileName, openapi_data)

    registered = register_from_openapi(org, app, openapi_data)
    return {
        "status": "success",
        "updated": updated,
        "orgid": org,
        "appid": app,
        "fileId": fileId,
        "fileName": fileName,
        "title": openapi_data.get("info", {}).get("title"),
        "version": openapi_data.get("info", {}).get("version"),
        "registered_functions": registered
    }

def parse_file_content(filename: str, content: bytes):
    """根据文件后缀解析内容"""
    try:
        if filename.endswith((".yaml", ".yml")):
            return yaml.safe_load(content)
        elif filename.endswith(".json"):
            return json.loads(content)
        else:
            # 默认尝试 YAML，再尝试 JSON
            try:
                return yaml.safe_load(content)
            except yaml.YAMLError:
                return json.loads(content)
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid file content: {e}")

def parse_yaml_string(yaml_str: str):
    try:
        return yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML string: {e}")


@router.delete("/delete")
def delete_openapi(
    orgid: str = Query(..., alias="org"),
    appid: str = Query(..., alias="app"),
    fileId: str = Query(...)
):
    """
    按 orgid + appid + title（可选 version）删除：
    1) 反注册所有由该 OpenAPI 生成的 functions
    2) 从数据库删除对应 OpenAPI 记录
    """
    with next(get_db()) as db:
        obj = crud.get_one_openapi(db, orgid, appid, fileId)
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
        count = crud.delete_openapi_file(db, orgid, appid, fileId)

    return {"deleted": count, "unregistered_functions": names}

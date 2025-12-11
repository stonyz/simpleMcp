from fastapi import APIRouter, UploadFile, Query, Form, Depends, HTTPException
from fastapi import Body
from sqlalchemy.orm import Session
from typing import Optional
import yaml, json
from app.db import get_db, get_db_context
from app.db import crud
from app.mcp.tenant_manager import tenant_manager
import logging

router = APIRouter()
log = logging.getLogger(__name__)

async def _register_openapi_logic(tenant: str, org: str, app: str, fileId: str, fileName: str, openapi_data: dict):
    """
    公共的 OpenAPI 注册逻辑
    """
    # 基本校验
    if not isinstance(openapi_data, dict) or "paths" not in openapi_data:
        raise HTTPException(status_code=400, detail="OpenAPI content missing 'paths'")

    # 使用现有的数据库操作方式
    with get_db_context() as db:
        obj, updated = crud.upsert_openapi_file(db, tenant, org, app, fileId, fileName, openapi_data)

    registered = tenant_manager.register_tools_from_openapi(tenant, org, app, openapi_data, fileId, fileName)
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

@router.post("/register-form")
async def register_openapi(
    tenant: str = Query(..., alias="tenant"),
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

    return await _register_openapi_logic(tenant, org, app, fileId, fileName, openapi_data)

@router.post("/register")
async def register_openapi_json(
    tenant: str = Query(..., alias="tenant"),
    request_data: dict = Body(...)
):
    """
    通过 JSON 注册 OpenAPI，功能与 /register 完全一样
    """
    # 从 JSON 中提取参数
    org = request_data.get("org")
    app = request_data.get("app")
    fileId = request_data.get("fileId")
    fileName = request_data.get("fileName")
    yaml_content = request_data.get("yaml_content")
    
    # 参数验证
    if not all([org, app, fileId, fileName]):
        raise HTTPException(status_code=400, detail="Missing required fields: org, app, fileId, fileName")
    
    if not yaml_content:
        raise HTTPException(status_code=400, detail="yaml_content is required")

    openapi_data = parse_yaml_string(yaml_content)
    return await _register_openapi_logic(tenant, org, app, fileId, fileName, openapi_data)

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
async def delete_openapi(
    tenant: str = Query(..., alias="tenant"),
    orgid: str = Query(..., alias="org"),
    appid: str = Query(..., alias="app"),
    fileId: str = Query(...)
):
    """
    按 orgid + appid + title（可选 version）删除：
    1) 反注册所有由该 OpenAPI 生成的 functions
    2) 从数据库删除对应 OpenAPI 记录
    """
    # 使用现有的数据库操作方式
    with get_db_context() as db:
        obj = crud.get_one_openapi(db, tenant, orgid, appid, fileId)
        if not obj:
            raise HTTPException(status_code=404, detail="OpenAPI record not found")

        openapi_data= yaml.safe_load(obj.openapi_yaml)
   
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
        tenant_manager.unregister_tools_by_origin(tenant, orgid, appid, names)

        # 从数据库删除
        count = crud.delete_openapi_file(db, tenant, orgid, appid, fileId)

    return {"deleted": count, "unregistered_functions": names}

from fastapi import APIRouter, UploadFile, Query, Form, Depends, HTTPException
from fastapi import Body
from sqlalchemy.orm import Session
from typing import Optional
from uuid import uuid4
import yaml, json
from app.db import get_db, get_db_context
from app.db import crud
from app.mcp.tenant_manager import tenant_manager
from app.mcp.tool_registry import parse_tools_from_openapi
from app import service_admin
import logging

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/")
def list_services(
    tenant: str = Query(..., min_length=1, max_length=63),
    org: Optional[str] = Query(None), app: Optional[str] = Query(None),
    q: Optional[str] = Query(None, max_length=256),
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
):
    with get_db_context() as db:
        return service_admin.list_documents(db, tenant_manager, tenant, org, app, q, page, page_size)


@router.get("/detail")
def service_detail(tenant: str = Query(..., min_length=1, max_length=63), org: str = Query(...),
                   app: str = Query(...), fileId: str = Query(...)):
    with get_db_context() as db:
        return service_admin.document_view(service_admin.find_document(db, tenant, org, app, fileId), tenant_manager, True)


@router.post("/preview")
def preview_service(body: service_admin.ServiceInput, tenant: str = Query(..., min_length=1, max_length=63)):
    with get_db_context() as db:
        preview, _ = service_admin.preview_document(db, tenant_manager, tenant, body)
        return preview


@router.post("/save")
async def save_service(body: service_admin.ServiceInput, tenant: str = Query(..., min_length=1, max_length=63)):
    with get_db_context() as db:
        preview, data = service_admin.preview_document(db, tenant_manager, tenant, body)
        if preview["conflicts"]:
            raise HTTPException(409, detail="工具名称与其他服务冲突，请调整 operationId 后重试")
    auth = service_admin.authorization_value(body)
    # Preserve stored auth in the live registry as well as in SQLite on update.
    if body.auth_action == "keep" and body.fileId:
        with get_db_context() as db:
            auth = service_admin.find_document(db, tenant, body.org, body.app, body.fileId).auth
    return await _register_openapi_logic(tenant, body.org, body.app, body.fileId, body.fileName, data, auth)

async def _register_openapi_logic(tenant: str, org: str, app: str, fileId: Optional[str], fileName: str, openapi_data: dict, auth: Optional[str] = None):
    """
    公共的 OpenAPI 注册逻辑
    """
    # 基本校验
    if not isinstance(openapi_data, dict) or "paths" not in openapi_data:
        raise HTTPException(status_code=400, detail="OpenAPI content missing 'paths'")

    fileId = fileId or uuid4().hex

    # Validate all operations before persisting or changing the live registry.
    try:
        parse_tools_from_openapi(org, app, openapi_data, fileId, fileName)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 使用现有的数据库操作方式
    with get_db_context() as db:
        obj, updated = crud.upsert_openapi_file(db, tenant, org, app, fileId, fileName, openapi_data, auth)

    registered = tenant_manager.register_tools_from_openapi(tenant, org, app, openapi_data, fileId, fileName, auth)
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
    fileId: Optional[str] = Form(None),
    fileName: str = Form(...),
    auth: Optional[str] = Form(None),
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

    return await _register_openapi_logic(tenant, org, app, fileId, fileName, openapi_data, auth)

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
    auth = request_data.get("auth")  # Extract auth from request data
    
    # 参数验证
    if not all([org, app, fileName]):
        raise HTTPException(status_code=400, detail="Missing required fields: org, app, fileName")
    
    if not yaml_content:
        raise HTTPException(status_code=400, detail="yaml_content is required")

    openapi_data = parse_yaml_string(yaml_content)
    return await _register_openapi_logic(tenant, org, app, fileId, fileName, openapi_data, auth)

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
    按 tenant + orgid + appid + fileId 删除：
    1) 立即从当前进程的内存注册表卸载仍归该文档所有的 functions
    2) 从数据库删除对应 OpenAPI 记录
    """
    # 使用现有的数据库操作方式
    with get_db_context() as db:
        obj = crud.get_one_openapi(db, tenant, orgid, appid, fileId)
        if not obj:
            raise HTTPException(status_code=404, detail="OpenAPI record not found")

        # Remove by actual document ownership, even if the stored YAML is broken.
        registry = tenant_manager.get_tenant_registry(tenant)
        names = registry.replace_file_functions(orgid, appid, fileId, [])

        # 从数据库删除
        count = crud.delete_openapi_file(db, tenant, orgid, appid, fileId)

    return {"deleted": count, "unregistered_functions": names}

from app.errors import ApiError
from fastapi import APIRouter, UploadFile, Query, Form, Depends
from fastapi import Body, Request
from app.access import authorize_request, check_identifier
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

router = APIRouter(dependencies=[Depends(authorize_request)])
log = logging.getLogger(__name__)


@router.get('/access')
def access_scope(request: Request, tenant: str = Query(...)):
    return {'tenant': tenant, 'org': None, 'app': None, 'role': 'manager'}


@router.get('/scopes')
def scope_directory(request: Request, tenant: str = Query(...)):
    with get_db_context() as db:
        return service_admin.scope_directory(db, tenant)


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
            raise ApiError(409, "document_tool_conflict")
    auth = service_admin.authorization_value(body)
    # Preserve stored auth in the live registry as well as in SQLite on update.
    if body.auth_action == "keep" and body.fileId:
        with get_db_context() as db:
            auth = service_admin.find_document(db, tenant, body.org, body.app, body.fileId).auth
    return await _register_openapi_logic(tenant, body.org, body.app, body.fileId, body.fileName, data, auth)

async def _register_openapi_logic(tenant: str, org: str, app: str, fileId: Optional[str], fileName: str, openapi_data: dict, auth: Optional[str] = None):
    """
    Shared OpenAPI registration logic.
    """
    for field, value, limit in [('tenant', tenant, 63), ('org', org, 64), ('app', app, 64)]:
        check_identifier(value, field, limit)
    # 基本校验
    if not isinstance(openapi_data, dict) or "paths" not in openapi_data:
        raise ApiError(400, "document_paths_required")

    fileId = fileId or uuid4().hex

    # Validate all operations before persisting or changing the live registry.
    try:
        service_admin.validate_document_timeouts(openapi_data)
        parse_tools_from_openapi(org, app, openapi_data, fileId, fileName)
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as exc:
        raise ApiError(400, "document_invalid") from exc

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
        raise ApiError(400, "document_content_required")

    return await _register_openapi_logic(tenant, org, app, fileId, fileName, openapi_data, auth)

@router.post("/register")
async def register_openapi_json(
    tenant: str = Query(..., alias="tenant"),
    request_data: dict = Body(...)
):
    """
    Register an OpenAPI document supplied as a JSON request body.
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
        raise ApiError(400, "document_fields_required")
    
    if not yaml_content:
        raise ApiError(400, "document_yaml_required")

    openapi_data = parse_yaml_string(yaml_content)
    return await _register_openapi_logic(tenant, org, app, fileId, fileName, openapi_data, auth)

def parse_file_content(filename: str, content: bytes):
    """Parse content using the file extension."""
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
    except (yaml.YAMLError, ValueError, TypeError, AttributeError, RecursionError) as e:
        raise ApiError(400, "document_file_invalid") from e

def parse_yaml_string(yaml_str: str):
    try:
        return yaml.safe_load(yaml_str)
    except (yaml.YAMLError, ValueError, TypeError, AttributeError, RecursionError) as e:
        raise ApiError(400, "document_yaml_invalid") from e


@router.delete("/delete")
async def delete_openapi(
    tenant: str = Query(..., alias="tenant"),
    orgid: str = Query(..., alias="org"),
    appid: str = Query(..., alias="app"),
    fileId: str = Query(...)
):
    """
    Delete a document by tenant, organization, application and file ID.
    Unregister its functions from the current process and remove its database record.
    """
    # 使用现有的数据库操作方式
    with get_db_context() as db:
        obj = crud.get_one_openapi(db, tenant, orgid, appid, fileId)
        if not obj:
            raise ApiError(404, "openapi_record_not_found")

        # Remove by actual document ownership, even if the stored YAML is broken.
        registry = tenant_manager.get_tenant_registry(tenant)
        names = registry.replace_file_functions(orgid, appid, fileId, [])

        # 从数据库删除
        count = crud.delete_openapi_file(db, tenant, orgid, appid, fileId)

    return {"deleted": count, "unregistered_functions": names}

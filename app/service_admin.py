"""Document queries and non-mutating validation for the administration UI."""
from copy import deepcopy
import json
from urllib.parse import urlparse
from typing import Literal, Optional

import yaml
from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func, or_

from app.db import crud
from app.db.models import OpenAPIFile
from app.mcp.tool_registry import parse_tools_from_openapi
from app.access import validate_identifier


class ServiceInput(BaseModel):
    org: str = Field(min_length=1, max_length=64)
    app: str = Field(min_length=1, max_length=64)
    fileId: Optional[str] = Field(default=None, min_length=1, max_length=64)
    fileName: str = Field(min_length=1, max_length=256)
    yaml_content: str = Field(min_length=1, max_length=2_000_000)
    auth_action: Literal["keep", "replace", "clear"] = "keep"
    auth_type: Optional[Literal["bearer", "basic", "oauth2"]] = None
    auth: Optional[str] = Field(default=None, max_length=65536)

    @field_validator('org', 'app')
    @classmethod
    def identifiers(cls, value, info):
        return validate_identifier(value, info.field_name)

    @field_validator("fileName")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value.strip()


def authorization_type(value):
    if not value:
        return "none"
    try:
        credentials = json.loads(value)
        if isinstance(credentials, dict):
            if "access_token" in credentials:
                return "bearer"
            if "username" in credentials and "password" in credentials:
                return "basic"
            if "client_id" in credentials and "client_secret" in credentials:
                return "oauth2"
    except (ValueError, TypeError, RecursionError):
        pass
    return "unknown"


def authorization_value(body):
    """Validate UI credentials without returning their values in diagnostics."""
    if body.auth_action == "keep":
        return None
    if body.auth_action == "clear":
        return ""
    try:
        credentials = json.loads(body.auth or "")
    except (ValueError, RecursionError) as exc:
        raise HTTPException(400, detail="上游认证配置必须是 JSON 对象") from exc
    if not isinstance(credentials, dict):
        raise HTTPException(400, detail="上游认证配置必须是 JSON 对象")
    # Untyped JSON remains supported for existing API clients. The UI always
    # sends an explicit type, which is checked against the executor's formats.
    if body.auth_type:
        required = {"bearer": ("access_token",), "basic": ("username", "password"),
                    "oauth2": ("client_id", "client_secret", "token_url")}[body.auth_type]
        allowed = set(required) | ({"scopes"} if body.auth_type == "oauth2" else set())
        if set(credentials) - allowed:
            raise HTTPException(400, detail="认证字段与所选授权方式不匹配")
        for field in required:
            value = credentials.get(field)
            if not isinstance(value, str) or not value or (field not in ("password", "client_secret", "access_token") and not value.strip()):
                raise HTTPException(400, detail=f"请填写有效的 {field}")
        if body.auth_type == "oauth2":
            try:
                address = urlparse(credentials["token_url"])
                if address.scheme not in ("http", "https") or not address.hostname or any(c.isspace() for c in credentials["token_url"]):
                    raise ValueError("invalid URL")
            except ValueError as exc:
                raise HTTPException(400, detail="token_url 必须是有效的 HTTP/HTTPS 地址") from exc
            scopes = credentials.get("scopes", [])
            if not isinstance(scopes, list) or any(not isinstance(scope, str) or not scope or any(c.isspace() for c in scope) for scope in scopes):
                raise HTTPException(400, detail="scopes 必须是权限范围字符串数组")
    return body.auth


def parse_document(content, org, app, file_id=None, file_name=None):
    try:
        data = yaml.safe_load(content)
        # YAML allows dates, sets, non-finite floats and cyclic aliases, while
        # OpenAPI and the browser require finite, JSON-compatible values.
        json.dumps(data, allow_nan=False)
        if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
            raise ValueError("文档必须包含 paths 对象")
        if not str(data.get("openapi", "")).startswith("3."):
            raise ValueError("请使用 OpenAPI 3.x 文档")
        info = data.get("info")
        if not isinstance(info, dict) or not isinstance(info.get("title"), str) or not info["title"].strip():
            raise ValueError("info.title 必须是非空字符串")
        if not isinstance(info.get("version"), str):
            raise ValueError("info.version 必须是字符串")
        for path, methods in data["paths"].items():
            if not isinstance(path, str) or not path.startswith("/") or not isinstance(methods, dict):
                raise ValueError("paths 中的路径及方法格式不正确")
            for method, operation in methods.items():
                if str(method).lower() in ("get", "post", "put", "delete", "patch", "head", "options"):
                    if not isinstance(operation, dict):
                        raise ValueError(f"{method} {path} 必须是对象")
                    for field in ("summary", "description"):
                        if field in operation and not isinstance(operation[field], str):
                            raise ValueError(f"{method} {path}: {field} 必须是字符串")
                    if "operationId" in operation and (not isinstance(operation["operationId"], str) or not operation["operationId"].strip()):
                        raise ValueError("operationId 必须是非空字符串")
        tools = parse_tools_from_openapi(org, app, deepcopy(data), file_id, file_name)
        names = [t["name"] for t in tools]
        if len(set(names)) != len(names):
            raise ValueError("同一文档内的工具名称不能重复")
        return data, tools
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except (yaml.YAMLError, AttributeError, TypeError, KeyError, RecursionError) as exc:
        raise HTTPException(400, detail="OpenAPI 文档结构或 YAML/JSON 格式不正确") from exc


def tool_view(tool, manager, tenant):
    meta = tool["metadata"]
    registry = manager.tenant_registries.get(tenant)
    live = registry.get_tool_metadata(tool["name"], tool["orgid"], tool["appid"]) if registry else None
    return {**tool["schema"], "method": meta["method"].upper(),
            "url": meta["url_template"], "timeout": meta["request_timeout_seconds"],
            "active": bool(live and live.get("fileId") == meta.get("fileId"))}


def document_view(row, manager, detail=False):
    error = None
    try:
        data, tools = parse_document(row.openapi_yaml, row.orgid, row.appid, row.fileId, row.fileName)
    except HTTPException:
        data, tools, error = {}, [], "已存文档无法解析，请编辑修复"
    views = [tool_view(t, manager, row.tenant) for t in tools]
    result = {"tenant": row.tenant, "org": row.orgid, "app": row.appid,
              "fileId": row.fileId, "fileName": row.fileName, "title": row.title,
              "version": row.version, "created_at": row.create_at, "updated_at": row.update_at,
              "tool_count": len(views), "active_tool_count": sum(t["active"] for t in views),
              "auth_configured": bool(row.auth), "auth_type": authorization_type(row.auth), "error": error}
    if detail:
        result.update(document=row.openapi_yaml, tools=views, servers=data.get("servers", []))
    return result


def find_document(db, tenant, org, app, file_id):
    row = crud.get_one_openapi(db, tenant, org, app, file_id)
    if row is None:
        raise HTTPException(404, detail="服务文档不存在，请刷新列表")
    return row


def list_documents(db, manager, tenant, org, app, q, page, page_size):
    filters = [OpenAPIFile.tenant == tenant]
    if org:
        filters.append(OpenAPIFile.orgid == org)
    if app:
        filters.append(OpenAPIFile.appid == app)
    if q:
        filters.append(or_(*(col.contains(q, autoescape=True) for col in
                            (OpenAPIFile.title, OpenAPIFile.fileName, OpenAPIFile.fileId))))
    total = db.scalar(select(func.count()).select_from(OpenAPIFile).where(*filters))
    rows = db.scalars(select(OpenAPIFile).where(*filters).order_by(OpenAPIFile.update_at.desc(), OpenAPIFile.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [document_view(row, manager) for row in rows], "total": total,
            "page": page, "page_size": page_size}


def scope_directory(db, tenant, org=None, app=None):
    stmt = select(OpenAPIFile.orgid, OpenAPIFile.appid, func.count()).where(OpenAPIFile.tenant == tenant)
    if org is not None:
        stmt = stmt.where(OpenAPIFile.orgid == org)
    if app is not None:
        stmt = stmt.where(OpenAPIFile.appid == app)
    rows = db.execute(stmt.group_by(OpenAPIFile.orgid, OpenAPIFile.appid)
                      .order_by(OpenAPIFile.orgid, OpenAPIFile.appid)).all()
    organizations = {}
    total = 0
    for org_id, app_id, count in rows:
        organization = organizations.setdefault(org_id, {'org': org_id, 'service_count': 0, 'apps': []})
        organization['apps'].append({'app': app_id, 'service_count': count})
        organization['service_count'] += count
        total += count
    return {'tenant': tenant, 'service_count': total, 'organizations': list(organizations.values())}


def preview_document(db, manager, tenant, body):
    authorization_value(body)
    data, tools = parse_document(body.yaml_content, body.org, body.app, body.fileId, body.fileName)
    old = {}
    if body.fileId:
        row = find_document(db, tenant, body.org, body.app, body.fileId)
        try:
            _, previous = parse_document(row.openapi_yaml, body.org, body.app, body.fileId, body.fileName)
            old = {t["name"]: t for t in previous}
        except HTTPException:
            pass  # A broken stored document must remain repairable.
    new = {t["name"]: t for t in tools}
    common = old.keys() & new.keys()
    changes = {"added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
               "modified": sorted(n for n in common if old[n] != new[n]),
               "unchanged": sorted(n for n in common if old[n] == new[n])}
    conflicts = []
    seen = set()
    registry = manager.tenant_registries.get(tenant)
    for name in new:
        live = registry.get_tool_metadata(name, body.org, body.app) if registry else None
        if live and live.get("fileId") != body.fileId:
            conflicts.append({"name": name, "fileId": live.get("fileId"), "fileName": live.get("fileName")})
            seen.add((name, live.get("fileId")))
    for other in crud.get_openapi_files(db, tenant, body.org, body.app):
        if other.fileId == body.fileId:
            continue
        try:
            # Legacy registration permits documents predating stricter admin
            # validation. Their declared tools must still reserve their names.
            other_tools = parse_tools_from_openapi(body.org, body.app, yaml.safe_load(other.openapi_yaml), other.fileId, other.fileName)
        except (yaml.YAMLError, ValueError, TypeError, AttributeError, KeyError, RecursionError):
            continue
        for name in sorted(new.keys() & {t["name"] for t in other_tools if isinstance(t["name"], str)}):
            if (name, other.fileId) not in seen:
                conflicts.append({"name": name, "fileId": other.fileId, "fileName": other.fileName})
    return {"title": data["info"]["title"], "version": data["info"]["version"],
            "tools": [tool_view(t, manager, tenant) for t in tools], "changes": changes, "conflicts": conflicts}, data

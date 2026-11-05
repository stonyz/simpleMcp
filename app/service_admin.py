"""Document queries and non-mutating validation for the administration UI."""
from app.errors import ApiError, message
from pydantic_core import PydanticCustomError
from copy import deepcopy
import json
import math
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
            raise PydanticCustomError("value_blank", message("value_blank"))
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
        raise ApiError(400, "auth_json_object") from exc
    if not isinstance(credentials, dict):
        raise ApiError(400, "auth_json_object")
    # Untyped JSON remains supported for existing API clients. The UI always
    # sends an explicit type, which is checked against the executor's formats.
    if body.auth_type:
        required = {"bearer": ("access_token",), "basic": ("username", "password"),
                    "oauth2": ("client_id", "client_secret", "token_url")}[body.auth_type]
        allowed = set(required) | ({"scopes"} if body.auth_type == "oauth2" else set())
        if set(credentials) - allowed:
            raise ApiError(400, "auth_fields_mismatch")
        for field in required:
            value = credentials.get(field)
            if not isinstance(value, str) or not value or (field not in ("password", "client_secret", "access_token") and not value.strip()):
                raise ApiError(400, "auth_field_required", field=field)
        if body.auth_type == "oauth2":
            try:
                address = urlparse(credentials["token_url"])
                if address.scheme not in ("http", "https") or not address.hostname or any(c.isspace() for c in credentials["token_url"]):
                    raise ValueError("invalid URL")
            except ValueError as exc:
                raise ApiError(400, "auth_token_url_invalid") from exc
            scopes = credentials.get("scopes", [])
            if not isinstance(scopes, list) or any(not isinstance(scope, str) or not scope or any(c.isspace() for c in scope) for scope in scopes):
                raise ApiError(400, "auth_scopes_invalid")
    return body.auth


def validate_document_timeouts(data):
    """Validate timeout extensions without rendering untrusted values."""
    for path, methods in data.get("paths", {}).items():
        if not isinstance(methods, dict):
            continue
        for method, operation in methods.items():
            if str(method).lower() not in ("get", "post", "put", "delete", "patch", "head", "options") or not isinstance(operation, dict):
                continue
            value = operation.get("x-request-timeout-seconds", 30)
            try:
                valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0
            except OverflowError:
                valid = False
            if not valid:
                raise ApiError(400, "document_timeout_invalid", method=str(method).upper(), path=path)


def parse_document(content, org, app, file_id=None, file_name=None):
    try:
        data = yaml.safe_load(content)
        # YAML allows dates, sets, non-finite floats and cyclic aliases, while
        # OpenAPI and the browser require finite, JSON-compatible values.
        json.dumps(data, allow_nan=False)
        if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
            raise ApiError(400, "document_paths_required")
        if not str(data.get("openapi", "")).startswith("3."):
            raise ApiError(400, "document_openapi_version")
        info = data.get("info")
        if not isinstance(info, dict) or not isinstance(info.get("title"), str) or not info["title"].strip():
            raise ApiError(400, "document_title_invalid")
        if not isinstance(info.get("version"), str):
            raise ApiError(400, "document_version_invalid")
        for path, methods in data["paths"].items():
            if not isinstance(path, str) or not path.startswith("/") or not isinstance(methods, dict):
                raise ApiError(400, "document_paths_invalid")
            for method, operation in methods.items():
                if str(method).lower() in ("get", "post", "put", "delete", "patch", "head", "options"):
                    if not isinstance(operation, dict):
                        raise ApiError(400, "document_operation_object", method=method, path=path)
                    for field in ("summary", "description"):
                        if field in operation and not isinstance(operation[field], str):
                            raise ApiError(400, "document_operation_field_string", method=method, path=path, field=field)
                    if "operationId" in operation and (not isinstance(operation["operationId"], str) or not operation["operationId"].strip()):
                        raise ApiError(400, "document_operation_id_invalid")
        validate_document_timeouts(data)
        tools = parse_tools_from_openapi(org, app, deepcopy(data), file_id, file_name)
        names = [t["name"] for t in tools]
        if len(set(names)) != len(names):
            raise ApiError(400, "document_duplicate_tools")
        return data, tools
    except (yaml.YAMLError, ValueError, AttributeError, TypeError, KeyError, RecursionError) as exc:
        raise ApiError(400, "document_invalid") from exc


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
        data, tools, error = {}, [], message("stored_document_invalid")
    views = [tool_view(t, manager, row.tenant) for t in tools]
    result = {"tenant": row.tenant, "org": row.orgid, "app": row.appid,
              "fileId": row.fileId, "fileName": row.fileName, "title": row.title,
              "version": row.version, "created_at": row.create_at, "updated_at": row.update_at,
              "tool_count": len(views), "active_tool_count": sum(t["active"] for t in views),
              "auth_configured": bool(row.auth), "auth_type": authorization_type(row.auth), "error": error}
    if error:
        result.update(error_code="stored_document_invalid", error_params={})
    if detail:
        result.update(document=row.openapi_yaml, tools=views, servers=data.get("servers", []))
    return result


def find_document(db, tenant, org, app, file_id):
    row = crud.get_one_openapi(db, tenant, org, app, file_id)
    if row is None:
        raise ApiError(404, "document_not_found")
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

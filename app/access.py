"""Scope identities and authorization shared by management and MCP routes."""
from typing import Literal, Optional
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.config import settings


def validate_identifier(value, field, limit=64):
    if (not isinstance(value, str) or not value or len(value) > limit or (field == 'tenant' and value in ('.', '..'))
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c in '/\\?#' for c in value)):
        raise ValueError(f'{field} must be a nonblank identifier of at most {limit} characters without whitespace or /\\?#')
    return value


def check_identifier(value, field, limit=64):
    try:
        return validate_identifier(value, field, limit)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


class AccessRule(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    tenant: str
    org: Optional[str] = None
    app: Optional[str] = None
    services: Optional[list[str]] = Field(default=None, min_length=1, max_length=500)
    operations: list[Literal['list', 'call']] = Field(default_factory=lambda: ['list', 'call'], min_length=1, max_length=2)

    @field_validator('tenant', 'org', 'app')
    @classmethod
    def identifiers(cls, value, info):
        return validate_identifier(value, info.field_name, 63 if info.field_name == 'tenant' else 64) if value is not None else None

    @field_validator('services')
    @classmethod
    def service_ids(cls, value):
        if value is not None:
            for identity in value:
                if not identity or len(identity) > 64:
                    raise ValueError('Invalid service fileId')
            return sorted(set(value))
        return value

    @model_validator(mode='after')
    def hierarchy(self):
        if self.app is not None and self.org is None:
            raise ValueError('An app scope requires an org')
        if self.services is not None and self.app is None:
            raise ValueError('Service selection requires org and app')
        return self

    def permits(self, tenant, org, app, file_id, operation):
        return (self.tenant == tenant and operation in self.operations
                and (self.org is None or self.org == org)
                and (self.app is None or self.app == app)
                and (self.services is None or file_id in self.services))


@dataclass(frozen=True)
class AccessPolicy:
    credential_id: str
    rules: tuple[AccessRule, ...]

    def allows(self, tenant, org, app, file_id, operation):
        return any(rule.permits(tenant, org, app, file_id, operation) for rule in self.rules)


current_policy: ContextVar[Optional[AccessPolicy]] = ContextVar('mcp_access_policy', default=None)


def rpc_scope(request, params):
    """Exactly the same precedence for authorization and execution."""
    return (params.get('orgid') or request.headers.get('X-Org-ID'),
            params.get('appid') or request.headers.get('X-App-ID'))


async def authorize_request(request: Request):
    path = request.scope['route'].path
    is_mcp = path in ('/mcp', '/mcp/list', '/mcp/call', '/functions/')
    if is_mcp and getattr(request.state, 'is_admin', False) and not settings.ADMIN_MCP_ENABLED:
        raise HTTPException(403, detail='Administrator tokens are restricted to management. Use a database MCP credential or enable ADMIN_MCP_ENABLED.')
    policy = getattr(request.state, 'mcp_policy', None)
    tenant = request.query_params.get('tenant')
    if tenant is not None:
        check_identifier(tenant, 'tenant', 63)
    if policy is not None:
        if not is_mcp:
            raise HTTPException(403, detail='MCP credentials cannot access management APIs')
        if not any(rule.tenant == tenant for rule in policy.rules):
            raise HTTPException(403, detail='Token does not permit this tenant')

    org = app = None
    if path.startswith('/services'):
        if request.method == 'POST':
            if path.endswith('register-form'):
                body = await request.form()
            else:
                try:
                    body = await request.json()
                except ValueError:
                    body = {}
            if isinstance(body, dict) or hasattr(body, 'getlist'):
                org, app = body.get('org'), body.get('app')
        else:
            org, app = request.query_params.get('org'), request.query_params.get('app')
    elif path in ('/mcp', '/mcp/call'):
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            if path == '/mcp':
                params = body.get('params', {})
                if isinstance(params, dict):
                    org, app = rpc_scope(request, params)
            else:
                org, app = body.get('orgid'), body.get('appid')
    else:
        org, app = request.query_params.get('orgid'), request.query_params.get('appid')
    for field, value in [('org', org), ('app', app)]:
        if value is not None and value != '':
            check_identifier(value, field)
    context = current_policy.set(policy)
    try:
        yield
    finally:
        current_policy.reset(context)

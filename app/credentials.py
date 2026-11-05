"""Database-backed credentials. Raw secrets only leave create/rotate responses."""
from app.errors import ApiError, message
from pydantic_core import PydanticCustomError
from datetime import datetime, timezone, timedelta
import hashlib
import secrets
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.access import AccessPolicy, AccessRule
from app.db.models import MCPCredential, MCPAccessRule, OpenAPIFile


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CredentialInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default='', max_length=2000)
    enabled: bool = True
    expires_at: datetime | None = None
    rules: list[AccessRule] = Field(min_length=1, max_length=100)

    @field_validator('name')
    @classmethod
    def name_nonblank(cls, value):
        if not value.strip():
            raise PydanticCustomError("name_blank", message("name_blank"))
        return value.strip()

    @field_validator('expires_at')
    @classmethod
    def utc_expiry(cls, value):
        if value is not None:
            if value.tzinfo is None:
                raise PydanticCustomError("expiry_timezone_required", message("expiry_timezone_required"))
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return None


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def rotate_secret(row):
    secret = 'mcp_' + secrets.token_urlsafe(32)
    row.token_hash = digest(secret)
    row.token_prefix = secret[:12]
    row.updated_at = utcnow()
    return secret


def rule_view(row):
    return {field: getattr(row, field) for field in ('tenant', 'org', 'app', 'services', 'operations')}


def timestamp(value):
    return value.isoformat() + 'Z' if value else None


def credential_view(row):
    return {'id': row.id, 'name': row.name, 'description': row.description,
            'token_prefix': row.token_prefix, 'enabled': row.enabled,
            'status': 'disabled' if not row.enabled else 'expired' if row.expires_at and row.expires_at <= utcnow() else 'active',
            **{field: timestamp(getattr(row, field)) for field in ('expires_at', 'created_at', 'updated_at', 'last_used_at')},
            'rules': [rule_view(rule) for rule in row.rules]}


def get_credential(db, identity, tenant=None):
    row = db.get(MCPCredential, identity)
    if row is None or (tenant is not None and (not row.rules or any(rule.tenant != tenant for rule in row.rules))):
        raise ApiError(404, "credential_not_found")
    return row


def save_credential(db, body, identity=None, tenant=None):
    from app.tenants import ensure_tenant, get_tenant
    if identity is not None:
        row = get_credential(db, identity, tenant)
    if tenant is not None:
        get_tenant(db, tenant)
        if any(rule.tenant != tenant for rule in body.rules):
            raise ApiError(403, "credential_tenant_mismatch")
    for rule in body.rules:
        if rule.services is not None:
            existing = set(db.scalars(select(OpenAPIFile.fileId).where(
                OpenAPIFile.tenant == rule.tenant, OpenAPIFile.orgid == rule.org,
                OpenAPIFile.appid == rule.app, OpenAPIFile.fileId.in_(rule.services))).all())
            if existing != set(rule.services):
                raise ApiError(400, "credential_service_not_found")
    for rule in body.rules:
        ensure_tenant(db, rule.tenant)
    secret = None
    if identity is None:
        row = MCPCredential(id=uuid4().hex, created_at=utcnow())
        secret = rotate_secret(row)
        db.add(row)
    else:
        row = get_credential(db, identity, tenant)
    row.name, row.description, row.enabled = body.name, body.description, body.enabled
    row.expires_at, row.updated_at = body.expires_at, utcnow()
    row.rules = [MCPAccessRule(**rule.model_dump()) for rule in body.rules]
    db.flush()
    result = credential_view(row)
    if secret:
        result['secret'] = secret
    return result


def authenticate(db, secret):
    row = db.scalar(select(MCPCredential).where(MCPCredential.token_hash == digest(secret)))
    if row is None or not row.enabled or (row.expires_at and row.expires_at <= utcnow()):
        return None
    policy = AccessPolicy(row.id, tuple(AccessRule(**rule_view(rule)) for rule in row.rules))
    now = utcnow()
    if row.last_used_at is None or row.last_used_at < now - timedelta(minutes=1):
        row.last_used_at = now
    return policy


def catalog(db, tenant):
    rows = db.execute(select(OpenAPIFile.tenant, OpenAPIFile.orgid, OpenAPIFile.appid,
                             OpenAPIFile.fileId, OpenAPIFile.title, OpenAPIFile.fileName).where(OpenAPIFile.tenant == tenant)
                      .order_by(OpenAPIFile.tenant, OpenAPIFile.orgid, OpenAPIFile.appid, OpenAPIFile.title)).all()
    return {'services': [{'tenant': t, 'org': o, 'app': a, 'fileId': f, 'title': title, 'fileName': name}
                         for t, o, a, f, title, name in rows]}

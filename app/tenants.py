"""Persistent tenant workspaces and registration of legacy resource owners."""
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, func

from app.access import validate_identifier
from app.db.models import Tenant, OpenAPIFile, MCPAccessRule


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TenantUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default='', max_length=2000)

    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Name must not be blank')
        return value.strip()


class TenantCreate(TenantUpdate):
    id: str

    @field_validator('id')
    @classmethod
    def identifier(cls, value):
        return validate_identifier(value, 'tenant', 63)


def ensure_tenant(db, identity):
    row = db.get(Tenant, identity)
    if row is None:
        row = Tenant(id=identity, name=identity, description='', created_at=now(), updated_at=now())
        db.add(row)
        db.flush()
    return row


def sync_tenants(db):
    identities = db.scalars(select(OpenAPIFile.tenant).union(select(MCPAccessRule.tenant))).all()
    if not identities and db.scalar(select(Tenant.id).limit(1)) is None:
        identities = ['default']
    for identity in identities:
        ensure_tenant(db, identity)


def get_tenant(db, identity):
    row = db.get(Tenant, identity)
    if row is None:
        raise HTTPException(404, detail='租户不存在，请返回租户入口重新选择')
    return row


def tenant_view(db, row):
    services = db.scalar(select(func.count()).select_from(OpenAPIFile).where(OpenAPIFile.tenant == row.id))
    credentials = db.scalar(select(func.count(func.distinct(MCPAccessRule.credential_id))).where(MCPAccessRule.tenant == row.id))
    return {'id': row.id, 'name': row.name, 'description': row.description,
            'service_count': services, 'credential_count': credentials,
            'created_at': row.created_at.isoformat() + 'Z', 'updated_at': row.updated_at.isoformat() + 'Z'}


def list_tenants(db):
    service_counts = dict(db.execute(select(OpenAPIFile.tenant, func.count()).group_by(OpenAPIFile.tenant)).all())
    credential_counts = dict(db.execute(select(MCPAccessRule.tenant, func.count(func.distinct(MCPAccessRule.credential_id)))
                                        .group_by(MCPAccessRule.tenant)).all())
    return {'items': [{'id': row.id, 'name': row.name, 'description': row.description,
                       'service_count': service_counts.get(row.id, 0), 'credential_count': credential_counts.get(row.id, 0),
                       'created_at': row.created_at.isoformat() + 'Z', 'updated_at': row.updated_at.isoformat() + 'Z'}
                      for row in db.scalars(select(Tenant).order_by(Tenant.name, Tenant.id)).all()]}

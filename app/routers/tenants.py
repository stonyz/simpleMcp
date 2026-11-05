from app.errors import ApiError
from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from app.access import authorize_request, check_identifier
from app.db import get_db_context
from app.db.models import Tenant
from app.tenants import TenantCreate, TenantUpdate, get_tenant, list_tenants, tenant_view, now

router = APIRouter(dependencies=[Depends(authorize_request)])


@router.get('/')
def tenants():
    with get_db_context() as db:
        return list_tenants(db)


@router.post('/')
def create_tenant(body: TenantCreate):
    with get_db_context() as db:
        if db.get(Tenant, body.id) is not None:
            raise ApiError(409, "tenant_exists")
        row = Tenant(**body.model_dump(), created_at=now(), updated_at=now())
        db.add(row)
        try:
            db.flush()
        except IntegrityError as exc:
            raise ApiError(409, "tenant_exists") from exc
        return tenant_view(db, row)


@router.get('/{identity}')
def detail(identity: str):
    check_identifier(identity, 'tenant', 63)
    with get_db_context() as db:
        return tenant_view(db, get_tenant(db, identity))


@router.put('/{identity}')
def update_tenant(identity: str, body: TenantUpdate):
    check_identifier(identity, 'tenant', 63)
    with get_db_context() as db:
        row = get_tenant(db, identity)
        row.name, row.description, row.updated_at = body.name, body.description, now()
        return tenant_view(db, row)


@router.delete('/{identity}')
def delete_tenant(identity: str):
    check_identifier(identity, 'tenant', 63)
    with get_db_context() as db:
        row = get_tenant(db, identity)
        view = tenant_view(db, row)
        if view['service_count'] or view['credential_count']:
            raise ApiError(409, "tenant_not_empty")
        db.delete(row)
        return {'deleted': True}

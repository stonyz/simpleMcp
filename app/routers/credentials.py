from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from pydantic import BaseModel, ConfigDict

from app.access import authorize_request
from app.credentials import CredentialInput, catalog, credential_view, get_credential, rotate_secret, save_credential
from app.db import get_db_context
from app.db.models import MCPCredential
from app.credentials import utcnow

router = APIRouter(dependencies=[Depends(authorize_request)])


class CredentialStatus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool


@router.get('/')
def list_credentials(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with get_db_context() as db:
        rows = db.scalars(select(MCPCredential).order_by(MCPCredential.created_at.desc())).all()
        return {'items': [credential_view(row) for row in rows]}


@router.get('/catalog')
def service_catalog():
    with get_db_context() as db:
        return catalog(db)


@router.post('/')
def create_credential(body: CredentialInput, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with get_db_context() as db:
        return save_credential(db, body)


@router.put('/{identity}')
def update_credential(identity: str, body: CredentialInput):
    with get_db_context() as db:
        return save_credential(db, body, identity)


@router.post('/{identity}/rotate')
def rotate_credential(identity: str, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with get_db_context() as db:
        row = get_credential(db, identity)
        secret = rotate_secret(row)
        return {**credential_view(row), 'secret': secret}


@router.patch('/{identity}/status')
def set_status(identity: str, body: CredentialStatus):
    with get_db_context() as db:
        row = get_credential(db, identity)
        row.enabled, row.updated_at = body.enabled, utcnow()
        return credential_view(row)


@router.delete('/{identity}')
def delete_credential(identity: str):
    with get_db_context() as db:
        db.delete(get_credential(db, identity))
        return {'deleted': True}

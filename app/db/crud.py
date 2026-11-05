from sqlalchemy.orm import Session
from sqlalchemy import select, delete, func
from app.db.models import OpenAPIFile
import json
import yaml
from typing import List, Optional, Tuple
def upsert_openapi_file(db: Session, tenant: str, orgid: str, appid: str, fileId: str, fileName: str, openapi_data: dict, auth: Optional[str] = None):
    from app.tenants import ensure_tenant
    ensure_tenant(db, tenant)
    info = openapi_data.get("info", {})
    title = info.get("title", "untitled")
    version = info.get("version") or ""

    # 先查是否存在
    stmt = select(OpenAPIFile).where(
        OpenAPIFile.tenant == tenant,
        OpenAPIFile.orgid == orgid,
        OpenAPIFile.appid == appid,
        OpenAPIFile.fileId == fileId
    )
    existed = db.execute(stmt).scalars().first()
    if existed:
        existed.openapi_yaml = yaml.dump(openapi_data, allow_unicode=True)
        existed.fileName = fileName
        existed.title = title
        existed.version = version
        # Update auth if provided
        if auth is not None:
            existed.auth = auth
        db.add(existed)
        db.commit()
        db.refresh(existed)
        return existed, True

    obj = OpenAPIFile(
        tenant=tenant,
        orgid=orgid,
        appid=appid,
        fileId=fileId,
        fileName=fileName,
        title=title,
        version=version,
        create_at= func.now(),
        openapi_yaml = yaml.dump(openapi_data, allow_unicode=True),
        auth=auth,  # Store auth data if provided
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj, False

def get_openapi_files(db: Session, tenant: Optional[str] = None, orgid: Optional[str] = None, appid: Optional[str] = None) -> List[OpenAPIFile]:
    stmt = select(OpenAPIFile)
    if tenant:
        stmt = stmt.where(OpenAPIFile.tenant == tenant)
    if orgid:
        stmt = stmt.where(OpenAPIFile.orgid == orgid)
    if appid:
        stmt = stmt.where(OpenAPIFile.appid == appid)
    return list(db.execute(stmt).scalars().all())

def get_one_openapi(db: Session, tenant: str, orgid: str, appid: str, fileId: str, version: Optional[str] = None) -> Optional[OpenAPIFile]:
    stmt = select(OpenAPIFile).where(
        OpenAPIFile.tenant == tenant,
        OpenAPIFile.orgid == orgid,
        OpenAPIFile.appid == appid,
        OpenAPIFile.fileId == fileId,
    )
    if version is not None:
        stmt = stmt.where(OpenAPIFile.version == version)
    return db.execute(stmt).scalars().first()

def delete_openapi_file(db: Session, tenant: str, orgid: str, appid: str, fileId: str, version: Optional[str] = None) -> int:
    stmt = delete(OpenAPIFile).where(
        OpenAPIFile.tenant == tenant,
        OpenAPIFile.orgid == orgid,
        OpenAPIFile.appid == appid,
        OpenAPIFile.fileId == fileId,
    )
    if version is not None:
        stmt = stmt.where(OpenAPIFile.version == version)
    result = db.execute(stmt)
    db.commit()
    return result.rowcount

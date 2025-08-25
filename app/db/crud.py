from sqlalchemy.orm import Session
from sqlalchemy import select, delete
from app.db.models import OpenAPIFile
import json
import yaml
from typing import List, Optional, Tuple

def upsert_openapi_file(db: Session, orgid: str, appid: str, openapi_data: dict):
    info = openapi_data.get("info", {})
    title = info.get("title", "untitled")
    version = info.get("version") or ""

    # 先查是否存在
    stmt = select(OpenAPIFile).where(
        OpenAPIFile.orgid == orgid,
        OpenAPIFile.appid == appid,
        OpenAPIFile.title == title,
        OpenAPIFile.version == version,
    )
    existed = db.execute(stmt).scalars().first()
    if existed:
        existed.openapi_yaml = yaml.dump(openapi_data, allow_unicode=True)
        db.add(existed)
        db.commit()
        db.refresh(existed)
        return existed, True

    obj = OpenAPIFile(
        orgid=orgid,
        appid=appid,
        title=title,
        version=version,
        openapi_yaml = yaml.dump(openapi_data, allow_unicode=True),
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj, False

def get_openapi_files(db: Session, orgid: Optional[str] = None, appid: Optional[str] = None) -> List[OpenAPIFile]:
    stmt = select(OpenAPIFile)
    if orgid:
        stmt = stmt.where(OpenAPIFile.orgid == orgid)
    if appid:
        stmt = stmt.where(OpenAPIFile.appid == appid)
    return list(db.execute(stmt).scalars().all())

def get_one_openapi(db: Session, orgid: str, appid: str, title: str, version: Optional[str]) -> Optional[OpenAPIFile]:
    stmt = select(OpenAPIFile).where(
        OpenAPIFile.orgid == orgid,
        OpenAPIFile.appid == appid,
        OpenAPIFile.title == title,
    )
    if version is not None:
        stmt = stmt.where(OpenAPIFile.version == version)
    return db.execute(stmt).scalars().first()

def delete_openapi_file(db: Session, orgid: str, appid: str, title: str, version: Optional[str]) -> int:
    stmt = delete(OpenAPIFile).where(
        OpenAPIFile.orgid == orgid,
        OpenAPIFile.appid == appid,
        OpenAPIFile.title == title,
    )
    if version is not None:
        stmt = stmt.where(OpenAPIFile.version == version)
    result = db.execute(stmt)
    db.commit()
    return result.rowcount

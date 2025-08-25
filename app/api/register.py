from fastapi import APIRouter, UploadFile, Form, Depends, HTTPException
from sqlalchemy.orm import Session
import yaml, json
from app.db import get_db
from app.db import crud
from app.mcp.openapi_loader import register_from_openapi
import logging

router = APIRouter()
log = logging.getLogger(__name__)

@router.post("/register")
async def register_openapi(
    orgid: str = Form(...),
    appid: str = Form(...),
    file: UploadFile = Form(...)
):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded")

    content = await file.read()
    try:
        if file.filename.endswith((".yaml", ".yml")):
            openapi_data = yaml.safe_load(content)
        else:
            openapi_data = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid OpenAPI file: {e}")

    # 基本校验
    if not isinstance(openapi_data, dict) or "paths" not in openapi_data:
        raise HTTPException(status_code=400, detail="OpenAPI content missing 'paths'")

    with next(get_db()) as db:  # 直接使用依赖函数提供的生成器
        obj, updated = crud.upsert_openapi_file(db, orgid, appid, openapi_data)

    registered = register_from_openapi(orgid, appid, openapi_data)
    return {
        "status": "success",
        "updated": updated,
        "orgid": orgid,
        "appid": appid,
        "title": openapi_data.get("info", {}).get("title"),
        "version": openapi_data.get("info", {}).get("version"),
        "registered_functions": registered
    }

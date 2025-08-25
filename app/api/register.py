from fastapi import APIRouter, UploadFile, Form, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
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
    file: Optional[UploadFile] = None,
    yaml_content: Optional[str] = Form(None)
):

    if file:
        content_bytes = await file.read()
        openapi_data = parse_file_content(file.filename, content_bytes)
    elif yaml_content:
        openapi_data = parse_yaml_string(yaml_content)
    else:
        raise HTTPException(status_code=400, detail="No file or YAML string provided")

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

def parse_file_content(filename: str, content: bytes):
    """根据文件后缀解析内容"""
    try:
        if filename.endswith((".yaml", ".yml")):
            return yaml.safe_load(content)
        elif filename.endswith(".json"):
            return json.loads(content)
        else:
            # 默认尝试 YAML，再尝试 JSON
            try:
                return yaml.safe_load(content)
            except yaml.YAMLError:
                return json.loads(content)
    except (yaml.YAMLError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid file content: {e}")

def parse_yaml_string(yaml_str: str):
    try:
        return yaml.safe_load(yaml_str)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML string: {e}")
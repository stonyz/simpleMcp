from fastapi import FastAPI
from app.config import settings
from app.logger import setup_logging
from app.midware.LoggingMiddleware import LoggingMiddleware
from app.db import engine, Base, get_db
from app.db import crud
from app.db.models import OpenAPIFile
from app.api import register as register_api
from app.api import functions as functions_api
from app.api import delete as delete_api
from app.api import mcp_api
from app.mcp.openapi_loader import register_from_openapi
import yaml
import logging

setup_logging()
log = logging.getLogger(__name__)

app = FastAPI(title=settings.APP_NAME)

app.add_middleware(LoggingMiddleware)
# 创建表（产品环境建议用 Alembic 做迁移）
Base.metadata.create_all(bind=engine)

# 路由
app.include_router(register_api.router)
app.include_router(functions_api.router)
app.include_router(delete_api.router)
app.include_router(mcp_api.router)

@app.on_event("startup")
def on_startup():
    """
    启动时从 DB 加载所有 OpenAPI，并注册为 functions
    """
    with next(get_db()) as db:
        files = crud.get_openapi_files(db)
        total_funcs = 0
        for f in files:
            try:
                data =  yaml.safe_load(f.openapi_yaml)
                names = register_from_openapi(f.orgid, f.appid, data)
                total_funcs += len(names)
            except Exception as e:
                log.exception(f"Failed to register OpenAPI (org={f.orgid}, app={f.appid}, title={f.title}): {e}")
        log.info(f"Startup loaded {len(files)} OpenAPI files, registered {total_funcs} functions")

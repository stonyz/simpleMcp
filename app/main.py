from fastapi import FastAPI
from app.config import settings
from app.logger import setup_logging
from app.midware.LoggingMiddleware import LoggingMiddleware
from app.midware.AuthMiddleware import AuthMiddleware
from app.midware.TenantMiddleware import TenantMiddleware
from app.midware.RequestIdMiddleware import RequestIdMiddleware
from app.db import engine, Base, get_db, get_db_context
from app.db import crud
from app.common.exception_handlers import register_exception_handlers

from app.mcp.tenant_manager import tenant_manager
import os
import pkgutil
import importlib
import yaml
import logging

setup_logging()
log = logging.getLogger(__name__)

app = FastAPI(title=settings.APP_NAME)

# Add middleware
# 注意中间件的顺序很重要，按照请求处理的顺序排列
# RequestIdMiddleware应该最后添加，这样它会最先执行，确保request_id在其他中间件中可用
app.add_middleware(TenantMiddleware)  # 处理租户提取
app.add_middleware(AuthMiddleware)    # 处理身份验证
app.add_middleware(LoggingMiddleware) # 处理日志记录
app.add_middleware(RequestIdMiddleware) # 最后添加，但最先执行，生成request_id

# 注册全局异常处理器
register_exception_handlers(app)

# 路由
# app.include_router(register_api.router)
# app.include_router(functions_api.router)
# app.include_router(delete_api.router)
# app.include_router(mcp_api.router)

def register_routers():
    # 获取 routers 文件夹的绝对路径
    base_path = os.path.dirname(os.path.abspath(__file__))  # 当前文件的绝对路径
    routers_path = os.path.join(base_path, "routers")  # 拼接 routers 目录路径

    # 确保路径存在
    if not os.path.exists(routers_path):
        raise FileNotFoundError(f"The routers directory does not exist: {routers_path}")

    # 遍历 routers 文件夹中的模块
    for _, module_name, _ in pkgutil.iter_modules([routers_path]):
        # 导入模块
        module = importlib.import_module(f"{__package__}.routers.{module_name}")  # 模块名加上路径前缀
        if hasattr(module, "router"):  # 检查是否定义了 `router`
            prefix = f"/{module_name}"
            app.include_router(module.router, prefix=prefix)
            log.info(f"Registered router from module: {module_name}")

register_routers()

@app.on_event("startup")
async def on_startup():
    """
    启动时从 DB 加载所有 OpenAPI，并注册为 functions
    """
    # 创建表（产品环境建议用 Alembic 做迁移）
    Base.metadata.create_all(bind=engine)
    
    # 使用现有的数据库操作方式加载数据
    with get_db_context() as db:
        files = crud.get_openapi_files(db)
        total_funcs = 0
        for f in files:
            try:
                data = yaml.safe_load(f.openapi_yaml)
         
                tenant = getattr(f, 'tenant', 'default')
                names = tenant_manager.register_tools_from_openapi(tenant, f.orgid, f.appid, data, f.fileId, f.fileName, f.auth)
                total_funcs += len(names)
            except Exception as e:
                log.exception(f"Failed to register OpenAPI (org={f.orgid}, app={f.appid}, title={f.title}): {e}")
        log.info(f"Startup loaded {len(files)} OpenAPI files, registered {total_funcs} functions")
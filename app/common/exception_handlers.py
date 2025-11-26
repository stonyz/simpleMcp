"""
全局异常处理器模块
提供统一的异常处理和错误响应格式
"""
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
import logging
import traceback

log = logging.getLogger(__name__)


def register_exception_handlers(app):
    """注册所有全局异常处理器到FastAPI应用"""
    
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """全局异常处理器，捕获所有未处理的异常"""
        # 记录异常到日志
        log.error(f"Unhandled exception in {request.method} {request.url}: {str(exc)}")
        log.error(f"Exception traceback: {traceback.format_exc()}")
        
        # 返回JSON格式的错误信息
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "type": "InternalServerError",
                    "message": "An unexpected error occurred",
                    "details": str(exc),
                    "path": request.url.path,
                    "method": request.method
                }
            }
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """HTTP异常处理器"""
        log.warning(f"HTTP exception in {request.method} {request.url}: {exc.status_code} - {exc.detail}")
        
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "type": "HTTPException",
                    "message": exc.detail,
                    "status_code": exc.status_code,
                    "path": request.url.path,
                    "method": request.method
                }
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """请求验证异常处理器"""
        log.warning(f"Validation error in {request.method} {request.url}: {exc.errors()}")
        
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "ValidationError",
                    "message": "Request validation failed",
                    "details": exc.errors(),
                    "path": request.url.path,
                    "method": request.method
                }
            }
        )

    log.info("Global exception handlers registered successfully")

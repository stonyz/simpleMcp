"""
全局异常处理器模块
提供统一的异常处理和错误响应格式
"""
from app.errors import CATALOG, message
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
        log.error(f"Unhandled exception in {request.method} {request.url.path}: {str(exc)}")
        log.error(f"Exception traceback: {traceback.format_exc()}")
        
        # 返回JSON格式的错误信息
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "type": "InternalServerError",
                    "message": message("internal_error"),
                    "code": "internal_error",
                    "params": {},
                    "details": "See server logs using the request ID",
                    "path": request.url.path,
                    "method": request.method
                }
            }
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        """HTTP异常处理器"""
        log.warning(f"HTTP exception in {request.method} {request.url.path}: {exc.status_code} - {exc.detail}")
        
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "error": {
                    "type": "HTTPException",
                    "message": exc.detail,
                    "code": getattr(exc, "code", "http_error"),
                    "params": getattr(exc, "params", {}),
                    "status_code": exc.status_code,
                    "path": request.url.path,
                    "method": request.method
                }
            }
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """请求验证异常处理器"""
        # Pydantic includes raw input and exception objects in its diagnostics.
        # Neither belongs in credential-bearing API responses or logs.
        safe_errors = []
        for error in exc.errors():
            diagnostic = {key: error[key] for key in ("type", "loc", "msg") if key in error}
            code = error.get("type")
            if code in CATALOG:
                params = {}
                # Only this validator has formatting context. Its field name
                # and numeric bound are controlled by our model definitions.
                # Never forward arbitrary Pydantic context or raw input.
                if code == "identifier_invalid":
                    context = error.get("ctx") or {}
                    if context.get("field") in ("tenant", "org", "app", "id"):
                        params["field"] = context["field"]
                    limit = context.get("limit")
                    if type(limit) is int and 1 <= limit <= 256:
                        params["limit"] = limit
                diagnostic.update(code=code, params=params)
            safe_errors.append(diagnostic)
        log.warning("Validation error in %s %s: %s", request.method, request.url.path,
                    [{"type": error.get("type"), "loc": error.get("loc")} for error in safe_errors])
        
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "ValidationError",
                    "message": message("validation_error"),
                    "code": "validation_error",
                    "params": {},
                    "details": safe_errors,
                    "path": request.url.path,
                    "method": request.method
                }
            }
        )

    log.info("Global exception handlers registered successfully")

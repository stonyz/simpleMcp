"""
Routes for verifying the global exception handlers.
"""
from fastapi import APIRouter, HTTPException
import logging

router = APIRouter()
log = logging.getLogger(__name__)

@router.get("/test-unhandled-exception")
async def test_unhandled_exception():
    """Trigger an unhandled exception to verify global error handling."""
    # 故意抛出一个异常，测试全局异常处理器
    raise ValueError("This is a test unhandled exception")

@router.get("/test-http-exception")
async def test_http_exception():
    """Trigger an HTTP exception to verify error handling."""
    raise HTTPException(status_code=400, detail="This is a test HTTP exception")

@router.get("/test-division-by-zero")
async def test_division_by_zero():
    """Trigger a division-by-zero exception to verify error handling."""
    result = 1 / 0  # 这会抛出ZeroDivisionError
    return {"result": result}

@router.get("/test-attribute-error")
async def test_attribute_error():
    """Trigger an attribute error to verify error handling."""
    obj = None
    obj.nonexistent_method()  # 这会抛出AttributeError
    return {"result": "should not reach here"}

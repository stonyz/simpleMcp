"""
测试异常处理器的路由
用于验证全局异常处理是否正常工作
"""
from fastapi import APIRouter, HTTPException
import logging

router = APIRouter()
log = logging.getLogger(__name__)

@router.get("/test-unhandled-exception")
async def test_unhandled_exception():
    """测试未处理的异常"""
    # 故意抛出一个异常，测试全局异常处理器
    raise ValueError("This is a test unhandled exception")

@router.get("/test-http-exception")
async def test_http_exception():
    """测试HTTP异常"""
    raise HTTPException(status_code=400, detail="This is a test HTTP exception")

@router.get("/test-division-by-zero")
async def test_division_by_zero():
    """测试除零异常"""
    result = 1 / 0  # 这会抛出ZeroDivisionError
    return {"result": result}

@router.get("/test-attribute-error")
async def test_attribute_error():
    """测试属性错误"""
    obj = None
    obj.nonexistent_method()  # 这会抛出AttributeError
    return {"result": "should not reach here"}

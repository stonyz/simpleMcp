from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.logger import request_logger

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 获取请求体（注意：如果请求体比较大或者需要重复读取，需要额外处理）
        body_bytes = await request.body()
        body_str = body_bytes.decode('utf-8') if body_bytes else ""
        if request.method in ["POST", "PUT", "PATCH"]:
            content_type = request.headers.get("content-type", "")
            
            if "multipart/form-data" in content_type:  # 处理 form-data
                form = await request.form()
                body_str = {key: value for key, value in form.items()}  # 转成字典
            elif "application/json" in content_type:  # 处理 JSON
                body_str = await request.json()
            else:
                req_body_bytes = await request.body()
                body_str = req_body_bytes.decode('utf-8') if req_body_bytes else ""

        query_str = f"?{request.query_params}" if request.query_params else ""
        
        # 获取请求头
        headers_dict = dict(request.headers)
        
        # 组合日志内容
        log_msg = f"{request.method} {request.url.path}{query_str}"

        # request_logger.info(log_msg)


        response = await call_next(request)
        if "text/event-stream" in response.headers.get("Content-Type", ""):
            # 对于 SSE，不处理响应体
            request_logger.info(f"{log_msg} {response.status_code} (SSE Connection)\nHeaders: {headers_dict}")
            return response

        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        # 重新创建 Response，确保响应内容仍能正确返回
        from starlette.responses import Response
        response = Response(content=response_body, status_code=response.status_code, headers=dict(response.headers))

        # 解析并记录响应体
        response_text = response_body.decode("utf-8") if response_body else ""
        request_logger.info(f"{log_msg} {response.status_code}\nHeaders: {headers_dict}\nReq:     `{body_str}\nResp:    `{response_text}\n")

        return response
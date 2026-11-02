from time import monotonic
import logging
from urllib.parse import urlencode

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.logger import request_logger


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = monotonic()
        debug = request_logger.isEnabledFor(logging.DEBUG) and 'credentials' not in request.url.path.strip('/').split('/')
        safe_url = request.url.replace(query=urlencode([(key, '[REDACTED]' if key.lower() == 'token' else value)
                                                        for key, value in request.query_params.multi_items()]))
        safe_headers = {key: '[REDACTED]' if key.lower() == 'authorization' else value
                        for key, value in request.headers.items()}
        if debug:
            # body() caches the bytes for downstream handlers; parsing form()
            # here would consume uploaded files before the route sees them.
            request_body = await request.body()
            request_logger.debug("%s %s\nHeaders: %s\nReq: %s", request.method, safe_url,
                                 safe_headers, request_body.decode("utf-8", errors="replace"))
        response = await call_next(request)
        request_logger.info("%s %s %s %.1fms", request.method, request.url.path,
                            response.status_code, (monotonic() - started) * 1000)
        if not debug:
            return response

        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        textual = (content_type.startswith("text/") or content_type in
                   ("application/json", "application/javascript", "application/xml", "application/yaml")
                   or content_type.endswith(("+json", "+xml")))
        encoded = response.headers.get("content-encoding", "identity") != "identity"
        if content_type == "text/event-stream" or not textual or encoded:
            request_logger.debug("%s %s %s\nResponse headers: %s\nResp: [%s]", request.method,
                                 safe_url, response.status_code, dict(response.headers),
                                 "SSE stream" if content_type == "text/event-stream" else "binary/encoded body")
            return response

        # Observe chunks as they are delivered. Do not rebuild the Response:
        # that would risk losing duplicate headers, cookies or background tasks.
        original_iterator = response.body_iterator

        async def log_response():
            chunks = []
            try:
                async for chunk in original_iterator:
                    chunks.append(chunk)
                    yield chunk
            finally:
                request_logger.debug("%s %s %s\nResponse headers: %s\nResp: %s", request.method,
                                     safe_url, response.status_code, dict(response.headers),
                                     b"".join(chunks).decode("utf-8", errors="replace"))

        response.body_iterator = log_response()
        return response

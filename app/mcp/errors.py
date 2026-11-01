"""Caller-facing execution errors, independent of the HTTP/MCP response envelope."""

from http import HTTPStatus
import json
import re
from typing import Any

import requests


MAX_ERROR_BODY = 4096
_CREDENTIAL_KEYS = {
    "password", "passwd", "client_secret", "access_token", "refresh_token",
    "authorization", "api_key", "apikey", "token", "secret",
}
_ASSIGNMENT = re.compile(
    r'''(?ix)(\b(?:password|passwd|client[_-]?secret|access[_-]?token|refresh[_-]?token|
    authorization|api[_-]?key|token|secret)\b["']?\s*[:=]\s*)
    (?:"[^"]*"|'[^']*'|[^\s,;&}\]]+)'''
)
_HTTP_AUTH = re.compile(r"(?i)\b(Basic|Bearer)\s+[^\s,;\"'<>]+")


def redact(value: Any) -> Any:
    """Redact common credential keys and text assignments before exposing errors."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower().replace("-", "_") in _CREDENTIAL_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _ASSIGNMENT.sub(r"\1[REDACTED]", _HTTP_AUTH.sub(r"\1 [REDACTED]", value))
    return value


class ToolExecutionError(Exception):
    def __init__(self, message: str, details: dict):
        super().__init__(message)
        self.details = details


def http_error(response: requests.Response, *, include_body: bool = True) -> ToolExecutionError:
    """Keep HTTP failure information without including request URLs or headers."""
    status = response.status_code
    try:
        reason = HTTPStatus(status).phrase
    except ValueError:
        reason = "HTTP error"
    details = {"type": "upstream_http_error", "status_code": status}
    message = f"上游接口返回 HTTP {status}"
    text = response.text
    ctype = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    is_html = ctype in ("text/html", "application/xhtml+xml") or text.lstrip().lower().startswith(("<html", "<!doctype html"))
    if is_html:
        return ToolExecutionError(f"{message}：{reason}", details)

    body = text
    if ctype == "application/json" or ctype.endswith("+json"):
        try:
            body = response.json()
        except (ValueError, RecursionError):
            pass
    try:
        body = redact(body)
        serialized = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
    except RecursionError:
        # An excessively nested body must not hide the original HTTP status.
        body = "错误响应嵌套过深"
        serialized = body

    cause = None
    if isinstance(body, dict):
        cause = next((body[key].strip() for key in ("error", "message", "detail")
                      if isinstance(body.get(key), str) and body[key].strip()), None)
    # Token endpoints expose only known message fields, never an arbitrary dump.
    if cause is None:
        cause = serialized.strip() if include_body else None
    cause = cause or reason
    if include_body:
        if len(serialized) > MAX_ERROR_BODY:
            details.update(body=serialized[:MAX_ERROR_BODY], truncated=True)
        else:
            details["body"] = body
    if len(cause) > MAX_ERROR_BODY:
        details["truncated"] = True
    return ToolExecutionError(f"{message}：{cause[:MAX_ERROR_BODY]}", details)


def request_error(exception: requests.RequestException) -> ToolExecutionError:
    """Network errors have no upstream HTTP status; raw exceptions can expose URLs."""
    if isinstance(exception, requests.Timeout):
        kind, message = "upstream_timeout", "上游接口请求超时"
    elif isinstance(exception, requests.ConnectionError):
        kind, message = "upstream_connection_error", "无法连接上游接口"
    else:
        kind, message = "upstream_request_error", "上游接口请求失败"
    return ToolExecutionError(message, {"type": kind})

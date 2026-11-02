import asyncio
import time
import httpx
import logging
import fnmatch
from typing import Dict, Any
from requests import PreparedRequest
from requests.utils import prepend_scheme_if_needed
from app.config import settings
from app.mcp.errors import http_error, request_error

log = logging.getLogger(__name__)

def _should_use_proxy(url: str) -> bool:
    """Check if the given URL should use proxy based on proxy rules"""
    if not settings.PROXY_URL or not settings.PROXY_RULES:
        return False
    
    # Split proxy rules by comma
    rules = settings.PROXY_RULES.split(',')
    
    # Check if URL matches any of the rules
    for rule in rules:
        rule = rule.strip()
        if fnmatch.fnmatch(url, rule):
            return True
    
    return False

async def execute_rest_call(method: str, url: str, headers: Dict[str, str], query: Dict[str, Any], body: Any,
                            request_timeout_seconds: float = 30) -> Any:
    """Bound the entire HTTP exchange, including redirects and the response body."""
    start_time = time.monotonic()
    log.debug(f"Send request to api: {method} {url}")

    # Preserve existing URL queries and Requests' null/list/bool query encoding
    # while using HTTPX for cancellable network I/O.
    prepared = PreparedRequest()
    prepared.prepare_url(url, query)
    
    # Prepare request parameters
    request_params = {
        "method": method.upper(),
        "url": prepared.url,
        "headers": headers,
        "json": body,
    }
    
    # Add proxy if needed
    client_options = {"timeout": None, "follow_redirects": True, "max_redirects": 30}
    if _should_use_proxy(url):
        client_options["proxy"] = prepend_scheme_if_needed(settings.PROXY_URL, "http")
        log.debug(f"Using proxy {settings.PROXY_URL} for URL: {url}")
    
    try:
        async with asyncio.timeout(request_timeout_seconds):
            async with httpx.AsyncClient(**client_options) as client:
                resp = await client.request(**request_params)
    except (TimeoutError, httpx.RequestError) as exc:
        raise request_error(exc) from exc
    elapsed_time = (time.monotonic() - start_time) * 1000
    log.debug(f"Get response from api: {method} {url} with status {resp.status_code} in {elapsed_time:.2f} ms")
    if 400 <= resp.status_code < 600:
        raise http_error(resp)
    # 自动判定 json / text
    ctype = resp.headers.get("Content-Type", "")
    if "application/json" in ctype:
        return resp.json()
    return resp.text

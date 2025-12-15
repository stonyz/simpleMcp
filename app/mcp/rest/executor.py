import requests
import logging
import fnmatch
from typing import Dict, Any
from app.config import settings

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

def execute_rest_call(method: str, url: str, headers: Dict[str, str], query: Dict[str, Any], body: Any) -> Any:
    """Execute the actual REST call and return the response"""
    import time
    start_time = time.time()
    log.debug(f"Send request to api: {method} {url}")
    
    # Prepare request parameters
    request_params = {
        "method": method.upper(),
        "url": url,
        "headers": headers,
        "params": query,
        "json": body,
        "timeout": 30
    }
    
    # Add proxy if needed
    if _should_use_proxy(url):
        request_params["proxies"] = {
            "http": settings.PROXY_URL,
            "https": settings.PROXY_URL
        }
        log.debug(f"Using proxy {settings.PROXY_URL} for URL: {url}")
    
    resp = requests.request(**request_params)
    elapsed_time = (time.time() - start_time) * 1000  # Convert to milliseconds
    log.debug(f"Get response from api: {method} {url} with status {resp.status_code} in {elapsed_time:.2f} ms")
    resp.raise_for_status()
    # 自动判定 json / text
    ctype = resp.headers.get("Content-Type", "")
    if "application/json" in ctype:
        return resp.json()
    return resp.text
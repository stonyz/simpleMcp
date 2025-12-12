import requests
import logging
from typing import Dict, Any

log = logging.getLogger(__name__)


def execute_rest_call(method: str, url: str, headers: Dict[str, str], query: Dict[str, Any], body: Any) -> Any:
    """Execute the actual REST call and return the response"""
    import time
    start_time = time.time()
    log.debug(f"Send request to api: {method} {url}")
    resp = requests.request(method.upper(), url, headers=headers, params=query, json=body, timeout=30)
    elapsed_time = (time.time() - start_time) * 1000  # Convert to milliseconds
    log.debug(f"Get response from api: {method} {url} with status {resp.status_code} in {elapsed_time:.2f} ms")
    resp.raise_for_status()
    # 自动判定 json / text
    ctype = resp.headers.get("Content-Type", "")
    if "application/json" in ctype:
        return resp.json()
    return resp.text
import requests
import logging
from typing import Dict, Any

log = logging.getLogger(__name__)


def execute_rest_call(method: str, url: str, headers: Dict[str, str], query: Dict[str, Any], body: Any) -> Any:
    """Execute the actual REST call and return the response"""
    resp = requests.request(method.upper(), url, headers=headers, params=query, json=body, timeout=30)
    resp.raise_for_status()
    # 自动判定 json / text
    ctype = resp.headers.get("Content-Type", "")
    if "application/json" in ctype:
        return resp.json()
    return resp.text
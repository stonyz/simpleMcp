import requests
import base64
import time
import logging
from typing import Dict, Any, List

log = logging.getLogger(__name__)

# Simple cache for OAuth2 tokens (in production, use Redis or similar)
_oauth_token_cache: Dict[str, Dict[str, Any]] = {}


class AuthHandler:
    """Handles different authentication methods for REST calls"""
    
    @staticmethod
    def _get_oauth2_token(token_url: str, client_id: str, client_secret: str, scopes: List[str]) -> str:
        """
        获取OAuth2客户端凭证令牌
        """
        cache_key = f"{token_url}:{client_id}:{':'.join(scopes)}"
        
        # 检查缓存中是否有有效的令牌
        if cache_key in _oauth_token_cache:
            cached = _oauth_token_cache[cache_key]
            # 如果令牌还未过期（提前5分钟刷新）
            if cached["expires_at"] > (time.time() + 300):
                return cached["access_token"]
        
        # 请求新令牌
        data = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        
        if scopes:
            data["scope"] = " ".join(scopes)
        
        try:
            response = requests.post(token_url, data=data)
            response.raise_for_status()
            token_data = response.json()
            
            access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            
            # 缓存令牌
            _oauth_token_cache[cache_key] = {
                "access_token": access_token,
                "expires_at": time.time() + expires_in
            }
            
            return access_token
        except Exception as e:
            log.error(f"Failed to get OAuth2 token: {e}")
            raise
    
    @staticmethod
    def process_auth_headers(headers: Dict[str, str], auth_info: Dict[str, Any]) -> Dict[str, str]:
        """Process authentication information and add appropriate headers"""
        final_headers = headers.copy()
        
        if not isinstance(auth_info, dict):
            return final_headers
            
        # Handle basic auth
        if "username" in auth_info and "password" in auth_info:
            # Extract username and password
            username = auth_info["username"]
            password = auth_info["password"]
            
            # Create basic auth header
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            final_headers["Authorization"] = f"Basic {credentials}"
            
        # Handle OAuth2 client credentials
        elif "client_id" in auth_info and "client_secret" in auth_info:
            # Extract OAuth2 client credentials
            client_id = auth_info["client_id"]
            client_secret = auth_info["client_secret"]
            scopes = auth_info.get("scopes", [])
            
            # Get token URL (this should ideally come from the OpenAPI spec)
            token_url = auth_info.get("token_url", "https://auth.example.com/oauth2/token")
            
            # Get access token
            access_token = AuthHandler._get_oauth2_token(token_url, client_id, client_secret, scopes)
            final_headers["Authorization"] = f"Bearer {access_token}"
            
        return final_headers
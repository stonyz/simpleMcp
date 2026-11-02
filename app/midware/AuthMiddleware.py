from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from app.config import settings
import logging

log = logging.getLogger(__name__)

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip authentication for certain paths (e.g., health checks, docs)
        skip_paths = ["/docs", "/redoc", "/openapi.json"]
        if request.url.path in skip_paths or request.url.path == "/admin" or request.url.path.startswith("/admin/"):
            return await call_next(request)
        
        # Get the Authorization header
        auth_header = request.headers.get("Authorization")
        token = None
        
        # Check if token is in Authorization header (Bearer token)
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        # Check if token is in query parameters
        elif "token" in request.query_params:
            token = request.query_params["token"]
        
        # If no token found in either place, return unauthorized
        if not token:
            log.warning(f"Unauthorized access attempt to {request.url.path} - Missing token")
            return JSONResponse(
                status_code=401,
                content={"error": "Missing token. Provide token in Authorization header or as query parameter 'token'"}
            )
        
        # Check if the token is in our valid tokens list
        valid_tokens = settings.AUTH_TOKENS
        if valid_tokens and token not in valid_tokens:
            log.warning(f"Unauthorized access attempt to {request.url.path} - Invalid token")
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or unauthorized token"}
            )
        
        # If we have no tokens configured, allow the request (backward compatibility)
        if not valid_tokens:
            log.debug("No AUTH_TOKENS configured, skipping authentication")
        
        # Proceed with the request
        response = await call_next(request)
        return response

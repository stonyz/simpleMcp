from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.concurrency import run_in_threadpool
from app.config import settings
from app.db import get_db_context
from app.credentials import authenticate
import logging

log = logging.getLogger(__name__)


def load_policy(token):
    with get_db_context() as db:
        return authenticate(db, token)

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
        policy = None
        if token not in valid_tokens:
            policy = await run_in_threadpool(load_policy, token)
        if token not in valid_tokens and policy is None:
            log.warning(f"Unauthorized access attempt to {request.url.path} - Invalid token")
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or unauthorized token"}
            )
        
        request.state.mcp_policy = policy
        request.state.is_admin = token in valid_tokens
        
        # Proceed with the request
        response = await call_next(request)
        return response

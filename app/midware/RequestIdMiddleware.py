from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import uuid
import logging
import contextvars

# Create a context variable to store the request ID
request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar('request_id')


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Generate a unique request ID
        request_id = str(uuid.uuid4())
        
        # Store the request ID in the context variable
        token = request_id_context.set(request_id)
        
        try:
            # Add the request ID to the request headers for downstream access
            request.scope['headers'] = list(request.scope['headers']) + [(b'x-request-id', request_id.encode())]
            
            # Process the request
            response: Response = await call_next(request)
            
            # Add the request ID to the response headers
            response.headers['X-Request-ID'] = request_id
            
            return response
        finally:
            # Reset the context variable to its previous state
            request_id_context.reset(token)


# Custom formatter that includes the request ID
class RequestIdFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Get the request ID from the context variable
        # Using default value of "N/A" when context is not set
        request_id = request_id_context.get("")
        
        # Add the request ID to the log record
        record.request_id = request_id
        
        # Format the log message with the request ID
        return super().format(record)
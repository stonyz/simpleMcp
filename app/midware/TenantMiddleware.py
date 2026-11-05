from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import logging
from urllib.parse import urlencode

log = logging.getLogger(__name__)

class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 检查是否已经存在tenant参数，如果存在则直接继续处理
        if 'tenant' in request.query_params:
            try:
                response = await call_next(request)
                return response
            except Exception as e:
                log.error(f"Error processing normal request: {e}")
                raise

        # Management queries require an explicit scope. Preserve the missing
        # field so FastAPI returns 422 instead of silently selecting default.
        if request.url.path.startswith('/credentials') or request.url.path in ("/services/", "/services/detail", "/services/preview", "/services/save"):
            return await call_next(request)
        
        # 检查请求路径是否匹配任何已注册的路由
        path = request.url.path
        
        # 获取应用实例来检查路由匹配
        app = request.app
        
        # 检查是否有匹配的路由
        matched_route = False
        try:
            from starlette.routing import Match
            for route in app.routes:
                match, _ = route.matches(request.scope)
                if match == Match.FULL:
                    matched_route = True
                    break
        except Exception as e:
            log.warning(f"Error checking route match: {e}")
        
        # 构造新的查询参数
        original_query_params = dict(request.query_params)
        
        # 如果没有匹配的路由，处理租户信息
        if not matched_route and path.startswith('/'):
            # 分割路径获取第一部分作为租户
            path_parts = path.strip('/').split('/', 1)
            if len(path_parts) > 0 and path_parts[0]:
                tenant = path_parts[0]
                original_query_params['tenant'] = tenant
                
                # 重构请求路径（移除租户部分）
                new_path = '/' + path_parts[1] if len(path_parts) > 1 else '/'
                
                # 更新请求的查询参数，不创建新请求对象
                request.scope['path'] = new_path
                request.scope['query_string'] = urlencode(original_query_params).encode()
                if 'raw_path' in request.scope:
                    request.scope['raw_path'] = new_path.encode('utf-8')
                
                # 更新query_params属性
                request._query_params = original_query_params
                
                log.info(f"Tenant extracted from path: {tenant}, new path: {new_path}")
        else:
            # 如果有匹配的路由，使用"default"作为租户
            original_query_params['tenant'] = 'default'
            
            # 更新请求的查询参数，不创建新请求对象
            request.scope['query_string'] = urlencode(original_query_params).encode()
            if 'raw_path' in request.scope:
                request.scope['raw_path'] = request.scope.get('raw_path', request.url.path.encode('utf-8'))
            
            # 更新query_params属性
            request._query_params = original_query_params
            
            log.info("Using default tenant for matched route")
        
        # 使用修改后的原始请求继续处理
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            log.error(f"Error processing request with tenant: {e}")
            raise

import json
from pathlib import Path
from string import Formatter
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


class ApiErrorTests(unittest.TestCase):
    def test_catalog_placeholders_match(self):
        catalog = json.loads((Path(__file__).parents[1] / 'app/error_messages.json').read_text())
        for code, translations in catalog.items():
            self.assertEqual(set(translations), {'en', 'zh'}, code)
            fields = lambda text: {name for _, name, _, _ in Formatter().parse(text) if name}
            self.assertEqual(fields(translations['en']), fields(translations['zh']), code)

    def test_route_errors_remain_english_in_both_languages(self):
        from app.errors import ApiError
        from app.common.exception_handlers import register_exception_handlers
        app = FastAPI()
        register_exception_handlers(app)
        @app.get('/test')
        def endpoint():
            raise ApiError(400, 'auth_field_required', field='client_id')
        with TestClient(app) as client:
            for language in ('zh-CN', 'en'):
                response = client.get('/test', headers={'Accept-Language': language})
                error = response.json()['error']
                self.assertEqual(response.status_code, 400)
                self.assertEqual(error['message'], 'Provide a valid client_id')
                self.assertEqual(error['code'], 'auth_field_required')
                self.assertEqual(error['params'], {'field': 'client_id'})

    def test_document_errors_have_safe_codes_and_dynamic_params(self):
        from app.errors import ApiError
        from app.service_admin import parse_document
        base = {'openapi': '3.0.0', 'info': {'title': 'API', 'version': '1'}, 'paths': {}}
        for value, code in [([], 'document_paths_required'),
                            ({**base, 'paths': {'/x': {'get': None}}}, 'document_operation_object'),
                            ({**base, 'paths': {'/x': {'get': {'summary': ['SECRET']}}}}, 'document_operation_field_string')]:
            with self.subTest(code=code), self.assertRaises(ApiError) as raised:
                parse_document(json.dumps(value), 'org', 'app')
            self.assertEqual(raised.exception.code, code)
            self.assertNotIn('SECRET', raised.exception.detail)
        self.assertEqual(raised.exception.params, {'method': 'get', 'path': '/x', 'field': 'summary'})
        with self.assertRaises(ApiError) as malformed:
            parse_document('secret: [PASSWORD', 'org', 'app')
        self.assertEqual(malformed.exception.code, 'document_invalid')
        self.assertNotIn('PASSWORD', malformed.exception.detail)

    def test_stored_document_exposes_translation_metadata(self):
        from app.service_admin import document_view
        row = SimpleNamespace(openapi_yaml='[', tenant='one', orgid='org', appid='app', fileId='id', fileName='api', title='API', version='1', create_at=None, update_at=None, auth=None)
        result = document_view(row, SimpleNamespace())
        self.assertEqual(result['error_code'], 'stored_document_invalid')
        self.assertEqual(result['error_params'], {})
        self.assertTrue(result['error'].isascii())

    def test_legacy_parser_and_middleware_keep_shapes_without_input(self):
        from app.errors import ApiError
        from app.routers.services import parse_yaml_string, parse_file_content
        from app.midware.AuthMiddleware import AuthMiddleware
        for parse, args in [(parse_yaml_string, ('password: [SECRET',)), (parse_file_content, ('x.json', b'{SECRET'))]:
            with self.assertRaises(ApiError) as raised:
                parse(*args)
            self.assertNotIn('SECRET', raised.exception.detail)
        app = FastAPI()
        app.add_middleware(AuthMiddleware)
        app.get('/test')(lambda: {})
        with TestClient(app) as client, patch('app.midware.AuthMiddleware.settings.AUTH_TOKENS', ['valid']), patch('app.midware.AuthMiddleware.load_policy', return_value=None):
            for headers, code in [({}, 'missing_token'), ({'Authorization': 'Bearer invalid'}, 'invalid_token')]:
                response = client.get('/test', headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertIsInstance(response.json()['error'], str)
                self.assertEqual(response.json()['code'], code)
                self.assertEqual(response.json()['params'], {})

    def test_validation_diagnostics_omit_secrets(self):
        from app.common.exception_handlers import register_exception_handlers
        from app.service_admin import ServiceInput
        app = FastAPI()
        register_exception_handlers(app)
        @app.post('/test')
        def endpoint(body: ServiceInput):
            return {}
        with TestClient(app) as client:
            response = client.post('/test', json={'org': 'SECRET INPUT', 'app': 'a', 'fileName': 'a', 'yaml_content': 'SECRET CONTENT', 'auth': {'secret': 'SECRET CREDENTIAL'}})
        error = response.json()['error']
        self.assertEqual(error['code'], 'validation_error')
        self.assertNotIn('SECRET', response.text)
        self.assertTrue(all(set(detail) <= {'type', 'loc', 'msg', 'code', 'params'} for detail in error['details']))

    def test_management_routes_return_catalog_errors(self):
        from contextlib import nullcontext
        from app.common.exception_handlers import register_exception_handlers
        from app.routers.services import router as services_router
        from app.routers.tenants import router as tenants_router
        app = FastAPI()
        app.include_router(services_router, prefix='/services')
        app.include_router(tenants_router, prefix='/tenants')
        register_exception_handlers(app)
        db = SimpleNamespace(get=lambda *args: None)
        with TestClient(app) as client, patch('app.routers.services.get_db_context', side_effect=lambda: nullcontext(db)), patch('app.routers.tenants.get_db_context', side_effect=lambda: nullcontext(db)):
            for language in ('en', 'zh-CN'):
                headers = {'Accept-Language': language}
                response = client.get('/tenants/missing', headers=headers)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()['error']['code'], 'tenant_not_found')
                self.assertTrue(response.json()['error']['message'].isascii())
                response = client.post('/services/preview?tenant=one', headers=headers, json={'org':'org', 'app':'app', 'fileName':'api.yaml', 'yaml_content':'[]'})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error']['code'], 'document_paths_required')
                response = client.post('/services/register?tenant=one', headers=headers, json={'org':'org', 'app':'app', 'fileName':'api.yaml', 'yaml_content':'secret: [SECRET'})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error']['code'], 'document_yaml_invalid')
                self.assertNotIn('SECRET', response.text)
                response = client.get('/services/?tenant=invalid/value', headers=headers)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()['error']['params'], {'field':'tenant', 'limit':63})

    def test_custom_validator_errors_keep_semantic_codes(self):
        from app.access import AccessRule
        from app.credentials import CredentialInput
        from app.tenants import TenantUpdate
        from app.service_admin import ServiceInput
        from app.common.exception_handlers import register_exception_handlers
        app = FastAPI()
        register_exception_handlers(app)
        @app.post('/tenant')
        def tenant(body: TenantUpdate):
            return {}
        @app.post('/service')
        def service(body: ServiceInput):
            return {}
        @app.post('/credential')
        def credential(body: CredentialInput):
            return {}
        @app.post('/rule')
        def rule(body: AccessRule):
            return {}
        service_body = {'org': 'org', 'app': 'app', 'fileName': 'api', 'yaml_content': 'SECRET CONTENT', 'auth': 'SECRET AUTH'}
        cases = [('/tenant', {'name': '   '}, 'name_blank', {}),
                 ('/service', {**service_body, 'fileName': '   '}, 'value_blank', {}),
                 ('/service', {**service_body, 'org': 'SECRET INPUT'}, 'identifier_invalid', {'field': 'org', 'limit': 64}),
                 ('/credential', {'name': '   ', 'rules': [{'tenant': 'one'}]}, 'name_blank', {}),
                 ('/credential', {'name': 'name', 'expires_at': '2030-01-01T00:00:00', 'rules': [{'tenant': 'one'}]}, 'expiry_timezone_required', {}),
                 ('/rule', {'tenant': 'one', 'org': 'org', 'app': 'app', 'services': ['']}, 'service_id_invalid', {}),
                 ('/rule', {'tenant': 'one', 'app': 'app'}, 'app_scope_org_required', {}),
                 ('/rule', {'tenant': 'one', 'services': ['id']}, 'service_scope_required', {})]
        with TestClient(app) as client:
            for route, body, code, params in cases:
                with self.subTest(code=code, route=route):
                    response = client.post(route, json=body)
                    self.assertEqual(response.status_code, 422)
                    diagnostic = response.json()['error']['details'][0]
                    self.assertEqual(diagnostic['type'], code)
                    self.assertEqual(diagnostic['code'], code)
                    self.assertEqual(diagnostic['params'], params)
                    self.assertNotEqual(diagnostic['msg'], 'Invalid value')
                    self.assertNotIn('SECRET', response.text)

    def test_validation_context_only_exposes_known_formatting_params(self):
        from fastapi.exceptions import RequestValidationError
        from app.common.exception_handlers import register_exception_handlers
        app = FastAPI()
        register_exception_handlers(app)
        @app.get('/test')
        def endpoint():
            raise RequestValidationError([{'type': 'identifier_invalid', 'loc': ('body', 'org'), 'msg': 'Invalid org', 'input': 'SECRET INPUT', 'ctx': {'field': 'org', 'limit': 64, 'credential': 'SECRET CREDENTIAL', 'error': ValueError('SECRET ERROR')}}])
        with TestClient(app) as client:
            response = client.get('/test')
        diagnostic = response.json()['error']['details'][0]
        self.assertEqual(diagnostic['params'], {'field': 'org', 'limit': 64})
        self.assertNotIn('SECRET', response.text)

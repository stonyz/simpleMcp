import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import settings
from app.midware.AuthMiddleware import AuthMiddleware
from app.midware.TenantMiddleware import TenantMiddleware
from app.routers import mcp, services, functions
import test_openapi_registration as registration


class CredentialTests(unittest.TestCase):
    setUp = registration.OpenAPIRegistrationTests.setUp
    register = registration.OpenAPIRegistrationTests.register

    def protected(self):
        from app.routers.credentials import router
        self.enterContext(patch.object(settings, 'AUTH_TOKENS', ['root']))
        self.enterContext(patch('app.midware.AuthMiddleware.get_db_context', self.database))
        self.enterContext(patch('app.routers.credentials.get_db_context', self.database))
        self.enterContext(patch('app.routers.mcp.tenant_manager', self.manager))
        self.enterContext(patch('app.routers.functions.tenant_manager', self.manager))
        app = FastAPI()
        app.add_middleware(TenantMiddleware)
        app.add_middleware(AuthMiddleware)
        for prefix, component in [('credentials', router), ('services', services.router),
                                   ('mcp', mcp.router), ('functions', functions.router)]:
            app.include_router(component, prefix='/' + prefix)
        return self.enterContext(TestClient(app))

    def create(self, client, rules, **extra):
        response = client.post('/credentials/', headers={'Authorization': 'Bearer root'},
                               json={'name': 'Partner', 'rules': rules, **extra})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def rpc(self, client, secret, method='tools/list', params=None, tenant='one', headers=None):
        return client.post(f'/mcp?tenant={tenant}', headers={
            'Authorization': f'Bearer {secret}', **(headers or {})}, json={
            'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})

    def names(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return {t['name'] for t in response.json()['result']['tools']}

    def seed(self):
        self.register('first', file_id='first')
        self.register('second', file_id='second')
        self.register('other_app', app='other')
        self.register('other_org', org='other')
        self.register('other_tenant', tenant='two')

    def test_hierarchy_filters_without_extra_client_scope(self):
        self.seed()
        client = self.protected()
        for rule, expected in [
            ({'tenant': 'one'}, {'first', 'second', 'other_app', 'other_org'}),
            ({'tenant': 'one', 'org': 'org'}, {'first', 'second', 'other_app'}),
            ({'tenant': 'one', 'org': 'org', 'app': 'app'}, {'first', 'second'}),
            ({'tenant': 'one', 'org': 'org', 'app': 'app', 'services': ['first']}, {'first'}),
        ]:
            item = self.create(client, [rule])
            self.assertEqual(self.names(self.rpc(client, item['secret'])), expected)
            self.assertEqual(self.rpc(client, item['secret'], tenant='two').status_code, 403)

    def test_union_operations_and_list_aliases(self):
        self.seed()
        client = self.protected()
        secret = self.create(client, [
            {'tenant': 'one', 'org': 'org', 'app': 'app', 'services': ['first'], 'operations': ['list']},
            {'tenant': 'one', 'org': 'other', 'operations': ['call']},
            {'tenant': 'two', 'operations': ['list']},
        ])['secret']
        for method in ['tools/list', 'list_tools']:
            self.assertEqual(self.names(self.rpc(client, secret, method)), {'first'})
        self.assertEqual(self.names(self.rpc(client, secret, tenant='two')), {'other_tenant'})
        for path in ['/mcp/list?tenant=one', '/functions/?tenant=one&orgid=org&appid=app']:
            response = client.get(path, headers={'Authorization': f'Bearer {secret}'})
            self.assertEqual({t['name'] for t in response.json()}, {'first'})
        self.assertEqual(self.rpc(client, secret, 'tools/call', {'name': 'first'}).status_code, 403)

    def test_actual_owner_and_header_override_checked_on_all_call_routes(self):
        self.seed()
        client = self.protected()
        secret = self.create(client, [{'tenant': 'one', 'org': 'org', 'app': 'app', 'services': ['first']}])['secret']
        async def execute(metadata, **arguments):
            return None, {'fileId': metadata['fileId']}
        with patch('app.mcp.tenant_manager.execute_tool', execute):
            allowed = self.rpc(client, secret, 'tools/call', {'name': 'first'})
            self.assertEqual(allowed.json()['result']['_meta']['fileId'], 'first')
            for method in ['tools/call', 'call_tool']:
                self.assertEqual(self.rpc(client, secret, method, {'name': 'second'}).status_code, 403)
            denied = self.rpc(client, secret, 'tools/call', {'name': 'first', 'orgid': 'other'},
                              headers={'X-Org-ID': 'org', 'X-App-ID': 'app'})
            self.assertEqual(denied.status_code, 403)
            legacy = client.post('/mcp/call?tenant=one', headers={'Authorization': f'Bearer {secret}'},
                                 json={'function_name': 'second', 'parameters': {}})
            self.assertEqual(legacy.status_code, 403)

    def test_same_name_resolves_only_authorized_candidate(self):
        self.register('shared', file_id='visible')
        self.register('shared', org='other', file_id='hidden')
        client = self.protected()
        secret = self.create(client, [{'tenant': 'one', 'org': 'org'}])['secret']
        async def execute(metadata, **arguments):
            return None, {'owner': metadata['orgid']}
        with patch('app.mcp.tenant_manager.execute_tool', execute):
            response = self.rpc(client, secret, 'tools/call', {'name': 'shared'})
            self.assertEqual(response.json()['result']['_meta']['orgid'], 'org')

    def test_hash_only_lifecycle_and_immediate_changes(self):
        from app.db.models import MCPCredential
        self.seed()
        client = self.protected()
        item = self.create(client, [{'tenant': 'one'}])
        secret, identity = item['secret'], item['id']
        admin = {'Authorization': 'Bearer root'}
        with self.database() as db:
            row = db.get(MCPCredential, identity)
            self.assertNotIn(secret, str(row.__dict__))
            self.assertEqual(len(row.token_hash), 64)
        listing = client.get('/credentials/', headers=admin)
        self.assertNotIn(secret, listing.text)
        self.assertNotIn('token_hash', listing.text)
        self.assertEqual(self.rpc(client, secret).status_code, 200)
        update = {'name': 'Changed', 'rules': [{'tenant': 'one', 'org': 'other'}], 'enabled': True}
        self.assertEqual(client.put(f'/credentials/{identity}', headers=admin, json=update).status_code, 200)
        self.assertEqual(self.names(self.rpc(client, secret)), {'other_org'})
        client.put(f'/credentials/{identity}', headers=admin, json={**update, 'enabled': False})
        self.assertEqual(self.rpc(client, secret).status_code, 401)
        client.put(f'/credentials/{identity}', headers=admin, json=update)
        rotated = client.post(f'/credentials/{identity}/rotate', headers=admin)
        self.assertEqual(rotated.status_code, 200, rotated.text)
        self.assertEqual(self.rpc(client, secret).status_code, 401)
        self.assertEqual(self.rpc(client, rotated.json()['secret']).status_code, 200)
        expires = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        client.put(f'/credentials/{identity}', headers=admin, json={**update, 'expires_at': expires})
        self.assertEqual(self.rpc(client, rotated.json()['secret']).status_code, 401)

    def test_mcp_token_cannot_manage_or_login(self):
        client = self.protected()
        secret = self.create(client, [{'tenant': 'one'}])['secret']
        headers = {'Authorization': f'Bearer {secret}'}
        for path in ['/services/access?tenant=one', '/services/?tenant=one', '/credentials/', '/credentials/catalog']:
            self.assertEqual(client.get(path, headers=headers).status_code, 403)
        self.assertEqual(client.post('/credentials/', headers=headers, json={'name': 'bad', 'rules': []}).status_code, 403)

    def test_disable_works_after_a_selected_service_is_deleted(self):
        self.seed()
        client = self.protected()
        item = self.create(client, [{'tenant': 'one', 'org': 'org', 'app': 'app', 'services': ['first']}])
        self.client.delete('/services/delete?tenant=one&org=org&app=app&fileId=first')
        response = client.patch(f"/credentials/{item['id']}/status", headers={'Authorization': 'Bearer root'}, json={'enabled': False})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.rpc(client, item['secret']).status_code, 401)

    def test_invalid_rules_and_unknown_token_fail_closed(self):
        client = self.protected()
        for rule in [{'tenant': 'one', 'app': 'app'}, {'tenant': 'one', 'services': ['first']},
                     {'tenant': 'one', 'org': 'org', 'app': 'app', 'services': []},
                     {'tenant': 'one', 'org': 'org', 'app': 'app', 'services': ['missing']},
                     {'tenant': 'one', 'orgid': 'wrong'}, {'tenant': 'bad tenant'},
                     {'tenant': 'one', 'operations': []}]:
            response = client.post('/credentials/', headers={'Authorization': 'Bearer root'},
                                   json={'name': 'invalid', 'rules': [rule]})
            self.assertIn(response.status_code, (400, 422), response.text)
        with patch.object(settings, 'AUTH_TOKENS', []):
            self.assertEqual(self.rpc(client, 'unknown').status_code, 401)

    def test_call_only_still_validates_output(self):
        data = registration.specification('typed')
        data['paths']['/typed']['get']['responses'] = {'200': {'description': 'ok', 'content': {
            'application/json': {'schema': {'type': 'object', 'required': ['count'],
                                           'properties': {'count': {'type': 'integer'}}}}}}}
        self.client.post('/services/register?tenant=one', json={'org': 'org', 'app': 'app', 'fileId': 'typed',
                          'fileName': 'api.yaml', 'yaml_content': json.dumps(data)})
        client = self.protected()
        secret = self.create(client, [{'tenant': 'one', 'operations': ['call']}])['secret']
        self.assertEqual(self.names(self.rpc(client, secret)), set())
        async def execute(metadata, **arguments):
            return None, {'count': 'wrong'}
        with patch('app.mcp.tenant_manager.execute_tool', execute):
            response = self.rpc(client, secret, 'tools/call', {'name': 'typed'})
            self.assertTrue(response.json()['result']['isError'], response.text)

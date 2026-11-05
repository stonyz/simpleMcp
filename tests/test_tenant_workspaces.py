import unittest
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.midware.AuthMiddleware import AuthMiddleware
from app.midware.TenantMiddleware import TenantMiddleware
from app.routers import credentials, services
import test_openapi_registration as registration


class TenantWorkspaceTests(unittest.TestCase):
    setUp = registration.OpenAPIRegistrationTests.setUp
    register = registration.OpenAPIRegistrationTests.register
    admin = {'Authorization': 'Bearer root'}

    def protected(self):
        from app.routers.tenants import router
        self.enterContext(patch.object(settings, 'AUTH_TOKENS', ['root']))
        for module in ['app.routers.tenants', 'app.routers.credentials', 'app.midware.AuthMiddleware']:
            self.enterContext(patch(module + '.get_db_context', self.database))
        app = FastAPI()
        app.add_middleware(TenantMiddleware)
        app.add_middleware(AuthMiddleware)
        app.include_router(router, prefix='/tenants')
        app.include_router(credentials.router, prefix='/credentials')
        app.include_router(services.router, prefix='/services')
        return self.enterContext(TestClient(app))

    def create(self, client, tenant, name=None):
        response = client.post('/tenants/', headers=self.admin, json={'id': tenant, 'name': name or tenant})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def token(self, client, tenant):
        response = client.post('/credentials/', params={'tenant': tenant}, headers=self.admin,
                               json={'name': 'test', 'rules': [{'tenant': tenant}]})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_create_edit_and_delete_empty_tenant(self):
        client = self.protected()
        self.create(client, 'alpha', 'Alpha Team')
        self.assertEqual(client.get('/tenants/alpha', headers=self.admin).json()['name'], 'Alpha Team')
        renamed = client.put('/tenants/alpha', headers=self.admin, json={'name': 'New name', 'description': 'team'})
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()['id'], 'alpha')
        self.assertEqual(renamed.json()['name'], 'New name')
        invalid = client.put('/tenants/alpha', headers=self.admin, json={'id': 'beta', 'name': 'Other'})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(client.delete('/tenants/alpha', headers=self.admin).status_code, 200)
        self.assertEqual(client.get('/tenants/alpha', headers=self.admin).status_code, 404)

    def test_legacy_service_tenants_are_registered_and_cannot_be_deleted(self):
        self.register('first', tenant='existing')
        client = self.protected()
        listing = client.get('/tenants/', headers=self.admin)
        self.assertEqual(listing.status_code, 200, listing.text)
        row = next(item for item in listing.json()['items'] if item['id'] == 'existing')
        self.assertEqual(row['service_count'], 1)
        self.assertEqual(client.delete('/tenants/existing', headers=self.admin).status_code, 409)

    def test_credential_list_catalog_and_all_mutations_are_tenant_scoped(self):
        self.register('one', tenant='one')
        self.register('two', tenant='two')
        client = self.protected()
        first, second = self.token(client, 'one'), self.token(client, 'two')
        listing = client.get('/credentials/?tenant=one', headers=self.admin).json()['items']
        self.assertEqual([item['id'] for item in listing], [first['id']])
        catalog = client.get('/credentials/catalog?tenant=one', headers=self.admin).json()['services']
        self.assertEqual({item['tenant'] for item in catalog}, {'one'})
        for method, suffix, body in [('put', '', {'name': 'changed', 'rules': [{'tenant': 'one'}]}),
                                     ('post', '/rotate', None), ('patch', '/status', {'enabled': False}),
                                     ('delete', '', None)]:
            response = client.request(method, f"/credentials/{second['id']}{suffix}?tenant=one", headers=self.admin, json=body)
            self.assertEqual(response.status_code, 404, response.text)
        foreign = client.post('/credentials/?tenant=one', headers=self.admin,
                              json={'name': 'bad', 'rules': [{'tenant': 'two'}]})
        self.assertEqual(foreign.status_code, 403)
        updated = client.put(f"/credentials/{first['id']}?tenant=one", headers=self.admin,
                             json={'name': 'bad', 'rules': [{'tenant': 'two'}]})
        self.assertEqual(updated.status_code, 403)
        self.assertEqual(client.get('/credentials/?tenant=two', headers=self.admin).json()['items'][0]['enabled'], True)

    def test_missing_scope_does_not_default_and_token_cannot_manage_tenants(self):
        client = self.protected()
        self.create(client, 'one')
        item = self.token(client, 'one')
        for path in ['/credentials/', '/credentials/catalog']:
            self.assertEqual(client.get(path, headers=self.admin).status_code, 422)
        self.assertEqual(client.get('/tenants/', headers={'Authorization': 'Bearer ' + item['secret']}).status_code, 403)
        self.assertEqual(client.delete('/tenants/one', headers=self.admin).status_code, 409)

    def test_duplicate_and_invalid_tenant_identifiers(self):
        client = self.protected()
        self.create(client, 'one')
        self.assertEqual(client.post('/tenants/', headers=self.admin, json={'id': 'one', 'name': 'dup'}).status_code, 409)
        for identity in [' ', 'a/b', 'x' * 64, '.', '..']:
            self.assertEqual(client.post('/tenants/', headers=self.admin, json={'id': identity, 'name': 'bad'}).status_code, 422)

    def test_legacy_cross_tenant_token_cannot_be_mutated_from_a_workspace(self):
        from app.credentials import CredentialInput, save_credential, authenticate
        with self.database() as db:
            legacy = save_credential(db, CredentialInput(name='legacy', rules=[{'tenant': 'one'}, {'tenant': 'two'}]))
        client = self.protected()
        for tenant in ['one', 'two']:
            response = client.get('/credentials/', params={'tenant': tenant}, headers=self.admin)
            self.assertEqual(response.json()['items'], [])
            response = client.patch(f"/credentials/{legacy['id']}/status?tenant={tenant}", headers=self.admin, json={'enabled': False})
            self.assertEqual(response.status_code, 404)
        with self.database() as db:
            policy = authenticate(db, legacy['secret'])
            self.assertEqual({rule.tenant for rule in policy.rules}, {'one', 'two'})

    def test_startup_import_preserves_existing_display_names(self):
        from app.tenants import sync_tenants, get_tenant
        self.register('legacy', tenant='old')
        with self.database() as db:
            row = get_tenant(db, 'old')
            row.name = 'Custom name'
            sync_tenants(db)
            self.assertEqual(get_tenant(db, 'old').name, 'Custom name')

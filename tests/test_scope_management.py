import unittest

from app.mcp.registry import MCPRegistry
from app.mcp.tenant_manager import TenantManager


class RegistryScopeTests(unittest.TestCase):
    def setUp(self):
        self.registry = MCPRegistry()
        self.registry.register_function('shared', {'owner': 'a'}, {}, 'org-a', 'app-a')
        self.registry.register_function('shared', {'owner': 'b'}, {}, 'org-b', 'app-b')

    def test_partial_scope_is_applied(self):
        self.assertEqual(self.registry.get_tool_metadata('shared', orgid='org-b'), {'owner': 'b'})
        self.assertEqual(self.registry.get_tool_metadata('shared', appid='app-b'), {'owner': 'b'})
        self.assertIsNone(self.registry.get_tool_metadata('shared', orgid='missing'))

    def test_ambiguous_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            self.registry.get_tool_metadata('shared')

    def test_read_unknown_tenant_does_not_create_registry(self):
        manager = TenantManager()
        self.assertEqual(manager.list_functions('missing'), [])
        self.assertEqual(manager.tenant_registries, {})

"""Catch newly introduced fixed Chinese wire messages without touching user data."""
import ast
import json
from pathlib import Path
import re
import unittest

HAN = re.compile(r'[\u3400-\u9fff\uf900-\ufaff]')


class ResponseLanguageAuditTests(unittest.TestCase):
    def test_python_runtime_literals_are_english(self):
        root = Path(__file__).parents[1] / 'app'
        failures = []
        for path in root.rglob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.body and isinstance(node.body[0], ast.Expr):
                        value = node.body[0].value
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            docstrings.add(id(value))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings and HAN.search(node.value):
                    failures.append(f'{path.relative_to(root)}:{node.lineno}: {node.value}')
        self.assertEqual(failures, [], 'Fixed messages belong in the bilingual catalog, with English API output')

    def test_public_openapi_documentation_is_english(self):
        from fastapi import FastAPI
        from app.routers import services, tenants, credentials, mcp, functions, test_exceptions
        app = FastAPI()
        for module in (services, tenants, credentials, mcp, functions, test_exceptions):
            app.include_router(module.router, prefix='/' + module.__name__.split('.')[-1])
        self.assertIsNone(HAN.search(json.dumps(app.openapi(), ensure_ascii=False)))

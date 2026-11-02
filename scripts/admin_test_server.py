"""Isolated browser-test server. Never opens the developer's database."""
import os
import tempfile

with tempfile.TemporaryDirectory(prefix="mcp-admin-e2e-") as directory:
    os.environ["DATABASE_URL"] = f"sqlite:///{directory}/test.db"
    os.environ["AUTH_TOKENS"] = '["admin-e2e-token"]'
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8017, log_level="warning")

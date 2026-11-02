"""Serve the built management UI without requiring a Node runtime."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles


def mount_admin(app: FastAPI, directory: Path | None = None):
    directory = directory or Path(__file__).resolve().parents[1] / "web" / "dist"

    @app.get("/admin", include_in_schema=False)
    def admin_redirect():
        return RedirectResponse("/admin/")

    if directory.is_dir():
        app.mount("/admin", StaticFiles(directory=directory, html=True), name="admin")
    else:
        # Reserve the whole prefix even before a build exists. Otherwise the
        # tenant middleware could rewrite an exempt /admin/services/* request.
        fallback = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

        @fallback.get("/", include_in_schema=False)
        def admin_not_built():
            return HTMLResponse(
                '<html lang="zh-CN"><meta charset="utf-8"><title>管理台尚未构建</title>'
                '<h1>管理台尚未构建</h1><p>请在 web 目录执行 npm ci 和 npm run build，'
                '然后重启 FastAPI。Docker 构建会自动完成此步骤。</p></html>', status_code=503,
            )
        app.mount("/admin", fallback, name="admin")

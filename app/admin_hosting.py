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
                '<html lang="en"><meta charset="utf-8"><title>Admin UI has not been built</title>'
                '<h1>Admin UI has not been built</h1><p>Run npm ci and npm run build in the web directory, '
                'then restart FastAPI. Docker builds complete this step automatically.</p></html>', status_code=503,
            )
        app.mount("/admin", fallback, name="admin")

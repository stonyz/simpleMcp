# SimpleMCP

**Turn existing OpenAPI APIs into MCP tools, with a visual console to manage them.**

English | [简体中文](README.zh-CN.md) · [GitHub](https://github.com/stonyz/simpleMcp)

SimpleMCP is a self-hosted OpenAPI-to-MCP gateway. Register an API specification, make its operations available as tools, and connect your AI clients through one HTTP endpoint. Manage services, tenant workspaces and client permissions from the built-in web console, without writing a separate MCP server for each API.

```text
Existing REST APIs → OpenAPI documents → SimpleMCP → MCP clients / AI assistants
                                           │
                              Web console · Workspaces · Access rules
```

## Why SimpleMCP?

- **Reuse your APIs.** Import YAML or JSON OpenAPI documents and turn operations into callable tools. Registered documents persist in SQLite and reload on startup.
- **Manage services visually.** Upload or paste specifications, edit with Monaco, preview tool additions/removals, inspect input/output schemas, export documents and copy client connection examples.
- **Keep teams organized.** Tenant workspaces isolate services and client credentials; organize APIs further by organization and application.
- **Control what each client can access.** Grant access to a tenant, organization, application or selected service documents. Set tool discovery and execution permissions independently; disable, expire or rotate tokens from the console.
- **Connect authenticated upstream APIs.** Configure Bearer, HTTP Basic or OAuth2 Client Credentials in dedicated forms. Calls can also provide upstream credentials through `arguments.auth`.
- **Expose structured tools over HTTP.** MCP JSON-RPC supports initialization, ping, tool discovery and execution, with structured results and schema validation. Operations can define individual timeout budgets.
- **Deploy as one service.** Docker builds the UI and backend into one image, served on one port. SQLite requires no separate database server. The console supports English and Simplified Chinese and loads its editor locally without a CDN.

## See it in action

Actual console screenshots with demonstration data. The sample APIs use `api.example.com`; no production services or real credentials are shown. The console language can be switched between English and Chinese.

### Service management

Search and filter APIs by organization/application, see registered tool counts, and manage document versions in one workspace.

![SimpleMCP service management console](docs/images/service-management.png)

### Tools at a glance

Inspect the tools declared by an OpenAPI document, their active registration status, input/output schemas and client connection configuration. Registration status does not indicate upstream availability.

![SimpleMCP service details and tool list](docs/images/service-tools.png)

### Tenant workspaces

Choose a workspace before managing its services and credentials. Create tenants and edit their names and descriptions from this page.

![SimpleMCP tenant workspace selection](docs/images/tenant-workspaces.png)

### Client access credentials

Manage tokens and their authorization rules, with separate controls for tool listing and calling.

![SimpleMCP client credential management](docs/images/access-credentials.png)

## Quick start

### Docker Compose

```bash
git clone https://github.com/stonyz/simpleMcp.git
cd simpleMcp
cp .env.example .env
```

Edit `.env` before starting:

```dotenv
APP_NAME=SimpleMCP
AUTH_TOKENS=["replace-with-a-long-random-admin-token"]
ADMIN_MCP_ENABLED=false
PROXY_URL=
PROXY_RULES=
DEBUG=false
log_level=INFO
```

Use your own administrator token. Set `PROXY_URL` and `PROXY_RULES` only if you need an outbound proxy; the example file includes sample proxy values.

```bash
docker compose up -d --build
```

Open **[http://localhost:8000/admin/](http://localhost:8000/admin/)** and sign in with the administrator token from `AUTH_TOKENS`.

1. Create or select a tenant workspace.
2. Click **Register service**, choose an organization and application, then upload or paste an OpenAPI YAML/JSON document.
3. Configure upstream authorization if needed, validate the tool preview, and save.
4. Open **Access credentials**, create a client token and choose its allowed services and operations. Copy the secret when it is displayed; creation and rotation show it only once.
5. Use the client token and the workspace's tenant ID to connect an MCP client.

Compose serves both UI and API on port `8000`. The database persists in `./data`, and logs in `./logs`. Check status with `docker compose ps` and logs with `docker compose logs --tail=100 -f simpleMcp`. After updating the source, run `docker compose up -d --build` again.

### Run from source

Requires Python 3.12+, Poetry, and Node.js 22.12+ or 24 LTS for the UI build.

```bash
git clone https://github.com/stonyz/simpleMcp.git
cd simpleMcp
python3.12 -m venv .venv
poetry env use .venv/bin/python
poetry install
cp .env.example .env
# Edit .env as described above.
cd web
npm ci
npm run build
cd ..
poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Build the frontend before starting the backend so that `/admin/` is mounted. For frontend development, start the backend at `127.0.0.1:8000`, then run `npm run dev` inside `web/` and open `/admin/` on the Vite URL.

## Connect an MCP client

The MCP endpoint is `POST /mcp?tenant=<tenant-id>`. Use a **client token created in the console**. Administrator tokens are for management; MCP access is disabled for them by default.

For clients accepting an HTTP `mcpServers` configuration:

```json
{
  "mcpServers": {
    "SimpleMCP": {
      "type": "http",
      "url": "http://localhost:8000/mcp?tenant=default",
      "headers": {
        "Authorization": "Bearer YOUR_MCP_CLIENT_TOKEN"
      }
    }
  }
}
```

Replace `default` with your tenant ID. Configuration format depends on the client. Add `X-Org-ID` and `X-App-ID` headers to narrow discovery and resolve duplicate tool names across applications; these filters never expand the token's permissions.

The endpoint supports MCP protocol versions `2025-06-18` and `2025-11-25`. It is stateless HTTP JSON-RPC, with no session ID or persistent cancellation state.

### Try the API directly

Register a local OpenAPI document using an administrator token:

```bash
export SIMPLEMCP_ADMIN_TOKEN='YOUR_ADMIN_TOKEN'
curl -X POST 'http://localhost:8000/services/register-form?tenant=default' \
  -H "Authorization: Bearer $SIMPLEMCP_ADMIN_TOKEN" \
  -F 'org=demo' \
  -F 'app=example' \
  -F 'fileId=example-api' \
  -F 'fileName=openapi.yaml' \
  -F 'file=@./openapi.yaml'
```

Create a client credential in the console granting access to that service, then initialize and discover tools:

```bash
export SIMPLEMCP_CLIENT_TOKEN='YOUR_MCP_CLIENT_TOKEN'
curl -X POST 'http://localhost:8000/mcp?tenant=default' \
  -H "Authorization: Bearer $SIMPLEMCP_CLIENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"demo","version":"1.0"}}}'

curl -X POST 'http://localhost:8000/mcp?tenant=default' \
  -H "Authorization: Bearer $SIMPLEMCP_CLIENT_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'MCP-Protocol-Version: 2025-11-25' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{"orgid":"demo","appid":"example"}}'
```

Call a returned tool using `tools/call` with `params: {"name":"<tool-name>","arguments":{...},"orgid":"demo","appid":"example"}`. Replace the tool name and arguments with those declared by your document.

## Configuration and behavior

| Setting | Purpose |
| --- | --- |
| `AUTH_TOKENS` | JSON array of administrator tokens for the console and management APIs |
| `ADMIN_MCP_ENABLED` | Explicitly allow administrator MCP access; defaults to `false` |
| `DATABASE_URL` | Local default: `sqlite:///./data/mcp.db`; Compose uses `sqlite:////app/data/mcp.db` |
| `API_TOKEN` | Optional default Bearer token for upstream APIs |
| `PROXY_URL`, `PROXY_RULES` | Optional outbound proxy and URL matching rules |
| `APP_NAME` | Backend application title; set to `SimpleMCP` |
| `log_level` | `INFO` for request summaries; `DEBUG` also records request/response details |

- **Two credential layers:** MCP client tokens authorize access to SimpleMCP; upstream credentials authorize calls to your APIs. Database client tokens cannot administer services or sign in to the console. Only token digests and display prefixes are stored.
- **Service identity:** `tenant + org + app + fileId`. Reuse this identity to update a document; omitted `fileId` creates a new document. Console validation rejects tool names that conflict with another document; the legacy registration API retains its existing overwrite behavior.
- **Authorization:** Bearer, Basic and OAuth2 Client Credentials can be kept, replaced or cleared when editing a service. Stored upstream secrets are not returned to the console. OAuth2 access tokens are obtained and cached before upstream calls.
- **Timeouts:** Set `x-request-timeout-seconds` on an OpenAPI operation. Positive finite numbers are supported; the default is 30 seconds. The budget covers the upstream HTTP exchange, not OAuth token acquisition or client/proxy timeouts. Timeout errors do not trigger automatic retries.
- **Outputs and errors:** Object results use `structuredContent` and JSON text. Non-object schemas use an object wrapper with a `data` field. Execution errors expose structured details and request IDs; management errors have stable codes for console localization.
- **Logs and backups:** Authorization headers and token query parameters are redacted. DEBUG bodies outside credential management may still contain upstream secrets. Back up `./data` while the service is stopped to preserve both services and client permissions.

## API overview

| Endpoint | Purpose |
| --- | --- |
| `POST /mcp?tenant=…` | MCP initialization, ping, `tools/list`, `tools/call` |
| `GET /mcp/list?tenant=…`, `POST /mcp/call?tenant=…` | REST compatibility interfaces |
| `GET /functions/?tenant=…&orgid=…&appid=…` | List registered functions |
| `POST /services/register?tenant=…` | Register or update a document with a JSON body |
| `POST /services/register-form?tenant=…` | Register using form fields or a file upload |
| `DELETE /services/delete?tenant=…&org=…&app=…&fileId=…` | Delete a document and its tools |
| `/tenants/`, `/credentials/?tenant=…` | Administrator tenant and credential management |

See the [technical reference](docs/reference.md) for detailed authentication payloads, isolation rules, protocol behavior and execution errors. The API schema is available at `/openapi.json`.

## Development and contributing

```bash
# Backend regression tests
poetry run python -m unittest discover -s tests -v

# Frontend build and browser regression tests
cd web
npm ci
npx playwright install chromium
npm run build
npm run test:e2e
```

Browser tests use a temporary SQLite database and a dedicated test token. To use an installed Chrome, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` to its executable path.

The backend lives in `app/`, the React console in `web/`, and tests in `tests/` and `web/e2e/`. Dependencies are tracked in `pyproject.toml` / `poetry.lock` and `web/package.json` / `web/package-lock.json`.

Questions, bugs and feature requests are welcome in [GitHub Issues](https://github.com/stonyz/simpleMcp/issues). To contribute, fork [stonyz/simpleMcp](https://github.com/stonyz/simpleMcp), create a branch, run the relevant checks and open a pull request.

## License

SimpleMCP is licensed under the [MIT License](LICENSE). Commercial use, modification and redistribution are permitted, provided the copyright and license notices are retained.

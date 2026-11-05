# SimpleMCP technical reference

[GitHub](https://github.com/stonyz/simpleMcp) · [README](../README.md) · [中文说明](../README.zh-CN.md)

## Core Concepts

### OpenAPI Registration

SimpleMCP dynamically loads OpenAPI specifications and converts them into callable functions. Each OpenAPI file is associated with an organization ID (`orgid`) and application ID (`appid`) for multi-tenant isolation.

### Function Registry

Functions extracted from OpenAPI specifications are stored in a registry and can be filtered by `orgid` and `appid`. The registry supports:
- Listing available functions
- Executing registered functions
- Managing function metadata

### Per-operation request timeout

Use `x-request-timeout-seconds` on an OpenAPI **operation** to declare the
time budget for that API. This is a custom extension supported by this gateway,
not a standard OpenAPI timeout field; other tools may ignore it.

```yaml
openapi: 3.0.3
info:
  title: Example API
  version: "1.0"
servers:
  - url: https://api.example.com
paths:
  /status:
    get:
      operationId: getStatus
      x-request-timeout-seconds: 5
      responses:
        '200':
          description: Current status
  /reports:
    post:
      operationId: generateReport
      x-request-timeout-seconds: 120
      responses:
        '200':
          description: Generated report
```

- The value must be a finite positive number in **seconds**; fractions such as
  `0.5` are supported. Zero, negative values, strings, booleans and null are
  rejected with HTTP 400 during registration, before the document is saved or
  the live registry is changed.
- An operation without this field defaults to **30 seconds**. Root-level and
  path-level values are not inherited; set it on each operation that needs an
  override.
- The budget covers the target upstream HTTP exchange: connection establishment,
  request transmission, all followed redirects, and reading the complete response
  body. Receiving occasional data does **not** reset the deadline. This replaces
  the previous fixed Requests timeout, which limited connection/read waits rather
  than the whole exchange.
- Argument validation, obtaining an OAuth token before the target request, and
  formatting the MCP response are outside this budget. MCP clients and intervening
  proxies have their own timeouts and may end the call earlier.
- On expiry the gateway cancels its HTTP exchange and returns the existing
  `upstream_timeout` execution error (`result.isError: true` for JSON-RPC;
  `status: "error"` for `/mcp/call`). Cancellation does not guarantee that the
  upstream service stops work already accepted; no automatic retry is performed.
- Register the updated OpenAPI document using `/services/register` (JSON) or
  `/services/register-form` (form/file). The extension is stored with the document,
  takes effect on registration, and is restored on server startup. It is not a
  tool argument and is not forwarded to the upstream API.

### Authentication

SimpleMCP supports multiple authentication mechanisms for both client access to the server and forwarding authentication to upstream services.

## API Endpoints

### Standard REST Endpoints

#### Functions

- `GET /functions/` - List available functions
  - Parameters: `tenant`, `orgid`, `appid` (required), `name` (optional)

#### Services

- `POST /services/register` - Register an OpenAPI specification
  - Query parameter: `tenant` (required)
  - JSON body: `org`, `app`, `fileName`, `yaml_content`; optional `fileId`, `auth`
- `POST /services/register-form` - Register using form fields or a file upload
  - Query parameter: `tenant` (required)
  - Form fields: `org`, `app`, `fileName`, `file` or `yaml_content`; optional `fileId`, `auth`
  - Both registration endpoints generate and return `fileId` when omitted or empty. Save this ID and send it on subsequent updates or deletion. Each registration without an ID creates a new document.
  - Supplying the same `tenant`, `org`, `app`, and `fileId` updates that document (`updated: true`) and replaces its tools, removing operations deleted or renamed in the new specification. Other documents' tools are preserved unless the new specification registers the same tool name in the same org/app, which retains the existing overwrite behavior.
- `DELETE /services/delete` - Delete an OpenAPI specification
  - Query parameters: `tenant`, `org`, `app`, `fileId` (all required)

#### MCP

- `GET /mcp/list` - List available functions (MCP style)
  - Parameters: `tenant` (required), `orgid`, `appid`, `name` (optional)
- `POST /mcp/call` - Call a function; `tenant` query parameter required
  - JSON body: `function_name`, `parameters`, `orgid` (optional), `appid` (optional)

### JSON-RPC 2.0 Endpoint

- `POST /mcp?tenant=<tenant-id>` - Standard MCP JSON-RPC 2.0 interface supporting:
  - `initialize` - Get server capabilities
  - `ping` - Return an empty result
  - `tools/list` or `list_tools` - List available tools
  - `tools/call` or `call_tool` - Call a tool

The stateless HTTP endpoint supports protocol versions `2025-06-18` and
`2025-11-25`. Initialization requires `protocolVersion`, `capabilities`, and
`clientInfo` (`name` and `version`). A supported version is echoed; other
versions negotiate `2025-11-25`. Clients must disconnect if they do not
support that version. Subsequent requests should carry `MCP-Protocol-Version`;
unsupported header values return HTTP 400. Notifications (including
`notifications/initialized`) receive HTTP 202 with an empty body. This
stateless endpoint does not maintain cancellation state or a session ID.

Successful JSON object results are returned in `structuredContent` and as
serialized JSON in `content[].text`. When an OpenAPI response schema is not
an object root (arrays, strings, numbers, nullable objects, or unions),
`tools/list` advertises an object schema with a required `data` field, and
`tools/call` returns `structuredContent: {"data": <upstream result>}` with
the same JSON in the text block. Existing stored schemas are converted when
read; re-registration is not required. Schema-less text results stay text.

Outputs are validated before being returned as successful tool results.
Schema mismatches produce `isError: true` with
`_meta.error_details.type: "output_validation_error"`. OpenAPI `nullable`
fields are converted to JSON Schema null unions, and OpenAPI 3.0 boolean
exclusive bounds are converted to numeric bounds. Output validation supports
JSON Schema 2020-12 (the default) and explicitly declared draft-07; other
dialects produce `unsupported_schema_dialect` tool errors. Local schema
references retain their targets when the output is wrapped. External schema references
are not fetched during validation. The legacy `/mcp/call` endpoint retains
its original unwrapped result format.

### Tool execution errors

When an upstream API returns HTTP 4xx/5xx, the gateway preserves its failure
reason and status code. For example, a 502 body
`{"error":"Device offline; location unavailable"}` produces:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "isError": true,
    "content": [
      {"type": "text", "text": "Upstream API returned HTTP 502: Device offline; location unavailable"}
    ],
    "_meta": {
      "x-request-id": "...",
      "error_details": {
        "type": "upstream_http_error",
        "status_code": 502,
        "body": {"error": "Device offline; location unavailable"}
      }
    }
  }
}
```

**Client migration:** `tools/call` and `call_tool` now report API failures,
network failures and tool argument validation failures as HTTP 200 with
`result.isError: true`, replacing the previous top-level JSON-RPC `error`.
Read `result.content` for the failure reason and `_meta.error_details` for
structured details. Unknown/inaccessible tools and malformed requests still
return top-level protocol errors. Tool identity fields and `x-request-id`
now use standard `result._meta` for both successful and failed JSON-RPC tool
calls. Clients that read `result.meta` must migrate to `result._meta`.

The legacy `POST /mcp/call` endpoint continues to return `status: "error"`,
a string `error`, and `meta`; it adds `error_details` with the same structured
details. Its existing HTTP status behavior is unchanged.

Error types include `upstream_http_error`, `upstream_timeout`,
`upstream_connection_error`, `upstream_request_error`, `output_validation_error`, `validation_error`, and
`tool_execution_error`. Network failures have no upstream HTTP status code.
Unexpected execution exceptions return a generic message; the server logs the
traceback for investigation using the request ID.

JSON error messages prefer string `error`, `message`, then `detail` fields.
Invalid JSON and plain text use a text fallback; empty and HTML responses use
an HTTP status description. Error bodies are limited to 4096 characters;
oversized bodies become truncated text with `truncated: true`. Common credential
fields and text assignments are redacted, but arbitrary sensitive free text
cannot be comprehensively identified. OAuth token errors expose the message
and status without the full response body. Request URLs and headers are not
included in these error details. No OpenAPI changes are needed.

## Authentication

### Server Access Authentication

SimpleMCP requires clients to authenticate using a token. Tokens can be configured in the `AUTH_TOKENS` setting. Clients can provide tokens via:
- Authorization header: `Authorization: Bearer <token>`
- Query parameter: `?token=<token>`

`AUTH_TOKENS` contains platform administrator credentials. MCP client credentials
are created in the Web console's **Access credentials** page and stored in SQLite.
Configuration-based scope grants have been removed; old scope configuration is
not imported automatically. Unknown, disabled and expired client tokens return
401, including when `AUTH_TOKENS` is empty.

A token may contain multiple allow rules; their permissions are combined:

| Rule fields | Authorized resources |
| --- | --- |
| `tenant` | All current and future services in the tenant |
| `tenant`, `org` | All current and future applications/services in the organization |
| `tenant`, `org`, `app` | All current and future services in the application |
| `tenant`, `org`, `app`, `services: [fileId, ...]` | Only the selected service documents |

Each rule has `operations: ["list", "call"]` by default. Either operation can
be removed independently. `services: null` permits the full scope; an empty
service array is rejected. App rules require org; service rules require both.
All rules created or edited in a workspace must belong to its selected tenant.
Multiple rules can combine organizations, applications and service selections within
that tenant. Selected services are validated against the database. Service identity is the full `tenant + org + app + fileId` tuple;
updating a document in place preserves its grant. Broad scopes include future
services, while deleting a selected service does not grant access to any other
service. Re-registering the same full identity is treated as the same service.

`tools/list` / `list_tools`, `/mcp/list` and `/functions/` automatically filter
results to the token's list permissions. Clients do not have to supply org/app
for authorization. Optional filters only narrow the result. `tools/call` /
`call_tool` and `/mcp/call` check call permissions against the actual tool's
registered org/app/fileId before execution. Unauthorized calls return HTTP 403.
MCP initialize/ping require a tenant present in a grant. Multiple authorized tools
with the same name remain ambiguous and require org/app filters.
Call-only permissions continue to validate output schemas.

Database tokens cannot access service administration or credential management.
`AUTH_TOKENS` grants administrator access to management. By default these tokens
cannot access MCP or its `/functions/` compatibility route (HTTP 403). Set
`ADMIN_MCP_ENABLED=true` and restart to explicitly permit administrator MCP access;
its default is `false`. Database credential permissions are unaffected.
Use Bearer headers for client credentials. The console can copy an MCP connection
example when issuing a token. JSON-RPC params take precedence over org/app headers.

Administrator tenant APIs (managed directly on the tenant selection page):

- `GET /tenants/`: tenant metadata and service/credential counts.
- `POST /tenants/`: create `{id, name, description}`.
- `GET /tenants/{id}`: inspect a tenant before entering its workspace.
- `PUT /tenants/{id}`: edit `{name, description}`; the ID is immutable.
- `DELETE /tenants/{id}`: delete an empty tenant; nonempty tenants return 409.

The `tenants` table is created on startup and populated from existing services and
credential rules. A fresh empty installation starts with a `default` tenant.
Legacy registration APIs continue to register their tenant automatically.
Returning to the tenant portal unmounts the workspace, clears editors and one-time
secrets, and aborts its list/catalog requests. A failed entry never opens a workspace.
The administrator token remains in page memory until logout or refresh.

All credential administration APIs below **require `?tenant=<selected-id>`**.
Missing tenant returns 422, including with the full middleware stack; it does not
silently select `default`. Lists/catalog only return that tenant's resources.
Create/update rules targeting another tenant return 403. Editing, disabling,
rotating or deleting another tenant's credential ID returns 404 and leaves it unchanged.
Historical credentials with rules spanning multiple tenants retain their MCP runtime
permissions but are excluded from tenant workspaces and cannot be modified there.
No existing secrets or grants are automatically changed.

Administrator credential APIs:

- `GET /credentials/`: list safe metadata, rules and status; no raw token or hash.
- `GET /credentials/catalog`: tenant/org/app/service candidates from stored documents.
- `POST /credentials/`: create a token and return its raw `secret` once.
- `PUT /credentials/{id}`: replace metadata and rules, preserving the secret.
- `PATCH /credentials/{id}/status`: enable/disable, even if selected services have been deleted.
- `POST /credentials/{id}/rotate`: issue a new secret; invalidate the previous secret.
- `DELETE /credentials/{id}`: remove the credential and its rules.

Create/update payload example (service selection is optional):

```json
{
  "name": "Partner order access",
  "description": "Order integration",
  "enabled": true,
  "expires_at": null,
  "rules": [
    {"tenant": "customer-a", "org": "engineering", "app": "orders",
     "services": ["orders-openapi"], "operations": ["list", "call"]}
  ]
}
```

Names, descriptions, expiry and enable state are editable. Expiry timestamps must
include a timezone; the console converts local input to UTC. Secrets are generated
with secure randomness; only SHA256 digests and non-authenticating prefixes are
persisted. Credential responses use `Cache-Control: no-store` when returning
secrets; request logging omits credential payloads and responses even at DEBUG.
Recent-use timestamps update at most once per minute. Authorization is loaded
from the database on each request; changes apply to subsequent requests without a
restart. Requests already authenticated use their existing permission snapshot.
No database Token is seeded automatically. Startup creates two new tables
(`mcp_credentials`, `mcp_access_rules`) without changing stored service documents.
Back up the SQLite database to preserve services and credentials together.

`GET /services/access?tenant=...` and `GET /services/scopes?tenant=...` remain
administrator-only console helpers. Tenant/org/app identifiers are case sensitive,
nonempty, have no whitespace or path/query delimiters, and are limited to
63/64/64 characters. Reading an unknown tenant does not create an in-memory registry.

### Upstream Service Authentication

SimpleMCP can forward authentication credentials to upstream services. Two methods are supported:

#### Basic Authentication from Arguments

When an OpenAPI specification includes a basicAuth security scheme, the MCP server can extract username and password from the `arguments.auth` field and automatically convert them to an HTTP Basic Authentication header.

##### OpenAPI Specification

```yaml
openapi: 3.1.0
info:
  title: Example API
  version: 1.0.0

components:
  securitySchemes:
    basicAuth:
      type: http
      scheme: basic

security:
  - basicAuth: []
```

##### Client Usage

When calling MCP services, include the username and password in the `auth` field within `arguments`:

```json
{
  "id": 2,
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "checkBasicAuth",
    "arguments": {
      "user": "admin",
      "passwd": "secret",
      "auth": {
        "username": "admin",
        "password": "secret"
      }
    }
  }
}
```

##### Processing Flow

1. Client sends a request with `arguments.auth` containing username and password
2. MCP server extracts the `auth` object from arguments
3. MCP server converts username/password to a Basic Auth header
4. MCP server removes the `auth` object from arguments to prevent it from being sent as a parameter
5. MCP server makes the upstream request with the Basic Auth header
6. Upstream service authenticates the request using the Basic Auth header

The MCP server will:
1. Extract `username` and `password` from `arguments.auth`
2. Create the header `Authorization: Basic YWRtaW46c2VjcmV0` (base64 encoded "admin:secret")
3. Make the request to `https://httpbin.org/basic-auth/admin/secret` with this header
4. Return the response from the upstream service

#### OAuth2 Client Credentials Authentication

When an OpenAPI specification includes an OAuth2 Client Credentials security scheme, the MCP server can extract client credentials from the `arguments.auth` field and automatically obtain an access token from the OAuth2 provider. This token is then used as a Bearer token in the Authorization header for requests to the upstream service.

##### OpenAPI Specification

```yaml
openapi: 3.1.0
info:
  title: Example API
  version: 1.0.0

components:
  securitySchemes:
    oauth2ClientCredentials:
      type: oauth2
      flows:
        clientCredentials:
          tokenUrl: https://auth.example.com/oauth2/token
          scopes:
            read: Read access
            write: Write access

security:
  - oauth2ClientCredentials:
      - read
```

##### Client Usage

When calling MCP services, include the client credentials in the `auth` field within `arguments`:

```json
{
  "id": 2,
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "checkBearerAuth",
    "arguments": {
      "auth": {
        "client_id": "my-client-id",
        "client_secret": "my-client-secret",
        "scopes": ["read"],
        "token_url": "https://auth.example.com/oauth2/token"
      }
    }
  }
}
```

Alternatively, you can use the direct /call endpoint:

Send `POST /mcp/call?tenant=your-tenant` with an MCP client Bearer token:

```json
{
  "function_name": "checkBearerAuth",
  "parameters": {
    "auth": {
      "client_id": "my-client-id",
      "client_secret": "my-client-secret",
      "scopes": [
        "read"
      ],
      "token_url": "https://auth.example.com/oauth2/token"
    }
  }
}
```

##### Processing Flow

1. Client sends a request with `arguments.auth` containing client credentials
2. MCP server extracts the `auth` object from arguments
3. MCP server uses the client credentials to obtain an access token from the OAuth2 provider
4. MCP server caches the token for future use (with automatic refresh)
5. MCP server adds the token as a Bearer token in the Authorization header
6. MCP server removes the `auth` object from arguments to prevent it from being sent as a parameter
7. MCP server makes the upstream request with the Bearer token
8. Upstream service authenticates the request using the Bearer token

##### Token Caching

Tokens are cached in memory to avoid unnecessary requests to the OAuth2 provider. Tokens are automatically refreshed before they expire.

## Bearer Token Authentication

When an OpenAPI specification includes an HTTP Bearer security scheme, the MCP server can use a pre-obtained bearer token from the `arguments.auth` field and automatically add it as an Authorization header for requests to the upstream service.

### OpenAPI Specification

```yaml
openapi: 3.1.0
info:
  title: Example API
  version: 1.0.0

components:
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer
      bearerFormat: JWT  # Optional token format, e.g. JWT, opaque token or signed token

security:
  - bearerAuth: []
```

### Client Usage

When calling MCP services, include the bearer token in the `auth` field within `arguments`:

```json
{
  "id": 2,
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "checkBearerAuth",
    "arguments": {
      "auth": {
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
      }
    }
  }
}
```

Alternatively, you can use the direct /call endpoint:

Send `POST /mcp/call?tenant=your-tenant` with an MCP client Bearer token:

```json
{
  "function_name": "checkBearerAuth",
  "parameters": {
    "auth": {
      "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    }
  }
}
```

### Processing Flow

1. Client sends a request with `arguments.auth` containing a bearer token
2. MCP server extracts the `auth` object from arguments
3. MCP server uses the provided bearer token directly
4. MCP server adds the token as a Bearer token in the Authorization header
5. MCP server removes the `auth` object from arguments to prevent it from being sent as a parameter
6. MCP server makes the upstream request with the Bearer token
7. Upstream service authenticates the request using the Bearer token

## Multi-Tenant Isolation

SimpleMCP isolates resources by `tenant`, then organizes tools by `orgid` and `appid`. Every MCP request requires the `tenant` query parameter and a permitted client token. We provide multiple ways to pass these parameters to accommodate different MCP clients.

### Supported Parameter Passing Methods

#### 1. Via JSON-RPC params (Recommended)

This is the most direct way, suitable for MCP clients that can customize parameters:

```bash
curl -X POST "http://localhost:8000/mcp?tenant=your-tenant" \
  -H "Authorization: Bearer $SIMPLEMCP_CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "listFiles",
      "arguments": {"file_id": "12042"},
      "orgid": "cyberobject",
      "appid": "qacheck"
    }
  }'
```

#### 2. Via HTTP Headers (For standard MCP clients)

For standard MCP clients that cannot modify params, parameters can be passed via HTTP Headers:

```bash
curl -X POST "http://localhost:8000/mcp?tenant=your-tenant" \
  -H "Authorization: Bearer $SIMPLEMCP_CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Org-ID: cyberobject" \
  -H "X-App-ID: qacheck" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "listFiles",
      "arguments": {"file_id": "12042"}
    }
  }'
```

#### 3. Initialization

Initialization negotiates protocol capabilities. Organization and application
IDs must be passed on each tool request via params or headers; this stateless
endpoint does not save defaults from `clientInfo`.

```bash
curl -X POST "http://localhost:8000/mcp?tenant=your-tenant" \
  -H "Authorization: Bearer $SIMPLEMCP_CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2025-11-25",
      "capabilities": {},
      "clientInfo": {
        "name": "MyMCPClient",
        "version": "1.0.0"
      }
    }
  }'
```

### Parameter Priority

When parameters are passed via multiple methods simultaneously, the priority is as follows:

1. **Parameters in JSON-RPC params** (Highest priority)
2. **Parameters in HTTP Headers**

### API Support for Isolation

#### tools/list (list_tools)
- ✅ Supports filtering via `orgid`/`appid`
- ✅ Supports HTTP Headers
- ✅ Database tokens only see authorized tools; administrators require `ADMIN_MCP_ENABLED=true` for MCP access

#### tools/call (call_tool)
- ✅ Supports permission checking via `orgid`/`appid`
- ✅ Supports HTTP Headers
- ✅ Applies token scope and role checks before execution; ambiguous tool names require org/app

#### register
- ✅ Supports `orgid`/`appid` isolation
- Each function is associated with a specific organization and application

### Error Handling

Scope and operation authorization failures return HTTP 403:

```json
{
  "error": {
    "type": "HTTPException",
    "status_code": 403,
    "message": "Token does not permit this tool call"
  }
}
```

### Backward Compatibility

- Existing administrator tokens remain valid for management; MCP access requires `ADMIN_MCP_ENABLED=true`.
- Calls without org/app still work when exactly one tool matches the name.
- Database credentials automatically filter authorized resources; client filters only narrow access.

### Best Practices

1. **For new MCP clients**: It is recommended to pass `orgid`/`appid` via params
2. **For existing standard MCP clients**: It is recommended to pass parameters via HTTP Headers
3. **For simple scenarios**: Pass organization and application IDs on every request
4. **For separate tenants or teams**: Create database MCP credentials in the console; org/app filters alone do not grant or restrict access

## Deployment

### Docker Deployment

The server needs Docker Engine and the Docker Compose plugin. Python and Poetry
are installed inside the image, so they are not required on the host.

1. In the project directory, create the configuration file on first deployment:
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and replace `AUTH_TOKENS` with your own tokens (a JSON array).
   Configure `PROXY_URL` and `PROXY_RULES` only if an outbound proxy is needed.

2. Build and start the service:
   ```bash
   docker compose up -d --build
   ```
   The API is available on port `8000`. Compose builds the image from this
   directory and automatically restarts the service unless explicitly stopped.

3. Check status and startup logs:
   ```bash
   docker compose ps
   docker compose logs --tail=100 -f simpleMcp
   ```

After updating the source, run `docker compose up -d --build` again.
The health check requests `/openapi.json` to confirm the application is serving.

### Environment Configuration

Configure the following environment variables in your `.env` file:

- `DATABASE_URL`: SQLite URL, defaults to `sqlite:///./data/mcp.db`.
  Relative paths are resolved from the server's working directory; parent directories
  and tables are created automatically. For an absolute path, use
  `sqlite:////absolute/path/mcp.db`.
- `API_TOKEN`: Default Bearer token for upstream APIs
- `AUTH_TOKENS`: JSON array of valid authorization tokens, e.g. `["your-token"]`

Docker Compose fixes `DATABASE_URL` to `sqlite:////app/data/mcp.db`, overriding
the value in `.env`, and mounts `./data` at `/app/data` to preserve the database
across container recreation. Logs are stored in `./logs`. Both host directories
are created on first startup. Back up `./data` while the server is stopped;
`docker compose down` preserves these host directories.
Existing `MYSQL_*` settings are ignored. Existing MySQL data is not imported
automatically; a new SQLite database starts empty.

Run the database regression tests with:

```bash
poetry run python -m unittest discover -s tests -v
```

## Development

### Development Environment Setup

To set up the development environment, follow these steps:

1. **Install Python using pyenv** (if not already installed):
   ```bash
   # Install pyenv (macOS via Homebrew)
   brew install pyenv
   
   # Or install pyenv (Linux)
   curl https://pyenv.run | bash
   
   # Add to your shell profile (.bashrc, .zshrc, etc.)
   export PYENV_ROOT="$HOME/.pyenv"
   export PATH="$PYENV_ROOT/bin:$PATH"
   eval "$(pyenv init -)"
   ```

2. **Install the required Python version** (Python 3.12+; see pyproject.toml):
   ```bash
   pyenv install 3.12.6  # or whatever version is specified in pyproject.toml
   pyenv local 3.12.6
   ```

3. **Install Poetry** (if not already installed):
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

4. **Navigate to the project directory** and execute the following commands:
   ```bash
   cd /path/to/simpleMcp
   python3.12 -m venv .venv
   poetry env use .venv/bin/python
   poetry install
   poetry env info
   ```

### Project Structure

```
app/
├── common/           # Common utilities and exception handlers
├── db/               # Database models and CRUD operations
├── mcp/              # Core MCP functionality
│   ├── rest/         # REST API execution and authentication
│   ├── registry.py   # Function registry
│   └── tool_executor.py  # Tool execution logic
├── midware/          # Middleware components
├── routers/          # API route handlers
├── config.py         # Application configuration
├── logger.py         # Logging configuration
└── main.py           # Application entry point
```

### Adding New Features

1. Implement new functionality in the appropriate module
2. Add new routes in the routers directory
3. Update the registry if new tool types are added
4. Document new features in the README or this reference

### Testing

Run tests with:
```bash
poetry run python -m unittest discover -s tests -v
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a pull request

### License

[MIT License](../LICENSE)

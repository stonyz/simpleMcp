# MCP Server

MCP Server is a backend service designed to manage and serve OpenAPI specifications, acting as a middleware or gateway for microservices. It supports dynamic loading of OpenAPI definitions, authentication, logging, and structured exception handling.

## Features

- RESTful API endpoints via FastAPI
- Dynamic OpenAPI specification loading from files
- Authentication and authorization support
- Logging and exception handling middleware
- Database integration using SQLAlchemy ORM
- Containerized deployment with Docker and docker-compose
- **NEW**: Client-provided authentication for upstream services
- Multi-tenant isolation with orgId/appId
- Built-in React service administration UI at `/admin/`

## Web 服务管理台

浏览器访问 `http://localhost:8000/admin/`，输入 `.env` 中 `AUTH_TOKENS`
配置的一个 Token 和目标 Tenant。管理台使用 React、TypeScript、Vite、Ant Design
和本地加载的 Monaco 编辑器，不依赖外部 CDN。

支持服务分页查询、按组织/应用筛选、搜索、YAML/JSON 上传或粘贴、工具变更预览、
注册、覆盖更新、删除、文档导出，以及复制 MCP 接入配置。更新锁定
`tenant + org + app + fileId`，保存前检查重名工具；其他文档有同名工具时拒绝保存，
现有 `/services/register` 的兼容行为保持不变。详情区分文档声明工具和当前注册表生效工具，
不检测上游健康状态。文档导出为数据库保存的 YAML，不保留原始文件的排版和注释。

管理台沿用服务端共享 Token：持有有效 Token 的管理员可切换 Tenant，
Tenant/Org/App 是数据范围筛选，不是用户级权限体系。Token 仅保存在页面内存中，
刷新或退出后需要重新输入；接入示例使用 `YOUR_TOKEN` 占位符。
上游 `auth` 配置不回显，编辑时可保留、替换或清除。HTTP 请求日志用日志级别控制：
`LOG_LEVEL=INFO` 记录方法、路径、状态和耗时；`.env` 设置 `LOG_LEVEL=DEBUG`
并重启后，会额外在 `logs/request-YYYY-MM-DD.log` 中完整记录请求 URL、请求头、
请求正文、响应头和文本响应正文（包括认证信息）。SSE 保持流式传输，不收集事件正文；
二进制或压缩响应只记录类型提示，避免将图片等强行解码成文本。

服务编辑页的“授权设置”按授权方式提供独立字段，无需手写 JSON：

| 授权方式 | 配置字段 | 调用行为 |
| --- | --- | --- |
| 无需认证 | 无 | 清除服务默认凭据；调用方仍可提供 `auth` |
| Bearer Token | `access_token` | 自动添加 `Authorization: Bearer …` |
| HTTP Basic | `username`、`password` | 自动生成 Basic Authorization 请求头 |
| OAuth2 Client Credentials | `token_url`、`client_id`、`client_secret`，可选 `scopes` | 获取并缓存访问令牌后调用业务 API |

已有服务默认选择“保留现有授权”，详情仅展示授权类型，不回显用户名、令牌、密钥等凭据。
切换授权类型需填写完整的新凭据，隐藏类型的字段不会随请求发送。OAuth2 的令牌地址必须为
HTTP/HTTPS 地址，scopes 可用回车、空格或逗号分隔。授权字段变化后必须重新校验预览才能保存。
管理接口通过可选 `auth_type`（`bearer`、`basic`、`oauth2`）进行对应字段校验；原有不传类型的
JSON `auth` 接口仍兼容。

Docker 构建会自动构建前端，仍通过一个镜像、一个 `8000` 端口提供页面和 API：

```bash
docker compose up -d --build
```

本地运行生产构建（Node.js 22.12+ 或 24 LTS）：

```bash
cd web
npm ci
npm run build
cd ..
poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端开发时，在后端已运行于 `127.0.0.1:8000` 的情况下，在 `web/` 执行
`npm run dev`，访问 Vite 输出地址下的 `/admin/`。Vite 将 `/services` 请求代理到后端。
后端启动时挂载 `web/dist`，首次构建后需重启后端。

浏览器回归使用独立临时 SQLite 数据库及专用测试 Token，不读取已有服务数据：

```bash
cd web
npx playwright install chromium
npm run build
npm run test:e2e
```

也可以设置 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 使用本机 Chrome。

## Table of Contents

1. [Getting Started](#getting-started)
2. [Core Concepts](#core-concepts)
3. [API Endpoints](#api-endpoints)
4. [Authentication](#authentication)
5. [Multi-Tenant Isolation](#multi-tenant-isolation)
6. [Deployment](#deployment)
7. [Development](#development)

## Getting Started

### Prerequisites

- Python 3.12+
- Poetry (for dependency management)
- SQLite (included with Python; no database server required)
- Docker (optional, for containerized deployment)

### Installation

1. Clone the repository
2. Create the project environment and install the locked dependencies:
   ```bash
   python3.12 -m venv .venv
   poetry env use .venv/bin/python
   poetry install
   ```
   Declare dependencies in `pyproject.toml` and commit `poetry.lock` to keep
   installations reproducible. Use `poetry add <package>` or
   `poetry remove <package>` to update both files.
3. Set up environment variables in `.env` file (see `.env.example`)
4. Run the server:
   ```bash
   poetry run uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

### Quick Example

1. Register an OpenAPI specification:
   ```bash
   curl -X POST "http://localhost:8000/services/register" \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "org=org1&app=app1&fileId=example&fileName=example.yaml&yaml_content=..."
   ```

2. List available functions:
   ```bash
   curl "http://localhost:8000/functions/?orgid=org1&appid=app1"
   ```

3. Call a function:
   ```bash
   curl -X POST "http://localhost:8000/mcp/call" \
     -H "Content-Type: application/json" \
     -d '{"function_name": "get_user", "parameters": {"user_id": "123"}}'
   ```

## Core Concepts

### OpenAPI Registration

MCP Server dynamically loads OpenAPI specifications and converts them into callable functions. Each OpenAPI file is associated with an organization ID (`orgid`) and application ID (`appid`) for multi-tenant isolation.

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

MCP Server supports multiple authentication mechanisms for both client access to the server and forwarding authentication to upstream services.

## API Endpoints

### Standard REST Endpoints

#### Functions

- `GET /functions/` - List available functions
  - Parameters: `orgid` (required), `appid` (required), `name` (optional)

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
  - Parameters: `orgid` (optional), `appid` (optional), `name` (optional)
- `POST /mcp/call` - Call a function
  - JSON body: `function_name`, `parameters`, `orgid` (optional), `appid` (optional)

### JSON-RPC 2.0 Endpoint

- `POST /mcp` - Standard MCP JSON-RPC 2.0 interface supporting:
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
`{"error":"手表不在线，无法获取位置信息"}` produces:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "isError": true,
    "content": [
      {"type": "text", "text": "上游接口返回 HTTP 502：手表不在线，无法获取位置信息"}
    ],
    "_meta": {
      "x-request-id": "...",
      "error_details": {
        "type": "upstream_http_error",
        "status_code": 502,
        "body": {"error": "手表不在线，无法获取位置信息"}
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

MCP Server requires clients to authenticate using a token. Tokens can be configured in the `AUTH_TOKENS` setting. Clients can provide tokens via:
- Authorization header: `Authorization: Bearer <token>`
- Query parameter: `?token=<token>`

### Upstream Service Authentication

MCP Server can forward authentication credentials to upstream services. Two methods are supported:

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

```json
POST /mcp/call
{
  "function_name": "checkBearerAuth",
  "parameters": {},
  "auth": {
    "client_id": "my-client-id",
    "client_secret": "my-client-secret",
    "scopes": ["read"],
    "token_url": "https://auth.example.com/oauth2/token"
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
      bearerFormat: JWT  # 可选，标注一下令牌类型（可写 JWT/opaque token/Signed Token 等）

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

```json
POST /mcp/call
{
  "function_name": "checkBearerAuth",
  "parameters": {},
  "auth": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
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

MCP Server supports multi-tenant isolation through `orgId` and `appId`. We provide multiple ways to pass these parameters to accommodate different MCP clients.

### Supported Parameter Passing Methods

#### 1. Via JSON-RPC params (Recommended)

This is the most direct way, suitable for MCP clients that can customize parameters:

```bash
curl -X POST "http://localhost:8000/mcp" \
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
curl -X POST "http://localhost:8000/mcp" \
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
- ✅ Backward compatible (returns all tools when no parameters are provided)

#### tools/call (call_tool)
- ✅ Supports permission checking via `orgid`/`appid`
- ✅ Supports HTTP Headers
- ✅ Backward compatible (no permission check when parameters are not provided)

#### register
- ✅ Supports `orgid`/`appid` isolation
- Each function is associated with a specific organization and application

### Error Handling

When access permissions are denied, detailed error information is returned:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32000,
    "message": "Function 'listFiles' not accessible for orgid 'wrong_org'. Function belongs to orgid 'cyberobject'"
  }
}
```

### Backward Compatibility

- When `orgid`/`appid` parameters are not provided, the system continues to work normally
- Existing MCP clients can continue to be used without modification
- The new isolation feature is optional and does not affect existing functionality

### Best Practices

1. **For new MCP clients**: It is recommended to pass `orgid`/`appid` via params
2. **For existing standard MCP clients**: It is recommended to pass parameters via HTTP Headers
3. **For simple scenarios**: Pass organization and application IDs on every request
4. **For production environments**: It is recommended to always provide `orgid`/`appid` to ensure data isolation

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
   cd /path/to/mcp-server
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
4. Document new features in this README

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

MIT License

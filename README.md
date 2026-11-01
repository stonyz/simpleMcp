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

### Authentication

MCP Server supports multiple authentication mechanisms for both client access to the server and forwarding authentication to upstream services.

## API Endpoints

### Standard REST Endpoints

#### Functions

- `GET /functions/` - List available functions
  - Parameters: `orgid` (required), `appid` (required), `name` (optional)

#### Services

- `POST /services/register` - Register an OpenAPI specification
  - Form parameters: `org`, `app`, `fileId`, `fileName`, `file` or `yaml_content`
- `DELETE /services/delete` - Delete an OpenAPI specification
  - Query parameters: `org`, `app`, `fileId`

#### MCP

- `GET /mcp/list` - List available functions (MCP style)
  - Parameters: `orgid` (optional), `appid` (optional), `name` (optional)
- `POST /mcp/call` - Call a function
  - JSON body: `function_name`, `parameters`, `orgid` (optional), `appid` (optional)

### JSON-RPC 2.0 Endpoint

- `POST /mcp` - Standard MCP JSON-RPC 2.0 interface supporting:
  - `initialize` - Get server capabilities
  - `tools/list` or `list_tools` - List available tools
  - `tools/call` or `call_tool` - Call a tool

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

#### 3. Via initialize (Setting default values)

Default organization and application IDs can be set during initialization:

```bash
curl -X POST "http://localhost:8000/mcp" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "clientInfo": {
        "name": "MyMCPClient",
        "version": "1.0.0",
        "orgid": "cyberobject",
        "appid": "qacheck"
      }
    }
  }'
```

### Parameter Priority

When parameters are passed via multiple methods simultaneously, the priority is as follows:

1. **Parameters in JSON-RPC params** (Highest priority)
2. **Parameters in HTTP Headers**
3. **Default values set during initialize** (Lowest priority)

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
3. **For simple scenarios**: Default values can be set during initialize
4. **For production environments**: It is recommended to always provide `orgid`/`appid` to ensure data isolation

## Deployment

### Docker Deployment

1. Build the Docker image:
   ```bash
   docker build -t mcp-server .
   ```

2. Run with docker-compose:
   ```bash
   docker-compose up -d
   ```

### Environment Configuration

Configure the following environment variables in your `.env` file:

- `DATABASE_URL`: SQLite URL, defaults to `sqlite:///./data/mcp.db`.
  Relative paths are resolved from the server's working directory; parent directories
  and tables are created automatically. For an absolute path, use
  `sqlite:////absolute/path/mcp.db`.
- `API_TOKEN`: Default Bearer token for upstream APIs
- `AUTH_TOKENS`: Comma-separated list of valid authorization tokens

Docker Compose mounts `./data` at `/app/data` to preserve the database across
container recreation. Back up this directory while the server is stopped.
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

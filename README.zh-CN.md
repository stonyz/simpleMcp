# SimpleMCP

**把现有 OpenAPI 接口变成 MCP 工具，用可视化管理台统一管理。**

[English](README.md) | 简体中文 · [GitHub 项目](https://github.com/stonyz/simpleMcp)

SimpleMCP 是一个可自行部署的 OpenAPI → MCP 网关。上传接口文档，就能把其中的操作注册成工具，让 AI 客户端通过统一的 HTTP 入口访问现有业务系统。内置管理台集中管理服务、租户工作空间和客户端权限，无需为每套 API 单独编写 MCP 服务。

```text
现有 REST 接口 → OpenAPI 文档 → SimpleMCP → MCP 客户端 / AI 助手
                                 │
                     可视化管理台 · 租户工作空间 · 访问授权
```

## 项目特色

- **复用现有 API。** 导入 YAML 或 JSON 格式的 OpenAPI 文档，将接口操作注册为可调用的 MCP 工具。文档持久化到 SQLite，服务重启后自动恢复注册。
- **可视化管理服务。** 支持文档上传、粘贴和 Monaco 编辑器，保存前预览工具的新增与移除；可查看工具参数与输出结构、导出文档、复制客户端接入示例。
- **按团队划分工作空间。** 租户之间隔离服务和客户端凭证，租户内继续按组织、应用管理接口，适合多团队共用一个网关。
- **精细控制客户端权限。** 可授权整个租户、组织、应用或指定服务文档，分别控制“列出工具”和“调用工具”，支持凭证停用、过期和密钥轮换。
- **接入需要认证的业务接口。** 通过专门的表单配置 Bearer 令牌、HTTP 基本认证或 OAuth2 客户端凭证；调用时也可以通过 `arguments.auth` 提供上游凭据。
- **通过 HTTP 提供 MCP 工具。** 支持 JSON-RPC 初始化、连通检查、工具发现和调用，以及结构化输出、输出结构校验和按接口设置超时。
- **一个服务即可部署。** Docker 自动打包前后端，一个镜像、一个端口提供管理台和 API。SQLite 无需额外数据库服务；管理台支持中英文切换，编辑器本地加载，不依赖外部 CDN。

## 界面预览

以下均为实际管理台截图，使用独立演示数据。示例 API 地址为 `api.example.com`，不包含真实业务服务或密钥。界面可随时切换为英文或简体中文。

### 服务管理：一眼看清接入了哪些 API

按组织、应用筛选和搜索服务，查看版本、工具数量及注册状态，在同一个工作空间完成文档管理。

![SimpleMCP 服务管理工作台](docs/images/service-management.png)

### 工具详情：从文档到可调用工具

查看 OpenAPI 声明的工具、当前生效状态、输入参数与输出结构，并获取客户端接入配置。注册生效状态不代表上游接口的可用性。

![SimpleMCP 服务详情与工具清单](docs/images/service-tools.png)

### 租户入口：为团队划分独立工作空间

先选择租户，再管理其中的服务与凭证；可直接新增租户，修改名称和说明。

![SimpleMCP 租户工作空间选择页](docs/images/tenant-workspaces.png)

### 访问凭证：让每个客户端只访问需要的服务

集中查看客户端凭证和授权规则，独立控制工具列表与调用权限。

![SimpleMCP 客户端访问凭证管理](docs/images/access-credentials.png)

## 快速开始

### 使用 Docker Compose 部署

```bash
git clone https://github.com/stonyz/simpleMcp.git
cd simpleMcp
cp .env.example .env
```

启动前编辑 `.env`：

```dotenv
APP_NAME=SimpleMCP
AUTH_TOKENS=["replace-with-a-long-random-admin-token"]
ADMIN_MCP_ENABLED=false
PROXY_URL=
PROXY_RULES=
DEBUG=false
log_level=INFO
```

请将管理员令牌替换成自己的随机长令牌。仅在需要出站代理时填写 `PROXY_URL` 和 `PROXY_RULES`；示例配置文件中的代理地址需按实际环境修改或清空。

```bash
docker compose up -d --build
```

打开 **[http://localhost:8000/admin/](http://localhost:8000/admin/)**，使用 `AUTH_TOKENS` 中配置的管理员令牌登录。

1. 新建或选择一个租户工作空间。
2. 点击“注册服务”，选择组织、应用，上传或粘贴 OpenAPI YAML/JSON 文档。
3. 按需配置上游授权，点击“校验并预览”，确认工具变更后保存。
4. 进入“访问凭证”，创建客户端令牌，选择允许访问的服务及操作。创建或轮换后，完整密钥仅显示一次，请及时保存。
5. 使用客户端令牌和当前工作空间的租户标识连接 MCP 客户端。

前后端统一使用 `8000` 端口。数据库持久化到宿主机 `./data`，日志保存在 `./logs`。使用 `docker compose ps` 查看状态，使用 `docker compose logs --tail=100 -f simpleMcp` 查看日志。更新源码后再次执行 `docker compose up -d --build` 即可重新构建并启动。

### 从源码运行

需要 Python 3.12+、Poetry，以及用于构建前端的 Node.js 22.12+ 或 24 LTS。

```bash
git clone https://github.com/stonyz/simpleMcp.git
cd simpleMcp
python3.12 -m venv .venv
poetry env use .venv/bin/python
poetry install
cp .env.example .env
# 按上文说明编辑 .env。
cd web
npm ci
npm run build
cd ..
poetry run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

先构建前端，再启动后端，后端才会挂载 `/admin/` 页面。开发前端时，先在 `127.0.0.1:8000` 启动后端，再进入 `web/` 执行 `npm run dev`，访问 Vite 输出地址下的 `/admin/`。

## 连接 MCP 客户端

MCP 入口为 `POST /mcp?tenant=<租户标识>`。请使用**在管理台创建的客户端令牌**。管理员令牌用于管理，默认没有 MCP 访问权限。

对于支持 HTTP 类型 `mcpServers` 配置的客户端，可参考：

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

将 `default` 替换为实际租户标识，将 `YOUR_MCP_CLIENT_TOKEN` 替换为客户端令牌。不同客户端的配置格式可能不同。可增加 `X-Org-ID`、`X-App-ID` 请求头，缩小工具查询范围，或区分不同应用中的同名工具；筛选条件不会扩大令牌已有权限。

当前支持 MCP 协议版本 `2025-06-18` 和 `2025-11-25`，采用无状态 HTTP JSON-RPC，不维护会话标识和持续的取消状态。

### 直接调用接口

使用管理员令牌注册本地 OpenAPI 文件：

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

在管理台创建允许访问该服务的客户端凭证，然后初始化并列出工具：

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

调用工具时使用 `tools/call`，参数格式为 `params: {"name":"<工具名称>","arguments":{...},"orgid":"demo","appid":"example"}`。请将工具名称和参数替换为已注册文档中的实际内容。

## 配置与使用说明

| 配置项 | 作用 |
| --- | --- |
| `AUTH_TOKENS` | 管理员令牌列表，JSON 数组格式，用于管理台和管理接口 |
| `ADMIN_MCP_ENABLED` | 是否显式允许管理员访问 MCP，默认 `false` |
| `DATABASE_URL` | 本地默认 `sqlite:///./data/mcp.db`；Compose 固定为 `sqlite:////app/data/mcp.db` |
| `API_TOKEN` | 可选的全局上游 API 默认 Bearer 令牌 |
| `PROXY_URL`、`PROXY_RULES` | 可选的出站代理地址及 URL 匹配规则 |
| `APP_NAME` | 后端应用标题，可设为 `SimpleMCP` |
| `log_level` | `INFO` 记录请求摘要；`DEBUG` 额外记录请求和响应详情 |

### 客户端授权与上游认证

客户端令牌决定“谁可以访问 SimpleMCP 中的哪些工具”；上游凭据决定“SimpleMCP 如何访问业务 API”。两者分别配置。数据库中的客户端令牌不能登录管理台或修改服务，只保存摘要和展示前缀。

每个客户端令牌可以有多条授权规则，权限合并生效。授权范围分为租户、组织、应用和指定服务，分别设置列出工具、调用工具的权限。广泛授权会包含该范围内以后新增的服务；指定服务授权绑定完整的 `tenant + org + app + fileId`，原位更新文档不会丢失授权。授权修改对后续请求生效，无需重启。

| 上游认证方式 | 配置字段 | 调用行为 |
| --- | --- | --- |
| 无需认证 | 无 | 不使用服务默认凭据；调用方仍可提供 `auth` |
| Bearer 令牌 | `access_token` | 添加 `Authorization: Bearer …` |
| HTTP 基本认证 | `username`、`password` | 生成 Basic Authorization 请求头 |
| OAuth2 客户端凭证 | `token_url`、`client_id`、`client_secret`，可选 `scopes` | 先获取并缓存访问令牌，再调用业务 API |

编辑服务时可以保留、替换或清除上游授权，已保存的凭据不会回显。调用时也可在 `arguments.auth` 中提供上述凭据；网关将其用于认证，不作为普通业务参数转发。

### 文档更新与工具冲突

服务以 `tenant + org + app + fileId` 唯一标识。传入相同标识会更新文档并替换其工具，删除或改名的接口会从注册表移除。不传 `fileId` 时生成新标识并创建新文档，请保存返回的标识以便后续更新和删除。

管理台在保存前拒绝与其他文档重名的工具；兼容注册接口保留原有的同名覆盖行为。详情页区分文档声明的工具和当前实际生效的工具。导出内容是数据库保存的 YAML，不保证保留上传文件的排版和注释。

### 按接口设置超时

在 OpenAPI 的具体操作上设置 `x-request-timeout-seconds`：

```yaml
paths:
  /reports:
    post:
      operationId: generateReport
      x-request-timeout-seconds: 120
      responses:
        '200':
          description: 报表生成成功
```

该扩展接受有限正数，单位为秒，未设置时默认 30 秒；不会继承文档根级或路径级的值。超时预算覆盖上游 HTTP 连接、发送、重定向和完整响应读取，不包含提前获取 OAuth 令牌的时间。客户端或代理仍有各自的超时限制。超时后返回 `upstream_timeout`，不自动重试，也不保证上游已接受的任务停止执行。

### 结构化输出与错误

对象结果同时通过 `structuredContent` 和 JSON 文本返回。数组、字符串等非对象输出结构会包装为带有 `data` 字段的对象。执行错误提供结构化错误详情和请求标识，便于排查认证失败、上游错误和超时。

后端生成的 API 提示统一使用英文，管理错误提供稳定的 `code` 和安全的 `params`；管理台据此显示中文或英文，切换语言后已显示的提示也会更新。租户名称、API 描述、文档和上游响应保持原文。

### 语言、日志与备份

管理台默认跟随浏览器语言，中文环境显示中文，其余环境显示英文。通过右上角语言菜单可选择“跟随系统 / English / 简体中文”，偏好保存在浏览器中，切换不会清除登录或表单内容。管理员登录令牌仅保存在页面内存，刷新或退出后清除。

`INFO` 日志记录请求方法、路径、状态和耗时，`DEBUG` 还会记录请求和响应详情。Authorization 请求头和令牌查询参数会脱敏，凭证管理接口只记录摘要；其他请求正文中的上游凭据仍可能出现在调试日志中。

停止服务后备份 `./data`，可一起保存服务文档、租户和客户端授权。Compose 重建容器或执行 `docker compose down` 不会删除宿主机的 `./data` 和 `./logs`。旧 `MYSQL_*` 配置不再使用，历史 MySQL 数据不会自动导入 SQLite。

## 接口概览

| 接口 | 用途 |
| --- | --- |
| `POST /mcp?tenant=…` | MCP 初始化、连通检查、`tools/list`、`tools/call` |
| `GET /mcp/list?tenant=…`、`POST /mcp/call?tenant=…` | REST 兼容接口 |
| `GET /functions/?tenant=…&orgid=…&appid=…` | 查询已注册函数 |
| `POST /services/register?tenant=…` | 使用 JSON 请求体注册或更新文档 |
| `POST /services/register-form?tenant=…` | 使用表单字段或上传文件注册文档 |
| `DELETE /services/delete?tenant=…&org=…&app=…&fileId=…` | 删除文档及其工具 |
| `/tenants/` | 管理员查询、新建、编辑和删除空租户 |
| `/credentials/?tenant=…` | 管理员管理当前租户的客户端凭证 |

租户标识创建后不能修改；包含服务或凭证规则的租户不能删除。工作空间内的凭证规则只能属于当前租户。管理接口使用管理员令牌，MCP 与函数查询接口使用客户端令牌。

更完整的协议行为、认证请求示例与错误字段见[技术参考（英文）](docs/reference.md)。API 结构定义可通过 `/openapi.json` 查看。

## 开发与参与贡献

```bash
# 后端回归测试
poetry run python -m unittest discover -s tests -v

# 前端构建与浏览器回归测试
cd web
npm ci
npx playwright install chromium
npm run build
npm run test:e2e
```

浏览器测试使用临时 SQLite 数据库及专用测试令牌，不读取已有业务数据库。也可以通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 指定本机 Chrome 的可执行文件。

后端代码位于 `app/`，React 管理台位于 `web/`，测试位于 `tests/` 和 `web/e2e/`。Python 依赖由 `pyproject.toml`、`poetry.lock` 管理，前端依赖由 `web/package.json`、`web/package-lock.json` 管理。

欢迎通过 [GitHub Issues](https://github.com/stonyz/simpleMcp/issues) 提交问题和建议。参与开发时，请先派生 [stonyz/simpleMcp](https://github.com/stonyz/simpleMcp) 仓库，创建分支，运行相关检查后提交拉取请求。

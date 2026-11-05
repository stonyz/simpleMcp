import { test, expect, type Page, type APIRequestContext } from '@playwright/test';

test.use({ locale: 'zh-CN' });

async function selectTenant(page: Page, request: APIRequestContext, tenant: string) {
  const headers = { Authorization: 'Bearer admin-e2e-token' };
  const existing = await request.get(`/tenants/${tenant}`, { headers });
  if (existing.status() === 404) {
    const created = await request.post('/tenants/', { headers, data: { id: tenant, name: tenant } });
    expect(created.ok()).toBeTruthy();
  } else expect(existing.ok()).toBeTruthy();
  await expect(page.getByRole('heading', { name: '选择租户', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '刷新', exact: true }).click();
  await page.getByRole('button', { name: `进入租户 ${tenant}`, exact: true }).click();
  await expect(page.getByRole('button', { name: '切换租户', exact: true })).toBeVisible();
}

test('tenant portal fixes workspace scope and isolates credentials when returning to choose another team', async ({ page, request }) => {
  const headers = { Authorization: 'Bearer admin-e2e-token' };
  await page.goto('/admin/');
  await expect(page.getByLabel('Tenant', { exact: true })).toHaveCount(0);
  await page.getByLabel('访问 Token').fill('admin-e2e-token');
  await page.getByRole('button', { name: '进入管理台' }).click();
  await page.getByRole('button', { name: '新增租户', exact: true }).click();
  await page.getByLabel('租户标识').fill('workspace-a');
  await page.getByLabel('租户名称').fill('工作组 A');
  await page.getByLabel('租户说明').fill('独立工作空间');
  await page.getByRole('button', { name: '保存租户' }).click();
  await expect(page.getByText('工作组 A', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '编辑租户 workspace-a', exact: true }).click();
  await expect(page.getByLabel('租户标识')).toBeDisabled();
  await page.getByLabel('租户名称').fill('工作组 A（已更新）');
  await page.getByRole('button', { name: '保存租户' }).click();
  await expect(page.getByText('工作组 A（已更新）', { exact: true })).toBeVisible();
  await expect(page.locator('.ant-modal-content')).toHaveCount(0);
  await page.screenshot({ path: 'test-results/tenant-portal-desktop.png', fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: '进入租户 workspace-a', exact: true }).click();
  await expect(page.getByLabel('切换 Tenant')).toHaveCount(0);
  await expect(page.locator('.topbar')).toContainText('工作组 A');
  await page.getByRole('button', { name: '访问凭证', exact: true }).click();
  await page.getByRole('button', { name: '创建凭证', exact: true }).click();
  await expect(page.getByLabel('租户', { exact: true })).toHaveCount(0);
  await page.getByLabel('凭证名称').fill('A-only credential');
  await page.getByRole('button', { name: '保存凭证', exact: true }).click();
  await expect(page.getByText('此 Token 仅显示一次')).toBeVisible();
  await page.getByRole('button', { name: '我已保存' }).click();
  await expect(page.getByText('A-only credential', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '切换租户' }).click();
  await selectTenant(page, request, 'workspace-b');
  await page.getByRole('button', { name: '访问凭证', exact: true }).click();
  await expect(page.getByText('A-only credential', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '切换租户' }).click();
  await page.getByRole('button', { name: '更多租户操作 workspace-b', exact: true }).click();
  await page.getByRole('menuitem', { name: '删除租户' }).click();
  await page.getByRole('button', { name: '确认删除租户' }).click();
  await expect(page.getByRole('button', { name: '进入租户 workspace-b', exact: true })).toHaveCount(0);
  await selectTenant(page, request, 'workspace-a');
  await page.getByRole('button', { name: '访问凭证', exact: true }).click();
  await expect(page.getByText('A-only credential', { exact: true })).toBeVisible();
  const scoped = await request.get('/credentials/?tenant=workspace-a', { headers });
  expect((await scoped.json()).items[0].rules.every((rule: { tenant: string }) => rule.tenant === 'workspace-a')).toBeTruthy();
});

test('database credentials can restrict services, edit rules, disable and rotate from the console', async ({ page, request }) => {
  const admin = { Authorization: 'Bearer admin-e2e-token' };
  for (const [fileId, name] of [['allowed', 'Allowed API'], ['hidden', 'Hidden API']]) {
    const response = await request.post('/services/register?tenant=scope-test', { headers: admin, data: {
      org: 'scoped-org', app: 'scoped-app', fileId, fileName: `${fileId}.yaml`, yaml_content: JSON.stringify({
        openapi: '3.0.3', info: { title: name, version: '1' }, paths: { [`/${fileId}`]: { get: { operationId: fileId } } } }) } });
    expect(response.ok()).toBeTruthy();
  }
  await page.goto('/admin/');
  await page.getByLabel('访问 Token').fill('admin-e2e-token');
  await page.getByRole('button', { name: '进入管理台' }).click();
  await selectTenant(page, request, 'scope-test');
  await page.getByRole('button', { name: '访问凭证', exact: true }).click();
  await page.getByRole('button', { name: '创建凭证', exact: true }).click();
  await page.getByLabel('凭证名称').fill('Partner A');
  await page.getByLabel('授权范围').press('ArrowDown');
  await page.getByText('指定服务', { exact: true }).click();
  await page.getByLabel('组织', { exact: true }).fill('scoped-org');
  await page.getByLabel('应用', { exact: true }).fill('scoped-app');
  await page.getByLabel('服务', { exact: true }).press('ArrowDown');
  await page.locator('.ant-select-item-option[title="Allowed API · allowed.yaml · allowed"]').click();
  await page.getByLabel('凭证名称').click();
  await page.getByRole('button', { name: '保存凭证', exact: true }).click();
  await expect(page.getByText('此 Token 仅显示一次')).toBeVisible();
  const secret = (await page.locator('.credential-secret').innerText()).match(/mcp_[A-Za-z0-9_-]+/)![0];
  const rpc = (token: string) => request.post('/mcp?tenant=scope-test', { headers: { Authorization: `Bearer ${token}` },
    data: { jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} } });
  expect((await (await rpc(secret)).json()).result.tools.map((item: { name: string }) => item.name)).toEqual(['allowed']);
  const denied = await request.post('/mcp?tenant=scope-test', { headers: { Authorization: `Bearer ${secret}` },
    data: { jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'hidden', arguments: {} } } });
  expect(denied.status()).toBe(403);
  expect((await request.get('/services/access?tenant=scope-test', { headers: { Authorization: `Bearer ${secret}` } })).status()).toBe(403);
  await page.getByRole('button', { name: '我已保存' }).click();
  await expect(page.getByText(secret, { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '编辑权限' }).click();
  await page.getByRole('button', { name: '添加授权规则' }).click();
  await expect(page.getByText('授权规则 2', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '保存凭证', exact: true }).click();
  expect((await (await rpc(secret)).json()).result.tools.map((item: { name: string }) => item.name).sort()).toEqual(['allowed', 'hidden']);
  await page.getByRole('switch', { name: '启用 Partner A' }).click();
  await expect(page.getByText('已停用', { exact: true })).toBeVisible();
  expect((await rpc(secret)).status()).toBe(401);
  await page.getByRole('switch', { name: '启用 Partner A' }).click();
  await expect(page.getByText('有效', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '轮换', exact: true }).click();
  await page.getByRole('button', { name: '确认轮换', exact: true }).click();
  const rotated = (await page.locator('.credential-secret').innerText()).match(/mcp_[A-Za-z0-9_-]+/)![0];
  expect(rotated).not.toBe(secret);
  expect((await rpc(secret)).status()).toBe(401);
  expect((await rpc(rotated)).status()).toBe(200);
  await page.getByRole('button', { name: '我已保存' }).click();
  await expect(page.locator('.ant-modal-content')).toHaveCount(0);
  await page.screenshot({ path: 'test-results/credentials-desktop.png', fullPage: true, animations: 'disabled' });
  await page.getByRole('button', { name: '删除', exact: true }).click();
  await page.getByRole('button', { name: '确认删除凭证' }).click();
  await expect(page.getByText('Partner A', { exact: true })).toHaveCount(0);
  expect((await rpc(rotated)).status()).toBe(401);
});

test('registration offers persisted org/app candidates and clears app on org change', async ({ page, request }) => {
  for (const [org, app] of [['catalog-org-a', 'catalog-app-a'], ['catalog-org-b', 'catalog-app-b']]) {
    const response = await request.post('/services/register?tenant=catalog-test', {
      headers: { Authorization: 'Bearer admin-e2e-token' },
      data: { org, app, fileName: 'catalog.yaml', yaml_content: JSON.stringify({
        openapi: '3.0.3', info: { title: org, version: '1' }, paths: {} }) },
    });
    expect(response.ok()).toBeTruthy();
  }
  await page.goto('/admin/');
  await page.getByLabel('访问 Token').fill('admin-e2e-token');
  await page.getByRole('button', { name: '进入管理台' }).click();
  await selectTenant(page, request, 'catalog-test');
  await page.getByRole('button', { name: '注册服务' }).first().click();
  await page.getByLabel('组织 Org').click();
  await page.locator('.ant-select-item-option[title="catalog-org-a"]').click();
  await page.getByLabel('应用 App').click();
  await expect(page.locator('.ant-select-item-option[title="catalog-app-a"]')).toBeVisible();
  await expect(page.locator('.ant-select-item-option[title="catalog-app-b"]')).toHaveCount(0);
  await page.locator('.ant-select-item-option[title="catalog-app-a"]').click();
  await page.getByLabel('组织 Org').fill('catalog-org-b');
  await expect(page.getByLabel('应用 App')).toHaveValue('');
  await page.getByLabel('应用 App').click();
  await expect(page.locator('.ant-select-item-option[title="catalog-app-b"]')).toBeVisible();
});

const yaml = `openapi: 3.0.3
info:
  title: Browser Test API
  version: "1.0"
servers:
  - url: https://example.com
paths:
  /status:
    get:
      operationId: browserStatus
      summary: 查询状态
      responses:
        '200':
          description: OK
`;

test('register, inspect, update, connect, scope and delete a service', async ({ page, request }) => {
  await page.goto('/admin/');
  await page.getByLabel('访问 Token').fill('wrong-token');
  await page.getByRole('button', { name: '进入管理台' }).click();
  await expect(page.getByText('Token 无效或已失效')).toBeVisible();
  await page.getByLabel('访问 Token').fill('admin-e2e-token');
  await page.getByRole('button', { name: '进入管理台' }).click();
  await selectTenant(page, request, 'browser-test');
  await page.getByRole('button', { name: '注册服务' }).first().click();
  await page.getByLabel('组织 Org').fill('browser-org');
  await page.getByLabel('应用 App').fill('browser-app');
  await page.getByLabel('文件名').fill('browser.yaml');
  await page.getByRole('button', { name: '纯文本编辑' }).click();
  await page.getByLabel('OpenAPI 文档').fill(yaml);
  await page.getByRole('button', { name: '校验并预览' }).click();
  await expect(page.getByText('新增 1')).toBeVisible();
  await page.getByRole('button', { name: '确认保存' }).click();
  await expect(page.getByRole('button', { name: 'Browser Test API', exact: true })).toBeVisible();
  await page.screenshot({ path: 'test-results/desktop.png', fullPage: true });
  await page.getByRole('button', { name: '切换租户' }).click();
  await selectTenant(page, request, 'another-tenant');
  await expect(page.getByText('还没有注册服务')).toBeVisible();
  await page.getByRole('button', { name: '切换租户' }).click();
  await selectTenant(page, request, 'browser-test');
  await page.getByRole('button', { name: 'Browser Test API', exact: true }).click();
  await expect(page.getByText('browserStatus', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: '接入配置' }).click();
  await expect(page.locator('pre').filter({ hasText: 'YOUR_TOKEN' })).toBeVisible();
  await page.getByRole('button', { name: '关闭' }).click();
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByRole('button', { name: '纯文本编辑' }).click();
  await page.getByLabel('OpenAPI 文档').fill(yaml.replace('Browser Test API', 'Updated API').replace('browserStatus', 'browserStatusV2'));
  await page.getByRole('button', { name: '校验并预览' }).click();
  await expect(page.getByText('移除 1')).toBeVisible();
  await page.getByRole('button', { name: '确认保存' }).click();
  await expect(page.getByRole('button', { name: 'Updated API', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '删除', exact: true }).click();
  await page.getByRole('button', { name: '确认删除' }).click();
  await expect(page.getByRole('button', { name: 'Updated API', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '退出' }).click();
  await expect(page.getByLabel('访问 Token')).toHaveValue('');
});

test('mobile login and service list have no horizontal overflow', async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/admin/');
  await page.getByLabel('访问 Token').fill('admin-e2e-token');
  await page.getByRole('button', { name: '进入管理台' }).click();
  await expect(page.getByRole('heading', { name: '选择租户', exact: true })).toBeVisible();
  await expect(page.locator('.ant-card-loading')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/tenant-portal-mobile.png', fullPage: true, animations: 'disabled' });
  await selectTenant(page, request, 'empty-mobile');
  await expect(page.getByText('还没有注册服务')).toBeVisible();
  await expect(page.locator('.ant-spin-spinning')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/mobile.png', fullPage: true });
  await page.getByRole('button', { name: '访问凭证', exact: true }).click();
  await expect(page.getByRole('button', { name: '创建凭证', exact: true })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/credentials-mobile.png', fullPage: true });
  await page.getByRole('button', { name: '创建凭证', exact: true }).click();
  await expect(page.getByLabel('凭证名称')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/credential-editor-mobile.png', fullPage: true, animations: 'disabled' });
});

test('local Monaco, upload, preview invalidation and conflict rejection', async ({ page, request }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/admin/');
  await page.getByLabel('访问 Token').fill('admin-e2e-token');
  await page.getByRole('button', { name: '进入管理台' }).click();
  await selectTenant(page, request, 'upload-test');
  await page.getByRole('button', { name: '注册服务' }).first().click();
  await expect(page.getByRole('textbox', { name: 'OpenAPI 代码编辑器' })).toBeVisible();
  await page.getByLabel('组织 Org').fill('upload-org');
  await page.getByLabel('应用 App').fill('upload-app');
  await page.locator('input[type=file]').setInputFiles({ name: 'upload.yaml', mimeType: 'application/yaml', buffer: Buffer.from(yaml) });
  await expect(page.getByLabel('文件名')).toHaveValue('upload.yaml');
  let releasePreview!: () => void;
  const previewGate = new Promise<void>(resolve => { releasePreview = resolve; });
  await page.route('**/services/preview?*', async route => { await previewGate; await route.continue(); }, { times: 1 });
  await page.getByRole('button', { name: '校验并预览' }).click();
  await expect(page.getByLabel('组织 Org')).toBeDisabled();
  await expect(page.getByLabel('应用 App')).toBeDisabled();
  releasePreview();
  await expect(page.getByText('新增 1')).toBeVisible();
  await page.getByLabel('文件名').fill('renamed.yaml');
  await expect(page.getByRole('button', { name: '确认保存' })).toBeDisabled();
  await page.getByRole('button', { name: '校验并预览' }).click();
  await page.getByRole('button', { name: '确认保存' }).click();
  await expect(page.getByRole('button', { name: 'Browser Test API', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '注册服务' }).first().click();
  await page.getByLabel('组织 Org').fill('upload-org');
  await page.getByLabel('应用 App').fill('upload-app');
  await page.locator('input[type=file]').setInputFiles({ name: 'duplicate.yaml', mimeType: 'application/yaml', buffer: Buffer.from(yaml) });
  await page.getByRole('button', { name: '校验并预览' }).click();
  await expect(page.getByText('存在工具重名冲突，无法保存')).toBeVisible();
  await expect(page.getByRole('button', { name: '确认保存' })).toBeDisabled();
  await page.getByRole('button', { name: '纯文本编辑' }).click();
  await page.getByLabel('OpenAPI 文档').fill('paths: []');
  await page.getByRole('button', { name: '校验并预览' }).click();
  await expect(page.getByText('文档必须包含 paths 对象')).toBeVisible();
  expect(errors).toEqual([]);
});

test('authorization forms validate fields, serialize each type and preserve secrets on edit', async ({ page, request }) => {
  await page.goto('/admin/');
  await page.getByLabel('访问 Token').fill('admin-e2e-token');
  await page.getByRole('button', { name: '进入管理台' }).click();
  await selectTenant(page, request, 'auth-form-test');
  await page.getByRole('button', { name: '注册服务' }).first().click();
  await page.getByLabel('组织 Org').fill('auth-org');
  await page.getByLabel('应用 App').fill('auth-app');
  await page.getByLabel('授权方式').press('ArrowDown');
  await page.getByRole('option', { name: 'HTTP Basic', exact: true }).click();
  await page.getByRole('button', { name: '校验并预览' }).click();
  await expect(page.getByText('请输入用户名')).toBeVisible();
  await expect(page.getByText('请输入密码')).toBeVisible();
  await page.getByLabel('用户名 username').fill('test-user');
  await page.getByLabel('密码 password', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: '校验并预览' }).click();
  await expect(page.getByRole('button', { name: '确认保存' })).toBeEnabled();
  const saved = page.waitForRequest(r => r.url().includes('/services/save?'));
  await page.getByRole('button', { name: '确认保存' }).click();
  const basic = (await saved).postDataJSON();
  expect(basic.auth_type).toBe('basic');
  expect(JSON.parse(basic.auth)).toEqual({ username: 'test-user', password: 'test-password' });
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await expect(page.getByText('当前授权：HTTP Basic')).toBeVisible();
  await expect(page.getByLabel('密码 password', { exact: true })).toHaveCount(0);
  await page.getByLabel('授权方式').press('ArrowDown');
  await page.getByRole('option', { name: 'Bearer Token', exact: true }).click();
  await page.getByLabel('访问令牌 access_token').fill('business-token');
  await page.getByRole('button', { name: '校验并预览' }).click();
  const bearerRequest = page.waitForRequest(r => r.url().includes('/services/preview?'));
  // Revalidate after another field change to inspect the exact payload.
  await page.getByLabel('文件名').fill('auth.yaml');
  await page.getByRole('button', { name: '校验并预览' }).click();
  expect(JSON.parse((await bearerRequest).postDataJSON().auth)).toEqual({ access_token: 'business-token' });
  await page.getByLabel('授权方式').press('ArrowDown');
  await page.getByRole('option', { name: 'OAuth2 · Client Credentials', exact: true }).click();
  await page.getByLabel('令牌地址 token_url').fill('invalid');
  await page.getByLabel('客户端 ID client_id').fill('client-id');
  await page.getByLabel('客户端密钥 client_secret').fill('client-secret');
  await page.getByRole('button', { name: '校验并预览' }).click();
  await expect(page.getByText('请输入有效的 HTTP/HTTPS 地址')).toBeVisible();
  await page.getByLabel('令牌地址 token_url').fill('https://auth.example/token');
  const oauthRequest = page.waitForRequest(r => r.url().includes('/services/preview?'));
  await page.getByRole('button', { name: '校验并预览' }).click();
  expect(JSON.parse((await oauthRequest).postDataJSON().auth)).toEqual({ client_id: 'client-id', client_secret: 'client-secret', token_url: 'https://auth.example/token', scopes: [] });
  await page.getByLabel('授权方式').press('ArrowDown');
  await page.getByRole('option', { name: '无需认证（清除配置）', exact: true }).click();
  await expect(page.getByRole('button', { name: '确认保存' })).toBeDisabled();
  await page.getByRole('button', { name: '校验并预览' }).click();
  const cleared = page.waitForRequest(r => r.url().includes('/services/save?'));
  await page.getByRole('button', { name: '确认保存' }).click();
  expect((await cleared).postDataJSON().auth_action).toBe('clear');
});

import { test, expect } from '@playwright/test';

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

test('register, inspect, update, connect, scope and delete a service', async ({ page }) => {
  await page.goto('/admin/');
  await page.getByLabel('访问 Token').fill('wrong-token');
  await page.getByLabel('Tenant').fill('browser-test');
  await page.getByRole('button', { name: '进入管理台' }).click();
  await expect(page.getByText('Token 无效或已失效')).toBeVisible();
  await page.getByLabel('访问 Token').fill('admin-e2e-token');
  await page.getByRole('button', { name: '进入管理台' }).click();
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
  await page.getByLabel('切换 Tenant').fill('another-tenant');
  await page.getByRole('button', { name: '切换租户' }).click();
  await expect(page.getByText('还没有注册服务')).toBeVisible();
  await page.getByLabel('切换 Tenant').fill('browser-test');
  await page.getByRole('button', { name: '切换租户' }).click();
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

test('mobile login and service list have no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/admin/');
  await page.getByLabel('访问 Token').fill('admin-e2e-token');
  await page.getByLabel('Tenant').fill('empty-mobile');
  await page.getByRole('button', { name: '进入管理台' }).click();
  await expect(page.getByText('还没有注册服务')).toBeVisible();
  await expect(page.locator('.ant-spin-spinning')).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: 'test-results/mobile.png', fullPage: true });
});

test('local Monaco, upload, preview invalidation and conflict rejection', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/admin/');
  await page.getByLabel('访问 Token').fill('admin-e2e-token');
  await page.getByLabel('Tenant').fill('upload-test');
  await page.getByRole('button', { name: '进入管理台' }).click();
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

test('authorization forms validate fields, serialize each type and preserve secrets on edit', async ({ page }) => {
  await page.goto('/admin/');
  await page.getByLabel('访问 Token').fill('admin-e2e-token');
  await page.getByLabel('Tenant', { exact: true }).fill('auth-form-test');
  await page.getByRole('button', { name: '进入管理台' }).click();
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

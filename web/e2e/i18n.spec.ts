import { test, expect, type Page } from '@playwright/test';
test.use({ locale: 'en-US' });
async function chooseLanguage(page: Page, preference: 'system' | 'en' | 'zh') {
  await page.getByRole('button', { name: /^(Language|语言)/ }).click();
  await page.getByRole('menuitem', { name: preference === 'system' ? /^(System default|跟随系统)$/ : preference === 'en' ? 'English' : '简体中文', exact: true }).click();
}

test('system language, live switching, persistence and English tenant forms', async ({ page, request }) => {
  await page.goto('/admin/');
  await expect(page.getByRole('heading', { name: 'Sign in to the console' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  const languageButton = page.getByRole('button', { name: /^Language/ });
  await expect(languageButton).toHaveText('English');
  await expect(page.getByRole('combobox')).toHaveCount(0);
  await languageButton.click();
  await expect(page.locator('.ant-dropdown-menu-item-selected')).toHaveText('System default');
  await page.getByRole('menuitem', { name: 'System default', exact: true }).click();
  await page.getByRole('button', { name: 'Sign in to the console' }).click();
  await expect(page.getByText('Enter your access token', { exact: true })).toBeVisible();
  await chooseLanguage(page, 'zh');
  await expect(page.getByRole('heading', { name: '进入管理台' })).toBeVisible();
  await expect(page.getByText('请输入访问 Token', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: '进入管理台' })).toBeVisible();
  await chooseLanguage(page, 'system');
  await expect(page.getByRole('heading', { name: 'Sign in to the console' })).toBeVisible();
  await page.getByLabel('Access token', { exact: true }).fill('admin-e2e-token');
  await page.getByRole('button', { name: 'Sign in to the console' }).click();
  await expect(page.getByRole('heading', { name: 'Choose a tenant' })).toBeVisible();
  await page.getByRole('button', { name: 'Add tenant', exact: true }).click();
  await expect(page.getByLabel('Tenant ID', { exact: true })).toBeVisible();
  const seeded = await request.post('/tenants/', { headers: { Authorization: 'Bearer admin-e2e-token' }, data: { id: 'duplicate-language', name: 'Existing tenant' } });
  expect(seeded.ok()).toBeTruthy();
  await page.getByLabel('Tenant ID', { exact: true }).fill('duplicate-language');
  await page.getByLabel('Tenant name', { exact: true }).fill('Duplicate');
  await page.getByRole('button', { name: 'Save tenant', exact: true }).click();
  await expect(page.getByText('Tenant identifier already exists', { exact: true })).toBeVisible();
});
test('Chinese locales and unsupported language fallback', async ({ browser }) => {
  for (const [locale, heading, lang] of [['zh-TW', '进入管理台', 'zh-CN'], ['fr-FR', 'Sign in to the console', 'en']]) {
    const context = await browser.newContext({ locale });
    const page = await context.newPage();
    await page.goto('/admin/');
    await expect(page.getByRole('heading', { name: heading })).toBeVisible();
    await expect(page.locator('html')).toHaveAttribute('lang', lang);
    await context.close();
  }
});

test('English workspace covers service details, authorization and credential rules without losing edits', async ({ page, request }) => {
  const headers = { Authorization: 'Bearer admin-e2e-token' };
  await request.post('/tenants/', { headers, data: { id: 'english-team', name: 'English team' } });
  const registered = await request.post('/services/register?tenant=english-team', { headers, data: {
    org: 'demo', app: 'api', fileId: 'english-api', fileName: 'english.yaml',
    yaml_content: 'openapi: 3.0.3\ninfo:\n  title: English API\n  version: "1.0"\npaths: {}',
  } });
  expect(registered.ok()).toBeTruthy();
  await page.goto('/admin/');
  await page.getByLabel('Access token', { exact: true }).fill('admin-e2e-token');
  await page.getByRole('button', { name: 'Sign in to the console' }).click();
  await page.getByRole('button', { name: 'Enter tenant english-team', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Services', exact: true })).toBeVisible();
  await expect(page.locator('.main-content')).not.toContainText(/\p{Script=Han}/u);
  await page.getByRole('button', { name: 'English API', exact: true }).click();
  await expect(page.getByText('Service details', { exact: true })).toBeVisible();
  await expect(page.locator('.ant-drawer-body')).not.toContainText(/\p{Script=Han}/u);
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await chooseLanguage(page, 'zh');
  await chooseLanguage(page, 'en');
  await page.getByRole('button', { name: /Register service/ }).click();
  await page.getByRole('button', { name: 'Plain text editor', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'OpenAPI document', exact: true })).not.toHaveValue(/获取服务状态/);
  await expect(page.getByText('Authorization settings', { exact: true })).toBeVisible();
  await page.getByLabel('Filename', { exact: true }).fill('keep-my-edits.yaml');
  await page.getByRole('button', { name: 'Validate and preview' }).click();
  await expect(page.getByText('Change preview', { exact: true })).toHaveCount(0);
  await expect(page.locator('.ant-drawer-body')).not.toContainText(/\p{Script=Han}/u);
  await expect(page.locator('.ant-drawer .language-selector')).toHaveCount(0);
  const preferencesPage = await page.context().newPage();
  await preferencesPage.goto('/admin/');
  await chooseLanguage(preferencesPage, 'zh');
  await expect(page.getByLabel('文件名', { exact: true })).toHaveValue('keep-my-edits.yaml');
  await chooseLanguage(preferencesPage, 'en');
  await preferencesPage.close();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Access credentials', exact: true }).first().click();
  await page.getByRole('button', { name: 'Create credential', exact: true }).click();
  await expect(page.getByText('Authorization rule 1', { exact: true })).toBeVisible();
  await expect(page.locator('.ant-drawer-body')).not.toContainText(/\p{Script=Han}/u);
  await page.screenshot({ path: 'test-results/i18n-english-credentials.png', fullPage: true, animations: 'disabled' });
});

test('system changes are observed and unavailable storage does not break language switching', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(Storage.prototype, 'getItem', { value() { throw new Error('Storage blocked'); } });
    Object.defineProperty(Storage.prototype, 'setItem', { value() { throw new Error('Storage blocked'); } });
  });
  await page.goto('/admin/');
  await expect(page.getByRole('heading', { name: 'Sign in to the console' })).toBeVisible();
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'languages', { value: ['zh-CN'], configurable: true });
    window.dispatchEvent(new Event('languagechange'));
  });
  await expect(page.getByRole('heading', { name: '进入管理台' })).toBeVisible();
  await chooseLanguage(page, 'en');
  await expect(page.getByRole('heading', { name: 'Sign in to the console' })).toBeVisible();
});

test('existing API errors follow language changes', async ({ page }) => {
  await page.goto('/admin/');
  await chooseLanguage(page, 'zh');
  await page.getByLabel('访问 Token', { exact: true }).fill('invalid-token');
  await page.getByRole('button', { name: '进入管理台' }).click();
  await expect(page.getByRole('alert')).toContainText('Token 无效或已失效');
  await chooseLanguage(page, 'en');
  await expect(page.getByRole('alert')).toContainText('Your token is invalid or expired');
});

test('new samples use the selected language after a Chinese startup on mobile', async ({ browser, request }) => {
  const created = await request.post('/tenants/', { headers: { Authorization: 'Bearer admin-e2e-token' }, data: { id: 'sample-language', name: 'Sample language' } });
  expect(created.ok()).toBeTruthy();
  const context = await browser.newContext({ locale: 'zh-CN', viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  await page.goto('/admin/');
  await chooseLanguage(page, 'en');
  await expect(page.getByRole('heading', { name: 'Sign in to the console' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: 'test-results/i18n-english-login-mobile.png', fullPage: true, animations: 'disabled' });
  await page.getByLabel('Access token', { exact: true }).fill('admin-e2e-token');
  await page.getByRole('button', { name: 'Sign in to the console' }).click();
  await page.getByRole('button', { name: 'Enter tenant sample-language', exact: true }).click();
  await page.getByRole('button', { name: /Register service/ }).first().click();
  await page.getByRole('button', { name: 'Plain text editor', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'OpenAPI document', exact: true })).toHaveValue(/summary: Get service status/);
  await context.close();
});

test('OpenAPI API errors use the selected language and update existing alerts', async ({ page, request }) => {
  const created = await request.post('/tenants/', { headers: { Authorization: 'Bearer admin-e2e-token' }, data: { id: 'error-language', name: 'Error language' } });
  expect(created.ok()).toBeTruthy();
  await page.goto('/admin/');
  await page.getByLabel('Access token', { exact: true }).fill('admin-e2e-token');
  await page.getByRole('button', { name: 'Sign in to the console' }).click();
  await page.getByRole('button', { name: 'Enter tenant error-language', exact: true }).click();
  await page.getByRole('button', { name: /Register service/ }).first().click();
  await page.getByLabel('Organization (Org)', { exact: true }).fill('audit');
  await page.getByLabel('Application (App)', { exact: true }).fill('audit');
  await page.getByRole('button', { name: 'Plain text editor', exact: true }).click();
  await page.getByRole('textbox', { name: 'OpenAPI document', exact: true }).fill('openapi: 3.0.3\ninfo:\n  title: Audit\n  version: "1"\n');
  await page.getByRole('button', { name: 'Validate and preview' }).click();
  await expect(page.locator('.ant-drawer').getByRole('alert')).not.toContainText(/\p{Script=Han}/u);
  await expect(page.locator('.ant-drawer').getByRole('alert')).toContainText('paths');
  const preferences = await page.context().newPage();
  await preferences.goto('/admin/');
  await chooseLanguage(preferences, 'zh');
  await expect(page.locator('.ant-drawer').getByRole('alert')).toContainText('文档必须包含 paths 对象');
  await expect(page.getByLabel('文件名', { exact: true })).toHaveValue('openapi.yaml');
  await chooseLanguage(preferences, 'en');
  await expect(page.locator('.ant-drawer').getByRole('alert')).not.toContainText(/\p{Script=Han}/u);
  await preferences.close();
});

test('error codes drive translation independently of English wording and preserve parameters', async ({ page }) => {
  await page.route('**/tenants/**', route => route.fulfill({ status: 400, json: {
    error: { code: 'document_operation_field_string', message: 'Server wording may change',
      params: { method: 'get', path: '/原文/{field}', field: 'summary' } },
  } }));
  await page.goto('/admin/');
  await page.getByLabel('Access token', { exact: true }).fill('test-only');
  await page.getByRole('button', { name: 'Sign in to the console' }).click();
  await expect(page.getByRole('alert')).toContainText('get /原文/{field}: summary must be a string');
  await chooseLanguage(page, 'zh');
  await expect(page.getByRole('alert')).toContainText('get /原文/{field}: summary 必须是字符串');
  await expect(page.getByLabel('访问 Token', { exact: true })).toHaveValue('test-only');
});

test('field diagnostics and network failures are localized when an existing error changes language', async ({ page }) => {
  await page.route('**/tenants/**', route => route.fulfill({ status: 422, json: {
    error: { code: 'validation_error', message: 'Request validation failed', details: [
      { type: 'string_too_short', loc: ['body', 'query'], msg: 'String should have at least 1 character' },
      { type: 'expiry_timezone_required', code: 'expiry_timezone_required', params: {}, loc: ['body', 'expires_at'], msg: 'Expiry must include a timezone' },
    ] },
  } }));
  await page.goto('/admin/');
  await page.getByLabel('Access token', { exact: true }).fill('test-only');
  await page.getByRole('button', { name: 'Sign in to the console' }).click();
  await expect(page.getByRole('alert')).toContainText('query: Value is too short');
  await expect(page.getByRole('alert')).toContainText('expires_at: Expiry must include a timezone');
  await chooseLanguage(page, 'zh');
  await expect(page.getByRole('alert')).toContainText('query: 值过短');
  await expect(page.getByRole('alert')).toContainText('expires_at: 到期时间必须包含时区');
  await page.unrouteAll();
  await page.route('**/tenants/**', route => route.abort('failed'));
  await page.getByRole('button', { name: '进入管理台' }).click();
  await expect(page.getByRole('alert')).toContainText('网络请求失败');
  await chooseLanguage(page, 'en');
  await expect(page.getByRole('alert')).toContainText('Network request failed');
});

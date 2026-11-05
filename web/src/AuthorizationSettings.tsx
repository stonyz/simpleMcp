import { t, useLanguage } from './i18n';
import { Alert, Form, Input, Select, Typography } from 'antd';
import { LockOutlined } from '@ant-design/icons';
import type { Service, ServiceInput } from './api';

export type AuthorizationMode = 'keep' | 'none' | 'bearer' | 'basic' | 'oauth2';
export interface EditorValues {
  org: string; app: string; fileName: string;
  auth_mode: AuthorizationMode;
  credentials?: { username?: string; password?: string; access_token?: string;
    client_id?: string; client_secret?: string; token_url?: string; scopes?: string[] };
}
export const authorizationLabels = (): Record<string, string> => ({
  none: t("无需认证"), bearer: 'Bearer Token', basic: 'HTTP Basic',
  oauth2: 'OAuth2 · Client Credentials', unknown: t("已有配置（类型未知）"),
});

export function authorizationInput(values: EditorValues): Pick<ServiceInput, 'auth_action' | 'auth_type' | 'auth'> {
  if (values.auth_mode === 'keep') return { auth_action: 'keep' };
  if (values.auth_mode === 'none') return { auth_action: 'clear' };
  const c = values.credentials || {};
  const credentials = values.auth_mode === 'bearer' ? { access_token: c.access_token }
    : values.auth_mode === 'basic' ? { username: c.username, password: c.password }
    : { client_id: c.client_id, client_secret: c.client_secret, token_url: c.token_url, scopes: c.scopes || [] };
  return { auth_action: 'replace', auth_type: values.auth_mode, auth: JSON.stringify(credentials) };
}

export default function AuthorizationSettings({ row }: { row: Service | null }) {
  useLanguage();
  const mode: AuthorizationMode = Form.useWatch('auth_mode');
  return <section className="auth-section">
    <div className="section-heading"><h3><LockOutlined /> {t("授权设置")}</h3>
      {row && <Typography.Text type="secondary">{t("当前授权：")}{authorizationLabels()[row.auth_type || (row.auth_configured ? 'unknown' : 'none')]}</Typography.Text>}
    </div>
    <p className="muted">{t("用于 MCP Server 访问业务 API，与管理台登录 Token 独立。")}</p>
    <Form.Item label={t("授权方式")} name="auth_mode" rules={[{ required: true }]}>
      <Select virtual={false} options={[
        ...(row ? [{ value: 'keep', label: t("保留现有授权") }] : []),
        { value: 'none', label: row ? t("无需认证（清除配置）") : t("无需认证") },
        { value: 'bearer', label: 'Bearer Token' },
        { value: 'basic', label: 'HTTP Basic' },
        { value: 'oauth2', label: 'OAuth2 · Client Credentials' },
      ]} />
    </Form.Item>
    {mode === 'keep' && <p className="auth-hint">{t("保持服务当前授权不变。已有用户名、令牌和密钥均不回显；切换授权方式时请填写完整的新凭据。")}</p>}
    {mode === 'none' && <p className="auth-hint">{t("不保存默认认证凭据。若 OpenAPI 声明了认证要求，调用方仍需提供相应凭据。")}</p>}
    {mode === 'bearer' && <>
      <Form.Item label={t("访问令牌 access_token")} name={['credentials', 'access_token']} preserve={false}
        rules={[{ required: true, whitespace: true, message: t("请输入访问令牌") }, { max: 32768 }]}
        extra={t("只填写令牌内容，无需添加 Bearer 前缀。调用时自动发送 Authorization: Bearer …。")}>
        <Input.Password autoComplete="new-password" placeholder={t("业务 API 的访问令牌")} />
      </Form.Item>
    </>}
    {mode === 'basic' && <>
      <div className="auth-fields-grid">
        <Form.Item label={t("用户名 username")} name={['credentials', 'username']} preserve={false}
          rules={[{ required: true, whitespace: true, message: t("请输入用户名") }, { max: 4096 }]}>
          <Input autoComplete="off" placeholder={t("业务 API 用户名")} />
        </Form.Item>
        <Form.Item label={t("密码 password")} name={['credentials', 'password']} preserve={false}
          rules={[{ required: true, message: t("请输入密码") }, { max: 32768 }]}>
          <Input.Password autoComplete="new-password" placeholder={t("业务 API 密码")} />
        </Form.Item>
      </div>
      <p className="auth-hint">{t("调用时自动将用户名和密码编码为 HTTP Basic Authorization 请求头。")}</p>
    </>}
    {mode === 'oauth2' && <>
      <Alert type="info" showIcon message={t("Client Credentials 授权")} description={t("服务器使用客户端凭据获取并缓存访问令牌，再使用 Bearer Token 调用业务 API。")} style={{ marginBottom: 20 }} />
      <Form.Item label={t("令牌地址 token_url")} name={['credentials', 'token_url']} preserve={false} normalize={v => v.trim()}
        rules={[{ required: true, message: t("请输入令牌地址") }, { validator: (_, value) => {
          if (!value) return Promise.resolve();
          try { const url = new URL(value); if (['http:', 'https:'].includes(url.protocol) && !/\s/.test(value)) return Promise.resolve(); } catch { /* validated below */ }
          return Promise.reject(new Error(t("请输入有效的 HTTP/HTTPS 地址")));
        } }]}>
        <Input placeholder="https://auth.example.com/oauth/token" autoComplete="off" />
      </Form.Item>
      <div className="auth-fields-grid">
        <Form.Item label={t("客户端 ID client_id")} name={['credentials', 'client_id']} preserve={false}
          rules={[{ required: true, whitespace: true, message: t("请输入客户端 ID") }, { max: 4096 }]}>
          <Input placeholder="client_id" autoComplete="off" />
        </Form.Item>
        <Form.Item label={t("客户端密钥 client_secret")} name={['credentials', 'client_secret']} preserve={false}
          rules={[{ required: true, message: t("请输入客户端密钥") }, { max: 32768 }]}>
          <Input.Password placeholder="client_secret" autoComplete="new-password" />
        </Form.Item>
      </div>
      <Form.Item label={t("权限范围 scopes")} name={['credentials', 'scopes']} preserve={false} extra={t("可选。输入权限范围后按回车，或用空格、逗号分隔。")}>
        <Select mode="tags" tokenSeparators={[' ', ',']} open={false} placeholder={t("例如 read、write")} />
      </Form.Item>
    </>}
  </section>;
}

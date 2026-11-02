export interface Service {
  tenant: string; org: string; app: string; fileId: string; fileName: string;
  title: string; version: string; created_at: string; updated_at: string;
  tool_count: number; active_tool_count: number; auth_configured: boolean; error: string | null;
  auth_type?: 'none' | 'bearer' | 'basic' | 'oauth2' | 'unknown';
}
export interface Tool {
  name: string; description: string; method: string; url: string; timeout: number;
  active: boolean; input_schema: unknown; output_schema: unknown;
}
export interface Detail extends Service { document: string; tools: Tool[]; servers: { url: string }[] }
export interface Listing { items: Service[]; total: number; page: number; page_size: number }
export interface ServiceInput {
  org: string; app: string; fileId?: string; fileName: string; yaml_content: string;
  auth_action: 'keep' | 'replace' | 'clear'; auth?: string;
  auth_type?: 'bearer' | 'basic' | 'oauth2';
}
export interface Preview {
  title: string; version: string; tools: Tool[];
  changes: { added: string[]; removed: string[]; modified: string[]; unchanged: string[] };
  conflicts: { name: string; fileId: string; fileName: string }[];
}
export type Api = ReturnType<typeof createApi>;
export interface AccessScope { tenant: string; org: string | null; app: string | null; role: 'reader' | 'caller' | 'manager' }
export interface ScopeDirectory {
  tenant: string; service_count: number;
  organizations: { org: string; service_count: number; apps: { app: string; service_count: number }[] }[];
}
export interface AccessRule { tenant: string; org: string | null; app: string | null; services: string[] | null; operations: ('list' | 'call')[] }
export interface CredentialInput { name: string; description: string; enabled: boolean; expires_at: string | null; rules: AccessRule[] }
export interface Credential extends CredentialInput {
  id: string; token_prefix: string; status: 'active' | 'disabled' | 'expired';
  created_at: string; updated_at: string; last_used_at: string | null;
}
export interface IssuedCredential extends Credential { secret: string }
export interface CatalogService { tenant: string; org: string; app: string; fileId: string; title: string; fileName: string }

export function createApi(token: string, tenant: string, unauthorized?: () => void) {
  async function request<T>(path: string, query: Record<string, string | number> = {}, body?: unknown,
                            method = 'GET', signal?: AbortSignal): Promise<T> {
    const params = new URLSearchParams({ tenant, ...Object.fromEntries(Object.entries(query).map(([k, v]) => [k, String(v)])) });
    const response = await fetch(`${path}?${params}`, {
      method, signal, credentials: 'omit',
      headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok) {
      if (response.status === 401) {
        unauthorized?.();
        throw new Error('Token 无效或已失效');
      }
      const error = await response.json().catch(() => ({}));
      const detail = error.detail ?? error.error?.message;
      const diagnostics = error.error?.details ?? error.detail;
      const fields = Array.isArray(diagnostics) ? diagnostics.map((item: { loc?: string[]; msg?: string }) =>
        `${item.loc?.slice(1).join('.') || '输入'}: ${item.msg || '格式错误'}`).join('；') : '';
      throw new Error(fields || (typeof detail === 'string' ? detail : `请求失败（${response.status}），请检查输入或重试`));
    }
    return response.json();
  }
  const identity = (row: Service) => ({ org: row.org, app: row.app, fileId: row.fileId });
  return {
    credentials: (signal?: AbortSignal) => request<{ items: Credential[] }>('/credentials/', {}, undefined, 'GET', signal),
    credentialCatalog: (signal?: AbortSignal) => request<{ services: CatalogService[] }>('/credentials/catalog', {}, undefined, 'GET', signal),
    createCredential: (body: CredentialInput) => request<IssuedCredential>('/credentials/', {}, body, 'POST'),
    updateCredential: (id: string, body: CredentialInput) => request<Credential>(`/credentials/${id}`, {}, body, 'PUT'),
    rotateCredential: (id: string) => request<IssuedCredential>(`/credentials/${id}/rotate`, {}, undefined, 'POST'),
    setCredentialStatus: (id: string, enabled: boolean) => request<Credential>(`/credentials/${id}/status`, {}, { enabled }, 'PATCH'),
    deleteCredential: (id: string) => request(`/credentials/${id}`, {}, undefined, 'DELETE'),
    access: () => request<AccessScope>('/services/access'),
    scopes: (signal?: AbortSignal) => request<ScopeDirectory>('/services/scopes', {}, undefined, 'GET', signal),
    list: (query: Record<string, string | number>, signal?: AbortSignal) => request<Listing>('/services/', query, undefined, 'GET', signal),
    detail: (row: Service, signal?: AbortSignal) => request<Detail>('/services/detail', identity(row), undefined, 'GET', signal),
    preview: (body: ServiceInput) => request<Preview>('/services/preview', {}, body, 'POST'),
    save: (body: ServiceInput) => request<{ fileId: string }>('/services/save', {}, body, 'POST'),
    remove: (row: Service) => request('/services/delete', identity(row), undefined, 'DELETE'),
  };
}

export const time = (value: string) => value ? new Date(value.endsWith('Z') ? value : `${value}Z`).toLocaleString('zh-CN', { hour12: false }) : '—';
export const serviceKey = (row: Service) => JSON.stringify([row.tenant, row.org, row.app, row.fileId]);
export function downloadDocument(detail: Detail) {
  const blob = new Blob([detail.document], { type: 'application/yaml;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = detail.fileName.replace(/\.[^.]+$/, '') + '.yaml';
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

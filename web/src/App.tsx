import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, App as AntApp, AutoComplete, Badge, Breadcrumb, Button, Card, Empty, Form, Input, Space, Table, Tag, Tooltip, Typography } from 'antd';
import { ApiOutlined, AppstoreOutlined, ArrowRightOutlined, BookOutlined, CloudServerOutlined, CodeOutlined,
  FileTextOutlined, KeyOutlined, LockOutlined, LogoutOutlined, PlusOutlined, ReloadOutlined, SearchOutlined, SafetyCertificateOutlined, SwapOutlined } from '@ant-design/icons';
import { createApi, serviceKey, time, type AccessScope, type Api, type Listing, type ScopeDirectory, type Service, type Tenant } from './api';
import ServiceEditor from './ServiceEditor';
import ServiceDetail from './ServiceDetail';
import CredentialManager from './CredentialManager';
import TenantPortal from './TenantPortal';

interface Session { token: string; tenant: string; access: AccessScope; workspace: Tenant }
type LoginValues = Pick<Session, 'token'>;

function Brand() { return <div className="brand"><span className="brand-icon"><ApiOutlined /></span><span>MCP<span className="brand-sub">SERVICE CONSOLE</span></span></div>; }

function Login({ onLogin, expired }: { onLogin: (token: string) => void; expired: boolean }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(expired ? 'Token 无效或已失效，请重新登录' : '');
  async function enter(values: LoginValues) {
    setBusy(true); setError('');
    try {
      const token = values.token.trim();
      await createApi(token).tenants();
      onLogin(token);
    } catch (e) { setError(e instanceof TypeError ? '连接失败，请检查服务是否可用' : (e as Error).message); }
    finally { setBusy(false); }
  }
  return <div className="login-page"><div className="login-story"><Brand />
    <div className="login-story-main"><div className="eyebrow">OPENAPI → MCP</div><h1>让服务接入，<br />清晰可控。</h1><p>集中管理 OpenAPI 文档和工具，<br />从注册到更新，在一个工作台完成。</p>
      <div className="login-flow"><FileTextOutlined /><span className="flow-line" /><ApiOutlined /><span className="flow-line" /><AppstoreOutlined /></div>
    </div><div className="login-foot">MCP SERVER <span>服务管理工作台</span></div>
  </div><div className="login-panel"><div className="login-card"><Tag color="green" bordered={false}>SERVICE ADMINISTRATION</Tag><h2>进入管理台</h2><p className="muted">使用管理员 Token 登录，再选择租户工作空间。</p>
    {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 24 }} />}
    <Form name="login" layout="vertical" onFinish={enter} requiredMark={false}>
      <Form.Item name="token" label="访问 Token" rules={[{ required: true, whitespace: true, message: '请输入访问 Token' }]}>
        <Input.Password size="large" prefix={<LockOutlined />} placeholder="AUTH_TOKENS 中的管理员 Token" autoComplete="off" />
      </Form.Item>
      <Button type="primary" size="large" block htmlType="submit" loading={busy}>进入管理台 <ArrowRightOutlined /></Button>
    </Form>
    <div className="login-security"><SafetyCertificateOutlined /><span>Token 仅保存在当前页面内存中，刷新或退出后清除。</span></div>
  </div></div></div>;
}

function Workspace({ session, api, onLogout, onLeave }: { session: Session; api: Api; onLogout: () => void; onLeave: () => void }) {
  const { message, modal } = AntApp.useApp();
  const [page, setPage] = useState<'services' | 'credentials'>('services');
  const [result, setResult] = useState<Listing>({ items: [], total: 0, page: 1, page_size: 20 });
  const defaultFilters = { org: session.access.org || '', app: session.access.app || '', q: '', page: 1, page_size: 20 };
  const [query, setQuery] = useState(defaultFilters);
  const canManage = session.access.role === 'manager';
  const [directory, setDirectory] = useState<ScopeDirectory>({ tenant: session.tenant, service_count: 0, organizations: [] });
  const [directoryError, setDirectoryError] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [editor, setEditor] = useState<{ row: Service | null } | null>(null);
  const [selected, setSelected] = useState<Service | null>(null);
  const [filters] = Form.useForm();
  const filterOrg = Form.useWatch('org', filters);
  useEffect(() => {
    const controller = new AbortController();
    setDirectoryError('');
    api.scopes(controller.signal).then(setDirectory).catch(e => {
      if (!controller.signal.aborted) setDirectoryError(e.message);
    });
    return () => controller.abort();
  }, [api, revision]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api.list(query, controller.signal).then(setResult).catch(e => {
      if (!controller.signal.aborted) { setResult({ items: [], total: 0, page: query.page, page_size: query.page_size }); setError(e.message); }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, query, revision]);
  const reload = () => setRevision(v => v + 1);
  const remove = (row: Service) => modal.confirm({
    title: `删除「${row.title}」？`, icon: <SafetyCertificateOutlined />,
    content: <><p>将删除文档并卸载其当前生效的 {row.active_tool_count} 个工具，此操作无法撤销。</p>
      <p className="mono">{row.tenant} / {row.org} / {row.app}<br />{row.fileId}</p></>,
    okText: '确认删除', cancelText: '取消', okButtonProps: { danger: true },
    onOk: async () => {
      try { await api.remove(row); message.success('服务已删除'); setQuery(q => ({ ...q, page: 1 })); reload(); }
      catch (e) { message.error((e as Error).message); throw e; }
    },
  });
  const currentTools = result.items.reduce((sum, row) => sum + row.tool_count, 0);
  const activeTools = result.items.reduce((sum, row) => sum + row.active_tool_count, 0);
  return <div className="console-shell"><aside className="sidebar"><Brand />
    <div className="sidebar-label">WORKSPACE</div><button className={`nav-button ${page === 'services' ? 'nav-active' : 'nav-link'}`} onClick={() => setPage('services')}><AppstoreOutlined /> 服务管理 <span className="nav-count">{result.total}</span></button>
    <button aria-label="访问凭证" className={`nav-button ${page === 'credentials' ? 'nav-active' : 'nav-link'}`} onClick={() => setPage('credentials')}><KeyOutlined aria-hidden /> 访问凭证</button>
    <a className="nav-link" href="/docs" target="_blank" rel="noreferrer"><BookOutlined /> API 文档 <ArrowRightOutlined /></a>
    <div className="sidebar-bottom"><div className="sidebar-orbit"><ApiOutlined /></div><strong>一个入口，连接服务</strong><p>OpenAPI 文档注册后，<br />即可通过 MCP 访问工具。</p><span className="sidebar-protocol">MODEL CONTEXT PROTOCOL</span></div>
  </aside><div className="workspace"><header className="topbar"><div className="workspace-location"><Tooltip title="切换租户"><Button type="text" aria-label="切换租户" icon={<SwapOutlined aria-hidden />} onClick={onLeave} /></Tooltip><Breadcrumb items={[{ title: <Tooltip title={`${session.workspace.name} · ${session.tenant}`}><span className="tenant-crumb">{session.workspace.name}</span></Tooltip> }, { title: page === 'services' ? '服务管理' : '访问凭证' }]} /></div>
    <Space><Button className="mobile-nav" size="small" onClick={() => setPage(page === 'services' ? 'credentials' : 'services')}>{page === 'services' ? '访问凭证' : '服务管理'}</Button><Button type="text" icon={<LogoutOutlined />} onClick={onLogout}>退出</Button></Space>
  </header><main className="main-content">{page === 'credentials' ? <CredentialManager api={api} tenant={session.tenant} /> : <><div className="page-heading"><div><div className="eyebrow">SERVICE REGISTRY</div><h1>服务管理 <span>Services</span></h1><p>管理 OpenAPI 服务文档，查看工具并配置 MCP 接入。</p></div>
    {canManage && <Button type="primary" size="large" icon={<PlusOutlined />} onClick={() => setEditor({ row: null })}>注册服务</Button>}</div>
    <div className="stats-grid">{[
      { label: '服务文档', value: result.total, icon: <CloudServerOutlined />, note: '当前筛选范围', color: 'green' },
      { label: '声明工具', value: currentTools, icon: <CodeOutlined />, note: '当前页服务中的工具', color: 'blue' },
      { label: '生效工具', value: activeTools, icon: <ApiOutlined />, note: '当前页已加载到注册表', color: 'amber' },
    ].map(stat => <Card key={stat.label} className="stat-card"><div><span className="stat-label">{stat.label}</span><strong>{loading || error ? '—' : stat.value}</strong><small>{stat.note}</small></div><span className={`stat-icon ${stat.color}`}>{stat.icon}</span></Card>)}</div>
    <section className="services-panel"><div className="panel-heading"><div><h2>服务列表 <Tag bordered={false}>{result.total}</Tag></h2><p>每份 OpenAPI 文档对应一个服务，更新后工具立即生效。</p></div>
      <Button icon={<ReloadOutlined />} onClick={reload} loading={loading}>刷新</Button></div>
      {directoryError && <Alert type="warning" showIcon message="组织和应用候选加载失败" description={directoryError} />}
      <Form name="service-filters" form={filters} className="filter-form" onFinish={values => setQuery(q => ({ ...q, ...values, page: 1 }))} initialValues={defaultFilters}
        onValuesChange={changed => { if ('org' in changed) filters.setFieldValue('app', session.access.app || ''); }}>
        <Form.Item name="q"><Input allowClear prefix={<SearchOutlined />} aria-label="搜索服务" placeholder="搜索服务名称、文件名或 ID" /></Form.Item>
        <Form.Item name="org"><AutoComplete allowClear disabled={!!session.access.org}
          options={directory.organizations.map(item => ({ value: item.org, label: `${item.org}（${item.service_count} 个服务）` }))} filterOption={(input, option) => !!option?.value.includes(input)}><Input aria-label="筛选组织" placeholder="组织 Org" /></AutoComplete></Form.Item>
        <Form.Item name="app"><AutoComplete allowClear disabled={!!session.access.app}
          options={directory.organizations.find(item => item.org === filterOrg)?.apps.map(item => ({ value: item.app, label: `${item.app}（${item.service_count} 个服务）` })) || []}
          filterOption={(input, option) => !!option?.value.includes(input)}><Input aria-label="筛选应用" placeholder="应用 App" /></AutoComplete></Form.Item>
        <Button htmlType="submit">查询</Button><Button type="text" onClick={() => { filters.resetFields(); setQuery(defaultFilters); }}>重置</Button>
      </Form>
      {error && <Alert type="error" showIcon message="服务列表加载失败" description={error} action={<Button onClick={reload}>重试</Button>} style={{ margin: '0 24px 20px' }} />}
      <Table<Service> rowKey={serviceKey} loading={loading} dataSource={result.items} scroll={{ x: 900 }}
        locale={{ emptyText: <div className="empty-state"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={<><strong>{query.q || query.org || query.app ? '没有匹配的服务' : '还没有注册服务'}</strong><p>上传 OpenAPI 文档，将接口转换为可调用的 MCP 工具。</p></>} />
          {canManage && <Button icon={<PlusOutlined />} onClick={() => setEditor({ row: null })}>注册服务</Button>}</div> }}
        pagination={{ current: query.page, pageSize: query.page_size, total: result.total, showSizeChanger: true, pageSizeOptions: [10, 20, 50, 100],
          showTotal: total => `共 ${total} 个服务`, onChange: (page, page_size) => setQuery(q => ({ ...q, page, page_size })) }}
        columns={[
          { title: '服务名称', key: 'name', width: 300, render: (_, row) => <div className="service-cell"><span className="service-icon"><FileTextOutlined /></span><div>
            <Button type="link" className="service-title" onClick={() => setSelected(row)}>{row.title}</Button><span className="file-name">{row.fileName}</span></div></div> },
          { title: '组织 / 应用', key: 'scope', width: 180, render: (_, row) => <div className="scope-cell"><span>{row.org}</span><small>{row.app}</small></div> },
          { title: '版本', dataIndex: 'version', width: 100, render: value => <Tag bordered={false}>{value || '—'}</Tag> },
          { title: '工具', key: 'tools', width: 140, render: (_, row) => <div className="scope-cell"><span>{row.tool_count} 个工具</span><small><Badge status={row.error || row.active_tool_count < row.tool_count ? 'warning' : 'success'} /> {row.error ? '需修复' : `${row.active_tool_count} 个已生效`}</small></div> },
          { title: '更新时间', dataIndex: 'updated_at', width: 180, render: value => <span className="muted table-time">{time(value)}</span> },
          ...(canManage ? [{ title: '操作', key: 'actions', width: 150, fixed: 'right' as const, render: (_: unknown, row: Service) => <Space size={0}><Button type="link" onClick={() => setEditor({ row })}>编辑</Button><Button type="link" danger onClick={() => remove(row)}>删除</Button></Space> }] : []),
        ]} />
    </section><footer className="workspace-footer"><span><SafetyCertificateOutlined /> 当前访问范围：{session.tenant}</span><span>MCP Service Console</span></footer>
  </>}</main></div>
    {editor && canManage && <ServiceEditor api={api} tenant={session.tenant} access={session.access} directory={directory} row={editor.row} onClose={() => setEditor(null)} onSaved={() => { setEditor(null); reload(); }} />}
    {selected && <ServiceDetail key={serviceKey(selected)} api={api} row={selected} onClose={() => setSelected(null)} onEdit={canManage ? () => { setEditor({ row: selected }); setSelected(null); } : undefined} />}
  </div>;
}

export default function App() {
  const activeToken = useRef<string | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [expired, setExpired] = useState(false);
  const unauthorized = useCallback(() => { activeToken.current = null; setToken(null); setSession(null); setExpired(true); }, []);
  const platformApi = useMemo(() => token ? createApi(token, undefined, unauthorized) : null, [token, unauthorized]);
  const api = useMemo(() => session ? createApi(session.token, session.tenant, unauthorized) : null, [session, unauthorized]);
  const logout = () => { activeToken.current = null; setToken(null); setSession(null); setExpired(false); };
  if (!token || !platformApi) return <Login expired={expired} onLogin={value => { activeToken.current = value; setSession(null); setExpired(false); setToken(value); }} />;
  if (!session || !api) return <TenantPortal api={platformApi} onLogout={logout} onEnter={async row => {
    const scoped = createApi(token, row.id, unauthorized);
    const [workspace, access] = await Promise.all([scoped.tenant(row.id), scoped.access()]);
    if (activeToken.current !== token) return;
    setSession({ token, tenant: row.id, access, workspace });
  }} />;
  return <Workspace key={session.tenant} api={api} session={session} onLogout={logout} onLeave={() => setSession(null)} />;
}

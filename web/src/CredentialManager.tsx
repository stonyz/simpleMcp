import { useEffect, useState } from 'react';
import { Alert, App, AutoComplete, Button, Card, Checkbox, Drawer, Empty, Form, Input, Modal, Select, Space, Switch, Table, Tag, Typography } from 'antd';
import { DeleteOutlined, KeyOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { AccessRule, Api, CatalogService, Credential, CredentialInput, IssuedCredential } from './api';
import { time } from './api';

type Level = 'tenant' | 'org' | 'app' | 'services';
interface EditableRule extends Omit<AccessRule, 'services'> { services?: string[]; level: Level }
interface Values { name: string; description: string; enabled: boolean; expires_at?: string; rules: EditableRule[] }
const levels = [{ value: 'tenant', label: '整个租户' }, { value: 'org', label: '指定组织' },
  { value: 'app', label: '指定应用' }, { value: 'services', label: '指定服务' }];
const operations = [{ label: '列出工具（tools/list）', value: 'list' }, { label: '调用工具（tools/call）', value: 'call' }];
const defaultRule = (tenant: string): EditableRule => ({ tenant, org: null, app: null, services: undefined, operations: ['list', 'call'], level: 'tenant' });
const unique = (values: string[]) => [...new Set(values)].sort().map(value => ({ value }));
const levelOf = (rule: AccessRule): Level => rule.services ? 'services' : rule.app ? 'app' : rule.org ? 'org' : 'tenant';
function scopeLabel(rule: AccessRule) {
  return [rule.tenant, rule.org || '全部组织', rule.org && (rule.app || '全部应用'), rule.services && `${rule.services.length} 个指定服务`].filter(Boolean).join(' / ');
}
function inputOf(row: Credential): CredentialInput {
  return { name: row.name, description: row.description, enabled: row.enabled, expires_at: row.expires_at, rules: row.rules };
}
function localTime(value: string | null) {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function RuleFields({ index, catalog, remove }: { index: number; catalog: CatalogService[]; remove: () => void }) {
  const form = Form.useFormInstance<Values>();
  const rule = Form.useWatch(['rules', index], form) as EditableRule | undefined;
  const level = rule?.level || 'tenant';
  const organizationServices = catalog.filter(item => item.tenant === rule?.tenant);
  const applicationServices = organizationServices.filter(item => item.org === rule?.org);
  const selectedServices = applicationServices.filter(item => item.app === rule?.app);
  function clear(fields: ('org' | 'app' | 'services')[]) {
    fields.forEach(field => form.setFieldValue(['rules', index, field], null));
  }
  return <Card size="small" className="credential-rule" title={`授权规则 ${index + 1}`}
    extra={<Button type="text" danger icon={<DeleteOutlined />} aria-label={`移除规则 ${index + 1}`} onClick={remove} />}>
    <div className="credential-rule-grid">
      <Form.Item name={[index, 'tenant']} label="租户" rules={[{ required: true, whitespace: true, max: 63 }]}>
        <AutoComplete options={unique(catalog.map(item => item.tenant))} onChange={() => clear(['org', 'app', 'services'])}
          filterOption={(input, option) => !!option?.value.includes(input)} placeholder="选择或输入 Tenant" />
      </Form.Item>
      <Form.Item name={[index, 'level']} label="授权范围"><Select options={levels} onChange={() => clear(['org', 'app', 'services'])} /></Form.Item>
      {level !== 'tenant' && <Form.Item name={[index, 'org']} label="组织" rules={[{ required: true, whitespace: true, max: 64 }]}>
        <AutoComplete options={unique(organizationServices.map(item => item.org))} onChange={() => clear(['app', 'services'])}
          filterOption={(input, option) => !!option?.value.includes(input)} placeholder="选择或输入 Org" />
      </Form.Item>}
      {(level === 'app' || level === 'services') && <Form.Item name={[index, 'app']} label="应用" rules={[{ required: true, whitespace: true, max: 64 }]}>
        <AutoComplete options={unique(applicationServices.map(item => item.app))} onChange={() => clear(['services'])}
          filterOption={(input, option) => !!option?.value.includes(input)} placeholder="选择或输入 App" />
      </Form.Item>}
    </div>
    {level === 'services' && <Form.Item name={[index, 'services']} label="服务" rules={[{ required: true, type: 'array', min: 1, message: '请至少选择一个服务' }]}>
      <Select mode="multiple" optionFilterProp="label" placeholder="只允许选中服务中的工具"
        options={selectedServices.map(item => ({ value: item.fileId, label: `${item.title} · ${item.fileName} · ${item.fileId}` }))} />
    </Form.Item>}
    <Form.Item name={[index, 'operations']} label="允许操作" rules={[{ required: true, type: 'array', min: 1, message: '请至少选择一种操作' }]}>
      <Checkbox.Group options={operations} />
    </Form.Item>
    <p className="auth-hint">{level === 'services' ? '只授权所选服务，文档原地更新后继续有效。' : '范围内现有和未来新增的服务都会获得授权。'} 多条规则的权限取并集。</p>
  </Card>;
}

export default function CredentialManager({ api, tenant }: { api: Api; tenant: string }) {
  const { message, modal } = App.useApp();
  const [items, setItems] = useState<Credential[]>([]);
  const [catalog, setCatalog] = useState<CatalogService[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [editor, setEditor] = useState<{ row: Credential | null } | null>(null);
  const [issued, setIssued] = useState<IssuedCredential | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState('');
  const [form] = Form.useForm<Values>();
  const reload = () => setRevision(value => value + 1);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    Promise.all([api.credentials(controller.signal), api.credentialCatalog(controller.signal)]).then(([list, directory]) => {
      setItems(list.items); setCatalog(directory.services);
    }).catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, revision]);
  function edit(row: Credential | null) {
    form.resetFields();
    form.setFieldsValue(row ? { ...inputOf(row), expires_at: localTime(row.expires_at), rules: row.rules.map(rule => ({ ...rule, services: rule.services || undefined, level: levelOf(rule) })) }
      : { name: '', description: '', enabled: true, expires_at: '', rules: [defaultRule(tenant)] });
    setEditor({ row });
  }
  async function save() {
    try {
      const values = await form.validateFields();
      const rules = values.rules.map(({ level, ...rule }) => ({ ...rule,
        org: level === 'tenant' ? null : rule.org,
        app: level === 'tenant' || level === 'org' ? null : rule.app,
        services: level === 'services' ? rule.services || [] : null }));
      const input: CredentialInput = { name: values.name, description: values.description || '', enabled: values.enabled,
        expires_at: values.expires_at ? new Date(values.expires_at).toISOString() : null, rules };
      setBusy(true);
      if (editor?.row) await api.updateCredential(editor.row.id, input);
      else setIssued(await api.createCredential(input));
      setEditor(null); reload(); message.success('访问凭证已保存');
    } catch (e) { if (e instanceof Error) message.error(e.message); }
    finally { setBusy(false); }
  }
  async function toggle(row: Credential) {
    setBusy(true);
    try { await api.setCredentialStatus(row.id, !row.enabled); reload(); }
    catch (e) { message.error((e as Error).message); }
    finally { setBusy(false); }
  }
  function rotate(row: Credential) {
    modal.confirm({ title: `轮换「${row.name}」的 Token？`, content: '旧 Token 将立即失效，请在客户端替换为新 Token。', okText: '确认轮换', cancelText: '取消',
      onOk: async () => { try { setIssued(await api.rotateCredential(row.id)); reload(); } catch (e) { message.error((e as Error).message); throw e; } } });
  }
  function remove(row: Credential) {
    modal.confirm({ title: `删除访问凭证「${row.name}」？`, content: 'Token 和全部授权规则将删除，客户端将无法继续访问。', okText: '确认删除凭证', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => { try { await api.deleteCredential(row.id); reload(); } catch (e) { message.error((e as Error).message); throw e; } } });
  }
  const config = issued ? JSON.stringify({ mcpServers: { [issued.name]: { type: 'http',
    url: `${location.origin}/mcp?tenant=${encodeURIComponent(issued.rules[0].tenant)}`, headers: { Authorization: `Bearer ${issued.secret}` } } } }, null, 2) : '';
  return <>
    <div className="page-heading"><div><div className="eyebrow">MCP ACCESS CONTROL</div><h1>访问凭证 <span>Tokens</span></h1><p>管理 MCP 工具的可见范围和调用权限，多条规则可组合授权。</p></div>
      <Button aria-label="创建凭证" type="primary" size="large" icon={<PlusOutlined aria-hidden />} onClick={() => edit(null)} disabled={loading || !!error}>创建凭证</Button></div>
    <Alert type="info" showIcon message="这里管理全部租户的 MCP 访问凭证" description="凭证只能访问获授权的工具，不能登录管理台。tools/list 自动过滤；tools/call 根据工具实际归属校验。" style={{ marginBottom: 24 }} />
    <section className="services-panel"><div className="panel-heading"><div><h2><KeyOutlined /> 访问凭证 <Tag>{items.length}</Tag></h2><p>密钥只在创建或轮换后显示一次；停用、改权和轮换在后续请求生效。</p></div><Button icon={<ReloadOutlined />} loading={loading} onClick={reload}>刷新</Button></div>
      <div className="credential-search"><Input.Search allowClear placeholder="搜索名称、说明或 Token 前缀" aria-label="搜索凭证" value={query} onChange={e => setQuery(e.target.value)} /></div>
      {error && <Alert type="error" showIcon message="访问凭证加载失败" description={error} />}
      <Table<Credential> rowKey="id" loading={loading} scroll={{ x: 1100 }} dataSource={items.filter(row => `${row.name} ${row.description} ${row.token_prefix}`.toLowerCase().includes(query.toLowerCase()))}
        pagination={{ pageSize: 10, showTotal: total => `共 ${total} 个凭证` }} locale={{ emptyText: <Empty description="还没有访问凭证" /> }} columns={[
          { title: '名称 / Token 前缀', width: 220, render: (_, row) => <div className="scope-cell"><strong>{row.name}</strong><small className="mono">{row.token_prefix}…</small><small>{row.description}</small></div> },
          { title: '授权范围', width: 380, render: (_, row) => <Space direction="vertical" size={8}>{row.rules.map((rule, index) => <div key={index} className="credential-summary"><span>{scopeLabel(rule)}</span><div>{rule.operations.map(operation => <Tag key={operation}>{operation === 'list' ? '列出工具' : '调用工具'}</Tag>)}</div></div>)}</Space> },
          { title: '状态', width: 110, render: (_, row) => <Space direction="vertical"><Tag color={row.status === 'active' ? 'success' : 'default'}>{({ active: '有效', disabled: '已停用', expired: '已过期' })[row.status]}</Tag><Switch size="small" checked={row.enabled} disabled={busy} aria-label={`启用 ${row.name}`} onChange={() => toggle(row)} /></Space> },
          { title: '时间', width: 200, render: (_, row) => <div className="scope-cell"><span>过期：{row.expires_at ? time(row.expires_at) : '永不过期'}</span><small>最近使用：{row.last_used_at ? time(row.last_used_at) : '尚未使用'}</small></div> },
          { title: '操作', width: 200, fixed: 'right', render: (_, row) => <Space size={0}><Button type="link" onClick={() => edit(row)}>编辑权限</Button><Button type="link" onClick={() => rotate(row)}>轮换</Button><Button type="link" danger onClick={() => remove(row)}>删除</Button></Space> },
        ]} />
    </section>
    <Drawer open={!!editor} width={900} title={editor?.row ? '编辑访问凭证' : '创建访问凭证'} onClose={() => { if (!busy) setEditor(null); }} maskClosable={!busy} keyboard={!busy} destroyOnClose
      footer={<div className="drawer-footer"><span>授权规则取并集；空的服务选择不会授权全部服务</span><Space><Button disabled={busy} onClick={() => setEditor(null)}>取消</Button><Button type="primary" loading={busy} onClick={save}>保存凭证</Button></Space></div>}>
      <Form form={form} layout="vertical" name="credential-editor" disabled={busy}>
        <div className="credential-rule-grid"><Form.Item name="name" label="凭证名称" rules={[{ required: true, whitespace: true, max: 128 }]}><Input placeholder="例如：合作方订单查询" /></Form.Item>
          <Form.Item name="expires_at" label="过期时间" extra="可不填，按浏览器本地时间选择"><Input type="datetime-local" /></Form.Item></div>
        <Form.Item name="description" label="说明"><Input.TextArea rows={2} maxLength={2000} placeholder="用途、使用方或负责人" /></Form.Item>
        <Form.Item name="enabled" label="启用凭证" valuePropName="checked"><Switch /></Form.Item>
        <Form.List name="rules" rules={[{ validator: async (_, rules) => { if (!rules?.length) throw new Error('请至少添加一条授权规则'); } }]}>
          {(fields, { add, remove }, { errors }) => <>{fields.map(field => <RuleFields key={field.key} index={field.name} catalog={catalog} remove={() => remove(field.name)} />)}
            <Form.ErrorList errors={errors} /><Button block type="dashed" icon={<PlusOutlined />} onClick={() => add(defaultRule(tenant))}>添加授权规则</Button></>}
        </Form.List>
      </Form>
    </Drawer>
    <Modal open={!!issued} title="保存访问 Token" onCancel={() => setIssued(null)} footer={<Button type="primary" onClick={() => setIssued(null)}>我已保存</Button>} width={760} maskClosable={false} destroyOnClose>
      {issued && <><Alert type="warning" showIcon message="此 Token 仅显示一次" description="请复制并安全保存。关闭后无法再次查看，遗失时可以轮换生成新 Token。" />
        <Typography.Paragraph copyable={{ text: issued.secret }} className="code-block credential-secret">{issued.secret}</Typography.Paragraph>
        <Typography.Text type="secondary">客户端接入示例（可修改 tenant 为规则中其他租户）：</Typography.Text>
        <Typography.Paragraph copyable={{ text: config }}><pre className="code-block">{config}</pre></Typography.Paragraph></>}
    </Modal>
  </>;
}

import { t, useLanguage, apiMessage, useLocalizedForm } from './i18n';
import { useEffect, useState } from 'react';
import { Alert, App, AutoComplete, Button, Card, Checkbox, Drawer, Empty, Form, Input, Modal, Select, Space, Switch, Table, Tag, Typography } from 'antd';
import { DeleteOutlined, KeyOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { AccessRule, Api, CatalogService, Credential, CredentialInput, IssuedCredential } from './api';
import { time } from './api';

type Level = 'tenant' | 'org' | 'app' | 'services';
interface EditableRule extends Omit<AccessRule, 'services'> { services?: string[]; level: Level }
interface Values { name: string; description: string; enabled: boolean; expires_at?: string; rules: EditableRule[] }
const levels = () => [{ value: 'tenant', label: t("整个租户") }, { value: 'org', label: t("指定组织") },
  { value: 'app', label: t("指定应用") }, { value: 'services', label: t("指定服务") }];
const operations = () => [{ label: t("列出工具（tools/list）"), value: 'list' }, { label: t("调用工具（tools/call）"), value: 'call' }];
const defaultRule = (tenant: string): EditableRule => ({ tenant, org: null, app: null, services: undefined, operations: ['list', 'call'], level: 'tenant' });
const unique = (values: string[]) => [...new Set(values)].sort().map(value => ({ value }));
const levelOf = (rule: AccessRule): Level => rule.services ? 'services' : rule.app ? 'app' : rule.org ? 'org' : 'tenant';
function scopeLabel(rule: AccessRule) {
  return [rule.tenant, rule.org || t("全部组织"), rule.org && (rule.app || t("全部应用")), rule.services && t("{0} 个指定服务", [rule.services.length])].filter(Boolean).join(' / ');
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
  useLanguage();
  const form = Form.useFormInstance<Values>();
  const rule = Form.useWatch(['rules', index], form) as EditableRule | undefined;
  const level = rule?.level || 'tenant';
  const organizationServices = catalog.filter(item => item.tenant === rule?.tenant);
  const applicationServices = organizationServices.filter(item => item.org === rule?.org);
  const selectedServices = applicationServices.filter(item => item.app === rule?.app);
  function clear(fields: ('org' | 'app' | 'services')[]) {
    fields.forEach(field => form.setFieldValue(['rules', index, field], null));
  }
  return <Card size="small" className="credential-rule" title={t("授权规则 {0}", [index + 1])}
    extra={<Button type="text" danger icon={<DeleteOutlined />} aria-label={t("移除规则 {0}", [index + 1])} onClick={remove} />}>
    <div className="credential-rule-grid">
      <Form.Item name={[index, 'tenant']} hidden><Input /></Form.Item>
      <Form.Item name={[index, 'level']} label={t("授权范围")}><Select options={levels()} onChange={() => clear(['org', 'app', 'services'])} /></Form.Item>
      {level !== 'tenant' && <Form.Item name={[index, 'org']} label={t("组织")} rules={[{ required: true, whitespace: true, max: 64 }]}>
        <AutoComplete options={unique(organizationServices.map(item => item.org))} onChange={() => clear(['app', 'services'])}
          filterOption={(input, option) => !!option?.value.includes(input)} placeholder={t("选择或输入 Org")} />
      </Form.Item>}
      {(level === 'app' || level === 'services') && <Form.Item name={[index, 'app']} label={t("应用")} rules={[{ required: true, whitespace: true, max: 64 }]}>
        <AutoComplete options={unique(applicationServices.map(item => item.app))} onChange={() => clear(['services'])}
          filterOption={(input, option) => !!option?.value.includes(input)} placeholder={t("选择或输入 App")} />
      </Form.Item>}
    </div>
    {level === 'services' && <Form.Item name={[index, 'services']} label={t("服务")} rules={[{ required: true, type: 'array', min: 1, message: t("请至少选择一个服务") }]}>
      <Select mode="multiple" optionFilterProp="label" placeholder={t("只允许选中服务中的工具")}
        options={selectedServices.map(item => ({ value: item.fileId, label: `${item.title} · ${item.fileName} · ${item.fileId}` }))} />
    </Form.Item>}
    <Form.Item name={[index, 'operations']} label={t("允许操作")} rules={[{ required: true, type: 'array', min: 1, message: t("请至少选择一种操作") }]}>
      <Checkbox.Group options={operations()} />
    </Form.Item>
    <p className="auth-hint">{level === 'services' ? t("只授权所选服务，文档原地更新后继续有效。") : t("范围内现有和未来新增的服务都会获得授权。")} {t("多条规则的权限取并集。")}</p>
  </Card>;
}

export default function CredentialManager({ api, tenant }: { api: Api; tenant: string }) {
  useLanguage();
  const { message, modal } = App.useApp();
  const [items, setItems] = useState<Credential[]>([]);
  const [catalog, setCatalog] = useState<CatalogService[]>([]);
  const [error, setError] = useState<string | Error>('');
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [editor, setEditor] = useState<{ row: Credential | null } | null>(null);
  const [issued, setIssued] = useState<IssuedCredential | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState('');
  const [form] = Form.useForm<Values>();
  useLocalizedForm(form);
  const reload = () => setRevision(value => value + 1);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    Promise.all([api.credentials(controller.signal), api.credentialCatalog(controller.signal)]).then(([list, directory]) => {
      setItems(list.items); setCatalog(directory.services);
    }).catch(e => { if (!controller.signal.aborted) setError(e); })
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
      const rules = values.rules.map(({ level, ...rule }) => ({ ...rule, tenant,
        org: level === 'tenant' ? null : rule.org,
        app: level === 'tenant' || level === 'org' ? null : rule.app,
        services: level === 'services' ? rule.services || [] : null }));
      const input: CredentialInput = { name: values.name, description: values.description || '', enabled: values.enabled,
        expires_at: values.expires_at ? new Date(values.expires_at).toISOString() : null, rules };
      setBusy(true);
      if (editor?.row) await api.updateCredential(editor.row.id, input);
      else setIssued(await api.createCredential(input));
      setEditor(null); reload(); message.success(t("访问凭证已保存"));
    } catch (e) { if (e instanceof Error) message.error(apiMessage(e)); }
    finally { setBusy(false); }
  }
  async function toggle(row: Credential) {
    setBusy(true);
    try { await api.setCredentialStatus(row.id, !row.enabled); reload(); }
    catch (e) { message.error(apiMessage(e as Error)); }
    finally { setBusy(false); }
  }
  function rotate(row: Credential) {
    modal.confirm({ title: t("轮换「{0}」的 Token？", [row.name]), content: t("旧 Token 将立即失效，请在客户端替换为新 Token。"), okText: t("确认轮换"), cancelText: t("取消"),
      onOk: async () => { try { setIssued(await api.rotateCredential(row.id)); reload(); } catch (e) { message.error(apiMessage(e as Error)); throw e; } } });
  }
  function remove(row: Credential) {
    modal.confirm({ title: t("删除访问凭证「{0}」？", [row.name]), content: t("Token 和全部授权规则将删除，客户端将无法继续访问。"), okText: t("确认删除凭证"), cancelText: t("取消"), okButtonProps: { danger: true },
      onOk: async () => { try { await api.deleteCredential(row.id); reload(); } catch (e) { message.error(apiMessage(e as Error)); throw e; } } });
  }
  const config = issued ? JSON.stringify({ mcpServers: { [issued.name]: { type: 'http',
    url: `${location.origin}/mcp?tenant=${encodeURIComponent(issued.rules[0].tenant)}`, headers: { Authorization: `Bearer ${issued.secret}` } } } }, null, 2) : '';
  return <>
    <div className="page-heading"><div><div className="eyebrow">MCP ACCESS CONTROL</div><h1>{t("访问凭证")}</h1><p>{t("管理 MCP 工具的可见范围和调用权限，多条规则可组合授权。")}</p></div>
      <Button aria-label={t("创建凭证")} type="primary" size="large" icon={<PlusOutlined aria-hidden />} onClick={() => edit(null)} disabled={loading || !!error}>{t("创建凭证")}</Button></div>
    <Alert type="info" showIcon message={t("仅管理当前租户的 MCP 访问凭证")} description={t("所有授权规则固定在当前租户内。凭证只能访问获授权的工具，不能登录管理台。")} style={{ marginBottom: 24 }} />
    <section className="services-panel"><div className="panel-heading"><div><h2><KeyOutlined /> {t("访问凭证")}<Tag>{items.length}</Tag></h2><p>{t("密钥只在创建或轮换后显示一次；停用、改权和轮换在后续请求生效。")}</p></div><Button icon={<ReloadOutlined />} loading={loading} onClick={reload}>{t("刷新")}</Button></div>
      <div className="credential-search"><Input.Search allowClear placeholder={t("搜索名称、说明或 Token 前缀")} aria-label={t("搜索凭证")} value={query} onChange={e => setQuery(e.target.value)} /></div>
      {error && <Alert type="error" showIcon message={t("访问凭证加载失败")} description={apiMessage(error)} />}
      <Table<Credential> rowKey="id" loading={loading} scroll={{ x: 1100 }} dataSource={items.filter(row => `${row.name} ${row.description} ${row.token_prefix}`.toLowerCase().includes(query.toLowerCase()))}
        pagination={{ pageSize: 10, showTotal: total => t("共 {0} 个凭证", [total]) }} locale={{ emptyText: <Empty description={t("还没有访问凭证")} /> }} columns={[
          { title: t("名称 / Token 前缀"), width: 220, render: (_, row) => <div className="scope-cell"><strong>{row.name}</strong><small className="mono">{row.token_prefix}…</small><small>{row.description}</small></div> },
          { title: t("授权范围"), width: 380, render: (_, row) => <Space direction="vertical" size={8}>{row.rules.map((rule, index) => <div key={index} className="credential-summary"><span>{scopeLabel(rule)}</span><div>{rule.operations.map(operation => <Tag key={operation}>{operation === 'list' ? t("列出工具") : t("调用工具")}</Tag>)}</div></div>)}</Space> },
          { title: t("状态"), width: 110, render: (_, row) => <Space direction="vertical"><Tag color={row.status === 'active' ? 'success' : 'default'}>{({ active: t("有效"), disabled: t("已停用"), expired: t("已过期") })[row.status]}</Tag><Switch size="small" checked={row.enabled} disabled={busy} aria-label={t("启用 {0}", [row.name])} onChange={() => toggle(row)} /></Space> },
          { title: t("时间"), width: 200, render: (_, row) => <div className="scope-cell"><span>{t("过期：")}{row.expires_at ? time(row.expires_at) : t("永不过期")}</span><small>{t("最近使用：")}{row.last_used_at ? time(row.last_used_at) : t("尚未使用")}</small></div> },
          { title: t("操作"), width: 200, fixed: 'right', render: (_, row) => <Space size={0}><Button type="link" onClick={() => edit(row)}>{t("编辑权限")}</Button><Button type="link" onClick={() => rotate(row)}>{t("轮换")}</Button><Button type="link" danger onClick={() => remove(row)}>{t("删除")}</Button></Space> },
        ]} />
    </section>
    <Drawer open={!!editor} width={900} title={editor?.row ? t("编辑访问凭证") : t("创建访问凭证")} onClose={() => { if (!busy) setEditor(null); }} maskClosable={!busy} keyboard={!busy} destroyOnClose
      footer={<div className="drawer-footer"><span>{t("授权规则取并集；空的服务选择不会授权全部服务")}</span><Space><Button disabled={busy} onClick={() => setEditor(null)}>{t("取消")}</Button><Button type="primary" loading={busy} onClick={save}>{t("保存凭证")}</Button></Space></div>}>
      <Form form={form} layout="vertical" name="credential-editor" disabled={busy}>
        <div className="credential-rule-grid"><Form.Item name="name" label={t("凭证名称")} rules={[{ required: true, whitespace: true, max: 128 }]}><Input placeholder={t("例如：合作方订单查询")} /></Form.Item>
          <Form.Item name="expires_at" label={t("过期时间")} extra={t("可不填，按浏览器本地时间选择")}><Input type="datetime-local" /></Form.Item></div>
        <Form.Item name="description" label={t("说明")}><Input.TextArea rows={2} maxLength={2000} placeholder={t("用途、使用方或负责人")} /></Form.Item>
        <Form.Item name="enabled" label={t("启用凭证")} valuePropName="checked"><Switch /></Form.Item>
        <Form.List name="rules" rules={[{ validator: async (_, rules) => { if (!rules?.length) throw new Error(t("请至少添加一条授权规则")); } }]}>
          {(fields, { add, remove }, { errors }) => <>{fields.map(field => <RuleFields key={field.key} index={field.name} catalog={catalog} remove={() => remove(field.name)} />)}
            <Form.ErrorList errors={errors} /><Button block type="dashed" icon={<PlusOutlined />} onClick={() => add(defaultRule(tenant))}>{t("添加授权规则")}</Button></>}
        </Form.List>
      </Form>
    </Drawer>
    <Modal open={!!issued} title={t("保存访问 Token")} onCancel={() => setIssued(null)} footer={<Button type="primary" onClick={() => setIssued(null)}>{t("我已保存")}</Button>} width={760} maskClosable={false} destroyOnClose>
      {issued && <><Alert type="warning" showIcon message={t("此 Token 仅显示一次")} description={t("请复制并安全保存。关闭后无法再次查看，遗失时可以轮换生成新 Token。")} />
        <Typography.Paragraph copyable={{ text: issued.secret }} className="code-block credential-secret">{issued.secret}</Typography.Paragraph>
        <Typography.Text type="secondary">{t("当前租户的客户端接入示例：")}</Typography.Text>
        <Typography.Paragraph copyable={{ text: config }}><pre className="code-block">{config}</pre></Typography.Paragraph></>}
    </Modal>
  </>;
}

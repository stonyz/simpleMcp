import { useEffect, useState } from 'react';
import { Alert, App, Button, Card, Dropdown, Empty, Form, Input, Modal, Space, Tag, Tooltip } from 'antd';
import { ArrowRightOutlined, CloudServerOutlined, EditOutlined, LogoutOutlined, MoreOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { Api, Tenant, TenantInput } from './api';

export default function TenantPortal({ api, onEnter, onLogout }: { api: Api; onEnter: (tenant: Tenant) => Promise<void>; onLogout: () => void }) {
  const { message, modal } = App.useApp();
  const [items, setItems] = useState<Tenant[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [revision, setRevision] = useState(0);
  const [entering, setEntering] = useState<string | null>(null);
  const [editor, setEditor] = useState<{ row: Tenant | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [form] = Form.useForm<TenantInput & { id: string }>();
  const reload = () => setRevision(value => value + 1);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    api.tenants(controller.signal).then(result => setItems(result.items))
      .catch(e => { if (!controller.signal.aborted) setError(e.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, revision]);
  async function enter(row: Tenant) {
    setEntering(row.id);
    try { await onEnter(row); }
    catch (e) { message.error((e as Error).message); }
    finally { setEntering(null); }
  }
  function edit(row: Tenant | null) {
    form.resetFields();
    form.setFieldsValue(row ? { id: row.id, name: row.name, description: row.description } : { id: '', name: '', description: '' });
    setEditor({ row });
  }
  async function save() {
    try {
      const values = await form.validateFields();
      setBusy(true);
      if (editor?.row) await api.updateTenant(editor.row.id, { name: values.name, description: values.description || '' });
      else await api.createTenant({ id: values.id, name: values.name, description: values.description || '' });
      setEditor(null); reload(); message.success('租户已保存');
    } catch (e) { if (e instanceof Error) message.error(e.message); }
    finally { setBusy(false); }
  }
  function remove(row: Tenant) {
    modal.confirm({ title: `删除租户「${row.name}」？`, content: '只允许删除没有服务和访问凭证的空租户。', okText: '确认删除租户', cancelText: '取消', okButtonProps: { danger: true },
      onOk: async () => { try { await api.deleteTenant(row.id); reload(); } catch (e) { message.error((e as Error).message); throw e; } } });
  }
  const filtered = items.filter(row => `${row.id} ${row.name} ${row.description}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="tenant-portal">
    <header className="tenant-portal-header"><div className="tenant-portal-brand"><CloudServerOutlined /><strong>MCP</strong><span>服务管理工作台</span></div><Button icon={<LogoutOutlined />} onClick={onLogout}>退出</Button></header>
    <main className="tenant-portal-main"><div className="page-heading"><div><div className="eyebrow">TENANT WORKSPACES</div><h1>选择租户</h1><p>选择工作空间，管理其中的服务与访问凭证。</p></div>
      <Button type="primary" aria-label="新增租户" icon={<PlusOutlined aria-hidden />} onClick={() => edit(null)}>新增租户</Button></div>
      <div className="tenant-portal-tools"><Input.Search allowClear aria-label="搜索租户" placeholder="搜索租户名称或标识" value={query} onChange={e => setQuery(e.target.value)} /><Tooltip title="刷新"><Button aria-label="刷新" icon={<ReloadOutlined aria-hidden />} loading={loading} onClick={reload} /></Tooltip></div>
      {error && <Alert type="error" showIcon message="租户列表加载失败" description={error} />}
      {loading ? <div className="tenant-grid">{[0, 1, 2].map(key => <Card key={key} loading />)}</div> : !filtered.length ? <Empty description={query ? '没有匹配的租户' : '还没有租户，点击右上角新增'} />
        : <div className="tenant-grid">{filtered.map(row => <Card key={row.id} className="tenant-card"><div className="tenant-card-head"><div className="tenant-card-icon"><CloudServerOutlined /></div><Space size={0}>
          <Tooltip title="编辑租户"><Button type="text" aria-label={`编辑租户 ${row.id}`} icon={<EditOutlined aria-hidden />} onClick={() => edit(row)} /></Tooltip>
          <Dropdown trigger={['click']} menu={{ items: [{ key: 'delete', label: '删除租户', danger: true, disabled: !!(row.service_count || row.credential_count), onClick: () => remove(row) }] }}>
            <Button type="text" aria-label={`更多租户操作 ${row.id}`} icon={<MoreOutlined aria-hidden />} />
          </Dropdown></Space></div>
          <h2>{row.name}</h2><Tag>{row.id}</Tag><p>{row.description || '独立的服务和访问凭证工作空间'}</p><div className="tenant-card-counts"><span>{row.service_count} 个服务</span><span>{row.credential_count} 个凭证</span></div>
          <Button block type="primary" loading={entering === row.id} disabled={entering !== null} aria-label={`进入租户 ${row.id}`} onClick={() => enter(row)}>进入工作空间 <ArrowRightOutlined /></Button>
        </Card>)}</div>}
    </main>
    <Modal open={!!editor} title={editor?.row ? '编辑租户' : '新增租户'} onCancel={() => { if (!busy) setEditor(null); }} maskClosable={!busy} destroyOnClose
      footer={<Space><Button disabled={busy} onClick={() => setEditor(null)}>取消</Button><Button type="primary" loading={busy} onClick={save}>保存租户</Button></Space>}>
      <Form form={form} layout="vertical" name="tenant-editor" disabled={busy}>
        <Form.Item name="id" label="租户标识" rules={[{ required: true, whitespace: true, max: 63 }, { pattern: /^(?!\.{1,2}$)[^\s/\\?#]+$/, message: '不能为 . 或 ..，也不能包含空白、路径或查询分隔符' }]} extra="用于 API 和 MCP 地址，创建后不可修改"><Input disabled={!!editor?.row || busy} placeholder="例如 team-alpha" /></Form.Item>
        <Form.Item name="name" label="租户名称" rules={[{ required: true, whitespace: true, max: 128 }]}><Input placeholder="例如研发团队" /></Form.Item>
        <Form.Item name="description" label="租户说明"><Input.TextArea maxLength={2000} rows={3} /></Form.Item>
      </Form>
    </Modal>
  </div>;
}

import { t, useLanguage, apiMessage, useLocalizedForm } from './i18n';
import { lazy, Suspense, useEffect, useState } from 'react';
import { Alert, App, AutoComplete, Button, Drawer, Form, Input, Space, Spin, Table, Tag, Upload, Typography } from 'antd';
import { CheckCircleOutlined, UploadOutlined } from '@ant-design/icons';
import type { AccessScope, Api, Preview, ScopeDirectory, Service, ServiceInput } from './api';
import AuthorizationSettings, { authorizationInput, type EditorValues } from './AuthorizationSettings';

const CodeEditor = lazy(() => import('./CodeEditor'));
const sample = () => t("openapi: 3.0.3\ninfo:\n  title: My Service\n  version: \"1.0.0\"\nservers:\n  - url: https://api.example.com\npaths:\n  /status:\n    get:\n      operationId: getStatus\n      summary: 获取服务状态\n      responses:\n        '200':\n          description: OK\n");

export default function ServiceEditor({ api, tenant, access, directory, row, onClose, onSaved }: {
  api: Api; tenant: string; access: AccessScope; directory: ScopeDirectory; row: Service | null; onClose: () => void; onSaved: () => void;
}) {
  useLanguage();
  const [form] = Form.useForm<EditorValues>();
  useLocalizedForm(form);
  const selectedOrg = Form.useWatch('org', form);
  const { message } = App.useApp();
  const [document, setDocument] = useState(() => row ? '' : sample());
  const [plain, setPlain] = useState(false);
  const [loading, setLoading] = useState(!!row);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | Error>('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [confirmedInput, setConfirmedInput] = useState<ServiceInput | null>(null);
  useEffect(() => {
    if (!row) return;
    const controller = new AbortController();
    api.detail(row, controller.signal).then(detail => {
      setDocument(detail.document);
      form.setFieldsValue({ org: detail.org, app: detail.app, fileName: detail.fileName, auth_mode: 'keep' });
    }).catch(e => { if (!controller.signal.aborted) setError(e); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [api, row, form]);
  const invalidate = () => { setPreview(null); setConfirmedInput(null); setError(''); };
  const changeDocument = (value: string) => { setDocument(value); invalidate(); };
  async function validate() {
    try {
      const values = await form.validateFields();
      const input: ServiceInput = { org: values.org, app: values.app, fileName: values.fileName,
        ...authorizationInput(values), ...(row ? { fileId: row.fileId } : {}), yaml_content: document };
      setBusy(true); setError(''); setPreview(null); setConfirmedInput(null);
      const result = await api.preview(input);
      setPreview(result); setConfirmedInput(input);
    } catch (e) { if (e instanceof Error) setError(e); }
    finally { setBusy(false); }
  }
  async function save() {
    if (!confirmedInput || !preview || preview.conflicts.length) return;
    setBusy(true); setError('');
    try { await api.save(confirmedInput); message.success(row ? t("服务已更新") : t("服务已注册")); onSaved(); }
    catch (e) { setError(e as Error); setPreview(null); setConfirmedInput(null); }
    finally { setBusy(false); }
  }
  return <Drawer open title={row ? t("编辑服务") : t("注册服务")} width={960} onClose={busy ? undefined : onClose}
    maskClosable={!busy} keyboard={!busy} destroyOnClose
    footer={<div className="drawer-footer"><span>{t("保存后立即更新 MCP 工具")}</span><Space>
      <Button onClick={onClose} disabled={busy}>{t("取消")}</Button>
      <Button onClick={validate} loading={busy && !preview} disabled={loading || busy}>{t("校验并预览")}</Button>
      <Button type="primary" icon={<CheckCircleOutlined />} onClick={save} loading={busy && !!preview}
        disabled={loading || busy || !preview || !!preview.conflicts.length}>{t("确认保存")}</Button>
    </Space></div>}>
    <Spin spinning={loading}>
      <div className="scope-note">{t("当前租户")}<Tag>{tenant}</Tag>{row && <Typography.Text type="secondary">{t("文档 ID：")}{row.fileId}</Typography.Text>}</div>
      {error && <Alert type="error" showIcon message={apiMessage(error)} style={{ marginBottom: 16 }} />}
      <Form name="service-editor" form={form} layout="vertical" initialValues={{ org: row?.org || access.org || '', app: row?.app || access.app || '', fileName: row?.fileName || 'openapi.yaml', auth_mode: row ? 'keep' : 'none' }}
        onValuesChange={changed => { if ('org' in changed) form.setFieldValue('app', access.app || ''); invalidate(); }} disabled={busy || loading}>
        <div className="form-grid">
          <Form.Item label={t("组织 Org")} name="org" rules={[{ required: true, whitespace: true, max: 64 }]}><AutoComplete disabled={!!row || !!access.org || busy || loading} placeholder={t("选择或输入组织标识")}
            options={directory.organizations.map(item => ({ value: item.org }))} filterOption={(input, option) => !!option?.value.includes(input)} /></Form.Item>
          <Form.Item label={t("应用 App")} name="app" rules={[{ required: true, whitespace: true, max: 64 }]}><AutoComplete disabled={!!row || !!access.app || busy || loading} placeholder={t("选择或输入应用标识")}
            options={directory.organizations.find(item => item.org === selectedOrg)?.apps.map(item => ({ value: item.app })) || []}
            filterOption={(input, option) => !!option?.value.includes(input)} /></Form.Item>
          <Form.Item label={t("文件名")} name="fileName" rules={[{ required: true, whitespace: true, max: 256 }]}><Input placeholder="openapi.yaml" /></Form.Item>
        </div>
        <div className="editor-toolbar"><strong>{t("OpenAPI 文档")}<small>{t("YAML / JSON · 最大 2 MB")}</small></strong><Space wrap>
          <Upload accept=".yaml,.yml,.json" showUploadList={false} disabled={busy || loading} beforeUpload={async file => {
            if (file.size > 2_000_000) { message.error(t("文档不能超过 2 MB")); return false; }
            setLoading(true);
            try { changeDocument(await file.text()); form.setFieldValue('fileName', file.name); }
            catch { message.error(t("文件读取失败")); }
            finally { setLoading(false); }
            return false;
          }}><Button icon={<UploadOutlined />}>{t("上传文档")}</Button></Upload>
          <Button onClick={() => setPlain(!plain)}>{plain ? t("代码编辑") : t("纯文本编辑")}</Button>
        </Space></div>
        <div className="code-editor">{plain ? <Input.TextArea aria-label={t("OpenAPI 文档")} value={document} onChange={e => changeDocument(e.target.value)}
          rows={18} spellCheck={false} disabled={busy} /> : <Suspense fallback={<div className="loading-panel"><Spin /></div>}>
            <CodeEditor value={document} onChange={value => { if (!busy) changeDocument(value); }} readOnly={busy} />
          </Suspense>}</div>
        <AuthorizationSettings row={row} />
      </Form>
      {preview && <div className="preview-panel">
        <div className="section-heading"><h3>{t("变更预览")}</h3><Tag color="green">{preview.title} · {preview.version}</Tag></div>
        <Space wrap>{([['added', t("新增"), 'green'], ['modified', t("修改"), 'gold'], ['removed', t("移除"), 'red'], ['unchanged', t("不变"), 'default']] as const).map(([key, label, color]) =>
          <Tag key={key} color={color}>{label} {preview.changes[key].length}</Tag>)}</Space>
        {preview.conflicts.length > 0 && <Alert type="error" showIcon message={t("存在工具重名冲突，无法保存")} description={preview.conflicts.map(c => `${c.name}（${c.fileName} / ${c.fileId}）`).join('；')} style={{ marginTop: 16 }} />}
        {!preview.tools.length && <Alert type="warning" message={t("此文档不包含工具，保存后将移除该服务已有的工具。")} style={{ marginTop: 16 }} />}
        <Table size="small" pagination={false} rowKey="name" dataSource={preview.tools} scroll={{ x: 520, y: 260 }} columns={[
          { title: t("工具名称"), dataIndex: 'name' }, { title: t("方法"), dataIndex: 'method', width: 90, render: v => <Tag>{v}</Tag> },
          { title: t("变更"), render: (_, tool) => preview.changes.added.includes(tool.name) ? t("新增") : preview.changes.modified.includes(tool.name) ? t("修改") : t("不变") },
        ]} />
        {preview.changes.removed.length > 0 && <p className="danger-text">{t("将移除：")}{preview.changes.removed.join('、')}</p>}
      </div>}
    </Spin>
  </Drawer>;
}

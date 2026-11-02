import { useEffect, useState } from 'react';
import { Alert, Button, Collapse, Descriptions, Drawer, Empty, Space, Spin, Tabs, Tag, Typography } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import { downloadDocument, time, type Api, type Detail, type Service } from './api';
import { authorizationLabels } from './AuthorizationSettings';

export default function ServiceDetail({ api, row, onClose, onEdit }: {
  api: Api; row: Service; onClose: () => void; onEdit: () => void;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    api.detail(row, controller.signal).then(setDetail).catch(e => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [api, row]);
  const mcpOrigin = import.meta.env.DEV ? 'http://127.0.0.1:8000' : location.origin;
  const mcpUrl = `${mcpOrigin}/mcp?tenant=${encodeURIComponent(row.tenant)}`;
  const config = JSON.stringify({ mcpServers: { [row.fileId]: {
    type: 'http', url: mcpUrl,
    headers: { Authorization: 'Bearer YOUR_TOKEN', 'X-Org-ID': row.org, 'X-App-ID': row.app },
  } } }, null, 2);
  return <Drawer open width={900} title="服务详情" onClose={onClose} extra={<Button type="primary" onClick={onEdit}>编辑服务</Button>}>
    {error ? <Alert type="error" showIcon message={error} /> : !detail ? <div className="loading-panel"><Spin /></div> : <>
      <div className="detail-title"><Tag color="green">OPENAPI {detail.version}</Tag><h2>{detail.title}</h2><p>{detail.fileName}</p></div>
      {detail.error && <Alert type="warning" message={detail.error} />}
      <Descriptions column={{ xs: 1, sm: 2 }} size="small" items={[
        { key: 'tenant', label: 'Tenant', children: detail.tenant },
        { key: 'scope', label: '组织 / 应用', children: `${detail.org} / ${detail.app}` },
        { key: 'id', label: '文档 ID', children: <Typography.Text copyable>{detail.fileId}</Typography.Text> },
        { key: 'auth', label: '上游认证', children: detail.auth_configured ? `${authorizationLabels[detail.auth_type || 'unknown']}（凭据不回显）` : '无需认证' },
        { key: 'created', label: '创建时间', children: time(detail.created_at) },
        { key: 'updated', label: '更新时间', children: time(detail.updated_at) },
      ]} />
      <Tabs items={[
        { key: 'tools', label: `工具清单 (${detail.tool_count})`, children: <>
          <p className="muted">已生效 {detail.active_tool_count} / 声明 {detail.tool_count} 个工具。注册状态不代表上游可用性。</p>
          {!detail.tools.length ? <Empty description="此服务没有工具" /> : <Collapse items={detail.tools.map(tool => ({
            key: tool.name, label: <Space wrap><Tag color={tool.method === 'GET' ? 'green' : 'blue'}>{tool.method}</Tag><strong>{tool.name}</strong><Tag color={tool.active ? 'success' : 'warning'}>{tool.active ? '已生效' : '未生效'}</Tag></Space>,
            children: <><p>{tool.description || '暂无描述'}</p><Typography.Paragraph copyable className="mono">{tool.url}</Typography.Paragraph><p>超时：{tool.timeout} 秒</p>
              <h4>输入参数</h4><pre className="code-block">{JSON.stringify(tool.input_schema, null, 2)}</pre>
              <h4>输出结构</h4><pre className="code-block">{JSON.stringify(tool.output_schema, null, 2) || '未声明'}</pre></>,
          }))} />}
        </> },
        { key: 'source', label: 'OpenAPI 文档', children: <><div className="section-heading"><p className="muted">数据库保存的 YAML，格式和注释可能与上传文件不同。</p>
          <Button icon={<DownloadOutlined />} onClick={() => downloadDocument(detail)}>导出 YAML</Button></div><pre className="code-block source-code">{detail.document}</pre></> },
        { key: 'connect', label: '接入配置', children: <>
          <Alert type="info" showIcon message="将 YOUR_TOKEN 替换为访问 Token" description="此配置限定租户、组织和应用范围；同范围内其他服务的工具也会被列出。不同客户端的配置字段可能不同。" />
          <h4>MCP 地址</h4><Typography.Paragraph copyable className="code-block">{mcpUrl}</Typography.Paragraph>
          <div className="section-heading"><h4>支持 HTTP 的 MCP 客户端配置</h4><Typography.Text copyable={{ text: config }}>复制配置</Typography.Text></div>
          <pre className="code-block">{config}</pre>
        </> },
      ]} />
    </>}
  </Drawer>;
}

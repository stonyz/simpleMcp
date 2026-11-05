import { useEffect, useSyncExternalStore } from 'react';
import { Button, Dropdown, type FormInstance } from 'antd';
import { CheckOutlined, GlobalOutlined } from '@ant-design/icons';
import { english } from './messages';
import serverMessages from '../../app/error_messages.json';
import { ApiError, type ErrorDiagnostic } from './apiErrors';

export type Language = 'en' | 'zh';
export type LanguagePreference = Language | 'system';
const storageKey = 'mcp-console-language';
function readPreference(): LanguagePreference {
  try {
    const stored = localStorage.getItem(storageKey);
    return stored === 'en' || stored === 'zh' ? stored : 'system';
  } catch { return 'system'; }
}
let preference = readPreference();
function systemLanguage(): Language {
  return (navigator.languages?.[0] || navigator.language || 'en').toLowerCase().startsWith('zh') ? 'zh' : 'en';
}
export function language(): Language { return preference === 'system' ? systemLanguage() : preference; }
const listeners = new Set<() => void>();
let snapshot = `${preference}:${language()}`;
function notify() {
  snapshot = `${preference}:${language()}`;
  document.documentElement.lang = language() === 'zh' ? 'zh-CN' : 'en';
  document.title = language() === 'zh' ? '服务管理台 · MCP Server' : 'Service Console · MCP Server';
  listeners.forEach(listener => listener());
}
window.addEventListener('languagechange', notify);
window.addEventListener('storage', event => {
  if (event.key === storageKey || event.key === null) { preference = readPreference(); notify(); }
});
notify();
export function setLanguage(value: LanguagePreference) {
  preference = value;
  try { localStorage.setItem(storageKey, value); } catch { /* Switching still works when storage is unavailable. */ }
  notify();
}
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export function useLanguage() {
  useSyncExternalStore(subscribe, () => snapshot);
  return language();
}
export function t(key: keyof typeof english, values: readonly unknown[] = []): string {
  const message = language() === 'zh' ? key : english[key];
  return message.replace(/\{(\d+)\}/g, (_, index: string) => String(values[Number(index)] ?? `{${index}}`));
}
export function LanguageSelector() {
  const lang = useLanguage();
  const currentLabel = lang === 'zh' ? '简体中文' : 'English';
  const items = [
    { key: 'system', label: lang === 'zh' ? '跟随系统' : 'System default' },
    { key: 'en', label: 'English' },
    { key: 'zh', label: '简体中文' },
  ].map(item => ({ ...item, icon: item.key === preference
    ? <CheckOutlined aria-hidden /> : <span className="language-check-space" aria-hidden /> }));
  return <Dropdown trigger={['click']} placement="bottomRight" menu={{
    items, selectable: true, selectedKeys: [preference],
    onClick: ({ key }) => setLanguage(key as LanguagePreference),
  }}>
    <Button type="text" className="language-selector" icon={<GlobalOutlined aria-hidden />}
      aria-label={`${lang === 'zh' ? '语言' : 'Language'}: ${currentLabel}`}>
      {currentLabel}
    </Button>
  </Dropdown>;
}

type ServerMessageCode = keyof typeof serverMessages;
function knownCode(code: string): code is ServerMessageCode {
  return Object.hasOwn(serverMessages, code);
}
function serverMessage(code: string, params: Record<string, unknown> = {}): string | undefined {
  if (!knownCode(code)) return undefined;
  const template = serverMessages[code][language()];
  return template.replace(/\{(\w+)\}/g, (placeholder, name: string) =>
    Object.hasOwn(params, name) ? String(params[name]) : placeholder);
}
function diagnosticMessage(item: ErrorDiagnostic): string {
  const path = item.loc?.slice(['body', 'query', 'path', 'header'].includes(String(item.loc[0])) ? 1 : 0).join('.')
    || (language() === 'zh' ? '输入' : 'Input');
  const code = item.code || `validation_${item.type}`;
  const description = serverMessage(code, item.params)
    || (language() === 'en' && item.msg ? item.msg : serverMessage('invalid_value'));
  return `${path}: ${description}`;
}

// Structured errors are localized at render time. Unknown upstream/user text stays intact.
export function apiMessage(value: string | Error, code?: string, params: Record<string, unknown> = {}): string {
  const message = value instanceof Error ? value.message : value;
  if (value instanceof ApiError) {
    if (value.diagnostics.length) return value.diagnostics.map(diagnosticMessage).join(language() === 'zh' ? '；' : '; ');
    code = value.code;
    params = value.params;
  }
  if (code) {
    const translated = serverMessage(code, params);
    // Generic legacy HTTP failures retain their useful server-provided explanation.
    if (translated && code !== 'http_error') return translated;
  }
  // Compatibility with prior servers and local UI error messages.
  if (Object.hasOwn(english, message)) return t(message as keyof typeof english);
  for (const entry of Object.values(serverMessages)) {
    if (entry.en === message || entry.zh === message) return entry[language()];
  }
  const field = /^请填写有效的 (.+)$/.exec(message);
  if (field && language() === 'en') return `Enter a valid ${field[1]}`;
  return message;
}

// Refresh only visible validation errors; untouched fields and form values stay unchanged.
export function useLocalizedForm<T>(form: FormInstance<T>) {
  const lang = useLanguage();
  useEffect(() => {
    const names = form.getFieldsError().filter(field => field.errors.length).map(field => field.name);
    if (names.length) void form.validateFields(names).catch(() => undefined);
  }, [form, lang]);
}

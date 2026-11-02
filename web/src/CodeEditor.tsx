import Editor, { loader } from '@monaco-editor/react';
import * as monaco from 'monaco-editor/esm/vs/editor/editor.api';
import EditorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import JsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker';
import 'monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution';
import 'monaco-editor/esm/vs/language/json/monaco.contribution';

self.MonacoEnvironment = { getWorker: (_: string, label: string) => label === 'json' ? new JsonWorker() : new EditorWorker() };
loader.config({ monaco });

export default function CodeEditor({ value, onChange, readOnly = false }: {
  value: string; onChange?: (value: string) => void; readOnly?: boolean;
}) {
  return <Editor height="420px" language={value.trimStart().startsWith('{') ? 'json' : 'yaml'}
    value={value} onChange={v => onChange?.(v || '')}
    options={{ readOnly, minimap: { enabled: false }, fontSize: 13, wordWrap: 'on',
      scrollBeyondLastLine: false, automaticLayout: true, tabSize: 2,
      ariaLabel: 'OpenAPI 代码编辑器', padding: { top: 14 } }} />;
}

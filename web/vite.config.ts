import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/admin/',
  plugins: [react()],
  server: { proxy: { '/services': 'http://127.0.0.1:8000' } },
  build: { rollupOptions: { output: { manualChunks: { antd: ['antd', '@ant-design/icons'] } } } },
});

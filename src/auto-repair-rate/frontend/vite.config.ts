import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const api_proxy_target = env.AUTO_REPAIR_RATE_API_PROXY
    || env.VITE_API_PROXY_TARGET
    || 'http://127.0.0.1:8000';
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      proxy: {
        '/api': api_proxy_target,
      },
    },
  };
});

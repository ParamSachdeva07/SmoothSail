import { defineConfig } from 'vite';

export default defineConfig({
  publicDir: 'public',
  server: {
    host: '0.0.0.0',
    proxy: {
      '/local-api': {
        target: 'http://127.0.0.1:8766',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/local-api/, '')
      }
    },
    fs: {
      allow: ['.']
    }
  },
  build: {
    chunkSizeWarningLimit: 900
  }
});

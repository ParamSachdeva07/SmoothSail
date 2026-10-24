import { defineConfig } from 'vite';

export default defineConfig({
  publicDir: 'public',
  server: {
    host: '0.0.0.0',
    fs: {
      allow: ['.']
    }
  },
  build: {
    chunkSizeWarningLimit: 900
  }
});

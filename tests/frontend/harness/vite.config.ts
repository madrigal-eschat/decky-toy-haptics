import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@decky/api': path.resolve(__dirname, '../mocks/decky-api.ts'),
      '@decky/ui': path.resolve(__dirname, '../mocks/decky-ui.tsx'),
    },
  },
});
